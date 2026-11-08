# Spike notes — daemon foundation reference scaffolding

- **Status:** Spike (working code, draft PR)
- **Tracking issue:** [#68](https://github.com/SAIL-Research-Lab/cheetahclaws/issues/68)
- **Tracks RFC:** [`0001-daemon-design-note.md`](./0001-daemon-design-note.md) (PR [#74](https://github.com/SAIL-Research-Lab/cheetahclaws/pull/74))
- **Branch:** `feature/daemon-spike`
- **Last updated:** 2026-04-30

This is a working reference implementation of the daemon contract described
in the RFC. **It does not integrate with `agent.run`, bridges, or the session
store.** Foundation PR rebuilds on this surface (or replaces individual
modules); none of the spike code is load-bearing for production.

## What's implemented

| File | LoC | Role |
|---|---|---|
| `daemon/server.py` | 250 | `ThreadedTCPServer`, `ThreadedUnixServer`, request handler, dispatch, SSE loop |
| `daemon/rpc.py` | 90 | JSON-RPC 2.0 dispatcher + method registry |
| `daemon/events.py` | 110 | In-memory ring buffer + pub/sub + SSE frame format |
| `daemon/auth.py` | 180 | `SO_PEERCRED` (Linux) + bearer token, audit log, brute-force throttle |
| `daemon/originator.py` | 70 | client_id mint / persist / resume |
| `daemon/permission.py` | 130 | Pending-request store, originator-only answer, timeout janitor |
| `daemon/methods.py` | 75 | `echo.ping` / `permission.demo` / `permission.answer` / `permission.refresh_timeout` / `permission.list` |
| `daemon/cli.py` | 165 | `cheetahclaws spike-daemon {serve, status, stop, rotate-token}` |
| `daemon/spike_client.py` | 175 | Stdlib-only smoke client (`ping`, `watch`, `request`, `answer`, `list`) |
| `tests/test_daemon_spike.py` | 290 | 13 cases (8 covering RFC must-fix matrix + 5 unit) |

`cheetahclaws.py` gets a single 4-line shim that intercepts `spike-daemon` before the main argparse runs. Nothing else in the main code is touched.

## RFC review-comment coverage

| # | RFC must-fix item | Spike validates? | Where |
|---|---|---|---|
| 1 | `ThreadingHTTPServer` w/ concurrency cap | ✓ | `server.py` (`request_queue_size = 256`); `test_concurrent_rpc_not_blocked_by_sse` |
| 2 | SSE 15s heartbeat | ✓ | `server.py` `_handle_events`; `test_sse_heartbeat_arrives` |
| 3 | `client_id` lifecycle (mint, persist, resume) | ✓ | `originator.py`; `test_client_id_resume`, `test_originator_store_persistence` |
| 4 | `session.send` semantics — variant A (sync RPC + async events) | ✓ | `methods.py:echo.ping`; `test_echo_ping_and_event_emission` |
| 5 | macOS peer-cred | ✗ | `auth.py: TODO(macos)` left in for foundation PR |
| 6 | API version header → 426 on mismatch | ✓ | `server.py:_check_api_version`; `test_api_version_mismatch_returns_426` |
| 7 | Event retention bounded; overflow → `gap` | ✓ | `events.py:replay_since`; `test_ring_buffer_overflow_emits_gap` |
| 8 | Audit log default-on (Unix and TCP) | ✓ | `auth.py:AuditLog`; `test_audit_log_records_outcomes` |
| 9 | Interactive permission timeout 30 min + extend RPC | ✓ | `permission.py`; `test_permission_default_timeout_is_30min`, `permission.refresh_timeout` |

Not covered (deferred to foundation PR):

- `/events` filter semantics in multi-client scenarios (#10 in review).
- Binary payload story (#11).
- `/metrics` redaction (#12) — spike has no metrics endpoint.

## Surprises / things foundation PR should know

1. **`request_queue_size` matters more than expected.** Default of 5 lets long-lived SSE connections cause new TCP `connect()`s to wait on SYN retransmit (~1s). Bumping to 256 fixed `test_concurrent_rpc_not_blocked_by_sse`. Foundation PR should keep this.

2. **`BaseHTTPRequestHandler` defaults to HTTP/1.0.** Without `Transfer-Encoding: chunked` (which 1.0 doesn't support), `curl --no-buffer` won't print SSE bytes until the connection closes. Browsers (`EventSource`) and `http.client` (which we use in `spike_client.py` and tests) handle it fine. Foundation PR may want to upgrade `protocol_version = "HTTP/1.1"` and emit chunked framing for `/events` to make `curl` debugging painless.

3. **`ThreadingMixIn.daemon_threads = True`** means SSE handlers don't keep the process alive; on shutdown, the server's `serve_forever` loop exits and the handler threads die. Graceful close (sending an `event: shutdown` frame to each subscriber so they unwind cleanly instead of getting TCP RST) is implemented via `DaemonState.shutdown()` publishing a `shutdown` event before stopping the server.

4. **`SO_PEERCRED` ucred struct on Linux** is `pid_t/uid_t/gid_t` = `iII` (signed pid, unsigned uid/gid). Older docs say `3i`; the unsigned variant is what current glibc emits. `auth.py:_UCRED_FMT = "iII"`. Foundation PR should keep an eye on this when adding macOS support.

5. **`OriginatorStore` persistence is whole-file rewrite on each mint.** Fine for a spike (low write rate) but trivially racy across daemon restarts. Foundation PR should swap for the SQLite session/originator schema.

6. **Permission store janitor runs on a 1s tick.** Means the spike's "expires_at" precision is ±1s. Foundation PR can tighten if needed.

## What this spike is **NOT**

- No `agent.run` connection. `session.send` doesn't exist; only `echo.ping` does.
- No bridges (Telegram/Slack/WeChat) wired up. Bridge migration is foundation PR's headline.
- No SQLite persistence of events. In-memory ring only.
- No cost guardrails / quota.
- No subprocess-per-agent runner.
- macOS peer-cred deliberately punted.

## How to run it

### Start the daemon

```bash
# TCP — easiest for testing; token printed to stdout
cheetahclaws spike-daemon serve --listen tcp://127.0.0.1:8765 --print-token

# Unix socket — default; peer-cred enforced (Linux only)
cheetahclaws spike-daemon serve

# Lifecycle
cheetahclaws spike-daemon status        # running? prints pid
cheetahclaws spike-daemon stop          # SIGTERM, falls back to SIGKILL after 5s
cheetahclaws spike-daemon rotate-token --print-token
```

### Talk to it

The smoke client lives at `daemon/spike_client.py`. It reads a token from
`$CHEETAHCLAWS_TOKEN` so you don't have to pass `--token` on every call —
which also sidesteps argparse's "value starts with `-`" trap on
URL-safe-base64 tokens.

```bash
export CHEETAHCLAWS_TOKEN="<the token printed by serve>"

# Sync RPC: returns immediately, also fires a ping_received event.
python -m daemon.spike_client --target tcp://127.0.0.1:8765 \
    --kind play ping --message hi

# Tail the event stream (heartbeats every 15s).
python -m daemon.spike_client --target tcp://127.0.0.1:8765 \
    --kind watcher watch
```

Don't try to use `curl` for `/events` — `BaseHTTPRequestHandler` defaults to
HTTP/1.0 (no chunked encoding), so curl buffers the whole response until the
connection closes. The Python `http.client` path used by `spike_client` and
the tests handles it correctly. (See "Surprises" item #2 above.)

### Demo the headline feature: originator routing

This is the part RFC §2 was written for — proves first-answer-wins is
structurally impossible.

```bash
# Two distinct clients (alice / bob) get distinct client_ids on first touch.
rm -f ~/.cheetahclaws/clients/alice.id ~/.cheetahclaws/clients/bob.id
python -m daemon.spike_client --target tcp://127.0.0.1:8765 --kind alice ping
python -m daemon.spike_client --target tcp://127.0.0.1:8765 --kind bob   ping

# Alice creates a PermissionRequest (originator = alice's client_id).
python -m daemon.spike_client --target tcp://127.0.0.1:8765 --kind alice \
    request --tool Bash --input '{"cmd":"rm -rf /tmp/x"}'
# → result.request_id = pr_<hex16>

export RID="<paste request_id here>"

# Bob tries to answer Alice's request:
python -m daemon.spike_client --target tcp://127.0.0.1:8765 --kind bob \
    answer --request-id "$RID" --approve
# → status 403, error.code -32001, "not the originator"

# Alice answers her own:
python -m daemon.spike_client --target tcp://127.0.0.1:8765 --kind alice \
    answer --request-id "$RID"
# → status 200, result.answer = {"approve": false}
```

Because `client_id` is persisted at `~/.cheetahclaws/clients/<kind>.id` and
the daemon writes it back on every connect, you can also `kill` the daemon,
restart it, and the same `--kind alice` invocation will resume against a
fresh process — that exercises the RFC §2.5 reconnect path.

### Inspect persistent state

```bash
# Server-side
cat /tmp/spike-play/logs/auth.jsonl     # one JSON line per auth event (RFC §3 audit log)
cat /tmp/spike-play/originators.json    # client_id → kind map
cat /tmp/spike-play/run/daemon.pid

# Client-side
ls -la ~/.cheetahclaws/clients/         # mode-0600 id files per client kind
```

### Tests

```bash
pytest tests/test_daemon_spike.py -v
# 13 cases, ~1.5s. Covers RFC items #1, 2, 3, 4, 6, 7, 8, 9.
```

## Hand-off to mxh1999

The spike commits to (and validates) the contract surface from the RFC.
Foundation PR can:

1. **Replace `methods.py` wholesale** — `echo.ping` is throwaway. Real `session.send` writes into the session store and triggers `agent.run`.
2. **Replace `events.py`'s ring buffer with the SQLite `daemon_events` table.** The pub/sub interface stays.
3. **Replace `permission.py`** with the real `agent.run`-integrated request flow. Originator routing logic should be reused.
4. **Keep `server.py`, `auth.py`, `originator.py`, `rpc.py`** more or less as-is (these encode the contract).
5. **Add macOS peer-cred** (the `TODO(macos)` comment in `auth.py` is the only thing missing for cross-platform).

Anything not on this list is fair game to redesign.
