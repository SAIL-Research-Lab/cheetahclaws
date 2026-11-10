"""Minimal async Docker Engine API client over the Unix socket (httpx).

Just what the sandbox manager needs, without pulling in the docker SDK.
"""
from __future__ import annotations

import io
import json
import tarfile
from typing import Optional

import httpx


class DockerError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"docker API {status}: {message}")
        self.status = status


class DockerAPI:
    def __init__(self, socket_path: str):
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://docker", timeout=120)

    async def close(self) -> None:
        await self._client.aclose()

    async def _req(self, method: str, path: str, ok=(200, 201, 204, 304),
                   **kw) -> httpx.Response:
        r = await self._client.request(method, path, **kw)
        if r.status_code not in ok:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise DockerError(r.status_code, msg)
        return r

    # ── containers ───────────────────────────────────────────────────────
    async def inspect(self, name: str) -> Optional[dict]:
        r = await self._client.get(f"/containers/{name}/json")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise DockerError(r.status_code, r.text)
        return r.json()

    async def create(self, name: str, spec: dict) -> str:
        r = await self._req("POST", "/containers/create", params={"name": name}, json=spec)
        return r.json()["Id"]

    async def start(self, name: str) -> None:
        await self._req("POST", f"/containers/{name}/start")

    async def stop(self, name: str, timeout: int = 10) -> None:
        await self._req("POST", f"/containers/{name}/stop", ok=(204, 304, 404),
                        params={"t": timeout})

    async def remove(self, name: str) -> None:
        await self._req("DELETE", f"/containers/{name}", ok=(204, 404),
                        params={"force": "true"})

    async def list(self, label: str) -> list[dict]:
        r = await self._req("GET", "/containers/json", params={
            "all": "true", "filters": json.dumps({"label": [label]})})
        return r.json()

    async def get_file(self, name: str, path: str) -> Optional[bytes]:
        r = await self._client.get(f"/containers/{name}/archive", params={"path": path})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise DockerError(r.status_code, r.text)
        with tarfile.open(fileobj=io.BytesIO(r.content)) as tf:
            for member in tf.getmembers():
                if member.isfile():
                    fh = tf.extractfile(member)
                    return fh.read() if fh else None
        return None

    async def put_file(self, name: str, directory: str, filename: str,
                       data: bytes, uid: int = 1000, gid: int = 1000,
                       mode: int = 0o600) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(filename)
            info.size, info.uid, info.gid, info.mode = len(data), uid, gid, mode
            tf.addfile(info, io.BytesIO(data))
        await self._req("PUT", f"/containers/{name}/archive", params={"path": directory},
                        content=buf.getvalue(),
                        headers={"Content-Type": "application/x-tar"})

    # ── volumes / networks ───────────────────────────────────────────────
    async def remove_volume(self, name: str) -> None:
        await self._req("DELETE", f"/volumes/{name}", ok=(204, 404), params={"force": "true"})

    async def ensure_network(self, name: str) -> None:
        r = await self._client.get(f"/networks/{name}")
        if r.status_code == 200:
            return
        await self._req("POST", "/networks/create", json={
            "Name": name, "Driver": "bridge", "CheckDuplicate": True,
            "Labels": {"cc.role": "sandbox-net"}})
