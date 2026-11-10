# Per-user CheetahClaws sandbox: the full agent plus the everyday tools it
# reaches for (git, node/npm for MCP servers, ripgrep, build basics).
# Build from the repo root:
#   docker build -f cloud/sandbox/Dockerfile -t cheetahclaws-sandbox:latest .
FROM python:3.13-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG APT_MIRROR=
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_INDEX_URL=${PIP_INDEX_URL}
RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|http://deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      git curl ca-certificates tini ripgrep procps less jq unzip \
      build-essential nodejs npm \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 --shell /bin/bash cheetah
WORKDIR /opt/cheetahclaws
COPY pyproject.toml requirements.txt README.md LICENSE NOTICE ./
COPY cheetahclaws ./cheetahclaws
RUN pip install '.[web]' && rm -rf /opt/cheetahclaws/build
RUN mkdir -p /home/cheetah/.cheetahclaws /workspace \
 && chown -R cheetah:cheetah /home/cheetah /workspace
USER cheetah
ENV HOME=/home/cheetah
WORKDIR /workspace
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--", "cheetahclaws"]
CMD ["--web", "--no-auth", "--host", "0.0.0.0", "--port", "8080"]
