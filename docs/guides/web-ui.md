# Web UI Guide

CheetahClaws ships with a production-ready browser UI built on a pure Python stdlib HTTP server plus ten small vanilla-JS modules — no Node.js, no bundler, no build step. This guide covers installation, accounts, the Chat UI, the PTY terminal, the full HTTP API, observability, and how the pieces fit together.

<div align="center">
 <img src="../media/demos/web_demo.gif" width="850" alt="Web UI demo — sidebar, tool cards, approval prompts, markdown streaming"/>
</div>

---

## Install and launch

```bash
# Install the web extras (SQLAlchemy, bcrypt, PyJWT):
pip install 'cheetahclaws[web]'

# Launch (auto-picks a free port if 8080 is taken):
cheetahclaws --web

# Explicit port / host / no-auth:
cheetahclaws --web --port 9000
cheetahclaws --web --host 0.0.0.0             # open to the local network
cheetahclaws --web --no-auth                  # localhost dev only — skips login

# Pin a model at launch (persists to ~/.cheetahclaws/config.json):
cheetahclaws --web --model custom/qwen2.5-72b
```

`--model` in `--web` mode is persisted to disk before the server starts, because every request handler reloads config from `~/.cheetahclaws/config.json`. To switch models without restarting, use the Settings panel in the Chat UI or send `/model <name>` in the message box.

