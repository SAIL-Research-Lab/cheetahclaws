# Daemon Foundation Roadmap

- **Status:** Tracking
- **Refs:** [#68](https://github.com/SAIL-Research-Lab/cheetahclaws/issues/68), [RFC 0001 design note](./0001-daemon-design-note.md)
- **Last updated:** 2026-05-12 (all nine items landed: F-1, F-2, F-3, F-4 incl. #1/#2/#3/#4, F-5, F-6 Phase 1+2, F-7, F-8, F-9 incl. quota-pause)

The "foundation PR" described at the end of [RFC 0001](./0001-daemon-design-note.md) is too big for one reviewable change (~5 KLoC including stdlib HTTP server, auth, JSON-RPC + SSE, SQLite schema, `daemon` CLI, bridges-into-daemon, subprocess-per-agent, and conservative cost defaults). This document splits it into nine stackable PRs and pins the acceptance criteria for each. Implementation follows this index in order; later items can land in parallel once F-1 and F-2 are merged.

## Index

| ID  | Scope                                               | Depends on | Est LoC | Status |
|-----|-----------------------------------------------------|------------|---------|--------|
| F-1 | `daemon/` package skeleton; `serve` + `daemon` CLI  | —          | ~1500   | MERGED #80 |
| F-2 | SQLite schema + events persistence + jobs migration | F-1        | ~700    | MERGED #101 + follow-ups (#fix-f2) |
| F-3 | `monitor/scheduler` runs in daemon                  | F-2        | ~700    | MERGED #101 + follow-ups (#fix-f2) |
| F-4 | `agent_runner` becomes subprocess-per-agent         | F-2        | ~1000   | skeleton complete; F-4.1 perm routing + F-4.2 bridge notify + F-4.3 restart policy + F-4.4 e2e all landed (see §F-4 below); Windows path remains out of scope |
| F-5 | `proactive` watcher runs in daemon                  | F-2        | ~200    | LANDED (see §F-5 below) |
| F-6 | Telegram bridge in daemon                           | F-2        | ~500    | LANDED — Phase 1 + Phase 2 inbound refactor both live (see §F-6 below) |
| F-7 | Slack bridge in daemon                              | F-6        | ~500    | LANDED — same Phase 1 + Phase 2 surface as F-6 |
| F-8 | WeChat bridge in daemon                             | F-6        | ~500    | LANDED — same Phase 1 + Phase 2 surface as F-6 (QR-login still REPL-driven) |
| F-9 | Conservative cost-guardrail defaults under `serve`  | F-1        | ~150    | LANDED (see §F-9 below) — defaults + RPCs + per-runner quota-pause hook all live |

## F-1 — daemon skeleton

**Scope.** Adopt the `daemon/` reference scaffolding from
[`feature/daemon-spike`](https://github.com/SAIL-Research-Lab/cheetahclaws/tree/feature/daemon-spike)
(`server`, `auth`, `originator`, `rpc`, `events`, `permission`, `methods`)
**as-is** — those modules encode the contract the maintainer reviewed in
PR #74.  Layer the foundation glue on top:

- `daemon/discovery.py` — atomic `~/.cheetahclaws/daemon.json` so
  REPL / Web / bridge clients can locate the running daemon (transport,
  address, version).  Spike's pid file stays for "is anything running?"
  liveness; discovery answers "where is it?".
- `daemon/system_methods.py` — registers `system.ping` (returns
  `"pong"`) and `system.shutdown` (sets `DaemonState.shutdown_event`,
  giving us cross-platform graceful exit since Windows can't deliver
  SIGTERM cleanly to another Python process).
- `daemon/cli.py` — rewritten `serve_main(argv)` that calls
  `bootstrap()`, pins `log_file` to `<data_dir>/logs/daemon.log`, threads
  the loaded `config` and the `--unauthenticated-metrics` flag through
  `DaemonState`, writes the discovery file on bind, watches the shutdown
  event, and clears discovery on exit.
- `daemon/server.py` — minimal patch: route `/healthz` `/readyz`
  `/metrics` through `health.payload_for(path, config)` instead of
  the spike's stub `{"status": "ok"}`.  Auth-gated by default; opt out
  via `--unauthenticated-metrics`.  Adds Windows guard around
  `socketserver.UnixStreamServer` (unavailable on Windows).
- `commands/daemon_cmd.py` — `cheetahclaws daemon {status, stop, logs,
  rotate-token}` subcommand handlers.  `status` reads discovery + pings
  `system.ping`; `stop` calls `system.shutdown` RPC then falls back to
  SIGTERM / TerminateProcess; `logs` tails `~/.cheetahclaws/logs/daemon.log`;
  `rotate-token` regenerates the token (notes that existing TCP clients
  receive 401 until they re-read the file).
- `health.py` — refactor: extract module-level `healthz_payload(config)`
  / `readyz_payload(config)` / `metrics_payload(config)` /
  `payload_for(path, config)` so both the existing standalone health
  HTTP server and `daemon/server.py` reuse the same
  circuit-breaker / quota / runtime-registry probes.  No behaviour
  change for existing `health_check_port` users.
- `cheetahclaws.py` — main() short-circuit: `cheetahclaws serve`
  dispatches to `daemon.cli.serve_main`; `cheetahclaws daemon
  <action>` dispatches to `commands.daemon_cmd.dispatch`.  Replaces the
  spike's `spike-daemon` shim.

**Acceptance.**
- `cheetahclaws serve` starts; `cheetahclaws daemon status` reports pid,
  transport, address, uptime, ping outcome.
- Unix socket (POSIX): `curl --unix-socket <path> -X POST /rpc
  -H "Cheetahclaws-Api-Version: 0" -d '{"jsonrpc":"2.0","id":1,"method":"system.ping"}'`
  returns `{"jsonrpc":"2.0","id":1,"result":"pong"}`.
- TCP: same call without `Authorization: Bearer <token>` returns 401;
  with valid token returns 200; sustained bad-token attempts trip the
  spike's brute-force throttle (429).
- `curl … GET /events` keeps the stream open; heartbeats arrive at
  spike's 15 s cadence.
- `cheetahclaws daemon stop` → `system.shutdown` RPC → discovery file
  cleared and process exits 0.
- `cheetahclaws daemon rotate-token` regenerates the token; existing TCP
  clients receive 401 on next request until they re-read the file.
- pytest green on Linux, macOS, Windows (TCP-only on Windows; Unix
  socket tests skip on Windows).

## F-2 — SQLite schema + events persistence + jobs migration

**Scope.** Seven additive tables in `~/.cheetahclaws/sessions.db`; swap
the F-1 in-memory event ring for a SQLite-backed channel; migrate
`jobs.py` JSON storage to SQLite.  **Originator-tracked permission flow
is already provided by spike's `daemon/originator.py` +
`daemon/permission.py`** (see PR #80) — this PR doesn't re-do it.

**Tables (additive — `sessions` from `session_store.py` untouched).**
`schema_meta`, `daemon_events`, `agent_runs`, `agent_iterations`,
`jobs`, `monitor_subscriptions`, `monitor_reports`, `bridges`.

**Deliverables.**
- `daemon/schema.py` — DDL + `init_schema(db_path)` (idempotent,
  internally locked) + `get_conn()` (thread-local, mirrors
  `session_store` pattern) + `get_schema_version()` accessor; future
  migrations land in `_apply_migrations()`.
- `daemon/cli.py:cmd_serve` calls `init_schema()` right after
  `bootstrap()` so tables exist before the first publish.
- `daemon/events.py` — rewritten: `EventBus.publish` does an INSERT
  into `daemon_events` (id from `AUTOINCREMENT`, monotonic across
  restarts and prunes), still fans out to in-process subscribers for
  live tail; `replay_since(N)` reads from SQLite and emits a synthetic
  `gap` event when `N` is older than the oldest surviving row.
  Default retention: 24 h / 100 K rows; opportunistic prune every 100
  publishes.
- `jobs.py` — `_persist`/`_row_to_job` hit SQLite; `_ensure_migrated()`
  imports legacy `~/.cheetahclaws/jobs.json` once (tracked via
  `schema_meta.jobs_migrated_from_json`).  Migration is **one-way**:
  after the marker is set, edits to the JSON file are no longer read.
  The file is left on disk for backward viewing only (prior-release
  users, backup tooling); SQLite is the source of truth from then on.
  Public API unchanged.

**Follow-ups (#fix-f2).**
- `daemon/schema.py` sets `PRAGMA synchronous=NORMAL` on init and
  on every thread-local connection.  Safe under WAL — only the most
  recent transactions can be lost on hard kernel crash, which for an
  event log already retention-pruned in 24 h windows is an acceptable
  trade.  Microbenchmark: `EventBus.publish` of 10 K `text_chunk`
  events drops from 305 μs/event to 39 μs/event (~8× — chauncygu
  #74 review §7 follow-up).
- `jobs.py` and `monitor/store.py` migration docstrings now make the
  one-way semantics explicit (the original "kept readable for one
  release as fallback" wording in PR #101 implied a fallback read
  path that didn't exist; users editing the JSON expecting it to be
  picked up would have been silently surprised).

**Acceptance.**
- `init_schema()` is idempotent across daemon restarts and concurrent
  callers (verified by 12 unit tests in `tests/test_daemon_schema.py`).
- Spike's 13 contract tests in `tests/test_daemon_spike.py` keep
  passing on the SQLite-backed bus (only the two ring-buffer tests
  needed an in-place rewrite to test retention-based eviction instead
  of the deleted in-memory cap).
- New `tests/test_daemon_events_sqlite.py` (15 tests) covers
  persistence, retention by row count + age, gap-on-old-since,
  cross-instance replay (simulated daemon restart), and the
  `reset_bus_for_tests()` truncate path.
- New `tests/test_jobs_sqlite.py` (14 tests) covers create / start /
  add_step / lifecycle / list_recent / list_running / `_MAX_JOBS`
  pruning + JSON-file migration (idempotency, corrupt-file tolerance,
  legacy-file kept readable).
- New e2e `tests/e2e_daemon_skeleton.py::test_events_persist_in_sqlite_across_daemon_restart`
  publishes events on daemon A via `echo.ping`, stops A, starts B
  against the same data dir, and verifies `GET /events?since=0`
  replays the events from SQLite.

## F-3 — monitor in daemon

**Scope.** `monitor/scheduler.py` runs daemon-side; subscription store
moves from JSON to the F-2 `monitor_subscriptions` table; reports
persist + emit SSE events; REPL skips its local scheduler when a
daemon is detected.

**Deliverables.**

- `monitor/store.py` — SQLite-backed (`monitor_subscriptions` and
  `monitor_reports` tables).  One-shot import of legacy
  `~/.cheetahclaws/monitor_subscriptions.json` on first call (tracked
  in `schema_meta.monitor_migrated_from_json`); JSON kept readable for
  one release.  New helpers: `save_report`, `list_reports`.  Public
  API of the legacy store unchanged.
- `monitor/scheduler.py` — `run_one()` persists the full report body
  via `save_report` and publishes a `monitor_report` event on
  `daemon.events.get_bus()` with `{topic, report_id, body, sent_to,
  errors}`.  Loop's idle wait switched from `time.sleep(30)` ×60 to a
  single `Event.wait(60)` so daemon shutdown isn't stalled by the
  scheduler thread napping.
- `daemon/monitor_methods.py` — registers `monitor.subscribe`,
  `monitor.unsubscribe`, `monitor.list`, `monitor.run` for external
  clients (Web UI / third-party tools).  `DaemonState.__init__` calls
  `monitor_methods.register` next to `system_methods`.
- `daemon/cli.py:cmd_serve` — starts the scheduler with
  `monitor.scheduler.start(config)` after schema init; the existing
  shutdown watcher calls `monitor.scheduler.stop()` before triggering
  HTTP-server shutdown.
- `commands/monitor_cmd.py` — `/monitor start` and `/monitor stop`
  detect a live daemon via `daemon.discovery.locate()` and no-op
  with a friendly message.  `/monitor subscribe` / `unsubscribe` /
  `list` continue to work in REPL because they hit SQLite directly.

**Follow-ups (#fix-f2).**
- `daemon/cli.py:cmd_serve` now starts `monitor.scheduler.start(...)`
  **after** the listener has bound and the discovery file is on disk
  (PR #101 had it before the bind).  Order matters — if a due
  subscription fires before the daemon is reachable, an LLM/network
  error in fetch/summarize/deliver surfaces in the log before the
  user sees the listening line, and external clients can't yet act
  on the resulting `monitor_report` SSE event.
- `monitor/scheduler.py` — `_foreign_daemon_running()` step-aside
  check at the top of every loop tick.  Closes the race where REPL
  `/monitor start` fires in the brief window before the daemon
  writes its discovery file: both schedulers would otherwise race on
  `last_run_at` and double-fire subscriptions.  Daemon passes
  `owned_by_daemon=True` to `start(...)` to opt out of the check
  (otherwise it would defer to its own discovery entry forever).

**Acceptance.**

- `cheetahclaws serve` running → `monitor.subscribe` over RPC persists
  to SQLite; daemon scheduler fires on cadence; reports show up in
  `monitor_reports` and on the SSE channel as `monitor_report` events.
- Daemon stop → start with same data dir → `monitor.list` over RPC
  returns the previously-subscribed topics.  (Verified by
  `tests/e2e_daemon_skeleton.py::test_monitor_subscribe_via_rpc_survives_daemon_restart`.)
- REPL `/monitor subscribe` while daemon is running: subscription
  visible via `monitor.list` from outside.  Daemon picks up the new
  row on its next 60 s poll.
- Without daemon: today's REPL-only behaviour unchanged
  (in-process scheduler thread).
- Telegram / Slack / WeChat delivery from daemon: out of scope for F-3
  (waits for F-6/F-7/F-8).  Reports + `monitor_report` events still
  fire so the digest isn't lost; bridges deliver only when REPL is
  running with the channel connected.

**Tests.** `tests/test_monitor_store_sqlite.py` (18), 
`tests/test_monitor_scheduler_events.py` (7),
`tests/test_daemon_monitor_methods.py` (12), plus 1 new e2e in
`tests/e2e_daemon_skeleton.py` for the survive-restart case.

## F-4 — agent_runner subprocess

**Scope.** Each `AgentRunner` is its own subprocess. From #68: *"subprocess-per-agent rather than threads — one leaking/crashing runner shouldn't take down the scheduler and bridges."*

**Deliverables.**
- `daemon/runner_supervisor.py` — spawn / monitor / restart agent-runner subprocesses.
- `daemon/runner_ipc.py` — line-delimited JSON over stdin/stdout between supervisor and runner.
- `agent_runner.py` — main entry point usable as `python -m agent_runner --pipe …`; iteration-log writes flow back to the daemon and land in `agent_iterations`.
- Permission requests from runners routed through supervisor → `daemon/permission.py`.

**Acceptance.**
- Runner crash (`kill -9 <runner_pid>`) does not kill the daemon; supervisor logs the crash and emits `agent_runner_crash` event.
- Runner OOM does not affect monitor or bridges.
- Runner subprocess stops within 5 s of `agent.stop` RPC.
- Iteration-log entries match in-process behavior (status, duration, summary, token counts).

### Skeleton landed — what's done so far

A POSIX-only skeleton landed under the `agent_runner_subprocess` /
`CHEETAHCLAWS_ENABLE_F4` feature flag (off by default; REPL is byte-for-byte
unchanged). Files:

| File | LoC | Role |
|------|-----|------|
| `daemon/runner_supervisor.py` | ~610 | Lifecycle (`start` / `stop` / `stop_all` / `get` / `list_all`), three-phase stop (IPC `stop` → SIGTERM → SIGKILL, ≤5 s), reader loop, crash classification, SQLite persistence helpers |
| `daemon/runner_ipc.py` | 33 | Thin re-export of `kernel.runner.ipc.JsonLineChannel` |
| `daemon/agent_methods.py` | ~100 | `agent.start` / `agent.stop` / `agent.list` / `agent.status` RPCs, registered from `daemon/server.py:DaemonState.__init__` |
| `agent_runner.py` | +231 | `python -m agent_runner --pipe` subprocess entry, `_PipeAgentRunner` shim that bridges `send_fn` and `iteration_done` to IPC, dispatch in `start_runner` / `stop_runner` |
| `tests/test_daemon_runner_supervisor.py` | ~430 | 17 unit tests: handshake, graceful stop, SIGKILL escalation on hung runner, crash via external SIGKILL, IPC shim identity, 9 SQLite persistence cases |
| `tests/test_daemon_agent_methods.py` | ~210 | 10 RPC tests: registration, param validation, list/status when empty, end-to-end list→stop with inline runner |

Acceptance status:

- ✅ **Crash detection.** `kill -9 <runner_pid>` flips `handle.status` to
  `"crashed"`, finalizes the `agent_runs` row (`status='crashed'`,
  `error="exit_code=-9; stderr_tail=..."`), and publishes
  `agent_runner_crash` on the event bus.
- ✅ **OOM resilience.** Same code path as `kill -9`; the OOM killer's
  SIGKILL is observed via `proc.poll()` from the reader loop.
- ✅ **Stop within 5 s.** Verified by
  `test_graceful_stop_within_5s` and `test_hanging_runner_escalates_to_sigkill`.
  Graceful IPC `stop` first; SIGTERM after 2 s; SIGKILL after another 3 s.
- ✅ **Iteration log parity.** jsonl format is byte-identical to today's
  in-thread `AgentRunner._persist_record`. `agent_iterations` and
  `agent_runs` SQLite rows are populated end-to-end (verified by 9
  persistence tests). `INSERT OR IGNORE` makes re-delivery idempotent.

### Still TODO before this can flip from "skeleton" to "MERGED"

1. **Permission routing.** ✅ *Landed (see §F-4.1 below).* The supervisor
   now routes `permission_request` IPC through
   `daemon/permission.py:PermissionStore` when the runner was started
   with `auto_approve=False`. The originator (the client_id that called
   `agent.start`) answers via `permission.answer` and the supervisor
   forwards the response back to the runner as `permission_response`.
2. **Bridge `notify` forwarding.** ✅ *Landed (see §F-4.2 below).* The
   supervisor's reader now routes `{"op":"notify", "text": ...}` IPC
   frames through `bridge_supervisor.notify(kind, text)` and publishes
   an `agent_runner_notify` event. The runner can target a specific
   bridge via `msg["bridge"]` or omit it for a `"*"` broadcast.
3. **Restart policy.** ✅ *Landed (see §F-4.3 below).* The originator
   picks a `restart_policy` ("none" | "on-crash") at `agent.start` time
   along with `max_restarts` / `backoff_base_s` / `backoff_cap_s`. The
   supervisor's reader hooks the lineage's restart counter into a
   `threading.Timer` after a crash; `stop()` cancels any pending Timer.
   Exhaustion publishes `agent_runner_restart_exhausted` so observers can
   take over.
4. **e2e test against the real `python -m agent_runner`.** ✅ *Landed
   (see §F-4.4 below).* `tests/e2e_f4_runner.py` spawns the real
   `python -m agent_runner --pipe` subprocess via `runner_supervisor.start`
   and verifies the `agent_runs` insert, the `agent_iterations` →
   `last_iteration` update, the `ended_at` finalisation on graceful
   stop, and the full F-4.1 permission round-trip end-to-end.
5. **Windows path.** Out of scope per RFC; `enabled()` returns False on
   `sys.platform.startswith("win")` and the dispatch in
   `agent_runner.start_runner` falls back to threads.

### §F-4.1 — Permission routing (landed)

The supervisor and runner now agree on one IPC round-trip per permission
prompt:

```
                       permission_request {request_id, tool, input, rationale}
runner ────────────────────────────────────────────────────────────────► supervisor
                                                                          │
                                                            permission_store.create(
                                                              originator = handle.originator,
                                                              on_answer  = _forward_back )
                                                                          │
                                            ┌── originator answers via JSON-RPC ──┐
                                            │   permission.answer(req_id, result)  │
                                            └─────────────────────────────────────┘
                                                                          │
                       permission_response {request_id, granted}          ▼
runner ◄──────────────────────────────────────────────────────────────── supervisor
```

Files touched:

| File | What changed |
|------|--------------|
| `daemon/permission.py`        | `PermissionRequest` gains an optional `on_answer(req)` callback; `PermissionStore.create()` accepts it, `answer()` fires it after the store has been mutated (outside the lock), the janitor synthesises `{"approve": False, "timeout": True}` and fires it on expiry. |
| `daemon/runner_supervisor.py` | `RunnerHandle` gains `originator: str` + `permission_store: Optional`. `start()` takes both as kwargs. `_reader_loop`'s `permission_request` branch now: (a) keeps the auto-approve fast path when `auto_approve=True` *or* no store is wired in (back-compat), (b) otherwise calls `store.create(originator=…, on_answer=…)` and the callback ships `permission_response` back to the runner. |
| `daemon/agent_methods.py`     | `agent.start` reads `ctx.client_id` for the originator and passes `daemon_state.permissions` as the store. `agent.list` / `agent.status` results now include `originator`. |
| `agent_runner.py`                | Extracted today's inline PermissionRequest handling into `AgentRunner._handle_permission_request(event) -> rec_status`. `_PipeAgentRunner` overrides it: emit `permission_request` with a fresh correlation id, wait on a `threading.Event` populated by the control-loop's `permission_response` handler (already in place), then set `event.granted` and either continue or stop. |

Semantics:

- **`auto_approve=True`** — runner doesn't even bother the supervisor; permission requests are granted in-process. Identical to today's REPL behaviour.
- **`auto_approve=False` and store present** — the originator's RPC client is the only client that can answer (`NotOriginator` for everyone else, just like spike's permission tests).
- **`auto_approve=False` and store absent** — the supervisor still grants (treated as the back-compat safety path so a misconfigured caller doesn't lock the runner up). Only RPC-driven flows pass a store.
- **Timeout** — the store's janitor fires the same callback path with `{"approve": False, "timeout": True}` so the runner unblocks rather than waiting `_PERMISSION_WAIT_S` (30 min) for an IPC frame that's never coming.

Tests live in `tests/test_daemon_runner_permission_routing.py` (10
new cases — store callback unit, supervisor approve/deny/timeout
round-trips, non-originator guard, missing-store fallback, and the
`agent.start` RPC wiring). The existing 17 supervisor tests + 10
agent-method tests + 11 spike tests all still pass.

### §F-4.2 — Bridge-notify forwarding (landed, unblocked by F-6)

The supervisor's reader used to drop the runner's ``{"op":"notify"}``
IPC frames on the floor — fine for F-4's skeleton because no bridge
was running in-daemon yet. With F-6's Phase 1 mailbox landed, the
forward path is one delegation:

```
runner._notify("text")
  │
  ▼
chan.send({"op":"notify", "text":"...", "bridge":"telegram"|"*"|...})
  │
  ▼
supervisor._reader_loop (op == "notify"):
  text   = msg.get("text") or msg.get("msg") or ""
  target = msg.get("bridge", "*")
  if text:
    delivered = bridge_supervisor.notify(target, text)
    bus.publish("agent_runner_notify",
                {name, run_id, bridge, delivered, text[:500]})
```

Defaults & semantics:

- **Default target = ``"*"``.** A runner that doesn't know which bridge
  its originator owns (the common case for `agent_runner._notify`) sends
  the message to every live bridge. Useful for "agent finished" pings.
- **Empty text is silently dropped.** No event, no bus traffic — keeps
  the iteration log from spamming when an agent template emits an
  empty notify (common during shutdown).
- **No backpressure.** If `bridge_supervisor.notify` raises, we capture
  it on `handle.error` and keep the reader thread alive. Bridges
  becoming unreachable mid-iteration must never crash a runner.
- **No retry.** `delivered: false` events are visible to observers via
  the bus; retry policy (if any) belongs to the originator, not the
  supervisor.

Tests live in `tests/test_daemon_runner_notify_routing.py` (3
cases — single-bridge dispatch, broadcast default, empty-text drop).
Verifies via an inline `python -c` runner that speaks the IPC
protocol and a `patch.object(bs, "notify", ...)` so we don't need a
real network bridge to exercise the wiring.

### §F-4.3 — Restart policy (landed)

The originator picks a policy at `agent.start` time. The supervisor's
reader-loop `finally` consults the policy after a crash and arms a
`threading.Timer` for the next attempt. A graceful `stop()` is never
followed by a restart.

`RestartPolicy` (dataclass, frozen):

| Field              | Default | Meaning                                                                 |
|--------------------|--------:|-------------------------------------------------------------------------|
| `mode`             | `"none"`| `"none"` (no auto-restart) or `"on-crash"` (respawn only on crash).      |
| `max_restarts`     | `0`     | Total restarts for the whole lineage. Zero disables even when `mode='on-crash'`. |
| `backoff_base_s`   | `1.0`   | First delay; doubles each subsequent attempt.                            |
| `backoff_cap_s`    | `60.0`  | Hard ceiling on the doubled delay.                                       |
| `backoff_jitter_s` | `0.5`   | Symmetric uniform jitter (clipped at zero).                              |

`next_delay(restart_count)` is a pure function — given the lineage's
running counter it returns the next delay in seconds, or `None` when
the policy is exhausted or disabled. Tests cover the full decision
matrix without touching a clock or a subprocess.

`agent.start` accepts these as flat params (`restart_policy`,
`max_restarts`, `backoff_base_s`, `backoff_cap_s`, `backoff_jitter_s`).
Bad values raise `TypeError` → JSON-RPC `-32602 invalid params`. The
nastiest footgun — `backoff_cap_s < backoff_base_s` (would clamp every
attempt down to the cap and "feel" disabled) — is rejected at config
time.

Lifecycle:

```
runner crashes
  │
  ▼
reader.finally:
  status='crashed'; agent_runs.error filled in; bus.publish(agent_runner_crash)
  │
  ▼
_maybe_schedule_restart(handle):
  delay = policy.next_delay(restart_count)
  if delay is None:
      if restart_count > 0 → bus.publish(agent_runner_restart_exhausted)
      stop                                      # default path for mode='none'
  else:
      bus.publish(agent_runner_restart_scheduled, {delay_s})
      handle._restart_timer = threading.Timer(delay, _do_restart, (handle,))
                              ↓ later …
_do_restart(prev):
  if registry slot is empty or has a newer run_id → abort silently
  new_handle = _RESTART_SPAWNER(**prev._start_kwargs,
                                _restart_count_carry=prev.restart_count + 1)
  bus.publish(agent_runner_restart, {old_run_id, new_run_id, restart_count})
```

Files touched:

| File                                                | What changed |
|-----------------------------------------------------|--------------|
| `daemon/runner_supervisor.py`                    | Adds `RestartPolicy` dataclass + `RunnerHandle.restart_policy / restart_count / _start_kwargs / _restart_timer / _restart_decided`. `start()` gains kwargs (`restart_policy`, `_restart_count_carry`) and stashes `_start_kwargs` for successor calls. Reader's `finally` invokes `_maybe_schedule_restart()` on crash. `stop()` cancels the pending Timer before the kill ladder. New `_RESTART_SPAWNER` module hook for tests. |
| `daemon/agent_methods.py`                        | `agent.start` parses `RestartPolicy.from_params(params)` and threads it through. `_handle_to_dict` now reports `restart_count` + flattened `restart_policy` on `agent.list` / `agent.status`. |
| `tests/test_daemon_runner_restart_policy.py`     | New, 16 cases: 10 pure-function (`next_delay` matrix, `from_params` validation), 3 reader-loop integration (`disabled → no timer`, `on-crash → spawner called with carry+1`, exhaustion publishes the event), 1 `stop()` cancellation, 2 handle serialisation / sanity. |
| `tests/test_daemon_runner_permission_routing.py` | `_FakeHandle` stub gains `restart_policy` + `restart_count` so `_handle_to_dict` doesn't `AttributeError`. |

Events:

- `agent_runner_crash` (unchanged) — first signal a lineage is in trouble.
- `agent_runner_restart_scheduled` — `{name, run_id, restart_count, delay_s}`.
- `agent_runner_restart` — successor handle spawned: `{name, old_run_id, new_run_id, restart_count, pid}`.
- `agent_runner_restart_failed` — successor handshake itself failed: `{name, run_id, restart_count, error}`.
- `agent_runner_restart_exhausted` — `max_restarts` hit: `{name, run_id, restart_count, max_restarts}`.

Race-safety notes:

- `_do_restart` re-checks the registry under `_handles_lock` and aborts if the slot no longer holds the original handle (covers the `stop()` raced with Timer-fire case).
- `stop()` cancels `_restart_timer` *before* the alive-check, so a lineage whose previous process already died is still properly killed off without a respawn.
- A failed spawn (handshake timeout, exception in `start`) does not chain into another retry — the lineage stops via `agent_runner_restart_failed`. Otherwise an import-time bug in the agent template would burn through `max_restarts` instantly.

Tests:

`pytest tests/test_daemon_runner_restart_policy.py` — 16/16 green in
~3 s. The wider F-4 regression
(`test_daemon_runner_supervisor.py` + `test_daemon_agent_methods.py` +
`test_daemon_runner_permission_routing.py`) is 55/55 green in ~13 s,
plus the F-4.4 e2e (4/4 in ~2 s) was rerun unchanged.

### §F-4.4 — End-to-end test with the real subprocess (landed)

`tests/e2e_f4_runner.py` covers the gap between the unit tests (which
use an inline `-c` subprocess that speaks the protocol) and a real
deployment. It spawns `python -m agent_runner --pipe` via
`runner_supervisor.start`, with the agent runtime stubbed in a tightly
scoped way:

- `agent_runner._pipe_main` checks `CHEETAHCLAWS_E2E_FAKE_AGENT=1` after
  the handshake and, if set, replaces `agent.run` with a small scripted
  generator (`TextChunk` → optional `PermissionRequest` → `TurnDone`).
  The hook is env-gated so production paths can never reach it.
- A companion env var `CHEETAHCLAWS_E2E_FAKE_PERMISSION=1` makes the
  stub emit one `PermissionRequest` so the test can drive the F-4.1
  routing through real IPC.

Cases:

1. `test_start_creates_agent_runs_row` — supervisor.start returns with
   the `agent_runs` row already inserted (sync write before reader
   thread starts, per the F-4 skeleton invariants).
2. `test_iteration_lands_in_sqlite_under_real_runner` — the real
   `_PipeAgentRunner._persist_record` emits `iteration_done` over IPC,
   the supervisor writes `agent_iterations` and bumps
   `agent_runs.last_iteration`. Tolerates 15 s for cold subprocess
   startup.
3. `test_graceful_stop_finalises_agent_runs_status` — `rs.stop()`
   delivers IPC "stop", runner exits, supervisor's reader finalises
   the row with `status='stopped'` and a non-null `ended_at`.
4. `test_real_runner_permission_routing_round_trip` — the stubbed
   `agent.run` yields a `PermissionRequest`, the real
   `_PipeAgentRunner._handle_permission_request` ships
   `permission_request` IPC, the supervisor opens a pending request in
   `PermissionStore` under originator `"alice"`, the test answers via
   `store.answer(..., "alice", {"approve": True})`, and the runner's
   iteration completes — `agent_iterations` row arrives, proving the
   approval flowed all the way back through the real subprocess.

All four pass in ~2.5 s on a developer laptop and ~3 s under the wider
F-4 regression suite (82 tests across supervisor unit, agent_methods
unit, permission routing, spike contract, dup-stop integration, and
e2e).

## F-5 — proactive watcher in daemon

**Scope.** `_proactive_watcher_loop` from `cheetahclaws.py` becomes a daemon-owned task.

**Acceptance.**
- `/proactive 5m` while daemon is running: setting persists, sentinel runs in daemon, survives REPL exit.
- Without daemon: unchanged.

### What landed

| File | Role |
|------|------|
| `daemon/proactive_state.py`     | `schema_meta`-backed KV for ``proactive.enabled`` / ``proactive.interval_s`` / ``proactive.last_tick_at``. Public surface: `get_state()`, `set_state()`, `disable()`, `tickle()`, `record_tick()`. Survives daemon restarts because it's on the same `sessions.db` the F-2 schema owns. |
| `daemon/proactive_scheduler.py` | Single background thread (`proactive-scheduler`). Ticks at `TICK_INTERVAL_S = 1.0`, reads `proactive_state`, publishes `proactive_tick` on the SSE bus when the idle threshold is crossed, and resets `last_tick_at` using one `now` reading so the event and the row share a clock. Mirrors F-3's `monitor.scheduler` (`owned_by_daemon`, `_foreign_daemon_running()`, interruptible `Event.wait` so shutdown doesn't stall). |
| `daemon/proactive_methods.py`   | `proactive.set` / `proactive.get` / `proactive.tickle` RPCs. Same param-validation conventions as `monitor.*`. Registered next to the other method modules in `DaemonState.__init__`. |
| `daemon/cli.py:cmd_serve`       | Starts the proactive scheduler after bind + discovery (so external clients can subscribe to `proactive_tick` *before* the first tick lands), with `owned_by_daemon=True`. Shutdown watcher stops it alongside `monitor.scheduler`. |
| `daemon/server.py`              | `DaemonState.__init__` registers `proactive_methods` alongside `system_methods`, `monitor_methods`, and `agent_methods`. |
| `commands/core.py:cmd_proactive`   | When a foreign daemon is registered, the slash command routes through the `proactive.set` / `proactive.get` RPCs instead of mutating `RuntimeContext`. On RPC failure, falls back to today's in-process path so a misbehaving daemon doesn't break the REPL UX. |
| `cheetahclaws.py:_proactive_watcher_loop` | Polls `_proactive_foreign_daemon_running()` and step-asides when a daemon owns the watcher — prevents double-fire across REPL + daemon. |

Event payload (`proactive_tick`):

```jsonc
{
  "interval_s":   300,          // configured idle threshold
  "last_tick_at": 1715520012.3, // when the user was last active
  "fired_at":     1715520312.8  // current time the tick was emitted
}
```

Consumers (REPL, bridges, future agents) decide what to do with it — typically inject the same "review previous messages" prompt the old in-REPL watcher used to fire. The scheduler itself never reaches into agent / bridge state; that coupling lives in the consumer, where it belongs.

### Tests

- `tests/test_daemon_proactive.py` — 20 cases across:
  - `proactive_state`: defaults, round-trip, validation (rejects 0/negative), `disable()` keeps interval, `tickle()` bumps timestamp, corrupt-row tolerance.
  - `proactive_scheduler`: disabled state silent, idle threshold publishes one event, `owned_by_daemon=True` disables foreign-check, `stop()` joins within 5 s, double-start returns False.
  - `proactive_methods`: round-trip, missing `enabled` rejected, non-int interval rejected, zero rejected, `tickle` bumps `last_tick_at`, `get` reports scheduler-running flag.
  - REPL step-aside helper: returns False for none / own pid, True for foreign pid.

Full daemon regression: 143 tests passing across schema, events, supervisor, agent_methods, monitor_methods, system_methods, permission routing, spike, discovery, CLI, the F-4 e2e, and the new F-5 module.

## F-6 / F-7 / F-8 — bridges in daemon (one PR per bridge)

**Scope per PR.** The named bridge (`telegram`, then `slack`, then `wechat`) runs inside daemon; incoming messages enter via `POST /rpc {"method":"session.send", …}`; outgoing replies come from an SSE subscription to that session's events.

**Per-bridge deliverables.**
- Move `bridges/<kind>.py` poll loop into a daemon-owned worker.
- Drop `RuntimeContext.<kind>_send` / `<kind>_input_event` and friends; replace with the API-mediated path.
- `bridge.start` / `bridge.stop` / `bridge.list` RPC methods.
- Persist bridge state to `bridges` table.

**Acceptance per bridge.**
- Phone message → daemon `session.send` → REPL/Web/another bridge can subscribe to the same session and see events.
- Bridge survives REPL exit; user can keep texting.
- Permission requests originating from a bridge-driven turn route only to that bridge for answer (per RFC 0001 §2).

F-7 depends on F-6 (shared scaffolding); F-8 the same.

### §F-6 — Telegram bridge skeleton (landed)

A POSIX + Windows-compatible skeleton landed under the
`CHEETAHCLAWS_ENABLE_F6` feature flag (off by default; REPL is
byte-for-byte unchanged). The Phase 1 surface is "everything F-4 #2
needs to deliver runner notifications, plus a clean lifecycle"; the
Phase 2 inbound refactor (phone → `session.send` → SSE-subscribed
clients) is documented separately at the end of this section.

Files:

| File | LoC | Role |
|------|-----|------|
| `daemon/bridge_supervisor.py`                 | ~430 | Lifecycle (`start` / `stop` / `stop_all` / `get` / `list_all`), per-kind feature-flag gate (`CHEETAHCLAWS_ENABLE_F6/7/8`), outbound `notify()` mailbox consumed by F-4 #2 + `bridge.send` RPC, `bridges` table upsert/finalize, redacted config snapshots in event payloads. |
| `daemon/bridge_methods.py`                    | ~135 | `bridge.start` / `bridge.stop` / `bridge.list` / `bridge.send` / `bridge.status` RPCs. Registered from `daemon/server.py:DaemonState.__init__` next to `agent_methods`. |
| `daemon/server.py`                            | +6   | `DaemonState.__init__` adds `bridge_methods.register`. The methods are exposed unconditionally so `bridge.list` always answers, but `bridge.start` itself enforces the per-kind flag. |
| `daemon/cli.py`                               | +6   | `_watch_shutdown` calls `bridge_supervisor.stop_all` before triggering the HTTP listener shutdown, so a SIGTERM cleanly tears down bridge worker threads. |
| `tests/test_daemon_bridge_supervisor.py`      | ~290 | 17 cases across feature flag, lifecycle (start/stop/double-start/dependency-on-F6), outbound `notify` (single + broadcast + empty drop), SQLite persistence (`list_persisted`, DB-failure tolerance), config redaction. |
| `tests/test_daemon_bridge_methods.py`         | ~210 | 10 RPC cases: registration, param validation across all five methods, start-list-stop round trip with redacted config in response, `bridge.send` outbound dispatch. |

Per-bridge flag matrix (per the "Bridge flag" decision):

| Env var                          | Effect                          |
|----------------------------------|---------------------------------|
| `CHEETAHCLAWS_ENABLE_F6`         | Telegram-in-daemon allowed.     |
| `CHEETAHCLAWS_ENABLE_F7`         | Slack-in-daemon (requires F-6). |
| `CHEETAHCLAWS_ENABLE_F8`         | WeChat-in-daemon (requires F-6).|

Acceptance status (Phase 1):

- ✅ **Bridge survives REPL exit.** The worker thread is daemon-owned;
  the REPL never owns its lifetime. `cheetahclaws daemon stop` shuts it
  down via `_watch_shutdown` → `bridge_supervisor.stop_all`.
- ✅ **Connection state persisted.** A row lands in the `bridges` table
  on every start/stop. `bridge.list` merges live handles + persisted
  rows so the caller sees disabled bridges from previous daemon runs.
  Tokens are redacted to last 4 chars before they hit the row /
  the wire / event payloads.
- ✅ **Outbound mailbox for F-4 #2.** `bridge_supervisor.notify(kind, text)`
  dispatches to the running bridge's send function (lazy-imported from
  `bridges/<kind>.py`, so the daemon and REPL share network code).
  `"*"` broadcasts to every live bridge.
- ✅ **REPL behaviour unchanged.** Default-off flag; the existing
  `/telegram` slash command still uses today's in-process supervisor.
- ⚠ **Phone → `session.send` (inbound API path).** Deferred to Phase 2
  — see below.

Bus events:

- `bridge_started` — payload includes redacted config.
- `bridge_stopped` — terminal state, with `last_error` for crash classification.
- `bridge_crash` — uncaught exception inside the worker.

### §F-6 — Phase 2 — inbound refactor (landed)

Phase 2 replaces the legacy `bridges/<kind>.py` supervisor (which
expects a REPL `session_ctx.run_query` callback) with a slim
daemon-driven loop that talks to the rest of the system via two events
on the bus:

```
phone ──── poll ────► bridge worker ───── publish session_inbound ────► event bus
                                                                          │
                                                          subscribers (REPL/Web)
                                                                          │
event bus ◄────── publish session_outbound ────── agent driver ◄──── consume inbound
   │
   └── subscribed by every Phase 2 bridge that matches session_id + target_bridges
       │
       └── handle.sender(config, text) ────► chat
```

New files / sections:

| File | Role |
|------|------|
| `daemon/session_methods.py` | `session.send(session_id, text, origin?, message_id?)` publishes `session_inbound`. `session.reply(session_id, text, target_bridges?, message_id?)` publishes `session_outbound`. `session.list_recent(limit=20)` reads the in-memory LRU. Permission-routing originator defaults to the RPC caller's `client_id` when no explicit `origin` is supplied. |
| `daemon/bridge_supervisor.py` | New `BridgeHandle.daemon_phase2` flag + `session_id()` helper (`tg:<chat_id>`, `sl:<channel>`, `wc:<user_id>`). When `daemon_phase2=True`, the worker bypasses the legacy supervisor and runs `_phase2_worker`, which: (a) subscribes to the bus, filters `session_outbound` by session_id + target_bridges, forwards to `handle.sender`; (b) runs a per-kind inbound poller (`_phase2_telegram_inbound`, `_phase2_slack_inbound`, `_phase2_wechat_inbound`) that re-uses the existing HTTP helpers in `bridges/<kind>.py` but publishes `session_inbound` on every new message instead of invoking `session_ctx.run_query`. |
| `daemon/bridge_methods.py` | `bridge.start` now accepts `daemon_phase2: bool` (default False). The bridge handle response surfaces `daemon_phase2` + `session_id` so the caller can confirm what mode the worker is in. |
| `daemon/server.py` | Registers `session_methods` on `DaemonState.__init__`. No feature flag — the methods are pure message-passing primitives and are safe on any daemon. |

Acceptance criteria revisited:

| Criterion (from the RFC's per-bridge "Acceptance" block) | Status |
|----------------------------------------------------------|:------:|
| Phone message → daemon `session.send` → REPL/Web/another bridge can subscribe to the same session and see events | ✅ via `session_inbound` events on the SSE feed |
| Bridge survives REPL exit; user can keep texting | ✅ (already from Phase 1; the daemon owns the worker thread) |
| Permission requests originating from a bridge-driven turn route only to that bridge for answer | ✅ via originator stamping — `session.send` writes `origin=<kind>:<session_id>` (or the explicit `origin` param) onto the event. The agent driver (REPL/Web) uses that string as the `originator` when minting a PermissionRequest; the existing `daemon/permission.py` `PermissionStore` already enforces "only this originator can answer." |

Bus events:

- `session_inbound` — `{session_id, text, origin, message_id, ts}`. Published by `session.send` *or* directly by a Phase 2 bridge worker on a new phone message. Identical shape either way so subscribers don't need to branch on source.
- `session_outbound` — `{session_id, text, target_bridges, message_id, ts}`. Published by `session.reply` (the agent driver's outbound surface). `target_bridges=null` is broadcast; a list of kinds restricts delivery. Phase 2 workers filter on `session_id == handle.session_id()` *and* `(target_bridges is None or handle.kind in target_bridges)`.

Tests:

- `tests/test_daemon_session_methods.py` — 13 cases (publish, LRU, param validation across `session.send` / `session.reply` / `session.list_recent`).
- `tests/test_daemon_bridge_phase2.py` — 7 cases: `session_id()` formatting (3, all three kinds), outbound delivery via `session_outbound` event matching session_id + target_bridges (2), inbound poller publishes `session_inbound` for a new Telegram message (1), `bridge.start` RPC passes `daemon_phase2` through and surfaces it on the response (1).

Phase 1 still works unchanged — `daemon_phase2=False` (the default) keeps the legacy `bridges/<kind>.py` supervisor as the worker, preserving the REPL-shaped behaviour for callers that haven't migrated.

What's *intentionally still REPL-driven* after Phase 2:

- **The agent loop itself.** The daemon publishes `session_inbound` and forwards `session_outbound`; it does not start agent turns. A REPL/Web/automation client consumes `session_inbound` events, runs the agent loop, and calls `session.reply` for each output. F-4's subprocess runner gives the cleanest deployment path: an originator that wants fully-headless operation runs `agent.start` for a template that subscribes to `session_inbound` and drives the conversation.
- **WeChat QR-login.** The daemon's inbound poller assumes `(token, base_url, user_id)` are already in the config; the QR handshake to mint them is still REPL-driven (`/wechat login`). Migrating QR-login into the daemon is a separate change, called out in §F-8 above.

### §F-7 — Slack bridge skeleton (landed)

F-7 is mostly *configuration*: the F-6 bridge supervisor already knows
how to dispatch a `kind="slack"` worker, and the existing
`bridges/slack.py` `_slack_supervisor(token, channel, config)` plugs
in alongside Telegram's. What's new for F-7:

- **Feature flag `CHEETAHCLAWS_ENABLE_F7`** (default off).
  `bridge_supervisor.enabled("slack")` reads this; `bridge.start kind="slack"`
  raises a clear error when it's missing — and a separate clear error
  when F-7 is on but F-6 isn't (the shared scaffolding has to be
  enabled for the daemon-side bridges feature surface to exist at all).
- **Outbound sender resolution.** `_resolve_sender("slack")` returns a
  thin wrapper over `bridges/slack.py:_slack_send(token, channel, text)`,
  so `bridge.send` and the F-4 `notify` IPC route through the same
  HTTP code the REPL uses.
- **`bridges` SQLite row.** Same schema as Telegram's; the
  `bridge.list` RPC merges Slack rows in.
- **Tests** in `tests/test_daemon_bridge_supervisor.py::TestSlackWorker`
  cover: F-6 dependency error, supervisor invocation with the expected
  `(token, channel, config)` shape, outbound sender wiring.

Acceptance status (Phase 1) — identical to F-6:

- ✅ Bridge survives REPL exit (daemon-owned thread).
- ✅ `bridges` row persisted on start/stop.
- ✅ Outbound `notify` mailbox accessible from F-4 runners.
- ✅ REPL `/slack` behaviour unchanged.
- ✅ Phone → `session.send` inbound path — landed via F-6 Phase 2 (this kind reuses `_phase2_worker` with its own `_phase2_<kind>_inbound`).

### §F-8 — WeChat bridge skeleton (landed)

Same shape as F-7, with two WeChat-specific wrinkles called out by
the existing `bridges/wechat.py`:

- **QR-login prerequisite.** WeChat's transport requires an authed
  `(token, base_url)` pair that today's `_wx_start_bridge` mints via
  a QR-code login. The daemon worker doesn't drive the QR flow itself
  — instead, the worker checks that `wechat_token` and
  `wechat_base_url` are already set in the config dict and exits
  cleanly with a clear `last_error` if either is missing. Operators
  are expected to run `/wechat login` (REPL) once to populate the
  config, after which the daemon can take over.
- **Per-user send.** WeChat doesn't have Telegram's chat_id /
  Slack's channel — outbound goes to a specific contact identified
  by `wechat_user_id` in the bridge config. `_resolve_sender("wechat")`
  threads this through `bridges/wechat.py:_wx_send(user_id, text, cfg)`.

Files / tests:

- **Feature flag `CHEETAHCLAWS_ENABLE_F8`** (default off; depends on
  F-6 enabled too).
- **Tests** in `tests/test_daemon_bridge_supervisor.py::TestWechatWorker`:
  F-6 dependency error, supervisor invocation with `(token, base_url,
  config)`, missing-config clean-exit path, outbound sender wiring.

Acceptance status (Phase 1) — identical to F-6:

- ✅ Bridge survives REPL exit (daemon-owned thread).
- ✅ `bridges` row persisted; secrets redacted before storage.
- ✅ Outbound `notify` mailbox accessible from F-4 runners.
- ✅ REPL `/wechat` behaviour unchanged.
- ✅ Phone → `session.send` inbound path — landed via F-6 Phase 2 (this kind reuses `_phase2_worker` with its own `_phase2_<kind>_inbound`).
- ⚠ QR-login *in-daemon* not yet supported (today the REPL still
  drives the auth handshake before the daemon can take ownership).

## F-9 — cost guardrail defaults under `serve`

**Scope.** When running under `cheetahclaws serve`, the four budget keys default to non-`None`:

```jsonc
{
  "session_token_budget": 200000,
  "session_cost_budget":   2.0,
  "daily_token_budget":   2000000,
  "daily_cost_budget":     20.0
}
```

REPL `--in-process` mode keeps `None` defaults (no surprise for existing users).

**Acceptance.**
- `cheetahclaws serve` started without overrides → `cheetahclaws daemon status` reports the four defaults.
- Agent runner exceeds per-session budget → status moves to `paused_budget`, `quota_warn` event emitted, runner pauses.
- `agent.resume` RPC with a new budget argument unpauses the runner.
- REPL without daemon: budgets still default to `None`.

### §F-9 — Cost-guardrail defaults (landed)

What landed:

| File | Role |
|------|------|
| `daemon/cli.py`              | New module-level `F9_SERVE_BUDGET_DEFAULTS` dict (200k tokens / $2 / 2M tokens / $20) plus `_apply_serve_defaults(config)` — pure function that flips any `None` budget key to its conservative default. Called from `cmd_serve` after `load_config()` and before `_bootstrap`, so the quota module sees the final values on first init. |
| `daemon/system_methods.py`   | New `system.status` RPC returning `{budgets: {…four keys…}, runners: int, bridges: int}`. The four keys are surfaced verbatim from `daemon_state.config` so `agent.resume`'s mutations are visible the next time someone polls. |
| `daemon/agent_methods.py`    | New `agent.resume` RPC accepting `budget_overrides: {key: value | null}`. Values are coerced (`int` for token budgets, `float` for cost). `null` resets to unlimited. Unknown keys → `-32602`. |
| `commands/daemon_cmd.py`        | `_status` now calls `system.status` after `system.ping` and prints a `budgets:` block plus live `runners` / `bridges` counts. Backward-compatible: an older daemon that doesn't speak `system.status` falls through silently (the `system.ping` line still appears). |
| `tests/test_daemon_f9_budgets.py` | 12 cases: `_apply_serve_defaults` (3, pure-function), `system.status` (3, returns budgets + counts, handles unlimited), `agent.resume` (6, merge, null=unlimited, unknown key, non-numeric, non-dict, noop empty). |

**Per-runner quota-pause hook (landed in second pass):**

| Stage | Where | Behaviour |
|-------|-------|-----------|
| Pre-iter check | `AgentRunner._run_loop` (top of every iteration body) | Calls `quota.check_quota(_session_id, _config)`. If raises `QuotaExceeded`, hands the exception to `_on_quota_exceeded`. |
| Base hook | `AgentRunner._on_quota_exceeded` | No-op. REPL path keeps today's behaviour — `agent.run` itself catches `QuotaExceeded` internally and yields a `[Quota exceeded …]` text chunk. |
| F-4 override | `_PipeAgentRunner._on_quota_exceeded` | Sends `{"op":"paused_budget", "reason": …}` IPC, sets `self.status='paused_budget'`, then blocks on `self._resume_event.wait()`. On wake sends `{"op":"resumed"}` and returns. |
| Supervisor inbound | `runner_supervisor._reader_loop` | New `paused_budget` branch: flips `handle.status='paused_budget'`, calls `_db_update_run_status` (updates `agent_runs.status` + error), publishes `quota_warn` on the bus. New `resumed` branch mirrors that back to `running` + publishes `agent_runner_resumed`. |
| Supervisor outbound | `runner_supervisor.resume(name)` | Public function. Sends `{"op":"resume"}` IPC frame to the named runner. Idempotent — a runner that wasn't paused absorbs the frame in its control loop. |
| RPC | `agent.resume` | Now accepts optional `name`. When supplied, calls `runner_supervisor.resume(name)` after merging budget overrides. Returns `{"budgets": {…}, "resumed": bool|null}` so the caller can confirm both the budget bump and the per-runner wake-up landed. |
| Control loop | `_pipe_main._control_loop` | New `resume` handler sets `runner._resume_event`. The `stop` handler also sets the event so a stop arriving while paused unblocks the runner cleanly instead of waiting up to 30 minutes for an IPC frame that's never coming. |

Events on the bus:

- `quota_warn` — `{name, run_id, reason}` — fired on the supervisor's first sighting of `paused_budget`.
- `agent_runner_resumed` — `{name, run_id}` — fired when the runner re-enters `running`.

The pre-iter check is **read-only** — it doesn't write to the quota file or consume tokens. The actual budget enforcement still happens inside `agent.run` on every API call (`record_usage` after each turn, `check_quota` before the next). The runner-side hook just adds a fast-fail check at iteration boundaries so a paused runner can sit cheaply on a `wait_event` instead of repeatedly bouncing off the quota inside `agent.run`.

Tests for the quota-pause hook in `tests/test_daemon_quota_pause.py` (2 cases): full IPC roundtrip (`paused_budget` → supervisor `quota_warn` → `resume` → `resumed` → `agent_runner_resumed`), and `runner_supervisor.resume("no-such-runner")` returns False. Plus 2 new cases in `tests/test_daemon_f9_budgets.py`: `agent.resume(name=…)` calls `runner_supervisor.resume`, and an empty `name` field is rejected with `-32602`.

Cost-default knobs operators can override:

```jsonc
// ~/.cheetahclaws/config.json (overrides win over F-9 defaults)
{
  "session_token_budget": 500000,   // 500k tokens per session
  "session_cost_budget":  5.0,      // $5 per session
  "daily_token_budget":   null,     // explicit "unlimited" survives F-9
  "daily_cost_budget":    100.0
}
```

REPL invariant: `cheetahclaws` (no `serve`) still imports `config`
directly, so the four budget keys remain `None` (unlimited) — F-9 only
fires inside `cmd_serve`. Verified by the existing
`tests/test_daemon_cli.py` round-trip plus the new `_apply_serve_defaults`
unit tests (which don't depend on a daemon being up).

## Cross-cutting conventions

- **Tests.** Every PR ships unit tests; F-1, F-3, F-4, F-6/7/8 also ship `tests/e2e_daemon_<area>.py`.
- **Docs.** Every PR updates the relevant section in `docs/architecture.md`. The "Daemon" header is created by F-1; subsequent PRs append.
- **Config keys.** New keys go in `config.DEFAULTS`; documented in `docs/architecture.md`.
- **Backwards compatibility.** Users who never run `cheetahclaws serve` see no behavior change until the eventual default flip — that flip is out of scope here and tracked in [#68](https://github.com/SAIL-Research-Lab/cheetahclaws/issues/68) as the "Phase D" item.

## Updating this document

When a PR lands, change its **Status** in the index from `TODO` to `MERGED #<pr>`. If acceptance criteria evolve during a PR, update the per-PR section in the same PR — do not let this doc drift from the implementation.
