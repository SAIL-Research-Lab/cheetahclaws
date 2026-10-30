# CheetahClaws — server image (Web UI + bridges)
#
# Targets headless deployments: home server, cloud VM, container hosts.
# Default CMD launches the web UI on 0.0.0.0:8080; configured Telegram /
# WeChat / Slack bridges auto-start in the same process.
#
# Build:    docker build -t cheetahclaws:latest .
# Compose:  see docker-compose.yml

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: occasionally invoked by the agent for status/log inside /workspace.
# tini: PID-1 signal handling (clean Ctrl-C / docker stop).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git tini \
 && rm -rf /var/lib/apt/lists/*

# Non-root user. UID 1000 matches the typical first Linux user; override at
# runtime with `--user "${UID}:${GID}"` when host UIDs differ so files
# written into mounted /workspace remain owner-readable on the host.
RUN useradd --create-home --uid 1000 --shell /bin/bash cheetah

WORKDIR /opt/cheetahclaws
COPY --chown=cheetah:cheetah pyproject.toml requirements.txt ./
COPY --chown=cheetah:cheetah . .

# Install with the [web] extra so chat-UI deps (sqlalchemy, bcrypt, PyJWT)
# are present. Use editable install so version metadata + entry point match
# the source tree.
RUN pip install --no-cache-dir -e '.[web]'

# Pre-create the data + workspace dirs owned by cheetah *before* dropping to
# the non-root user. Otherwise the anonymous volume for .cheetahclaws (and the
# WORKDIR-created /workspace) default to root ownership, and cheetah can't
# write them — first run dies with PermissionError creating sessions/.
RUN mkdir -p /home/cheetah/.cheetahclaws /workspace \
 && chown -R cheetah:cheetah /home/cheetah/.cheetahclaws /workspace

USER cheetah

# Persist config, sessions, history. Mount this in compose to survive
# container recreation.
VOLUME ["/home/cheetah/.cheetahclaws"]

# Workspace where the agent reads/writes files. Mount your project from
# the host onto this path.
WORKDIR /workspace

EXPOSE 8080

# Healthcheck: /health is the unauthenticated liveness endpoint (200 once
# the server + DB are up). Don't point this at /api/* — those require a
# login cookie and would report the container as permanently unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status == 200 else 1)" \
  || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "cheetahclaws"]
# Binds 0.0.0.0 so the published port is reachable from outside the
# container. That is only safe because auth stays ON: the terminal page needs
# the generated password and the chat UI needs an account (first visitor
# becomes admin; further accounts are admin-created). Never add --no-auth
# here — anyone who can reach the port would get a shell.
CMD ["--web", "--host", "0.0.0.0", "--port", "8080"]
