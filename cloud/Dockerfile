# CheetahClaws Cloud gateway (accounts, billing, model gateway, proxy).
# Build from the repo root:  docker build -f cloud/Dockerfile -t cheetahclaws-cloud-gateway .
FROM python:3.13-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_INDEX_URL=${PIP_INDEX_URL}
WORKDIR /app
COPY cloud/requirements.txt .
RUN pip install -r requirements.txt
COPY cloud/ccloud ./ccloud
COPY cloud/models.example.json ./models.json
EXPOSE 8000
# Talks to the Docker socket to manage per-user sandboxes, so it runs as root
# inside its container (the socket is root-owned on the host).
CMD ["uvicorn", "--factory", "ccloud.app:factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
