"""fetch_tool.py — bounded HTTP for agents (RFC 0025).

The second-most-dangerous tool the kernel ships (after Exec).
Threats + safety properties are documented in RFC 0025; the
boundary in this module is:

  * https/http schemes only — no file://, gopher://, ftp://, data:.
  * Method allowlist: GET, HEAD, POST.
  * Per-hop capability ``check_net`` + DNS resolution +
    private-IP block (defends SSRF + DNS rebinding).
  * Redirects opt-in; each hop re-validates; Authorization /
    Cookie stripped on redirect.
  * Streaming body read with size cap (4 MB default, 16 MB max).
  * Wall-clock timeout (30 s default, 120 s max).
  * Stdlib only (``http.client``); no third-party HTTP libs.
  * No cookie jar; each fetch is fresh.
  * No env-based proxy.

NOT in register_builtin_tools — operators must call
``register_fetch_tool(registry)`` explicitly.
"""
from __future__ import annotations

import base64
import http.client
import ipaddress
import socket
import ssl
import time
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from .registry import (
    Tool,
    ToolContext,
    ToolFailed,
    ToolInvalidArgs,
    ToolNetDenied,
    ToolRegistry,
)

if TYPE_CHECKING:
    pass


# ── Defaults / limits ────────────────────────────────────────────────────


DEFAULT_MAX_BYTES = 4 * 1024 * 1024
MAX_MAX_BYTES     = 16 * 1024 * 1024
MIN_MAX_BYTES     = 1024

DEFAULT_TIMEOUT_S = 30
MAX_TIMEOUT_S     = 120
MIN_TIMEOUT_S     = 1

DEFAULT_MAX_REDIRECTS = 3
MAX_MAX_REDIRECTS     = 5

ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST"})
ALLOWED_SCHEMES = frozenset({"http", "https"})

MAX_BODY_BYTES = 1024 * 1024     # 1 MB POST body cap
MAX_HEADER_NAME_LEN  = 64
MAX_HEADER_VALUE_LEN = 4096

# Headers we never let the caller set — we control them.
RESERVED_HEADERS = frozenset({"host", "content-length"})

# Headers stripped on redirect (security).
SENSITIVE_HEADERS = frozenset({"authorization", "cookie",
                                "proxy-authorization"})


# ── IP classification ────────────────────────────────────────────────────


def _is_private_ip(ip_str: str) -> bool:
    """True iff the IP is in a private / loopback / link-local /
    metadata range. Belt-and-braces against SSRF."""
    try:
        ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    except (ValueError, AttributeError):
        # Couldn't parse — be conservative.
        return True
    # ::ffff:127.0.0.1 and friends reach the embedded IPv4 address.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _is_private_ip(str(mapped))
    if ip.is_loopback:        return True   # 127/8, ::1
    if ip.is_private:         return True   # 10/8, 172.16/12, 192.168/16, fc00::/7
    if ip.is_link_local:      return True   # 169.254/16, fe80::/10
    if ip.is_unspecified:     return True   # 0.0.0.0
    if ip.is_reserved:        return True
    if ip.is_multicast:       return True
    # Cloud metadata endpoints are link-local (already covered),
    # but extra defence:
    if ip_str in ("169.254.169.254", "fd00:ec2::254"):
        return True
    # Shared address space (100.64/10, carrier-grade NAT; also Alibaba
    # Cloud's 100.100.100.200 metadata endpoint) is not "private" to the
    # stdlib but is never a public destination either.
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return False


# Public alias so other fetchers (tools/web.py WebFetch) share one SSRF rule.
is_private_ip = _is_private_ip


def resolve_host_ips(host: str) -> list[str]:
    """Every address ``host`` resolves to (IPv4 and IPv6), de-duplicated.

    A literal IP is returned as-is. Raises OSError when resolution fails.
    Checking *all* answers matters: a name with one public and one private
    A record would otherwise pass a first-answer-only check.
    """
    h = host.strip("[]")
    try:
        ipaddress.ip_address(h.split("%", 1)[0])
        return [h]
    except ValueError:
        pass
    out: list[str] = []
    for info in socket.getaddrinfo(h, None, proto=socket.IPPROTO_TCP):
        addr = info[4][0]
        if addr not in out:
            out.append(addr)
    if not out:
        raise OSError(f"no addresses for {host!r}")
    return out


# ── Validation helpers ───────────────────────────────────────────────────


