# Security & Environment Variables

This page is the single reference for cheetahclaws' security model and every
environment variable that gates a sensitive subsystem. Read this before you
expose cheetahclaws to a remote bridge, a multi-user web deployment, or an
untrusted plugin.

## Threat model — at a glance

cheetahclaws is built around a single trusted operator running on a single
host. Inside that boundary the defaults favour usability; once you cross it
(remote bridge, web UI on a LAN, shared daemon, third-party plugins) the
hardening below kicks in.

| Surface | Default posture | Tighten with |
|---|---|---|
| Local REPL `!command` | Allowed (you typed it) | NUL / length / control-char filter |
| Bash tool (`Bash`) | LLM-driven, owner-confirmed; process group killed on Ctrl-C / timeout | Hard denylist (`rm -rf /` / `~`, fork bombs, `dd of=/dev/sd…`, `mkfs`, `find / -delete`, …) · opt-in OS sandbox `bash_sandbox` · `bash_scrub_env` |
| Remote bridge `!cmd` (Telegram / Slack / WeChat / QQ) | **Enabled by default**, owner-only: per-sender allowlist (`<bridge>_allowed_users`, owner auto-bound on first private message) + hard denylist | `CHEETAHCLAWS_BRIDGE_TERMINAL=0` to disable entirely |
| File I/O (`Read` / `Write` / `Edit`) | CWD-relative, credential paths denied | `allowed_root` config / `CHEETAHCLAWS_FS_NO_SANDBOX=1` |
| Plugins (`plugin/loader.py`) | Manifest-driven, runs arbitrary Python; **project** plugins only in trusted folders; git installs show manifest + deps and ask | `CHEETAHCLAWS_DISABLE_PLUGINS=1` / `CHEETAHCLAWS_PLUGIN_ALLOWLIST=…` |
| Project `.mcp.json` / plugins / hooks | **Not started until you trust the folder** (`/trust`, asked once at REPL start); re-approval when an entry's command changes | `trust_all_projects: true` / `CHEETAHCLAWS_TRUST_ALL=1` restores the old auto-load |
| `WebFetch` | Public addresses only, re-checked on every redirect (no localhost / LAN / cloud metadata) | `webfetch_allowed_hosts` / `webfetch_allow_private: true` |
| MCP server env | Dangerous keys (`LD_PRELOAD`, `PYTHONPATH`, …) stripped | `CHEETAHCLAWS_MCP_TRUST_ENV=1` to allow |
| Web UI (chat) | JWT cookie + CSRF double-submit + owner-bound terminal sessions; cross-origin requests and WebSocket upgrades refused; registration closed after the first (admin) user | `--no-auth` still requires a per-launch token in the URL |

## v3.5.90 hardening — what changed and how to opt out

Every change below keeps a documented escape hatch, and the message you see
when something is refused names it.

**Workspace trust.** Opening a repository no longer runs its code. A
project's `.mcp.json` servers, `.cheetahclaws/plugins.json` plugins and
`.cheetahclaws/settings.json` hooks stay off until you trust the folder: the
REPL asks once at start (`Trust this folder and start them? [y/N]`), or run
`/trust` (also `/trust list`, `/trust revoke [dir]`, and `cheetahclaws trust`
from the shell). Trust is stored in `~/.cheetahclaws/trust.json` (0600), and
each server/plugin is pinned by a hash of its command — if a `git pull`
changes what an entry runs, it is skipped again until re-approved. User-level
config (`~/.cheetahclaws/mcp.json`, user plugins) is unaffected. Opt out:
`trust_all_projects: true` or `CHEETAHCLAWS_TRUST_ALL=1`.

**Bridges.** One shared check (`bridges/auth.py`) runs before any `!` shell,
slash command, permission reply or agent dispatch on Telegram, WeChat, QQ and
Slack. Allowed senders come from `<bridge>_allowed_users` (e.g.
`telegram_allowed_users`, `wechat_allowed_users`); with an empty list the
first private-chat sender is bound as the owner and saved, so single-owner
setups keep working. Group members not on the list are refused with a reply
saying how to add them. Opt out: `<bridge>_allow_all_senders: true`.

