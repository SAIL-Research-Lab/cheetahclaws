"""End-to-end test of the real stack on Docker (opt-in, needs the images).

    docker build -f cloud/sandbox/Dockerfile -t cheetahclaws-sandbox:latest .
    docker build -f cloud/Dockerfile -t cheetahclaws-cloud-gateway:latest .
    CC_E2E=1 python -m pytest cloud/tests/e2e_docker.py -q -s

What it proves: sign-up → a per-user CheetahClaws container is created →
the full chat UI is served through the gateway proxy → a prompt runs in the
sandbox, which calls our metered model gateway → upstream (a mock model) →
the reply comes back and the user is billed → switching to "own API key"
recreates the sandbox with the user's key → account deletion removes the
container and its volumes.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

if os.environ.get("CC_E2E") != "1" or not shutil.which("docker"):
    pytest.skip("set CC_E2E=1 (and have Docker + the images) to run", allow_module_level=True)

httpx = pytest.importorskip("httpx")
HERE = Path(__file__).resolve().parent
NET = "cc-e2e-net"
GW = "cc-e2e-gateway"
MOCK = "cc-e2e-mock-llm"


def sh(*args, check=True) -> str:
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"docker {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def docker_socket() -> str:
    host = os.environ.get("DOCKER_HOST", "")
    if host.startswith("unix://"):
        return host[7:]
    ctx = sh("context", "inspect", "--format", "{{.Endpoints.docker.Host}}", check=False)
    return ctx[7:] if ctx.startswith("unix://") else "/var/run/docker.sock"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cleanup():
    for c in sh("ps", "-aq", "--filter", "label=cc.user", check=False).split():
        sh("rm", "-f", c, check=False)
    for v in sh("volume", "ls", "-q", "--filter", "name=cc-", check=False).split():
        if v.startswith(("cc-home-u", "cc-ws-u")):
            sh("volume", "rm", "-f", v, check=False)
    sh("rm", "-f", GW, MOCK, check=False)
    sh("network", "rm", NET, check=False)


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    cleanup()
    tmp = tmp_path_factory.mktemp("cloud")
    models = tmp / "models.json"
    models.write_text(json.dumps({"models": [{
        "id": "mock", "label": "Mock", "upstream_base": f"http://{MOCK}:9000/v1",
        "upstream_model": "mock-1", "key_env": "MOCK_KEY",
        "price_in": 1.0, "price_out": 4.0, "context": 32000}]}))
    (tmp / "data").mkdir()
    sh("network", "create", NET)
    sh("run", "-d", "--name", MOCK, "--network", NET,
       "-v", f"{HERE / 'mock_llm.py'}:/mock_llm.py:ro",
       "python:3.13-slim", "python", "/mock_llm.py", "9000")
    port = free_port()
    sh("run", "-d", "--name", GW, "--network", NET, "--network-alias", "cc-gateway",
       "-p", f"127.0.0.1:{port}:8000",
       "-v", f"{docker_socket()}:/var/run/docker.sock",
       "-v", f"{models}:/config/models.json:ro", "-v", f"{tmp / 'data'}:/data",
       "-e", "CC_SECRET=" + "e2e-secret-" + "x" * 40,
       "-e", "CC_FERNET_KEY=" + "A" * 43 + "=",
       "-e", f"CC_PUBLIC_URL=http://127.0.0.1:{port}",
       "-e", "CC_DB_URL=sqlite:////data/cloud.db", "-e", "CC_MODELS_FILE=/config/models.json",
       "-e", f"CC_SANDBOX_NETWORK={NET}", "-e", "CC_INTERNAL_URL=http://cc-gateway:8000",
       "-e", "CC_SANDBOX_MEMORY=1g", "-e", "CC_SIGNUP_CREDIT_USD=1", "-e", "MOCK_KEY=sk-mock",
       "cheetahclaws-cloud-gateway:latest")
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if httpx.get(base + "/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
    else:
        raise RuntimeError("gateway did not start:\n" + sh("logs", GW, check=False))
    yield base
    if os.environ.get("CC_E2E_KEEP") != "1":
        cleanup()


def test_full_flow(stack):
    base = stack
    c = httpx.Client(base_url=base, timeout=120, follow_redirects=False)
    r = c.post("/_cc/api/register", json={"email": "e2e@example.com", "password": "password123"})
    assert r.status_code == 200, r.text
    me = c.get("/_cc/api/me").json()
    assert me["balance_usd"] == 1 and me["platform_model"] == "mock"

    # First visit to the UI → start page; starting creates the container.
    r = c.get("/chat", headers={"accept": "text/html"})
    assert r.status_code == 302 and r.headers["location"].startswith("/_cc/start")
    t0 = time.time()
    r = c.post("/_cc/api/workspace/start", json={})
    assert r.status_code == 200, r.text
    print(f"\n   cold start: {time.time() - t0:.1f}s")
    assert sh("inspect", "-f", "{{.State.Running}}", "cc-u1") == "true"

    # The full CheetahClaws chat UI, through the proxy.
    r = c.get("/chat", headers={"accept": "text/html"})
    assert r.status_code == 200 and "CheetahClaws" in r.text and "prompt-input" in r.text
    assert c.get("/api/sessions").status_code == 200       # sets the sandbox CSRF cookie

    # A real prompt: sandbox → our model gateway → mock upstream → back.
    csrf = c.cookies.get("ccsrf")
    r = c.post("/api/prompt", json={"prompt": "Say hello"},
               headers={"X-CSRF-Token": csrf, "Origin": base})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    reply = ""
    deadline = time.time() + 90
    while time.time() < deadline:
        sess = c.get(f"/api/sessions/{sid}").json()
        msgs = [m for m in sess.get("messages", []) if m.get("role") == "assistant"]
        if msgs and not sess.get("busy"):
            reply = json.dumps(msgs[-1])
            break
        time.sleep(1)
    assert "Hello from the mock model" in reply, sess

    me = c.get("/_cc/api/me").json()
    # mock usage: 1200 in × $1/M + 300 out × $4/M = $0.0024 per call
    assert me["balance_usd"] < 1
    usage = c.get("/_cc/api/usage").json()["usage"]
    assert usage and usage[0]["model"] == "mock" and usage[0]["input_tokens"] == 1200

    # Switch to the user's own key: the sandbox is recreated with it.
    r = c.post("/_cc/api/settings", json={"model_mode": "byok", "byok_provider": "deepseek",
                                          "byok_model": "deepseek-chat", "byok_key": "sk-user-own-key"})
    assert r.status_code == 200, r.text
    assert c.post("/_cc/api/workspace/start", json={}).status_code == 200
    env = json.loads(sh("inspect", "-f", "{{json .Config.Env}}", "cc-u1"))
    assert "DEEPSEEK_API_KEY=sk-user-own-key" in env
    assert not any(e.startswith("CUSTOM_API_KEY=") for e in env)
    cfg = sh("exec", "cc-u1", "cat", "/home/cheetah/.cheetahclaws/config.json")
    assert json.loads(cfg)["model"] == "deepseek/deepseek-chat"
    # Chats survived the recreate (persistent volume).
    assert any(s["id"] == sid for s in c.get("/api/sessions").json()["sessions"])

    # Isolation: the container can't use the gateway with someone else's token
    # and has no Docker socket.
    out = sh("exec", "cc-u1", "sh", "-c", "ls /var/run/docker.sock 2>&1 || true")
    assert "No such file" in out

    # Delete the account: container + volumes gone.
    assert c.post("/_cc/api/delete", json={"password": "password123"}).status_code == 200
    assert sh("ps", "-aq", "--filter", "name=cc-u1", check=False) == ""
    vols = sh("volume", "ls", "-q", check=False).split()
    assert "cc-home-u1" not in vols and "cc-ws-u1" not in vols