def _validate_url(url) -> str:
    if not isinstance(url, str) or not url:
        raise ToolInvalidArgs("'url' must be a non-empty string")
    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise ToolInvalidArgs(f"unparseable url: {e}") from e
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ToolInvalidArgs(
            f"scheme {parsed.scheme!r} not allowed; "
            f"only {sorted(ALLOWED_SCHEMES)}",
        )
    if not parsed.hostname:
        raise ToolInvalidArgs("url must include a hostname")
    return url


def _validate_method(method) -> str:
    if not isinstance(method, str):
        raise ToolInvalidArgs("'method' must be a string")
    m = method.upper()
    if m not in ALLOWED_METHODS:
        raise ToolInvalidArgs(
            f"method {method!r} not allowed; "
            f"only {sorted(ALLOWED_METHODS)}",
        )
    return m


def _validate_headers(headers) -> dict:
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise ToolInvalidArgs("'headers' must be a dict")
    out = {}
    for k, v in headers.items():
        if not isinstance(k, str) or not k:
            raise ToolInvalidArgs(
                f"header name must be non-empty str, got {k!r}",
            )
        if k.lower() in RESERVED_HEADERS:
            raise ToolInvalidArgs(
                f"header {k!r} is reserved (set by Fetch internally)",
            )
        if len(k) > MAX_HEADER_NAME_LEN:
            raise ToolInvalidArgs(
                f"header name too long: {k!r}",
            )
        if not isinstance(v, str):
            raise ToolInvalidArgs(
                f"header value for {k!r} must be str",
            )
        if len(v) > MAX_HEADER_VALUE_LEN:
            raise ToolInvalidArgs(
                f"header value for {k!r} too long",
            )
        # Reject CR/LF in header values (HTTP request smuggling).
        if "\r" in v or "\n" in v:
            raise ToolInvalidArgs(
                f"header value for {k!r} contains CR/LF",
            )
        # Reject NUL/control in header name.
        for ch in k:
            if ord(ch) < 0x20 or ord(ch) == 0x7f:
                raise ToolInvalidArgs(
                    f"header name {k!r} contains control char",
                )
        out[k] = v
    return out


def _build_body(body, method: str) -> bytes:
    if body is None:
        return b""
    if method != "POST":
        raise ToolInvalidArgs(
            f"'body' only valid with POST, got {method}",
        )
    if isinstance(body, str):
        data = body.encode("utf-8")
    elif isinstance(body, dict) and "_b64" in body:
        # base64-encoded bytes envelope
        b64 = body["_b64"]
        if not isinstance(b64, str):
            raise ToolInvalidArgs("'body._b64' must be a string")
        try:
            data = base64.b64decode(b64, validate=True)
        except Exception as e:
            raise ToolInvalidArgs(
                f"'body._b64' is not valid base64: {e}",
            ) from e
    else:
        raise ToolInvalidArgs(
            "'body' must be a string or {'_b64': '...'}",
        )
    if len(data) > MAX_BODY_BYTES:
        raise ToolInvalidArgs(
            f"body too large: {len(data)} > {MAX_BODY_BYTES}",
        )
    return data


def _validate_max_bytes(n) -> int:
    if n is None:
        return DEFAULT_MAX_BYTES
    if not isinstance(n, int) or n < MIN_MAX_BYTES or n > MAX_MAX_BYTES:
        raise ToolInvalidArgs(
            f"'max_bytes' must be int in [{MIN_MAX_BYTES}, "
            f"{MAX_MAX_BYTES}], got {n!r}",
        )
    return n


def _validate_timeout(t) -> int:
    if t is None:
        return DEFAULT_TIMEOUT_S
    if not isinstance(t, (int, float)):
        raise ToolInvalidArgs("'timeout_s' must be a number")
    t_int = int(t)
    if t_int < MIN_TIMEOUT_S or t_int > MAX_TIMEOUT_S:
        raise ToolInvalidArgs(
            f"'timeout_s' must be in [{MIN_TIMEOUT_S}, "
            f"{MAX_TIMEOUT_S}], got {t_int}",
        )
    return t_int


def _validate_max_redirects(n) -> int:
    if n is None:
        return DEFAULT_MAX_REDIRECTS
    if not isinstance(n, int) or n < 0 or n > MAX_MAX_REDIRECTS:
        raise ToolInvalidArgs(
            f"'max_redirects' must be int in [0, {MAX_MAX_REDIRECTS}], "
            f"got {n!r}",
        )
    return n