> **Prerequisite for `custom/<model>`.** The `custom/` provider is an OpenAI-compatible client with **no built-in base URL** — it always reads `CUSTOM_BASE_URL` (env var) or `custom_base_url` (in `~/.cheetahclaws/config.json`). If both are empty you'll get `ValueError: custom provider requires a base_url`. Quick setup before the launch line above:
>
> ```bash
> export CUSTOM_BASE_URL=http://localhost:8000/v1   # don't forget the /v1 suffix
> export CUSTOM_API_KEY=EMPTY                       # vLLM ignores it, but the OpenAI SDK needs a non-empty string
> ```
>
> See [`recipes.md` → "Alternative: self-hosted vLLM …"](recipes.md#alternative-self-hosted-vllm-or-any-openai-compatible-endpoint-via-the-custom-provider) for the full vLLM walkthrough (server-side flags, tool-call parser, `/v1/models` discovery, troubleshooting table).

Startup banner:

```
  CheetahClaws Web Terminal
  ────────────────────────────────────────
  Terminal: http://localhost:8080
  Chat UI:  http://localhost:8080/chat
  Terminal pwd: e_7rJ4  (for / index page only)
  Chat UI:  first visit will prompt you to register an admin account
  ────────────────────────────────────────
  Press Ctrl+C to stop
```

Open the Chat UI URL and you'll see a **Create your first account** form on the very first visit (`/api/auth/bootstrap` reports `has_users: false`); after that it switches to **Sign in**. The **first registered user is marked admin**.

The leaping-cheetah favicon is served at `/favicon.ico` (root) and `/static/favicon.png`.

---

## Accounts and authentication

Two completely separate auth flows run side-by-side on the same port:

| Page | Auth | Cookie | Created |
|------|------|--------|---------|
| `/chat` (Chat UI) | `username + password` → bcrypt verify → **JWT** | `ccjwt` | Users register themselves |
| `/` (PTY terminal) | One-time generated password | `cctoken` | Printed on startup |

Chat-UI auth endpoints:

```
GET  /api/auth/bootstrap   →  { has_users, no_auth }
POST /api/auth/register    →  { username, password }  (first user becomes admin)
POST /api/auth/login       →  { username, password }
POST /api/auth/logout      →  clears ccjwt
GET  /api/auth/whoami      →  { user: { id, username, is_admin, created_at } }
```

- Password hashing: **bcrypt** (called directly — passlib was dropped because it crashes on `bcrypt>=4.1`; existing `$2b$...` hashes remain compatible).
- JWT: **PyJWT**, HS256, **7-day TTL**. Signing secret is generated once and persisted to `~/.cheetahclaws/web_secret` with `O_CREAT \| O_EXCL` + 0o600. If the file's mode is later loosened (world-readable), the loader refuses to read it and prints a clear `chmod 600` fixup message. Override with the `CHEETAHCLAWS_WEB_SECRET` env var (recommended in production — secret never touches disk).
- Cookie: `ccjwt=<jwt>; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800`.
- `--no-auth` short-circuits auth to a synthetic single-user `user_id=1` for localhost testing.

Every other `/api/*` route requires a valid `ccjwt` cookie → `401 { "error": "auth required" }` otherwise.

### CSRF (double-submit cookie)

`SameSite=Strict` on the JWT cookie is the first-line defence. As a second line, every state-changing request (POST/PUT/PATCH/DELETE) must carry an `X-CSRF-Token` header that matches a non-HttpOnly `ccsrf` cookie:

- The server mints `ccsrf=<32B>; Path=/; SameSite=Strict; Max-Age=86400` on the first GET that arrives without one — usually the initial page load.
- The bundled frontend's `web/static/js/csrf.js` monkey-patches `window.fetch` so the header is added automatically for every state-changing call. Custom clients (curl, integration scripts) need to read the cookie and echo it back.
- Exempt paths (no CSRF check, because the user has no cookie yet): `/api/auth/bootstrap`, `/api/auth/register`, `/api/auth/login`, `/api/auth/logout`, `/api/auth` (legacy terminal-password endpoint).
- Mismatch ⇒ `403 { "error": "csrf token mismatch" }`.

### Terminal session ownership

The PTY terminal (`/`) and the Chat UI (`/chat`) both can spawn JWT-authenticated PTY sessions via `/api/session`. Each session is tagged with the creating user's JWT `sub` at creation time:

| Auth flow | `owner_uid` on the session | Effect |
|---|---|---|
| `cctoken` password only (legacy terminal) | `None` | Any holder of the password can attach (shared secret model). |
| `ccjwt` cookie present | The JWT's `sub` | `/api/stream`, `/api/input`, `/api/resize` reject every other user with `403 not session owner` even if they guess the `sid`. |

This means in a multi-user web deployment, user A cannot hijack user B's terminal by knowing or guessing B's session id.

---

## Persistence

All session metadata and message history live in SQLite, not RAM. Server restarts do **not** lose anything.

- **DB file:** `~/.cheetahclaws/web.db` (0600). Override with `CHEETAHCLAWS_WEB_DB`.
- **Five tables** (SQLAlchemy 2.x, declared in `web/models.py`):

| Table | Columns | Notes |
|-------|---------|-------|
| `users` | `id`, `username`, `password_hash`, `is_admin`, `created_at` | Username unique + indexed |
| `folders` | `id`, `user_id` (fk, cascade), `name`, `created_at` | unique(user_id, name) |
| `chat_sessions` | `id` (12-hex pk), `user_id` (fk), `title`, `created_at`, `last_active`, `config_json`, `folder_id` (fk, nullable) | `last_active` and `folder_id` indexed |
| `messages` | `id`, `session_id` (fk, cascade), `role`, `content`, `tool_calls_json`, `created_at` | |
| `api_credentials` | `id`, `user_id` (fk), `provider`, `api_key`, unique(user_id, provider) | Future: encrypt at rest |

Schema is bootstrapped on first run via `Base.metadata.create_all`. **In-place migration for upgraders:** `init_db()` runs a `PRAGMA table_info(chat_sessions)` probe at startup; if `folder_id` is missing it `ALTER TABLE`s the column in place and adds the index. No Alembic yet — for any other model change, drop the DB (or migrate by hand) and restart.

### Session lifecycle

1. User submits a prompt with no `session_id` → server creates a row in `chat_sessions` (title `"New chat"`) + starts an in-memory `ChatSession`.
2. First user message auto-titles the session (up to 60 chars of the first line).
3. Every assistant + user message is persisted to `messages` via a write-through cache.
4. On restart, the in-memory cache is empty. When the UI asks for a session the server **hydrates from DB**: loads the row, re-reads messages, re-creates the agent state.
5. Cross-user isolation: both `repo.get_session(id, user_id)` (DB) and `get_chat_session(id, user_id, ...)` (in-memory cache hit) enforce ownership — a user can never see another user's session, even if they guess the id.

---

## The Chat UI (`/chat`)

The thin `chat.html` (~550 lines of HTML + CSS) loads ten small JS modules in order:

```
web/static/js/csrf.js       — patches window.fetch to echo the CSRF cookie on writes (loaded first)
web/static/js/chat.js       — ChatApp class, constructor, send(), WS, SSE, event dispatch
web/static/js/util.js       — _escapeHtml, _fmtRelTime, _renderMd (with XSS strip), _scrollBottom
web/static/js/auth.js       — bootstrap, doAuth, whoami, logout, _fetchAuth
web/static/js/sidebar.js    — loadSessions, _renderSessionList, _showSessMenu, rename/delete/export/new/switch
web/static/js/tools.js      — _addToolCard, _completeToolCard, activity indicator, input requests, menus
web/static/js/approval.js   — _showApproval / _resolveApproval / approve(granted)
web/static/js/settings.js   — theme, toggleSettings, _renderModels, updateConfig, setApiKey
web/static/js/welcome.js    — dashboard cards (Core / Agent / Session / Multi-Model / Dev / Bridges / Media)
web/static/js/init.js       — instantiates `app = new ChatApp()`, wires input handlers
```

Every module except `chat.js` and `init.js` extends the prototype:

```js
Object.assign(ChatApp.prototype, { method1, method2, ... });
```

This way `app.foo()` call sites don't change when methods move files, and there's no bundler.

### Layout

- **Left sidebar** — folder tree + session list (title + relative time + message count + busy dot), search box (client-side filter), header buttons `+ Folder` / `Select` / `+ New`, optional batch action bar at the bottom (when in select mode), footer with current username + Sign out.
- **Center** — scrollable chat area with user bubbles, assistant bubbles (Markdown rendered via `marked.js` with `<tag>` stripping for XSS), tool cards, approval cards, activity indicator.
- **Top bar** — title (with `· in <Folder>` breadcrumb when an active folder is selected), status dot, theme toggle (☀/☾), settings gear (⚙).
- **Resizable divider** — drag the 4-px handle between the sidebar and main panes to set a custom width (200–600 px clamp). Double-click the handle to reset to the default. Width persists across reloads via `localStorage["cc-sidebar-w"]`. Hidden under `@media (max-width: 768px)` so the mobile drawer keeps its swipe behavior.

### Session management

| Action | UI | API |
|--------|-----|-----|
| List | Sidebar auto-loads | `GET /api/sessions` (rows include `folder_id`) |
| Switch | Click a session | `GET /api/sessions/{id}` (replays messages) |
| New | `+ New` button (or just type a message) | `POST /api/prompt` with empty `session_id`; if a folder is active, the new session is auto-PATCHed into it |
| Rename | Right-click → Rename | `PATCH /api/sessions/{id}` `{ "title": "..." }` |
| Delete | Right-click → Delete | `DELETE /api/sessions/{id}` |
| Move to folder | Drag onto a folder row, or right-click → `Move to: ...` | `PATCH /api/sessions/{id}/folder` `{ "folder_id": int\|null }` |
| Export | Right-click → Export Markdown | `GET /api/sessions/{id}/export` (downloads `chat-<id>.md`) |
| Search | Search box | Client-side over `_sessions` array (title + id) |
| Batch select | "Select" button → click rows → action bar | (per-row HTTP via batch endpoints below) |
| Batch delete | Select mode → Delete | `POST /api/sessions/batch_delete` `{ "ids": [...] }` |
| Batch export | Select mode → Export | `POST /api/sessions/batch_export` `{ "ids": [...] }` (downloads `chats-N-sessions.md`) |
| Select all (filtered) | Select mode → "Select all" link | Honors current search filter |

### Folders & active-folder context

Folders are flat (no nesting) and per-user. A session belongs to **at most one** folder; sessions without a folder live in an "Ungrouped" pseudo-section.

**Creating, renaming, deleting**

- `+ Folder` button in the sidebar header → prompts for a name.
- Right-click a folder header → `Rename...` or `Delete folder`. Deleting a folder **does not** delete its sessions; they're reparented to Ungrouped (the repo layer NULLs the column explicitly because `PRAGMA foreign_keys` is off in this engine, so `ON DELETE SET NULL` wouldn't fire on its own).
- Folder name uniqueness is enforced per user — duplicate creates return `409 Conflict`.