**Web UI / desktop.** Requests whose `Origin` is not the server itself are
refused (WebSocket upgrades and every state-changing method), and CORS only
echoes allow-listed origins (`web_allowed_origins`). `--no-auth` now prints a
URL with a per-launch token; without it pages return 401 — the desktop app
passes the token automatically (`web_no_auth_require_token: false` to drop
it). After the first user (who becomes admin), registration needs an admin
(`web_open_registration: true` to reopen). Non-admins cannot raise
`permission_mode` above the owner's, widen `tool_profile`, change provider
base URLs or run privileged slash commands (`web_nonadmin_privileged: true`
restores full rights). `/metrics` needs a login (`web_public_metrics: true`).

**Bash permissions.** An "always allow" grant now covers a chained command
only if *every* segment is read-only or itself granted — approving
`git status` no longer approves `git status && curl … | sh`. Command
substitution, redirects to files, `eval`, `bash -c`, `sudo`, `git -c` and
`LD_*`/`PATH`/`GIT_*` prefixes never match a grant. The read-only classifier
closes known bypasses (`sed 'e'`/`w`, `git -c core.fsmonitor=…`,
`--ext-diff`, `rg --pre`, `tar --checkpoint-action`, `$VAR` expansion in
network commands, newline / `#` command smuggling). `curl` is no longer
auto-approved; add it back with `bash_safe_extra: ["curl"]`.

**Bash execution.** Ctrl-C and timeouts kill the whole process group, so
interrupted commands no longer keep running. Default timeout is 120 s
(`bash_default_timeout`). Opt-in isolation:

| Key | Values | Effect |
|---|---|---|
| `bash_sandbox` | `off` (default) · `workspace-write` · `read-only` | Run every `Bash` tool call under bubblewrap (Linux) or `sandbox-exec` (macOS); fails closed with a hint if the sandbox is unavailable |
| `bash_sandbox_network` | `false` (default) | Allow network inside the sandbox |
| `bash_sandbox_writable` | list of paths | Extra writable paths besides the workspace |
| `bash_scrub_env` | `false` (default) | Strip provider API keys / tokens from the child environment |
| `bash_env_keep` | list of names | Keep these variables even when scrubbing |

**WebFetch.** Every hop, redirects included, must be http(s) and resolve to
public addresses — no localhost, RFC 1918, link-local, CGNAT, cloud metadata
(`169.254.169.254`) or IPv4-mapped IPv6 tricks. Opt out per host with
`webfetch_allowed_hosts: ["intranet.example.com", ".corp.example"]` or
globally with `webfetch_allow_private: true`.

**Secrets on disk.** `config.json`, `mcp.json`, `trust.json` and the daemon
token are written atomically with mode 0600 (directory 0700). API keys that
came from environment variables are never copied into `config.json`.

**File editing.** `Edit`, `MultiEdit`, `ApplyPatch` and overwriting `Write`
require the file to have been read in this session and refuse if it changed
on disk since (`edit_require_read: false` to disable). Writes are atomic
(temp file + `fsync` + rename, mode bits kept), non-UTF-8 files are never
re-encoded or filled with U+FFFD, and line endings outside the edited region
are left untouched. The approval prompt shows a dry-run diff first
(`permission_diff_preview: false` to hide).

## Environment variables

