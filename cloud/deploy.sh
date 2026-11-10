#!/usr/bin/env bash
# Deploy CheetahClaws Cloud on one Linux server (e.g. a Tencent Cloud CVM).
#
#   git clone <repo> && cd cheetahclaws/cloud
#   sudo ./deploy.sh --domain cloud.example.com          # overseas / HK region
#   sudo ./deploy.sh --domain cloud.example.com --cn     # mainland region (mirrors)
#
# Re-run any time to update (pull the repo first): images are rebuilt and the
# gateway restarted; user sandboxes are recreated on their next visit.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DOMAIN="" CN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --cn) CN=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo ./deploy.sh ...)"

# ── Docker ────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  if [ "$CN" = 1 ]; then
    curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
  else
    curl -fsSL https://get.docker.com | sh
  fi
  systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing (apt/yum install docker-compose-plugin)"

if [ "$CN" = 1 ] && [ ! -f /etc/docker/daemon.json ]; then
  say "Configuring the Tencent Cloud Docker Hub mirror"
  mkdir -p /etc/docker
  echo '{"registry-mirrors": ["https://mirror.ccs.tencentyun.com"]}' > /etc/docker/daemon.json
  systemctl restart docker
fi

# ── Config ────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  say "Creating .env"
  [ -n "$DOMAIN" ] || die "first run needs --domain your.domain"
  cp .env.example .env
  secret=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))' 2>/dev/null \
           || openssl rand -base64 48 | tr -d '\n/+=')
  fkey=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' 2>/dev/null \
         || openssl rand -base64 32 | tr '+/' '-_')
  sed -i "s|^CC_DOMAIN=.*|CC_DOMAIN=${DOMAIN}|; s|^CC_PUBLIC_URL=.*|CC_PUBLIC_URL=https://${DOMAIN}|; \
          s|^CC_SECRET=.*|CC_SECRET=${secret}|; s|^CC_FERNET_KEY=.*|CC_FERNET_KEY=${fkey}|" .env
  if [ "$CN" = 1 ]; then
    sed -i "s|^# PIP_INDEX_URL=|PIP_INDEX_URL=|" .env
  fi
  chmod 600 .env
  echo "   wrote cloud/.env — add your model provider keys there."
elif [ -n "$DOMAIN" ]; then
  sed -i "s|^CC_DOMAIN=.*|CC_DOMAIN=${DOMAIN}|; s|^CC_PUBLIC_URL=.*|CC_PUBLIC_URL=https://${DOMAIN}|" .env
fi
[ -f models.json ] || { cp models.example.json models.json; echo "   wrote cloud/models.json — set your models and prices."; }
mkdir -p data

set -a; . ./.env; set +a
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
APT_MIRROR=""
[ "$CN" = 1 ] && APT_MIRROR="http://mirrors.cloud.tencent.com"

# ── Images ────────────────────────────────────────────────────────────────
say "Building the user sandbox image"
docker build -f sandbox/Dockerfile -t cheetahclaws-sandbox:latest \
  --build-arg PIP_INDEX_URL="$PIP_INDEX_URL" --build-arg APT_MIRROR="$APT_MIRROR" ..

# ── Network hardening ─────────────────────────────────────────────────────
# Sandboxes run user/agent code. Keep them away from the cloud metadata
# service (169.254.0.23 on Tencent Cloud — it can hand out instance
# credentials) and other link-local addresses.
say "Blocking sandbox access to the cloud metadata service"
if command -v iptables >/dev/null 2>&1; then
  iptables -C DOCKER-USER -d 169.254.0.0/16 -j DROP 2>/dev/null \
    || iptables -I DOCKER-USER -d 169.254.0.0/16 -j DROP
  echo "   (persist it with iptables-persistent / your firewall tooling)"
fi

# ── Start ─────────────────────────────────────────────────────────────────
say "Starting gateway + HTTPS proxy"
PIP_INDEX_URL="$PIP_INDEX_URL" docker compose up -d --build

say "Done"
cat <<EOF
   Open:      https://${CC_DOMAIN}
   Logs:      docker compose logs -f gateway
   Users:     docker compose exec gateway python -m ccloud.admin users
   Credits:   docker compose exec gateway python -m ccloud.admin credit EMAIL 10

   Checklist
   - DNS: an A record for ${CC_DOMAIN} → this server's public IP.
   - Tencent Cloud security group: allow inbound TCP 80 and 443.
   - Mainland-China region: the domain needs ICP filing before 80/443 serve.
   - Put your upstream keys in .env and models/prices in models.json, then:
       docker compose up -d
   - Stripe (optional): webhook URL https://${CC_DOMAIN}/_cc/stripe/webhook
     (event: checkout.session.completed); put the keys in .env.
EOF