**Moving sessions**

Two interactions cover the same `PATCH /api/sessions/{id}/folder` endpoint:

- **Drag-and-drop** — every session row is `draggable="true"`. Folder headers and the Ungrouped header are drop targets and light up in accent colour while the drag is over them.
- **Right-click context menu** — each session has a flat `Move to:` section listing every folder, plus `(Ungrouped)` (only when the session is currently in a folder) and `+ New folder…` (creates a folder from a prompt and moves the session in a single click).

**Active-folder context (ChatGPT-style)**

Clicking a folder **name** (not the disclosure arrow) "enters" that folder:

- The folder row gets accent highlighting (`.active-folder`).
- The topbar title grows a `Chat · in <Folder>` breadcrumb so you always know which scope you're in.
- **`+ New` and direct-typing auto-create both drop the new session into the active folder** — same UX as OpenAI Projects.
- Switching to a session in another folder syncs the active context to that folder.
- Clicking the active folder again (or clicking an Ungrouped session) exits the context.
- The disclosure arrow (`▾`/`▸`) is wired separately — clicking the arrow only toggles collapse, never changes the active folder.

State persists across reloads (`localStorage["cc-active-folder"]`, `localStorage["cc-collapsed-folders"]`); a deleted folder auto-clears its active reference on next render.