| Variable | Default | Behaviour |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | (unset) | Recommended way to provide the Telegram bot token. Token from env never lands in `readline` history or `~/.cheetahclaws/config.json`. Beats the `/telegram <token> <chat_id>` syntax. |
| `SLACK_BOT_TOKEN` | (unset) | Same idea for Slack (`xoxb-…`). |
| `QQ_SECRET` | (unset) | QQ bot AppSecret (qq-botpy). Env-supplied secret never lands in `readline` history or `~/.cheetahclaws/config.json`. Beats the `/qq <appid> <secret>` syntax. |
| `QQ_APPID` | (unset) | QQ bot AppID — a public identifier, not sensitive. Optional convenience so `/qq` works with no args. |
| `CHEETAHCLAWS_BRIDGE_TERMINAL` | `1` | Set to `0` to hard-disable remote `!cmd` shell from any bridge (Telegram / Slack / WeChat / QQ). Useful when a bridge owner is *not* the same person as the host operator. |
| `CHEETAHCLAWS_FS_NO_SANDBOX` | `0` | Bypass the credential-path denylist (SSH private keys, `~/.aws`, `~/.gnupg`, `/etc/shadow`, etc.). Only set if you're deliberately auditing your own secrets. |
| `CHEETAHCLAWS_DISABLE_PLUGINS` | `0` | Hard-disable plugin loading regardless of what's installed in `~/.cheetahclaws/plugins/`. |
| `CHEETAHCLAWS_PLUGIN_ALLOWLIST` | (unset) | Comma-separated plugin names. When set, only these plugins are loaded — everything else is silently skipped, even if enabled in the registry. |
| `CHEETAHCLAWS_MCP_TRUST_ENV` | `0` | Set to `1` to allow MCP server configs to inject `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_*`, `PYTHONPATH`, `PYTHONSTARTUP`, `PYTHONHOME`, `NODE_OPTIONS`, `NODE_PATH`, `BASH_ENV`, or `ENV`. Default is to silently strip these from `mcp.json`-supplied env. |
| `CHEETAHCLAWS_WEB_SECRET` | (unset) | Per-deployment JWT signing secret for the web UI. Strongly recommended for production — overrides the auto-generated file at `~/.cheetahclaws/web_secret`. |
| `CHEETAHCLAWS_TRUST_ALL` | `0` | Set to `1` to skip workspace trust: every project's `.mcp.json` servers, plugins and hooks load without asking (the pre-v3.5.90 behaviour). Same as config `trust_all_projects: true`. |
| `CHEETAHCLAWS_PLUGIN_INSTALL_YES` | `0` | Set to `1` to approve `/plugin install` confirmation prompts non-interactively (CI / bridges). |
| `CHEETAHCLAWS_BASH_SANDBOX` | (unset) | `workspace-write` or `read-only` runs every `Bash` tool call inside bubblewrap (Linux) / `sandbox-exec` (macOS). Same as config `bash_sandbox`. |
| `CHEETAHCLAWS_BASH_SCRUB_ENV` | `0` | Set to `1` to strip API keys / tokens from the environment of `Bash` tool commands. Same as config `bash_scrub_env`. |
| `CHEETAHCLAWS_WEBFETCH_ALLOW_PRIVATE` | `0` | Set to `1` to let `WebFetch` reach localhost / private / link-local addresses. Same as config `webfetch_allow_private`. |
| `CHEETAHCLAWS_WEB_ALLOWED_ORIGINS` | (unset) | Comma-separated extra origins the web UI accepts (reverse proxies that rewrite `Host`). Same as config `web_allowed_origins`. |
| `CHEETAHCLAWS_DISABLE_HOOKS` | `0` | Set to `1` to skip every user / project hook (see [hooks.md](hooks.md)). |
| `CHEETAHCLAWS_IMAGE_OCR` | `1` | Set to `0` to disable local-OCR enrichment of `/image`. When on (and `pytesseract`/`tesseract` are installed), `/image` transcribes the clipboard screenshot and appends the text to the prompt so non-vision models can act on it. Disable to avoid the synchronous OCR latency or to keep the raw image the only signal sent to a vision model. |

## Bot tokens — recommended setup

Tokens passed as `/telegram <TOKEN> <chat_id>` in the REPL land in your
`readline` history file (`~/.cheetahclaws/input_history.txt`). Subsequent
processes that read this file (including a curious shell user with read
access) can extract the token.

Recommended:

```bash
export TELEGRAM_BOT_TOKEN=7812345678:AAFxyz...
cheetahclaws
[myproject] ❯ /telegram 987654321        # only chat_id on the command line
```

If you do use the old two-arg form, cheetahclaws will:

- print a deprecation warning,
- run `readline.remove_history_item` on every line in history that contains
  the token (so it disappears the moment the command runs).

WeChat does not have a token-in-argv path — its session token is obtained
via QR-code scan and stored in `~/.cheetahclaws/config.json` (0600).

