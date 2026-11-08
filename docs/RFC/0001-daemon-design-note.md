# Design Note: cheetahclaws daemon — IPC, permission routing, local auth

- **Status:** Draft for review
- **Tracking issue:** [#68](https://github.com/SAIL-Research-Lab/cheetahclaws/issues/68)
- **Author:** @mxh1999
- **Last updated:** 2026-04-29

This note covers the three items requested in [#68](https://github.com/SAIL-Research-Lab/cheetahclaws/issues/68): IPC + transport, permission routing, and local auth. Scope is intentionally narrow — these are the contract the foundation PR will commit to. Service inventory, phasing, persistence, and cost guardrail defaults were settled in the issue thread and are not re-litigated here.

## 1. IPC: transport and protocol

### Transport

- **Default — Unix domain socket** at `$XDG_RUNTIME_DIR/cheetahclaws/daemon.sock`, file mode `0600`. Falls back to `~/.cheetahclaws/run/daemon.sock` if `$XDG_RUNTIME_DIR` is unset.
- **Optional — TCP** via `cheetahclaws serve --listen tcp://127.0.0.1:8765` (or any host:port). Bearer-token auth required (see §3).
- **Windows** — TCP loopback only. Default address `127.0.0.1:8765`. (Standard-library Unix-socket support on Windows is partial and inconsistent across versions; not worth the complexity for v1.)

A given daemon binds exactly one address. Switching transport requires restart.

### Protocol

HTTP/1.1 framing on top of the chosen socket. Three endpoints on the same listener:

| Endpoint | Purpose |
|---|---|
| `POST /rpc` | JSON-RPC 2.0 — request/response for everything (`session.send`, `agent.start`, `monitor.subscribe`, `permission.answer`, …) |
| `GET /events?since=<id>` | Server-Sent Events — push channel for daemon-originated notifications (text chunks, tool starts/ends, permission requests, agent iterations, monitor reports, bridge in/out) |
| `GET /healthz` `/readyz` `/metrics` | Existing endpoints from `health.py`, unchanged behavior, auth added (see §3) |

Why HTTP framing on a Unix socket:

- Reuses stdlib `http.server` and `http.client`. No third-party dependency. Same code on Unix-socket and TCP transports.
- Web UI works via plain `fetch()` + `EventSource`. No protocol bridge layer.
- Tool-friendly: `curl --unix-socket` for debugging.

Why JSON-RPC for the data plane: single endpoint, named methods, batch requests, error semantics already specified. Avoids growing a REST URL hierarchy as services land — adding a method is a code-only change, no route table to maintain.

### Event channel

`GET /events?since=<id>` returns the global event stream (filtered by the caller's auth — see §2). Clients subscribe with the last id they saw to backfill anything missed during disconnects. Replay is bounded by the `daemon_events` retention window (rolling, default 7 days / 1M rows).

### Method namespace (illustrative, finalized in foundation PR)

```
session.create        session.send         session.cancel
session.list          session.get
agent.start           agent.stop           agent.list
agent.iterations
job.list              job.get              job.cancel
monitor.subscribe     monitor.unsubscribe  monitor.list
monitor.run
bridge.start          bridge.stop          bridge.list
permission.answer
config.get            config.set
```

## 2. Permission routing

### The race condition we're avoiding

An earlier draft proposed broadcasting `PermissionRequest` to every connected client and accepting the first answer ("first answer wins"). This is racy: a Telegram bridge could approve a destructive operation that the REPL user is *currently being asked about*, before the REPL user has read it. Permission state then desyncs from user intent, and the only fix is "don't connect both clients at once" — a non-fix.

### The model

Every `PermissionRequest` carries an `originator`, set at request creation:

```jsonc
{
  "request_id": "pr_abc123",
  "session_id": "repl:7f3e",
  "originator": {
    "client_kind": "repl",          // repl | web | bridge | agent_runner
    "client_id":   "7f3e9c…",
    "session_id":  "repl:7f3e"
  },
  "tool":  "Bash",
  "input": { "command": "rm -rf …" },
  "rationale": "…"
}
```

The originator is whoever caused the turn that produced this request:

- A user message from REPL → REPL is the originator.
- A user message from Telegram → that bridge connection is the originator.
- An autonomous agent runner iteration → the agent runner is the originator (with `approve_via` defining who actually answers — see below).

### Routing rules

1. **Only the originator may answer.** `permission.answer` calls from any other client receive `403 not_originator`. The daemon does not check who's *first*; it checks who's *allowed*. First-answer-wins is structurally impossible.
2. **Other subscribers see the event** through `/events`, read-only. This is for observability and Web UI dashboards. They cannot answer.
3. **Timeout** runs against the originator's window. On expiry the daemon auto-denies and emits a `permission_timeout` event. Defaults: 5 min for `unattended` mode, unlimited for interactive modes.
4. **Originator is autonomous (no human attached)** — e.g. an `/agent` runner. The request falls through to that originator's configured `approve_via` chain (see `unattended` mode in #68). The chosen approver becomes the answer authority for *that request only*; answers from other clients still get `403`.
5. **Originator disconnects mid-request** — the request is held until timeout. On reconnect, the originator gets the request back via SSE replay scoped to its own pending requests (so SSE replay must be originator-scoped, not just session-scoped).

### Override / escape hatch

A future `permission.takeover` RPC could let an admin client steal a pending request from a stuck originator. **Not in v1.** v1 ships with strict originator-only.

### Auth tie-in

Every `permission.answer` is authenticated by the caller's connection (token or socket peer credential — §3) and matched against the originator record stored at request-creation time. The auth check is the routing check.

## 3. Local auth

### Threat model

Single-user, single-host. The daemon process runs as the user. The auth boundary defends against:

- Other local users on a shared machine reaching the daemon's socket file or TCP port.
- Other processes the same user runs (random scripts, browser-launched apps with renderer privileges) talking to the daemon when they shouldn't.

Out of scope: protecting the user from themselves, network-borne attackers (use a firewall, don't expose), TLS interception (run behind a local reverse proxy if needed).

This is a **security boundary, not a multi-user feature.** No RBAC, accounts, or login flows are introduced.

### Unix socket

- Path: `$XDG_RUNTIME_DIR/cheetahclaws/daemon.sock` (fallback `~/.cheetahclaws/run/daemon.sock`).
- Created with mode `0600`, owned by the daemon's effective UID.
- Containing directory: mode `0700`.
- Daemon refuses to bind if either path is world- or group-readable.
- Daemon checks peer credentials on accept (`SO_PEERCRED` on Linux, `LOCAL_PEERCRED` on macOS) and rejects connections from a different UID.

No bearer token on the Unix socket — filesystem permissions and peer credentials are the auth.

### TCP

- Required: `Authorization: Bearer <token>`.
- Token: 32 random bytes, base64url. Generated on first `serve --listen tcp://…` start. Stored at `~/.cheetahclaws/daemon_token`, mode `0600`. `cheetahclaws daemon rotate-token` regenerates and forces reconnect.
- No token → `401`. Wrong token → `401` (same response, no leakage of "exists vs wrong"). Three failures from one peer in 10 s → 60 s connection-level cooldown.
- Token never logged. Never appears in `/metrics`, `/events`, or error messages.
- `/healthz` `/readyz` `/metrics` are token-protected by default. `cheetahclaws serve --unauthenticated-metrics` opts out for Prometheus scraping (off by default; documented as a deliberate weakening with a one-line warning at startup).

### TLS

Out of scope for v1. Document running behind a local reverse proxy (nginx, caddy) for users who want `https://` on the TCP variant.

### CSRF / browsers

Web UI uses `Authorization` headers, not cookies — CSRF does not apply at v1. If a future Web UI ships cookie-based auth, that's the Web UI design note's problem; this note assumes header-only.

### Audit log

Every authentication event (outcome, transport, peer info where available) lands in `~/.cheetahclaws/logs/auth.jsonl` (rotated). Off by default for the Unix socket (peer-cred-checked, low-noise). On by default for TCP.

## Related decisions (settled, listed for context)

Not part of this note's scope but referenced above:

- **Subprocess-per-agent** (chauncygu's note in #68) — agent runners are subprocesses, not threads, for crash isolation. Cross-process state plumbing belongs to the foundation PR, not this note.
- **Bridges land in foundation, not Phase B** — agreed in #68.
- **Cost guardrail defaults** — conservative under `serve`, shipped with foundation.
- **API stability window** — RC one minor version before the default flip.

## Open questions for review

1. **HTTP-on-socket vs raw newline-delimited JSON-RPC.** The note picks HTTP for tooling and Web UI alignment. Trade-off is a small framing overhead in exchange for `curl`-debuggability and a single transport surface. Push back if you'd prefer raw RPC on the data-plane socket.
2. **`agent_runner` as its own originator class.** The note treats an autonomous agent runner as a distinct originator with `approve_via` defining the answer route. Alternative: treat the configured bridge as the originator for these requests. Current shape was chosen so iteration logs attribute requests to the agent that produced them, not to the bridge that approved them.
3. **Audit log default for the Unix socket.** Off in this note (low-value given peer credentials). Flip if you'd prefer always-on for forensics.

---

Once the choices in this note are accepted, the foundation PR follows: stdlib HTTP server skeleton, auth (Unix-socket peer-cred + TCP token), SQLite schema additions, `cheetahclaws daemon {status, stop, logs, rotate-token}` subcommands, and the bridges-into-daemon scope agreed in #68.
