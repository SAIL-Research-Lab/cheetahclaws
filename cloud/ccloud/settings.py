"""Gateway configuration, read once from the environment (see .env.example)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _docker_socket() -> str:
    explicit = _env("CC_DOCKER_SOCK")
    if explicit:
        return explicit
    host = _env("DOCKER_HOST")
    if host.startswith("unix://"):
        return host[len("unix://"):]
    return "/var/run/docker.sock"


@dataclass
class Settings:
    public_url: str = field(default_factory=lambda: _env("CC_PUBLIC_URL", "http://localhost:8000").rstrip("/"))
    secret: str = field(default_factory=lambda: _env("CC_SECRET"))
    fernet_key: str = field(default_factory=lambda: _env("CC_FERNET_KEY"))
    db_url: str = field(default_factory=lambda: _env("CC_DB_URL", "sqlite:///./cloud.db"))

    # ── Per-user sandboxes ────────────────────────────────────────────────
    docker_sock: str = field(default_factory=_docker_socket)
    sandbox_image: str = field(default_factory=lambda: _env("CC_SANDBOX_IMAGE", "cheetahclaws-sandbox:latest"))
    sandbox_network: str = field(default_factory=lambda: _env("CC_SANDBOX_NETWORK", "cc-sandbox"))
    # "network": reach a sandbox by container name on sandbox_network (the
    # gateway itself runs in a container on that network — production).
    # "published": publish the sandbox port on 127.0.0.1 (gateway on the host,
    # e.g. local development with rootless Docker).
    sandbox_reach: str = field(default_factory=lambda: _env("CC_SANDBOX_REACH", "network"))
    sandbox_memory: str = field(default_factory=lambda: _env("CC_SANDBOX_MEMORY", "2g"))
    sandbox_cpus: float = field(default_factory=lambda: float(_env("CC_SANDBOX_CPUS", "1.0")))
    sandbox_pids: int = field(default_factory=lambda: int(_env("CC_SANDBOX_PIDS", "512")))
    sandbox_runtime: str = field(default_factory=lambda: _env("CC_SANDBOX_RUNTIME"))   # e.g. runsc (gVisor)
    sandbox_idle_minutes: int = field(default_factory=lambda: int(_env("CC_SANDBOX_IDLE_MINUTES", "30")))
    # How sandboxes call the metered model gateway (no trailing slash).
    internal_url: str = field(default_factory=lambda: _env("CC_INTERNAL_URL", "http://cc-gateway:8000").rstrip("/"))

    # ── Credits / billing ─────────────────────────────────────────────────
    signup_credit_usd: float = field(default_factory=lambda: float(_env("CC_SIGNUP_CREDIT_USD", "0.50")))
    stripe_secret: str = field(default_factory=lambda: _env("CC_STRIPE_SECRET"))
    stripe_webhook_secret: str = field(default_factory=lambda: _env("CC_STRIPE_WEBHOOK_SECRET"))
    topup_packs_usd: list = field(default_factory=lambda: [
        float(x) for x in _env("CC_TOPUP_PACKS_USD", "5,20,50").split(",") if x.strip()])

    # ── Our model service ─────────────────────────────────────────────────
    models_file: str = field(default_factory=lambda: _env(
        "CC_MODELS_FILE", str(Path(__file__).resolve().parent.parent / "models.json")))

    registration_open: bool = field(default_factory=lambda: _env("CC_REGISTRATION_OPEN", "true").lower() != "false")

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    def load_models(self) -> list[dict]:
        """The platform model catalog. Each entry:
        {id, label, upstream_base, upstream_model, key_env,
         price_in, price_out (USD per 1M tokens, what the user pays),
         context}"""
        try:
            data = json.loads(Path(self.models_file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        models = data.get("models", data) if isinstance(data, dict) else data
        return [m for m in models if isinstance(m, dict) and m.get("id")]

    def validate(self) -> None:
        missing = [n for n, v in (("CC_SECRET", self.secret),
                                  ("CC_FERNET_KEY", self.fernet_key)) if not v]
        if missing:
            raise RuntimeError(
                f"missing required settings: {', '.join(missing)} — see cloud/.env.example "
                "(cloud/deploy.sh generates them)")
        if len(self.secret) < 32:
            raise RuntimeError("CC_SECRET must be at least 32 characters")


settings = Settings()