**Schema migration for upgraders.** `init_db()` runs a one-shot `PRAGMA table_info(chat_sessions)` probe and `ALTER TABLE` adds the `folder_id` column on databases that predate folders. No Alembic; existing rows keep all data and start out as Ungrouped.

### Theme (light / dark / system)

Light is the default; when no explicit choice is stored, CSS media query `@media (prefers-color-scheme: dark)` swaps in the dark palette automatically. The toggle button **cycles** `system → light → dark → system ...`:

- `localStorage.cc-theme == null` → no `data-theme` attribute → CSS picks based on OS.
- `localStorage.cc-theme == 'light'` or `'dark'` → `data-theme` attribute forces that theme regardless of OS.

An inline `<script>` in `<head>` applies the stored theme before first paint to avoid a flash of the wrong theme on load.

### Tool cards, permissions, activity

Streaming events from the agent are rendered as distinct UI components, not raw text. See the WebSocket events table below.

---

## PTY terminal (`/`)

A full xterm.js (v5.5) terminal emulator in the browser — identical to running `cheetahclaws` in a native shell. 100% feature parity.

- WebSocket transport with automatic SSE fallback (works through VS Code port forwarding and other proxies that break `Upgrade: websocket`).
- Fit addon + web-links addon + 256-color ANSI.
- Gated by the one-time generated password (the `Terminal pwd:` line in the startup banner). **This is a completely different auth system from the Chat UI.**

---

## HTTP API reference

All `/api/*` routes other than `/api/auth/*` and the ops endpoints require a valid `ccjwt` cookie. Ops endpoints (`/health`, `/metrics`) are unauthenticated so Prometheus / k8s probes can hit them.

### Auth

| Route | Method | Body | Response |
|-------|--------|------|----------|
| `/api/auth/bootstrap` | GET | — | `{"has_users": bool, "no_auth": bool}` |
| `/api/auth/register` | POST | `{username, password}` | `{ok:true, user}` + `Set-Cookie: ccjwt=...` (first user is admin; username ≥ 2 chars, password ≥ 6) |
| `/api/auth/login` | POST | `{username, password}` | `{ok:true, user}` + cookie, or `401 {"error":"invalid credentials"}` |
| `/api/auth/logout` | POST | — | `{ok:true}` + `Set-Cookie: ccjwt=; Max-Age=0` |
| `/api/auth/whoami` | GET | — | `{user: {id, username, is_admin, created_at}}` or `401` |