QQ works the same way as Telegram/Slack: prefer `export QQ_SECRET=…` and run
`/qq <appid>` (only the public AppID on the command line). The AppSecret from
the environment is never written to `config.json`; the deprecated
`/qq <appid> <secret>` form warns and scrubs the secret from history.

## Bash tool — hard denylist

A small set of command patterns is rejected by `tools/shell.py` even when
`permission_mode=accept-all` is active. The denylist is intentionally
narrow to avoid false positives:

- `rm -rf /` (and variations like `rm --recursive --force /`)
- `mkfs.*`
- `dd of=/dev/sd*` / `dd of=/dev/nvme*` / `dd of=/dev/hd*` / `dd of=/dev/vd*` / `dd of=/dev/mmcblk*` / `dd of=/dev/xvd*`
- `> /dev/sd*` / `> /dev/nvme*` / `> /dev/hd*` (and similar)
- `chmod -R 777 /`
- `chown -R <user> /`
- `:(){:|:&};:` fork bomb

These also apply to bridge-originated `!cmd` invocations and to tmux pane
commands. Set `permission_mode` correctly if you need a one-off override;
the denylist has no opt-out (by design).

## File-system sandbox

When `config["allowed_root"]` is set, `Read` / `Write` / `Edit` / `Glob`
will refuse paths outside that root. This is the strict mode for
multi-user deployments and is what `cheetahclaws daemon` uses.

Even without `allowed_root`, a credential denylist is enforced:

- `~/.ssh/id_*` (private keys)
- `~/.aws/*`, `~/.gnupg/*`, `~/.kube/*`, `~/.docker/*`
- `~/.netrc`, `~/.pgpass`
- `/etc/shadow`, `/etc/gshadow`, `/etc/sudoers`, `/etc/sudoers.d/*`
- `/root/*`

Public-by-convention SSH files (`~/.ssh/config`, `known_hosts`,
`authorized_keys`) are still readable.

Set `CHEETAHCLAWS_FS_NO_SANDBOX=1` to disable the denylist (e.g. when
intentionally auditing your own keys).

## Web UI

See [`docs/guides/web-ui.md`](web-ui.md) for the full chat-UI auth flow.
Quick summary of the security pieces:

| Defence | Mechanism |
|---|---|
| Login | `username + password` → bcrypt verify → HS256 JWT |
| JWT cookie | `ccjwt=…; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800` |
| CSRF | Double-submit cookie: `ccsrf=…; SameSite=Strict` non-HttpOnly cookie minted on first GET, every POST/PUT/PATCH/DELETE must echo it in the `X-CSRF-Token` header. Exempted: `/api/auth/bootstrap`, `/api/auth/register`, `/api/auth/login`, `/api/auth/logout`, `/api/auth` (legacy terminal). Frontend `web/static/js/csrf.js` patches `window.fetch` so this is automatic for the bundled UI. |
| Terminal session ownership | `/api/session` creator's JWT uid is tagged onto the `_PtySession`. `/api/stream`, `/api/input`, `/api/resize` reject any other authenticated caller with `403`. Password-only mode (`cctoken` auth, no JWT) skips this check since all callers share the same secret. |
| Terminal password | 32-char `secrets.token_urlsafe(32)` (~190 bits of entropy) generated at startup, displayed once. |
| JWT signing secret | `secrets.token_urlsafe(32)` saved to `~/.cheetahclaws/web_secret` with `O_CREAT \| O_EXCL` + 0o600. If the post-write `stat` shows world-readable mode the file is removed and the secret falls back to in-memory only; override with `CHEETAHCLAWS_WEB_SECRET`. |

## Plugins

Plugins are loaded by `importlib` from `~/.cheetahclaws/plugins/<name>/`
or any directory on `$CHEETAHCLAWS_PLUGIN_PATH`. Each module runs with
the same privileges as the cheetahclaws process — there is no sandbox.

Mitigations on by default:

- Module paths are confined to the plugin's `install_dir` (no
  `../../etc/passwd` traversal).