# ── Per-hop capability + IP check ────────────────────────────────────────


def _check_hop(url: str, ctx: ToolContext) -> tuple:
    """Run capability + DNS + IP checks on a URL. Returns parsed
    components for the actual fetch."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ToolInvalidArgs(
            f"scheme {parsed.scheme!r} not allowed in URL {url!r}",
        )
    host = parsed.hostname
    if not host:
        raise ToolInvalidArgs(f"URL has no hostname: {url!r}")
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    path_q = parsed.path or "/"
    if parsed.query:
        path_q = f"{path_q}?{parsed.query}"

    # Capability gate via cap.check_net.
    if ctx.kernel is not None:
        if not ctx.kernel.cap.check_net(ctx.pid, host):
            raise ToolNetDenied(
                f"agent {ctx.pid} not granted net for {host!r}",
            )

    # DNS resolve + IP block.
    try:
        ip = socket.gethostbyname(host)
    except OSError as e:
        raise ToolFailed(f"DNS resolution failed for {host!r}: {e}") from e
    if _is_private_ip(ip):
        raise ToolNetDenied(
            f"hostname {host!r} resolved to non-public IP {ip}",
        )

    return parsed.scheme, host, port, path_q, ip


# ── HTTP execution ───────────────────────────────────────────────────────


def _read_capped(
    resp, max_bytes: int,
    *,
    on_chunk=None,
    chunk_metadata: dict = None,
) -> tuple[bytes, bool]:
    """Stream-read up to max_bytes+1 to detect truncation cleanly.

    RFC 0029: when ``on_chunk`` is supplied, each ``resp.read(8192)``
    block also fires the callback with a chunk message. Once the
    truncation cap is reached, no further chunks are emitted —
    matches the body-trimming behaviour for the final result.
    """
    buf = bytearray()
    while len(buf) < max_bytes + 1:
        chunk = resp.read(8192)
        if not chunk:
            break
        # Only emit chunks for bytes that fit under the cap. The
        # one-byte overflow used for truncation detection isn't
        # streamed.
        if on_chunk is not None and len(buf) < max_bytes:
            slice_end = min(len(chunk), max_bytes - len(buf))
            streamable = chunk[:slice_end]
            if streamable:
                meta = dict(chunk_metadata or {})
                meta["bytes_so_far"] = len(buf) + len(streamable)
                try:
                    on_chunk({
                        "op":       "chunk",
                        "kind":     "body",
                        "content":  streamable.decode(
                            "utf-8", errors="replace",
                        ),
                        "metadata": meta,
                    })
                except Exception:
                    pass
        buf.extend(chunk)
    truncated = len(buf) > max_bytes
    return bytes(buf[:max_bytes]), truncated


def _decode_body(raw: bytes) -> tuple[str, str]:
    """Best-effort UTF-8 decode; fall back to base64 for binary."""
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return base64.b64encode(raw).decode("ascii"), "base64"


def _do_request(
    scheme: str, host: str, port: int, path_q: str,
    method: str, headers: dict, body_bytes: bytes,
    timeout_s: float,
):
    """Open a single http.client connection, send, return the
    response object (caller reads + closes)."""
    if scheme == "https":
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(
            host, port=port, timeout=timeout_s, context=ctx,
        )
    else:
        conn = http.client.HTTPConnection(
            host, port=port, timeout=timeout_s,
        )
    try:
        # Build header dict for http.client.
        h = dict(headers)
        if body_bytes and "content-type" not in {k.lower() for k in h}:
            h["Content-Type"] = "application/octet-stream"
        conn.request(method, path_q, body=body_bytes or None, headers=h)
        return conn, conn.getresponse()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise


def _absolutise(base_url: str, location: str) -> str:
    """Anchor a redirect Location header against the base URL."""
    return urljoin(base_url, location)


# ── Handler ──────────────────────────────────────────────────────────────


def fetch_handler(args: dict, ctx: ToolContext) -> dict:
    url            = _validate_url(args.get("url"))
    method         = _validate_method(args.get("method", "GET"))
    headers_in     = _validate_headers(args.get("headers"))
    body_bytes     = _build_body(args.get("body"), method)
    max_bytes      = _validate_max_bytes(args.get("max_bytes"))
    timeout_s      = _validate_timeout(args.get("timeout_s"))
    follow         = bool(args.get("follow_redirects", False))
    max_redirects  = _validate_max_redirects(args.get("max_redirects"))
    stream_arg     = args.get("stream")
    if stream_arg is not None and not isinstance(stream_arg, bool):
        raise ToolInvalidArgs(
            f"'stream' must be bool, got {type(stream_arg).__name__}",
        )
    stream_enabled = bool(stream_arg) and ctx.on_chunk is not None

    redirects: list = []
    current_url     = url
    current_headers = dict(headers_in)
    started_at      = time.monotonic()

    final_resp = None
    final_body_raw = b""
    final_body_truncated = False
    final_status = 0
    final_headers: dict = {}

    for hop in range(max_redirects + 2):  # +1 attempts, +1 cap-check
        scheme, host, port, path_q, _ip = _check_hop(current_url, ctx)
        try:
            conn, resp = _do_request(
                scheme, host, port, path_q,
                method, current_headers, body_bytes, timeout_s,
            )
        except (socket.timeout, TimeoutError) as e:
            raise ToolFailed(
                f"request timed out after {timeout_s}s",
            ) from e
        except (ConnectionError, OSError) as e:
            raise ToolFailed(f"connection error: {e}") from e
        try:
            status = resp.status
            resp_headers = dict(
                (k.lower(), v) for k, v in resp.getheaders()
            )
            # Decide redirect or terminal.
            if 300 <= status < 400 and follow:
                if hop >= max_redirects:
                    raise ToolFailed(
                        f"too many redirects (> {max_redirects})",
                    )
                # Drain body before reusing
                resp.read()
                location = resp_headers.get("location")
                if not location:
                    final_resp = resp
                    final_body_raw, final_body_truncated = b"", False
                    final_status = status
                    final_headers = resp_headers
                    break
                next_url = _absolutise(current_url, location)
                redirects.append({
                    "from":   current_url,
                    "to":     next_url,
                    "status": status,
                })
                # Strip auth headers per RFC 0025 §1 "Defended
                # against — Auth/Cookie leak across redirect".
                current_headers = {
                    k: v for k, v in current_headers.items()
                    if k.lower() not in SENSITIVE_HEADERS
                }
                # If redirect is 303, force GET; if 307/308, keep
                # method. RFC 7231.
                if status == 303:
                    method = "GET"
                    body_bytes = b""
                current_url = next_url
                continue
            # Terminal — read body with cap. Only the terminal hop
            # streams; intermediate redirect bodies are drained
            # via the resp.read() above without emitting chunks.
            final_body_raw, final_body_truncated = _read_capped(
                resp, max_bytes,
                on_chunk=ctx.on_chunk if stream_enabled else None,
                chunk_metadata={
                    "tool":   "Fetch",
                    "url":    current_url,
                    "status": int(status),
                },
            )
            final_status = status
            final_headers = resp_headers
            final_resp = resp
            break
        finally:
            try:
                conn.close()
            except Exception:
                pass
    else:
        raise ToolFailed("redirect loop exceeded")

    if final_resp is None:
        raise ToolFailed("no response captured")

    body_text, encoding = _decode_body(final_body_raw)
    duration_s = round(time.monotonic() - started_at, 4)

    return {
        "url":         current_url,
        "status":      int(final_status),
        "headers":     final_headers,
        "body":        body_text,
        "encoding":    encoding,
        "body_bytes":  len(final_body_raw) + (1 if final_body_truncated else 0),
        "truncated":   final_body_truncated,
        "redirects":   redirects,
        "duration_s":  duration_s,
    }


FETCH_TOOL = Tool(
    name="Fetch",
    description=(
        "Issue an HTTP request to a URL. "
        "Requires 'Fetch' tool capability AND net_grants on the URL's "
        "host. Resolved IP must be public (private/loopback ranges "
        "blocked as a DNS-rebinding defence). Body capped, timeout "
        "enforced, redirects opt-in with auth-header strip. "
        "See RFC 0025 for the threat model."
    ),
    handler=fetch_handler,
    requires_capability=True,
    requires_fs=(),  # Handler does its own net + IP checks.
)


def register_fetch_tool(registry: ToolRegistry, **_) -> str:
    """Register the Fetch tool. **Opt-in** — not called by
    ``register_builtin_tools``. Operators must explicitly enable
    network access for agents."""
    registry.register(FETCH_TOOL)
    return FETCH_TOOL.name


__all__ = [
    "FETCH_TOOL", "fetch_handler", "register_fetch_tool",
    "DEFAULT_MAX_BYTES", "DEFAULT_TIMEOUT_S",
]
