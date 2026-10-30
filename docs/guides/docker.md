# Docker / Home Server Guide

Run CheetahClaws in a container as a long-running home-server service: Web UI in the browser, Telegram bridge for your phone, all backed by an Ollama instance on the host.

This guide targets a Linux host (Ubuntu / DGX-Spark) running Docker 20.10+ and a local Ollama install. The same compose file works on macOS or Windows with minor tweaks called out inline.

> CheetahClaws also runs perfectly well as a normal `pip install`. Use Docker when you want a long-running service, network-accessible UI, or process isolation. For local CLI use against your own files, native install is usually smoother.

## Pull from Docker Hub

If you just want to run CheetahClaws without cloning the source, use the pre-built image on Docker Hub under the `chauncygu` namespace.

```bash
docker pull chauncygu/cheetahclaws:latest        # or pin a version: :3.5.84
```

Run the Web UI directly:

```bash
docker run --rm -p 8080:8080 \
  -v "$PWD/workspace:/workspace" \
  -v "$PWD/data:/home/cheetah/.cheetahclaws" \
  chauncygu/cheetahclaws:latest
```

Then open `http://localhost:8080/chat`. The two volumes persist your workspace files and config/history across container restarts (`mkdir -p ./workspace ./data` first).

**Using the published image with compose** — the bundled `docker-compose.yml` builds locally by default, but you can point it at the Hub image instead and skip the build:

```bash
CHEETAH_IMAGE=chauncygu/cheetahclaws:latest docker compose up -d
```

The rest of this guide covers the build-from-source compose workflow (host Ollama, Telegram bridge, SMB share), which applies to the pulled image too.

### Publishing the image (maintainers)

`scripts/docker-publish.sh` reads the version from `pyproject.toml` and pushes both `:latest` and `:<version>` tags (multi-arch by default):

```bash
docker login
DOCKERHUB_USERNAME=chauncygu ./scripts/docker-publish.sh
```

Pass `SINGLE_ARCH=1` for a host-arch-only build, or `DRY_RUN=1` to preview the commands.

## Interactive setup / CLI mode

The image's default command is `--web`, so `docker run` boots straight into the **Web UI** — you configure the provider, API key, and model in its **Settings** panel (there is no terminal wizard in this mode). That's the intended path for a long-running server.

If you'd rather use the same **interactive first-run wizard** you get from a native `pip install` (step-by-step provider + API-key setup), run the container with a TTY (`-it`) and pass `--setup`, which overrides the default web command:

```bash
mkdir -p ~/cheetahclaws/data
docker run --rm -it \
  -v ~/cheetahclaws/data:/home/cheetah/.cheetahclaws \
  chauncygu/cheetahclaws:latest --setup
```

To drop straight into the CLI REPL instead (the wizard auto-triggers on first run when stdin is a TTY):

```bash
docker run --rm -it \
  -e ANTHROPIC_API_KEY=sk-ant-...  \
  -v ~/cheetahclaws/workspace:/workspace \
  -v ~/cheetahclaws/data:/home/cheetah/.cheetahclaws \
  chauncygu/cheetahclaws:latest --model claude-sonnet-4-6
```

> **Apple Silicon:** the published image is `linux/amd64` only — add `--platform linux/amd64` to any `docker run` above; it runs under Rosetta emulation.

> **Persist your config.** Always mount `-v <host-dir>:/home/cheetah/.cheetahclaws`. Without it, the API key and provider you enter live only inside the container and are lost on `--rm` exit, so every run looks like a "first run" again. With it, config lands in `<host-dir>/config.json` on the host.

The wizard's trigger (`cli.py`) is: **first run** (`config.json` missing/empty) **and** stdin is a TTY **and** not `--print` mode. Web mode and non-`-it` runs skip it by design.

### Three ways to configure

| Run mode | How you configure | Best for |
|---|---|---|
| Default (`--web`) | Web UI → Settings panel | Browser chat, long-running service |
| `-it … --setup` | Interactive wizard (like `pip` install) | Guided provider + key setup |
| `-it …` (no `--web`) | Wizard auto-triggers → CLI REPL | Pure terminal use |

## Prerequisites

- Docker Engine 20.10 or newer (`docker --version`)
- Docker Compose v2 (`docker compose version`)
- Ollama running on the host with at least one model pulled:
  ```
  ollama serve &
  ollama pull qwen2.5:7b   # or whichever model you plan to use
  ```
- Optional: a Telegram bot token (`@BotFather`) and your numeric chat id

## 1. Get the source

```bash
git clone https://github.com/SAIL-Research-Lab/cheetahclaws.git
cd cheetahclaws
```

## 2. Configure the environment

```bash
cp .env.example .env
$EDITOR .env
```

Set:

- `UID` / `GID` — match your host user (`id -u`, `id -g`) so files written into `./workspace` are owned by you, not by root or some random container UID.
- `WEB_PORT` — public port on the host. Default 8080.
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — only if you plan to use the cloud providers. Leave blank for an Ollama-only setup.

## 3. Create the host directories

```bash
mkdir -p ./workspace ./data
```

- `./workspace` — the agent's working directory. Mount whatever you want it to read/edit. **Share this folder over Samba** to access it from your phone or other PCs.
- `./data` — persists `~/.cheetahclaws` (config, session history, snapshots).

## 4. Bring the stack up

```bash
docker compose up -d --build
docker compose logs -f cheetahclaws
```

You should see:

```
CheetahClaws Web Terminal
────────────────────────────────────────
Terminal: http://localhost:8080
Chat UI:  http://localhost:8080/chat
Host:     0.0.0.0 (network accessible)
Terminal pwd: <auto-generated>
```