### Chat

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/prompt` | POST | Submit a prompt or slash command. If the body's `prompt` starts with `/` and the request has `Accept: text/event-stream`, the server keeps the connection open and streams SSE events until the command finishes. Otherwise returns `{session_id, events}` inline. |
| `/api/events` | WS | Real-time structured event stream for a session. First client frame: `{"session_id": "..."}`. Server streams `text_chunk`, `tool_start`, `tool_end`, `permission_request`, `turn_done`, etc. |
| `/api/approve` | POST | Respond to a `permission_request`. Body: `{session_id, granted: bool}`. |

### Sessions

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/sessions` | GET | `{sessions: [{id, title, created_at, last_active, message_count, busy, folder_id}, ...]}` — this user only |
| `/api/sessions/{id}` | GET | `{id, title, messages, config, busy}` — messages include `tool_calls` |
| `/api/sessions/{id}` | PATCH | `{title}` — rename (returns 400 on empty) |
| `/api/sessions/{id}` | DELETE | Remove session + cascade messages |
| `/api/sessions/{id}/folder` | PATCH | `{folder_id: int\|null}` — move session into a folder, or set `null` for Ungrouped. Cross-user folders return 404. |
| `/api/sessions/{id}/export` | GET | Download conversation as Markdown (`Content-Disposition: attachment; filename="chat-<id>.md"`) |
| `/api/sessions/batch_delete` | POST | `{ids: [...]}` → `{deleted, failed: [...], requested}`. IDs the caller doesn't own are skipped (counted as `failed`), never erased — same ownership check as the single-session DELETE. |
| `/api/sessions/batch_export` | POST | `{ids: [...]}` → combined Markdown attachment (`chats-N-sessions.md`). Empty list returns 400; if no requested id is owned by the caller, returns 404. |

### Folders

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/folders` | GET | `{folders: [{id, name, created_at, session_count}, ...]}` — this user only |
| `/api/folders` | POST | `{name}` → `{id, name, created_at, session_count}`. Duplicate name for the same user returns `409 Conflict`; missing/empty name returns 400. |
| `/api/folders/{id}` | PATCH | `{name}` → `{ok: true, name}` or 404 if not yours / duplicate. |
| `/api/folders/{id}` | DELETE | `{ok: true}` — sessions inside are reparented to Ungrouped (`folder_id = NULL`), not deleted. Cross-user delete returns `{ok: false}` (matches the per-session DELETE convention). |

### Config / models

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/config?sid=...` | GET | Read safe config keys for a session |
| `/api/config` | PATCH | `{session_id, config: {key:value, ...}}` — writable keys: `model`, `permission_mode`, `verbose`, `thinking`, `thinking_budget`, `max_tokens`, `tool_profile` (`full`/`standard`/`research`/`orchestration`; an invalid value returns `400`), plus per-provider API keys (session-only, not persisted) |
| `/api/models` | GET | `{providers: [{provider, models, context_limit, needs_api_key, has_api_key}, ...]}` |

### Ops

| Route | Method | Response |
|-------|--------|----------|
| `/health` | GET | `200 {"ok": true, "db": "ok", "uptime_s": ...}` or `503` with `db_err` if the DB is unreachable |
| `/metrics` | GET | Prometheus v0.0.4 text. Exports `cheetahclaws_uptime_seconds`, `cheetahclaws_requests_total`, `cheetahclaws_requests_4xx`, `cheetahclaws_requests_5xx`, `cheetahclaws_auth_logins_total`, `cheetahclaws_auth_logins_failed`, `cheetahclaws_auth_registrations_total`, `cheetahclaws_users_total`, `cheetahclaws_ws_connections_total` |

### WebSocket events

Frames are newline-delimited JSON objects with `{type, data, ts}`.

