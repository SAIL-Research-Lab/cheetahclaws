# CheetahClaws Cloud

Users download the app (iOS, Android, desktop, or open the website), create an
account, choose **CheetahClaws models** (paid from credits) or **their own API
key**, and get the complete CheetahClaws agent. Nothing to install, and every
feature works, because each user gets their own CheetahClaws running on its
own computer in the cloud.

```
 iPhone / Android app · desktop app · browser
                 │  https://cloud.example.com
                 ▼
 ┌ Caddy (HTTPS, automatic certificates) ─────────────────────────────┐
 └────────────────────────────┬───────────────────────────────────────┘
                              ▼
 ┌ Gateway (this folder, FastAPI) ────────────────────────────────────┐
 │ accounts · credits · Stripe · encrypted user API keys              │
 │ reverse proxy (HTTP / SSE / WebSocket) → the user's own sandbox    │
 │ /internal/v1  metered OpenAI-compatible model gateway              │
 └──────┬──────────────────────────────────────────────┬──────────────┘
        │ Docker API                                    │ our provider keys
        ▼                                               ▼
 cc-u1   cc-u2   cc-u3 …   one container per user   DeepSeek / OpenRouter /
 full `cheetahclaws --web`, 2 persistent volumes    DashScope / any OpenAI-
 (chats·memory·config, /workspace), CPU/RAM/PID     compatible upstream
 limits, no capabilities, stopped when idle
```

- **All features, no multi-tenant rewrite.** A sandbox is the normal
  single-user CheetahClaws. Users are separated by container boundaries. Bash,
  files, MCP, skills, sub-agents, memory, research, scheduled jobs and the
  web terminal all work. The sandbox stops after 30 idle minutes, but never
  mid-task, and wakes on the next visit.
- **Two ways to pay for models.**
  - *Platform mode*: the sandbox's model calls go to `/internal/v1`. The
    gateway checks the user's credit, forwards the call with your upstream
    key, and charges the user from the reported token usage at your prices
    (`models.json`).
  - *Own key*: the key is stored encrypted (Fernet) and given only to that
    user's sandbox. No credits are used.
- **Security.**
  - The browser never holds a sandbox credential. The gateway injects the
    sandbox's token and strips the platform session cookie before proxying.
  - Sandboxes have no Docker socket, run with `CapDrop: ALL` and
    `no-new-privileges`, and are blocked from the cloud metadata service.
  - Platform POSTs are JSON-only (CSRF), and sign-up and sign-in are rate
    limited.

## Deploy on a Tencent Cloud server

Needs one Linux CVM (4 vCPU / 8 GB handles roughly 5–10 active users at the
default 1 CPU / 2 GB per sandbox; idle users cost only disk) and a domain.

```bash
git clone https://github.com/SAIL-Research-Lab/cheetahclaws.git
cd cheetahclaws/cloud
sudo ./deploy.sh --domain cloud.example.com        # Hong Kong / overseas region
sudo ./deploy.sh --domain cloud.example.com --cn   # mainland region: Tencent mirrors
```

Then:

1. **DNS**: point an A record for the domain at the server's public IP.
2. **Security group**: allow inbound TCP 80 and 443.
3. **Model keys**: edit `cloud/.env` (`DEEPSEEK_API_KEY=…` etc.) and
   `cloud/models.json` (which models you sell, and your per-1M-token prices),
   then run `docker compose up -d`.
4. Open `https://cloud.example.com` and create the first account.

> **Mainland China region**
> - A domain served on 80/443 must have ICP filing (备案).
> - Some upstreams (OpenAI, Anthropic, OpenRouter) are not reachable from the
>   mainland. Use DeepSeek, DashScope (Qwen), Zhipu, or Moonshot there, or
>   deploy in Hong Kong or overseas.
> - A public generative-AI service for mainland users also needs algorithm
>   and model filing (生成式 AI 备案). Hong Kong or overseas avoids all three.

### Our model service: `models.json`

```json
{"models": [{
  "id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash",
  "upstream_base": "https://api.deepseek.com/v1", "upstream_model": "deepseek-chat",
  "key_env": "DEEPSEEK_API_KEY",
  "price_in": 0.40, "price_out": 1.60, "context": 128000
}]}
```

`price_in` / `price_out` are what **users** pay per 1M tokens. Set them above
your upstream cost to cover the margin. Any OpenAI-compatible upstream works,
including your own vLLM. The example file's prices and upstream model names
are placeholders; check them against your provider before going live.

### Credits

- New accounts get `CC_SIGNUP_CREDIT_USD` (default $0.50).
- **Stripe** (optional): set `CC_STRIPE_SECRET` / `CC_STRIPE_WEBHOOK_SECRET` and
  add the webhook `https://<domain>/_cc/stripe/webhook` with the event
  `checkout.session.completed`. Top-up buttons then appear on the account page
  (never inside the iOS app; see below).
- **By hand**:
  ```bash
  docker compose exec gateway python -m ccloud.admin credit someone@example.com 10
  docker compose exec gateway python -m ccloud.admin users
  docker compose exec gateway python -m ccloud.admin set-password someone@example.com
  ```

### Operating

| | |
|---|---|
| Logs | `docker compose logs -f gateway` |
| Update | `git pull && sudo ./deploy.sh` (sandboxes pick up the new image on their next start) |
| Backups | `cloud/data/cloud.db` (accounts, credits) and the `cc-home-u*` / `cc-ws-u*` Docker volumes (user data) |
| Stronger isolation | install gVisor and set `CC_SANDBOX_RUNTIME=runsc` |

## The apps

- **iOS / Android** (`../mobile`): set the GitHub repository variable
  `CC_CLOUD_URL=https://cloud.example.com` and run the **Apps** workflow. The
  app opens with **Sign in to CheetahClaws**; connecting to your own computer
  stays available as a second option.
- **Desktop** (`../desktop`) and **web**: open the domain.

### App Store checklist

These are the parts that are already handled:

- **Account deletion inside the app** (Guideline 5.1.1(v)): Account → Delete
  account.
- **Sign in with Apple** (4.8) is only required if you add Google or other
  social logins. Email + password needs none.
- **No in-app purchases.** The iOS app shows no prices or top-up buttons, so
  credits bought on the web are used in the app (3.1.3(b), multiplatform
  services). To sell credits *inside* iOS, add StoreKit / RevenueCat.
- **Native value beyond a web view** (4.2): the app has its own sign-in
  screen, QR pairing with a computer, and the camera scanner. Push
  notifications are a good next addition before review.
- **You need to provide**: a privacy policy URL, a support URL, and the
  privacy "nutrition labels" in App Store Connect (account email; user
  content is processed to provide the service).

## Develop

```bash
cd cloud
pip install -r requirements.txt
python -m pytest tests -q                       # unit tests (no Docker)

# Real stack on Docker: sign-up → container → prompt → billing → delete
docker build -f cloud/sandbox/Dockerfile -t cheetahclaws-sandbox:latest ..
docker build -f cloud/Dockerfile -t cheetahclaws-cloud-gateway:latest ..
CC_E2E=1 python -m pytest tests/e2e_docker.py -q -s
```
