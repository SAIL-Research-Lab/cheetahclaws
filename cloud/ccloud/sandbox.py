"""One isolated CheetahClaws container per user.

Each user gets ``cc-u<id>`` running the stock ``cheetahclaws --web --no-auth``
server, with two persistent volumes (config/sessions/memory and the agent's
/workspace). Nothing about CheetahClaws is cut down — the container *is* a
full single-user CheetahClaws, which is why multi-tenancy needs no changes
inside the agent: users are separated by container boundaries.

Access: the container's web server requires its pinned launch token, which
only the gateway knows (derived from CC_SECRET), so another user's container
on the same network cannot drive it. Model access is injected as env vars:
our metered gateway (platform mode) or the user's own key (BYOK mode).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

from .db import Database, User
from .docker_api import DockerAPI
from .security import KeyBox, launch_token, model_token
from .settings import Settings

log = logging.getLogger("ccloud.sandbox")

SANDBOX_PORT = 8080
CONFIG_DIR = "/home/cheetah/.cheetahclaws"
LAUNCH_COOKIE = "cclaunch"

# BYOK providers → the env var CheetahClaws reads the key from.
BYOK_PROVIDERS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "custom": "CUSTOM_API_KEY",          # any OpenAI-compatible endpoint
}


def _mem_bytes(spec: str) -> int:
    spec = spec.strip().lower()
    mult = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30}.get(spec[-1:], 1)
    return int(float(spec.rstrip("kmg")) * mult)


class SandboxManager:
    def __init__(self, settings: Settings, db: Database, keybox: KeyBox,
                 docker: Optional[DockerAPI] = None):
        self.s = settings
        self.db = db
        self.keybox = keybox
        self.docker = docker or DockerAPI(settings.docker_sock)
        self._locks: dict[int, asyncio.Lock] = {}
        self._last_seen: dict[int, float] = {}
        self._http = httpx.AsyncClient(timeout=5)

    @staticmethod
    def name(uid: int) -> str:
        return f"cc-u{uid}"

    def touch(self, uid: int) -> None:
        self._last_seen[uid] = time.time()

    def _lock(self, uid: int) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    # ── what goes into a sandbox ─────────────────────────────────────────
    def model_setup(self, user: User) -> tuple[dict, str]:
        """(env vars, model string) for the user's current model settings."""
        env: dict[str, str] = {}
        if user.model_mode == "byok" and user.byok_provider in BYOK_PROVIDERS:
            prov = user.byok_provider
            env[BYOK_PROVIDERS[prov]] = self.keybox.open(user.byok_key_enc)
            if prov == "custom":
                env["CUSTOM_BASE_URL"] = user.byok_base_url
            model = user.byok_model.strip()
            if not model.startswith(prov + "/"):
                model = f"{prov}/{model}"
            return env, model
        env["CUSTOM_BASE_URL"] = f"{self.s.internal_url}/internal/v1"
        env["CUSTOM_API_KEY"] = model_token(self.s.secret, user.id)
        return env, f"custom/{user.platform_model}"

    def _spec(self, user: User) -> dict:
        env, _model = self.model_setup(user)
        env.update({
            "CHEETAHCLAWS_LAUNCH_TOKEN": launch_token(self.s.secret, user.id),
            "HOME": "/home/cheetah",
            "PYTHONUNBUFFERED": "1",
        })
        host_cfg: dict = {
            "Mounts": [
                {"Type": "volume", "Source": f"cc-home-u{user.id}", "Target": CONFIG_DIR},
                {"Type": "volume", "Source": f"cc-ws-u{user.id}", "Target": "/workspace"},
            ],
            "Memory": _mem_bytes(self.s.sandbox_memory),
            "NanoCpus": int(self.s.sandbox_cpus * 1e9),
            "PidsLimit": self.s.sandbox_pids,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "NetworkMode": self.s.sandbox_network,
            "RestartPolicy": {"Name": "no"},
            "LogConfig": {"Type": "json-file",
                          "Config": {"max-size": "10m", "max-file": "2"}},
        }
        if self.s.sandbox_runtime:
            host_cfg["Runtime"] = self.s.sandbox_runtime
        if self.s.sandbox_reach == "published":
            host_cfg["PortBindings"] = {f"{SANDBOX_PORT}/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}]}
        return {
            "Image": self.s.sandbox_image,
            "Cmd": ["--web", "--no-auth", "--host", "0.0.0.0", "--port", str(SANDBOX_PORT)],
            "Env": [f"{k}={v}" for k, v in env.items()],
            "Labels": {"cc.user": str(user.id), "cc.rev": str(user.settings_rev),
                       "cc.image": self.s.sandbox_image},
            "ExposedPorts": {f"{SANDBOX_PORT}/tcp": {}},
            "HostConfig": host_cfg,
        }

    async def _apply_model(self, user: User) -> None:
        """Point the sandbox's default model at the user's choice — once per
        settings revision, so a model the user later picks in the chat UI
        isn't overwritten on every restart."""
        name = self.name(user.id)
        raw = await self.docker.get_file(name, f"{CONFIG_DIR}/config.json")
        try:
            cfg = json.loads(raw) if raw else {}
        except ValueError:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        if cfg.get("cloud_rev") == user.settings_rev:
            return
        _env, model = self.model_setup(user)
        cfg.update({"model": model, "cloud_rev": user.settings_rev})
        # The sandbox is a private, single-user workspace: run autonomously,
        # like the CLI default, without the per-command approval menu.
        cfg.setdefault("auto_approve", True)
        await self.docker.put_file(name, CONFIG_DIR, "config.json",
                                   json.dumps(cfg, indent=2).encode())

    # ── lifecycle ────────────────────────────────────────────────────────
    def _base_url(self, info: dict) -> str:
        if self.s.sandbox_reach == "published":
            ports = (info.get("NetworkSettings") or {}).get("Ports") or {}
            binding = (ports.get(f"{SANDBOX_PORT}/tcp") or [{}])[0]
            return f"http://127.0.0.1:{binding.get('HostPort')}"
        return f"http://{self.name(int(info['Config']['Labels']['cc.user']))}:{SANDBOX_PORT}"

    async def ensure_running(self, user: User) -> str:
        """Start (creating or recreating as needed) and return its base URL."""
        name = self.name(user.id)
        async with self._lock(user.id):
            info = await self.docker.inspect(name)
            if info:
                labels = info["Config"].get("Labels") or {}
                if (labels.get("cc.rev") != str(user.settings_rev)
                        or labels.get("cc.image") != self.s.sandbox_image):
                    log.info("recreating %s (settings or image changed)", name)
                    await self.docker.remove(name)
                    info = None
            if info is None:
                await self.docker.ensure_network(self.s.sandbox_network)
                await self.docker.create(name, self._spec(user))
                await self._apply_model(user)
                await self.docker.start(name)
                info = await self.docker.inspect(name)
            elif not info["State"].get("Running"):
                await self.docker.start(name)
                info = await self.docker.inspect(name)
            base = self._base_url(info)
            await self._wait_healthy(base)
            self.touch(user.id)
            return base

    async def _wait_healthy(self, base: str, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = await self._http.get(f"{base}/health")
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
        raise RuntimeError("your workspace did not start in time — please retry")

    async def running_url(self, uid: int) -> Optional[str]:
        info = await self.docker.inspect(self.name(uid))
        if info and info["State"].get("Running"):
            return self._base_url(info)
        return None

    async def status(self, uid: int) -> str:
        info = await self.docker.inspect(self.name(uid))
        if not info:
            return "none"
        return "running" if info["State"].get("Running") else "stopped"

    async def stop(self, uid: int) -> None:
        await self.docker.stop(self.name(uid))

    async def destroy(self, uid: int) -> None:
        """Delete the container and both volumes (account deletion)."""
        async with self._lock(uid):
            await self.docker.remove(self.name(uid))
            await self.docker.remove_volume(f"cc-home-u{uid}")
            await self.docker.remove_volume(f"cc-ws-u{uid}")

    async def _busy(self, uid: int, base: str) -> bool:
        """True if any chat session in the sandbox is mid-turn."""
        try:
            r = await self._http.get(
                f"{base}/api/sessions",
                cookies={LAUNCH_COOKIE: launch_token(self.s.secret, uid)})
            return any(s.get("busy") for s in r.json().get("sessions", []))
        except (httpx.HTTPError, ValueError, AttributeError):
            return True   # unsure → don't kill a possibly working agent

    async def reap_idle(self) -> list[int]:
        """Stop sandboxes idle longer than the limit and not mid-task."""
        stopped = []
        limit = self.s.sandbox_idle_minutes * 60
        now = time.time()
        for c in await self.docker.list("cc.user"):
            if c.get("State") != "running":
                continue
            uid = int(c["Labels"]["cc.user"])
            # First sighting (e.g. after a gateway restart) starts the clock
            # rather than counting as "idle forever".
            if now - self._last_seen.setdefault(uid, now) < limit:
                continue
            base = await self.running_url(uid)
            if base and await self._busy(uid, base):
                self.touch(uid)     # check again after another idle window
                continue
            log.info("stopping idle sandbox %s", self.name(uid))
            await self.stop(uid)
            stopped.append(uid)
        return stopped

    async def close(self) -> None:
        await self._http.aclose()
        await self.docker.close()