| `type` | `data` fields | When |
|--------|---------------|------|
| `text_chunk` | `text` | Assistant streams text |
| `thinking_chunk` | `text` | Extended thinking chunk |
| `tool_start` | `name`, `inputs` | Tool invocation starts |
| `tool_end` | `name`, `result`, `permitted` | Tool finished / denied |
| `permission_request` | `description` | Agent asks for approval |
| `permission_response` | `granted` | After user answers |
| `turn_done` | `input_tokens`, `output_tokens` | End of a turn |
| `status` | `state: "running" \| "idle"` | Status transitions |
| `command_result` | `command`, `output` | Slash command finished |
| `interactive_menu` | `menu`, `items` | `/ssj` etc. |
| `input_request` | `prompt`, `command`, `placeholder` | Command wants a parameter |
| `error` | `message` | Something blew up |

---

## Observability

### Structured JSON logging

Every HTTP response emits one JSON record on stderr through the `web.server` logger:

```json
{"ts":1776368300.054,"level":"info","logger":"web.server","msg":"req","method":"POST","path":"/api/auth/login","status":200,"dur_ms":259,"user_id":1,"peer":"127.0.0.1:45122"}
```

Other structured events: `server_start`, `server_stop`, `register`, `login`, `login_failed`, `db_init_failed`, `message persist failed` (from `web.api`). Level controlled by `CHEETAHCLAWS_LOG_LEVEL` (default `INFO`; set `DEBUG` for verbose).

Child loggers (`web.server`, `web.auth`, `web.api`, `web.db`) all inherit the JSON formatter set up in `web/logging_setup.py`.

### Metrics

Point Prometheus at `/metrics` — it returns v0.0.4 text format. The in-process counters are updated inline by `_send_http` (status-coded buckets) and the auth routes (login_total / login_failed / registrations_total). `users_total` reads from the DB.

### Testing

```bash
pytest tests/test_web_api.py -v
```

31 end-to-end tests spin the real server in a background thread on a random port, truncate the DB between tests, and drive it with `httpx`. Coverage includes auth, session CRUD, batch delete/export, folders (CRUD, duplicate name 409, move-into-folder, delete-preserves-as-ungrouped, cross-user isolation), `folder_id` shape on session list, and config/CORS. No mocks — real SQLite, real bcrypt, real JWT. Runs in ~10s.