- EXTERNAL-scope plugins (loaded via `$CHEETAHCLAWS_PLUGIN_PATH`) print a
  one-time stderr warning on first load so a stolen env var doesn't
  load code silently.

Use `CHEETAHCLAWS_DISABLE_PLUGINS=1` for an emergency kill switch or
`CHEETAHCLAWS_PLUGIN_ALLOWLIST=a,b,c` to whitelist exactly the plugins
you trust.

## MCP

MCP server configs (`.mcp.json`, plugin manifests) supply a `command`,
`args`, and an `env` map. cheetahclaws merges `env` over `os.environ`
before spawning, but first strips a hard-coded set of process-hijack
keys: `LD_PRELOAD`, `LD_LIBRARY_PATH`, `LD_AUDIT`, `DYLD_INSERT_LIBRARIES`,
`DYLD_LIBRARY_PATH`, `PYTHONPATH`, `PYTHONSTARTUP`, `PYTHONHOME`,
`PYTHONEXECUTABLE`, `NODE_OPTIONS`, `NODE_PATH`, `BASH_ENV`, `ENV`.

A dropped key prints a one-line `[mcp] Dropped potentially-dangerous env
keys …` notice to stderr. Set `CHEETAHCLAWS_MCP_TRUST_ENV=1` if a
legitimate MCP server actually needs one of these.

## What runs without asking (`auto` mode)

The permission prompt exists for actions that can **change your files, run
arbitrary code, or reach outside the session**. Everything else runs silently,
because a prompt a user always answers "yes" to trains them to stop reading it
— and a user who reaches for `accept-all` out of prompt fatigue ends up with
*less* protection than one who is asked only about the things that matter.

Auto-approval is decided by classification, never by string prefix:

- **Tools** — `ToolDef.read_only` in the registry. Reads, searches, document
  extraction, diagnostics, task/memory queries. Anything unclassified
  (MCP servers, third-party plugins) defaults to prompting.
- **Shell** — the command is parsed with `shlex`, split on `|`, `&&`, `||`,
  `;`, and *every* segment must be a known read-only invocation. Output
  redirection (`>`), backgrounding (`&`), subshells, and command substitution
  (`` ` ``, `$(…)`, `<(…)`) are refused outright, since each can act — or hide
  a second command — after a safe-looking prefix.
- **Writes** — creating a *new* file inside the workspace destroys nothing and
  runs; overwriting an existing file, writing outside the workspace, or
  creating any dot-prefixed path (`.git/hooks/*`, `.github/workflows/*`,
  `.env` — locations other tools execute or trust) still prompts.

Two things are deliberately **not** auto-approved even though they read as
routine: interpreters (`python`, `node`, `ruby`, `perl`, `sh`) and anything
that runs a program it is handed (`xargs`, `env VAR=… cmd`, `timeout`, `make`,
`npm run`, `pytest`). `python script.py` is indistinguishable from
`python -c 'os.system("…")'` at the permission layer, so both ask. Their
`--version`/`--help` forms still run silently — those execute nothing.

> Earlier versions matched a list of *prefixes* and auto-ran anything starting
> with `python `, `node `, `ruby `, `perl `, or `find ` — which auto-approved
> arbitrary code execution and `find … -delete`. Those are now classified
> properly and prompt.

**Session grants.** Answering `s` at a prompt grants one signature
(`Bash:git commit`, `Edit:/repo/app.py`) for the rest of the session. Grants
are held on the in-memory `RuntimeContext`, never persisted, dropped when the
session ends, ignored entirely in `manual` mode, and clearable with
`/permissions clear`. Prefer it to `accept-all`: it removes the repeat prompt
without removing the gate on everything else.

**Extending the allowlist.** `/config bash_safe_extra=["your-query-tool"]`
adds project-specific read-only programs. Only add a program that cannot
write, delete, or execute another program — the entry bypasses the prompt for
every invocation of it, whatever its arguments.

## Permission mode `accept-all`

`/permissions accept-all` (or clicking "Accept all" at the permission
prompt) is now **session-scoped**. The value is *not* persisted to
`~/.cheetahclaws/config.json`, so launching cheetahclaws again starts
back in `auto` (the safe default).