Open `http://<host-ip>:8080/chat` from any device on your LAN.

## 5. First-run configuration (inside the container)

The first time you visit the Chat UI it'll prompt to create an account. After login:

- **Pick a model**: open settings → choose `custom` provider, set the base URL to `http://host.docker.internal:11434/v1`, and set the model to `ollama/qwen2.5:7b` (or whatever you pulled). Save.
- **Telegram bridge** (optional): in the agent prompt, type `/config telegram_token <your-bot-token>` and `/config telegram_chat_id <your-chat-id>`. Restart the container (`docker compose restart`) — the bridge auto-starts on next boot.

Config persists to `./data/config.json` on the host.

## Reaching Ollama on the host

The compose file adds:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Inside the container, `host.docker.internal` resolves to the host's Docker gateway IP. Use `http://host.docker.internal:11434/v1` as the OpenAI-compatible base URL.

If your Ollama is bound only to `127.0.0.1` on the host, you'll need to either:
- Set `OLLAMA_HOST=0.0.0.0:11434` before `ollama serve`, or
- Add `network_mode: host` to the service in compose (and remove the `ports:` block, since host networking takes them as-is).

## Sharing the workspace over SMB (Linux host)

```bash
sudo apt install samba
sudo tee -a /etc/samba/smb.conf <<'EOF'
[cheetahclaws]
   path = /home/<you>/cheetahclaws/workspace
   browseable = yes
   writable = yes
   guest ok = no
   valid users = <you>
EOF
sudo smbpasswd -a <you>
sudo systemctl restart smbd
```

From your other PC / phone, connect to `smb://<host-ip>/cheetahclaws`. Files you drop in show up at `/workspace` inside the container immediately.

## Common operations

| Task | Command |
|---|---|
| Tail logs | `docker compose logs -f cheetahclaws` |
| Restart | `docker compose restart` |
| Update to latest source | `git pull && docker compose up -d --build` |
| Shell into the container | `docker compose exec cheetahclaws bash` |
| Run the CLI directly | `docker compose exec cheetahclaws cheetahclaws` |
| Reset config | `rm -rf ./data && docker compose restart` |

## Troubleshooting

**"Cannot connect to Ollama"** — the container can't reach `host.docker.internal:11434`. Verify:
```bash
docker compose exec cheetahclaws curl -s http://host.docker.internal:11434/api/tags
```
If this fails, your Ollama is bound to localhost only. Set `OLLAMA_HOST=0.0.0.0:11434` and restart it.

**Files in `/workspace` show up as `root`-owned on the host** — `UID`/`GID` in `.env` don't match the host user. Run `id -u`/`id -g`, update `.env`, `docker compose up -d`.

**Web UI not reachable from phone** — check the host firewall (`sudo ufw allow 8080/tcp`) and confirm `--host 0.0.0.0` is in the logs.

**Telegram bridge not responding** — check `docker compose logs cheetahclaws | grep -i telegram`. Token/chat-id are loaded from `~/.cheetahclaws/config.json` (i.e., `./data/config.json` on the host). Validate they're set, then restart the container.

**Chat UI loads but every JS/CSS asset is 404** (`/marked.min.js`, `/static/js/chat.js`, …) — the running server is reading static files from a `web/` directory that doesn't actually contain them. This almost always means a custom Dockerfile used a non-editable install (`pip install .[all]`) without bundling package data, so `web/` in `site-packages/` is missing the `static/js/` subtree. Two ways out:

- Easiest: use this repo's `Dockerfile` + `docker-compose.yml` unchanged. It uses `pip install -e '.[web]'`, which keeps `web/` pointed at the source tree.
- Or, in your custom Dockerfile, switch to editable install:
  ```dockerfile
  RUN pip install --no-cache-dir -e '.[all]'
  ```
  Editable install leaves `web/server.py` next to its `static/` directory, so the asset paths resolve correctly regardless of how setuptools handled package-data.

If you must do a non-editable install, make sure your build is using `setuptools >= 62` and that `pyproject.toml`'s `[tool.setuptools.package-data]` for `web` includes `static/**/*` (it does, on `main`). Older setuptools or stale build caches can silently drop subdirectory data.

## Custom Dockerfile pitfalls

If you're rolling your own image instead of the one in this repo, keep these in mind:

- **Use editable install (`pip install -e '.[web]'`).** The chat UI's static files (`web/static/js/*.js`) are package data, not Python code. Editable install removes any dependency on package-data correctly making it into the wheel — `web/server.py` is read directly from the source tree.
- **Don't `WORKDIR` away before `pip install`.** The install must run with the project's `pyproject.toml` at the build context root so setuptools can resolve `[tool.setuptools.package-data]`.
- **`COPY` the full source tree, not just `pyproject.toml` + a few `.py` files.** The chat UI ships HTML/JS/CSS that lives outside the Python source — leaving them out is the most common reason `/chat` loads but assets 404.
- **Match Python ≥ 3.10.** The server uses `Path.is_relative_to`, `match`/`case`, and other 3.10+ features.
- **Run `cheetahclaws --web --host 0.0.0.0`.** Without `--host 0.0.0.0` the server only binds to `127.0.0.1` inside the container, which Docker's port mapping cannot reach from the host.

## Security notes

- The Web UI ships with **first-visit-creates-admin** auth. Don't run with `--no-auth` outside `127.0.0.1`.
- Restrict `WEB_PORT` to the LAN with your router/firewall — it is **not** designed to be exposed to the public internet without extra hardening (reverse proxy + TLS + IP allowlist at minimum).
- The agent has full read/write inside `/workspace`. Mount only directories you're comfortable letting it edit.