---

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `CHEETAHCLAWS_WEB_DB` | `~/.cheetahclaws/web.db` | SQLite file path |
| `CHEETAHCLAWS_WEB_SECRET` | persisted to `~/.cheetahclaws/web_secret` | JWT HS256 signing key |
| `CHEETAHCLAWS_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `CHEETAHCLAWS_WEB_SERVER` | set by `start_web_server` to `1` | Guards against recursive `--web` launches via shell aliases |

---

## Architecture notes

```
web/
  server.py           — stdlib HTTP + WebSocket (RFC 6455) + SSE, routing, auth gates
  api.py              — ChatSession (agent-generator → event broadcast), slash-cmd bridge
  auth.py             — bcrypt password hashing + PyJWT encode/decode + cookie helpers
  db.py               — SQLAlchemy engine, session_scope(), repo (CRUD helpers)
  models.py           — User, ChatSessionRow, Message, ApiCredential ORM
  logging_setup.py    — JsonFormatter + in-process counter snapshot
  chat.html           — the shell (thin — most logic moved to static/js/*.js)
  static/
    favicon.png, favicon.ico
    js/chat.js, util.js, auth.js, sidebar.js, tools.js,
       approval.js, settings.js, welcome.js, init.js
  marked.min.js       — Markdown renderer (bundled)
  xterm.min.js / .css — Terminal emulator + styles (bundled)
```

Key design choices:

- **Pure stdlib HTTP server.** Raw sockets, manual header parsing, RFC 6455 WebSocket implementation. No Flask / FastAPI / aiohttp. The only new runtime deps are the three chat-UI extras (`sqlalchemy`, `bcrypt`, `PyJWT`).
- **In-process agent.** The Chat UI runs `agent.run()` directly (no PTY subprocess). A `queue.Queue` fans events out to WS subscribers; a 500-event ring buffer lets late-joining subscribers replay missed events.
- **Single-source slash-command events.** `handle_slash_sync` (HTTP POST `/api/prompt`) and `handle_slash_stream` (SSE) deliver synchronous slash-command events through their own response channel only — **not** also via the live WS broadcaster. Re-broadcasting would duplicate every reply in the same client (which iterates `data.events` AND fires `_handleEvent` from `ws.onmessage`). Background-thread events (sentinel flows, agent runs spawned from a slash command) still go through `_broadcast` normally because the helpers restore it in `finally` before the worker thread emits anything.
- **In-place schema migration for `folder_id`.** `init_db()` runs a `PRAGMA table_info(chat_sessions)` check after `Base.metadata.create_all` and `ALTER TABLE`s the column in for older databases. SQLite's `PRAGMA foreign_keys` is left **off** (matching the pre-existing engine config), so the `ON DELETE SET NULL` declared on the FK does not fire automatically — `repo.delete_folder` instead issues an explicit `UPDATE chat_sessions SET folder_id = NULL` before deleting the folder row. Cascade deletes on `User → ChatSessionRow → Message` continue to work because they're driven by SQLAlchemy ORM `cascade="all, delete-orphan"` rather than DB-level constraints.
- **Two-step session-into-folder placement.** New sessions are still created via the unchanged `POST /api/prompt` (empty body) flow, which always returns a session with `folder_id = NULL`. The Chat UI reads its active-folder context (`localStorage["cc-active-folder"]`) and immediately follows up with `PATCH /api/sessions/{id}/folder`. Two requests, but the contract for non-folder-aware clients (e.g. CLI tooling that POSTs to `/api/prompt`) stays identical.
- **Write-through persistence.** Messages live in memory (for fast replay) AND SQLite (for survival). Config changes PATCH both.
- **Two cookies on the same origin.** Chat UI uses `ccjwt` (7-day JWT), PTY terminal uses `cctoken` (one-time password). The browser sends both; each route only reads the one it cares about.
- **Thread-local request context** for access logs: `_req_ctx` holds method/path/start_ts/user_id/peer. `_send_http` reads it once per response and logs + increments counters.
- **Auto-port** with explicit-port override: if `--port` is omitted, try 8080, fall back to `bind(host, 0)` to let the kernel pick any free port. Explicit `--port N` binds exactly N or fails.
- **ETag + `no-cache`** on JS/CSS/HTML so edits show up on plain reload (no hard-refresh needed), while images/fonts keep 24h cache.

---

## Troubleshooting

**"No users, please register" on first visit**
That's expected. Fill in the `Create your first account` form; the first user becomes admin.

**401 on every API call**
The `ccjwt` cookie is missing or expired. Refresh the page; the Chat UI will pop the login overlay automatically.

**8080 is taken**
`cheetahclaws --web` (with no `--port`) auto-falls back to a free port — check the banner for the real URL. If you must use 8080, stop the conflicting process first.

**I changed a JS file but the browser shows the old version**
Normal reload now works (we send `Cache-Control: no-cache, must-revalidate` + weak ETag). If it's really stuck, `Ctrl+Shift+R` / `Cmd+Shift+R` forces a bypass.

**`/chat` loads but every JS/CSS asset is 404** (`/marked.min.js`, `/static/js/chat.js`, …)
Two known causes:

1. **Non-editable install missing package data.** The chat UI's static files live in `web/static/js/` as setuptools package-data. If you installed CheetahClaws non-editable (`pip install .` or `pip install cheetahclaws`) with an old `setuptools` (< 62) or a stale build cache, the `web/static/` subtree may not have been copied into `site-packages/web/`. Reinstall editable (`pip install -e '.[web]'`) or upgrade build tooling (`pip install -U pip setuptools build` then reinstall).
2. **Install path contains a hidden directory** (e.g. `~/.venv/`, `~/.local/`). Older versions of `web/server.py` rejected any served file whose absolute path contained a dot-prefixed segment, even when that segment was in the install prefix and not the requested file. Fixed on `main` — the dotfile guard now only inspects path segments inside the `web/` package itself.

If you're hitting this in Docker specifically, see [docs/guides/docker.md](docker.md#custom-dockerfile-pitfalls) for the Dockerfile-specific variant.

**Lost my admin password**
Blow away the SQLite DB and re-register: `rm ~/.cheetahclaws/web.db` then restart. You'll lose all chat history — for real recovery, open the DB with any SQLite client and rewrite the `password_hash` (`bcrypt.hashpw(b"newpass", bcrypt.gensalt()).decode()`).

**Can't connect from another device**
Start with `--host 0.0.0.0`. Your firewall must also allow the port, and mobile devices need to reach the host by IP (not `localhost`).

**Prometheus scrape is failing**
`/metrics` returns plain text at `text/plain; version=0.0.4`. It's unauthenticated and works without the `ccjwt` cookie. If it 401s, you're hitting `/api/metrics` instead of `/metrics` — note the leading segment.

**"DB init failed" on startup**
The log line is JSON with the full exception. Usually a file-permission issue on `~/.cheetahclaws/web.db` or a broken install of SQLAlchemy. Verify `pip install 'cheetahclaws[web]'` completed without errors.

**Slash command output appears twice in the Chat UI but once in the terminal**
Fixed (May 10, 2026). The chat client used to receive every synchronous slash-command event through both the HTTP `data.events` payload **and** the WS broadcast, so each reply rendered twice; the terminal has no parallel WS path so it always rendered once. If you see this on an older build, pull `web/api.py` from `main` — `handle_slash_sync` and `handle_slash_stream` no longer re-broadcast events to WS subscribers when a single-client response channel is already in use. See [Issue #111](https://github.com/SAIL-Research-Lab/cheetahclaws/issues/111).

**`ValueError: custom provider requires a base_url. Set CUSTOM_BASE_URL env var or run: /config custom_base_url=http://...`**
You launched with `--model custom/<name>` (e.g. against a local vLLM) but never told CheetahClaws where the server lives. The `custom/` provider has no default endpoint — it's a generic OpenAI-compatible client. Fix either way:

```bash
# Env-var form (one-shot for this terminal):
export CUSTOM_BASE_URL=http://localhost:8000/v1   # /v1 suffix is mandatory
export CUSTOM_API_KEY=EMPTY                       # any non-empty string; vLLM ignores it
cheetahclaws --web --model custom/qwen2.5-72b

# Persisted form (saved to ~/.cheetahclaws/config.json):
cheetahclaws
/config custom_base_url=http://localhost:8000/v1
/config custom_api_key=EMPTY
/model custom/qwen2.5-72b
```

Verify the server is actually reachable first: `curl http://localhost:8000/v1/models` should list the model whose name matches the suffix after `custom/`. Full walkthrough including vLLM launch flags and tool-call setup: [recipes.md → "Alternative: self-hosted vLLM …"](recipes.md#alternative-self-hosted-vllm-or-any-openai-compatible-endpoint-via-the-custom-provider).

**`cheetahclaws --web --model X` runs but the agent calls a different model**
Fixed (May 10, 2026). The CLI override branch only ran in the interactive-REPL path, so `--web` ignored `--model` and the per-request `load_config()` call kept using the previous saved value (typically the last model you ran in the REPL). Symptom: `404: model 'X' does not exist` against your `custom_base_url` even though the CLI argument names a different model. Pull from `main` so `args.model` is persisted to `~/.cheetahclaws/config.json` before `start_web_server` runs. Workaround on older builds: edit the config file directly, or use `/model custom/<name>` from the Chat UI.

---

## What's NOT implemented yet

These are candidates for a later phase — the web UI is production-capable today but these would round it out:

- WebSocket auto-reconnect after suspend/resume (currently retries with backoff but doesn't handle laptop-lid-close perfectly).
- Rate limiting on auth endpoints (bcrypt is slow, which is your main guardrail today).
- CSRF protection (`SameSite=Strict` is the current defense).
- AES-GCM encryption for `api_credentials.api_key` at rest.
- Alembic migrations (schema is still `Base.metadata.create_all`).
- ARIA labels / keyboard-only navigation for accessibility.
- Mobile touch gestures beyond what responsive CSS gives.

PRs welcome.
