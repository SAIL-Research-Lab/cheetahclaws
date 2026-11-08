"""tools_web.py — Web tool implementations: WebFetch, WebSearch."""
from __future__ import annotations

import asyncio
import os
import time
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse


_DEFAULT_WEB_FETCH_MAX_BYTES = 512 * 1024
_DEFAULT_WEB_MAX_SECONDS = 30


# ── SSRF guard ────────────────────────────────────────────────────────────
#
# WebFetch is auto-approved as a read-only tool, so a prompt-injected page
# could otherwise point the model at http://169.254.169.254/ (cloud
# credentials), http://localhost:8080/admin, or a router on the LAN.  Every
# hop — the first URL and every redirect target — must resolve only to
# public addresses.  The IP classification is shared with the kernel Fetch
# tool (kernel/tools/fetch_tool.py) so the two can't drift apart.
#
# Loopback (localhost, 127/8, ::1) is allowed by default when the model asks
# for it directly — fetching a local dev server is the common case — but a
# redirect from any non-loopback host into loopback is still refused, so a
# public page cannot bounce the fetch onto local services.  Turn this off
# with ``webfetch_allow_loopback: false``.
#
# Escape hatches: ``webfetch_allow_private: true`` turns the check off;
# ``webfetch_allowed_hosts: ["intranet.corp", ".internal.example"]`` exempts
# exact hosts (or, with a leading dot, a domain and its subdomains).  The
# CHEETAHCLAWS_WEBFETCH_ALLOW_PRIVATE=1 environment variable is the
# config-less equivalent of the first.
#
# Residual risk: the name is resolved here and again by the HTTP client, so
# a DNS server answering differently within milliseconds (rebinding) can
# still slip through.  Use bash_sandbox / network policy for hard isolation.

_ALLOWED_SCHEMES = ("http", "https")


def _resolve_host_ips(host: str) -> list[str]:
    from cheetahclaws.kernel.tools.fetch_tool import resolve_host_ips
    return resolve_host_ips(host)


def _is_loopback_ip(ip_str: str) -> bool:
    import ipaddress
    try:
        ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


def _host_allowlisted(host: str, allowed) -> bool:
    if isinstance(allowed, str):
        allowed = [allowed]
    h = host.lower().rstrip(".")
    for a in allowed or ():
        a = str(a).strip().lower().rstrip(".")
        if not a:
            continue
        if a.startswith("."):
            if h == a[1:] or h.endswith(a):
                return True
        elif h == a:
            return True
    return False


def _webfetch_url_guard(config: dict | None) -> Callable[[str], Optional[str]]:
    """Return a per-hop checker: URL → error string, or None when allowed."""
    cfg = config or {}
    allow_private = cfg.get("webfetch_allow_private")
    if allow_private is None:
        allow_private = os.environ.get("CHEETAHCLAWS_WEBFETCH_ALLOW_PRIVATE", "0") == "1"
    allowed_hosts = cfg.get("webfetch_allowed_hosts") or ()
    allow_loopback = cfg.get("webfetch_allow_loopback")
    if allow_loopback is None:
        allow_loopback = os.environ.get("CHEETAHCLAWS_WEBFETCH_ALLOW_LOOPBACK", "1") != "0"
    # The first hop decides whether loopback is in play: only a fetch that
    # *starts* on loopback may stay on loopback through its redirects.
    state = {"first": True, "loopback_chain": False}

    def check(url: str) -> Optional[str]:
        first = state["first"]
        state["first"] = False
        try:
            parsed = urlparse(url)
        except ValueError as e:
            return f"Error: WebFetch could not parse URL {url!r}: {e}"
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            return (f"Error: WebFetch only fetches http(s) URLs, "
                    f"not {parsed.scheme or 'scheme-less'!s} ({url!r}).")
        host = parsed.hostname
        if not host:
            return f"Error: WebFetch URL has no hostname: {url!r}"
        if allow_private or _host_allowlisted(host, allowed_hosts):
            return None
        from cheetahclaws.kernel.tools.fetch_tool import is_private_ip
        try:
            ips = _resolve_host_ips(host)
        except OSError as e:
            return f"Error: WebFetch could not resolve {host!r}: {e}"
        blocked = [ip for ip in ips if is_private_ip(ip)]
        all_loopback = bool(ips) and all(_is_loopback_ip(ip) for ip in ips)
        if all_loopback and allow_loopback and (first or state["loopback_chain"]):
            state["loopback_chain"] = True
            return None
        state["loopback_chain"] = False
        if blocked:
            if all_loopback and allow_loopback:
                return (
                    f"Error: WebFetch refused a redirect to {host!r}: a page on "
                    f"another host may not redirect onto loopback. Fetch the "
                    f"local URL directly instead."
                )
            return (
                f"Error: WebFetch refused {host!r}: it resolves to the "
                f"non-public address {blocked[0]} (loopback, private network, "
                f"link-local or cloud-metadata range). To fetch internal "
                f"hosts, allow this one with /config webfetch_allowed_hosts="
                f"[\"{host}\"] or all of them with /config "
                f"webfetch_allow_private=true."
            )
        return None

    return check

# HTML void elements emit no matching end tag (when written bare, e.g.
# ``<img>``/``<br>`` as DuckDuckGo serves them), so depth counters that
# increment on every start tag and decrement on every end tag would drift.
_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


def _coerce_max_seconds(value: int | float) -> float:
    try:
        return float(max(1, float(value)))
    except (TypeError, ValueError):
        return float(_DEFAULT_WEB_MAX_SECONDS)


class _HTMLTextExtractor(HTMLParser):
    """Extract visible HTML text without regex backtracking hazards."""

    def __init__(self, char_cap: int):
        super().__init__(convert_charrefs=True)
        self._char_cap = char_cap
        self._parts: list[str] = []
        self._chars = 0
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data):
        if self._ignored_depth or not data or self._chars >= self._char_cap:
            return
        text = " ".join(data.split())
        if not text:
            return
        remaining = self._char_cap - self._chars
        self._parts.append(text[:remaining])
        self._chars += min(len(text), remaining)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


class _DuckDuckGoResultParser(HTMLParser):
    """Small, bounded parser for DuckDuckGo's HTML-only result cards."""

    def __init__(self, result_cap: int = 8, field_cap: int = 4_000):
        super().__init__(convert_charrefs=True)
        self._result_cap = result_cap
        self._field_cap = field_cap
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._result_div_depth = 0
        self._title_depth = 0
        self._snippet_depth = 0

    @staticmethod
    def _classes(attrs) -> set[str]:
        # A valueless attribute (e.g. ``<div class>``) yields ('class', None),
        # so ``.get("class", "")`` returns None, not the default — guard with
        # ``or ""`` so a single bare attribute can't crash the whole parse.
        return set((dict(attrs).get("class") or "").split())

    def _finish_current(self) -> None:
        if self._current and (self._current["title"] or self._current["link"]):
            self.results.append(self._current)
        self._current = None
        self._result_div_depth = 0
        self._title_depth = 0
        self._snippet_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in _VOID_ELEMENTS:
            # No end tag will follow, so touching the depth counters here would
            # leave title/snippet depth permanently offset and misattribute the
            # rest of the result's text.
            return
        classes = self._classes(attrs)
        if tag.lower() == "div" and "result" in classes:
            self._finish_current()
            if len(self.results) < self._result_cap:
                self._current = {"title": "", "link": "", "snippet": ""}
                self._result_div_depth = 1
        if self._current is None:
            return
        if tag.lower() == "div" and not ("result" in classes and self._result_div_depth == 1):
            self._result_div_depth += 1
        if "result__title" in classes:
            self._title_depth += 1
        elif self._title_depth:
            self._title_depth += 1
        if "result__snippet" in classes:
            self._snippet_depth += 1
        elif self._snippet_depth:
            self._snippet_depth += 1
        if tag.lower() == "a" and self._title_depth:
            href = dict(attrs).get("href")
            if href:
                self._current["link"] = href[:self._field_cap]

    def handle_endtag(self, tag):
        if tag.lower() in _VOID_ELEMENTS:
            # Mirror handle_starttag: a self-closed void tag (``<br/>``) drives
            # the parser's default start+end pair, so skip it on both sides to
            # keep the depth counters balanced.
            return
        if tag.lower() == "div" and self._current is not None:
            self._result_div_depth -= 1
            if self._result_div_depth <= 0:
                self._finish_current()
                return
        if self._title_depth:
            self._title_depth -= 1
        if self._snippet_depth:
            self._snippet_depth -= 1

    def handle_data(self, data):
        if self._current is None or not data:
            return
        field = "title" if self._title_depth else "snippet" if self._snippet_depth else None
        if not field:
            return
        text = " ".join(data.split())
        if not text:
            return
        existing = self._current[field]
        if len(existing) < self._field_cap:
            separator = " " if existing else ""
            self._current[field] = (existing + separator + text)[:self._field_cap]

    def close(self):
        super().close()
        self._finish_current()


def _read_response_bytes(
    response,
    max_bytes: int,
    max_seconds: int | float = _DEFAULT_WEB_MAX_SECONDS,
    deadline: float | None = None,
) -> tuple[bytes, bool]:
    """Consume at most ``max_bytes`` from a streamed HTTP response."""
    data = bytearray()
    truncated = False
    deadline = deadline if deadline is not None else time.monotonic() + _coerce_max_seconds(max_seconds)
    try:
        content_length = int(response.headers.get("content-length", ""))
    except (TypeError, ValueError):
        content_length = None

    if time.monotonic() >= deadline:
        return b"", True
    # With identity encoding, raw chunks avoid HTTPX's decoded-byte chunker
    # buffering a slow drip until it reaches 64 KiB before we can check time.
    iterator = response.iter_raw() if hasattr(response, "iter_raw") else response.iter_bytes(chunk_size=64 * 1024)
    for chunk in iterator:
        if time.monotonic() >= deadline:
            truncated = True
            break
        remaining = max_bytes - len(data)
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            data.extend(chunk[:remaining])
            truncated = True
            break
        data.extend(chunk)
        if len(data) == max_bytes:
            # Stop immediately: an unknown length is conservatively marked as
            # truncated rather than waiting for another possibly slow chunk.
            truncated = content_length is None or content_length > len(data)
            break

    if content_length is not None:
        truncated = truncated or content_length > len(data)
    return bytes(data), truncated


def _stream_identity_bytes(httpx, url: str, *, params: dict | None,
                           headers: dict[str, str], max_bytes: int,
                           deadline: float,
                           url_guard: Callable[[str], Optional[str]] | None = None,
                           ) -> tuple[bytes | None, bool, dict, str, str | None]:
    """Follow a small redirect chain without resetting the total deadline."""
    current_url = url
    current_params = params
    for redirect_count in range(6):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, True, {}, "utf-8", "Error: web request exceeded its elapsed-time budget."
        if url_guard is not None:
            refused = url_guard(current_url)
            if refused:
                return None, True, {}, "utf-8", refused
        with httpx.stream(
            "GET", current_url, params=current_params, headers=headers,
            timeout=remaining, follow_redirects=False,
        ) as response:
            response_headers = dict(response.headers)
            status = getattr(response, "status_code", 0)
            location = response_headers.get("location")
            if status in {301, 302, 303, 307, 308} and location:
                if redirect_count == 5:
                    return None, True, {}, "utf-8", "Error: web request exceeded 5 redirects."
                current_url = urljoin(str(getattr(response, "url", current_url)), location)
                current_params = None
                continue
            response.raise_for_status()
            content_encoding = response_headers.get("content-encoding", "identity").lower()
            if content_encoding not in {"", "identity"}:
                return (
                    None, True, {}, "utf-8",
                    "Error: compressed HTTP responses are not accepted; retry with identity encoding.",
                )
            raw, truncated = _read_response_bytes(
                response, max_bytes, deadline=deadline,
            )
            return raw, truncated, response_headers, response.encoding or "utf-8", None
    return None, True, {}, "utf-8", "Error: web request could not resolve redirects."


async def _read_response_bytes_async(
    response,
    max_bytes: int,
    deadline: float,
) -> tuple[bytes, bool]:
    """Async counterpart that permits cancellation while a body is stalled."""
    data = bytearray()
    truncated = False
    try:
        content_length = int(response.headers.get("content-length", ""))
    except (TypeError, ValueError):
        content_length = None

    async for chunk in response.aiter_raw():
        if time.monotonic() >= deadline:
            truncated = True
            break
        remaining = max_bytes - len(data)
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            data.extend(chunk[:remaining])
            truncated = True
            break
        data.extend(chunk)
        if len(data) == max_bytes:
            truncated = content_length is None or content_length > len(data)
            break

    if content_length is not None:
        truncated = truncated or content_length > len(data)
    return bytes(data), truncated


async def _stream_identity_bytes_async_impl(
    httpx,
    url: str,
    *,
    params: dict | None,
    headers: dict[str, str],
    max_bytes: int,
    deadline: float,
    url_guard: Callable[[str], Optional[str]] | None = None,
) -> tuple[bytes | None, bool, dict, str, str | None]:
    """Async transport path; outer ``wait_for`` owns the global deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None, True, {}, "utf-8", "Error: web request exceeded its elapsed-time budget."

    async with httpx.AsyncClient(
        headers=headers,
        timeout=remaining,
        follow_redirects=False,
    ) as client:
        current_url = url
        current_params = params
        for redirect_count in range(6):
            if url_guard is not None:
                refused = url_guard(current_url)   # every hop, redirects too
                if refused:
                    return None, True, {}, "utf-8", refused
            request = client.build_request(
                "GET", current_url, params=current_params,
            )
            response = await client.send(request, stream=True)
            try:
                response_headers = dict(response.headers)
                status = getattr(response, "status_code", 0)
                location = response_headers.get("location")
                if status in {301, 302, 303, 307, 308} and location:
                    if redirect_count == 5:
                        return None, True, {}, "utf-8", "Error: web request exceeded 5 redirects."
                    current_url = urljoin(str(getattr(response, "url", current_url)), location)
                    current_params = None
                    continue
                response.raise_for_status()
                content_encoding = response_headers.get("content-encoding", "identity").lower()
                if content_encoding not in {"", "identity"}:
                    return (
                        None, True, {}, "utf-8",
                        "Error: compressed HTTP responses are not accepted; retry with identity encoding.",
                    )
                raw, truncated = await _read_response_bytes_async(
                    response, max_bytes, deadline,
                )
                return raw, truncated, response_headers, response.encoding or "utf-8", None
            finally:
                await response.aclose()
    return None, True, {}, "utf-8", "Error: web request could not resolve redirects."


async def _stream_identity_bytes_async(
    httpx,
    url: str,
    *,
    params: dict | None,
    headers: dict[str, str],
    max_bytes: int,
    deadline: float,
    url_guard: Callable[[str], Optional[str]] | None = None,
) -> tuple[bytes | None, bool, dict, str, str | None]:
    """Enforce one cancellable elapsed-time budget for the entire request."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None, True, {}, "utf-8", "Error: web request exceeded its elapsed-time budget."
    try:
        return await asyncio.wait_for(
            _stream_identity_bytes_async_impl(
                httpx, url, params=params, headers=headers,
                max_bytes=max_bytes, deadline=deadline, url_guard=url_guard,
            ),
            timeout=remaining,
        )
    except asyncio.TimeoutError:
        return None, True, {}, "utf-8", "Error: web request exceeded its elapsed-time budget."


def _stream_bounded_identity_bytes(httpx, url: str, *, params: dict | None,
                                   headers: dict[str, str], max_bytes: int,
                                   deadline: float,
                                   url_guard: Callable[[str], Optional[str]] | None = None,
                                   ) -> tuple[bytes | None, bool, dict, str, str | None]:
    """Use cancellable async I/O in production, retaining a minimal test fallback."""
    if not hasattr(httpx, "AsyncClient"):
        # Lightweight fake HTTP clients used by unit tests only implement the
        # synchronous ``stream`` API. Real httpx always exposes AsyncClient.
        return _stream_identity_bytes(
            httpx, url, params=params, headers=headers,
            max_bytes=max_bytes, deadline=deadline, url_guard=url_guard,
        )
    return asyncio.run(_stream_identity_bytes_async(
        httpx, url, params=params, headers=headers,
        max_bytes=max_bytes, deadline=deadline, url_guard=url_guard,
    ))


def _webfetch(
    url: str,
    prompt: str = None,
    max_bytes: int = _DEFAULT_WEB_FETCH_MAX_BYTES,
    max_seconds: int | float = _DEFAULT_WEB_MAX_SECONDS,
    config: dict | None = None,
) -> str:
    """Fetch ``url`` (bounded in bytes and time) and return its text.

    Every hop, redirects included, must resolve to public addresses; see the
    SSRF guard above for the ``webfetch_allow_private`` /
    ``webfetch_allowed_hosts`` escape hatches carried in ``config``.
    """
    try:
        import httpx
        byte_limit = max(1, int(max_bytes or _DEFAULT_WEB_FETCH_MAX_BYTES))
        seconds = _coerce_max_seconds(max_seconds)
        deadline = time.monotonic() + seconds
        raw, source_truncated, response_headers, encoding, error = _stream_bounded_identity_bytes(
            httpx, url, params=None,
            headers={"User-Agent": "NanoClaude/1.0", "Accept-Encoding": "identity"},
            max_bytes=byte_limit, deadline=deadline,
            url_guard=_webfetch_url_guard(config),
        )
        if error:
            return error
        assert raw is not None
        content_type = response_headers.get("content-type", "")

        text = raw.decode(encoding, errors="replace")
        if "html" in content_type.lower():
            extractor = _HTMLTextExtractor(char_cap=25_000)
            extractor.feed(text)
            extractor.close()
            text = extractor.get_text()

        output = text[:25000]
        if source_truncated:
            output += (
                f"\n\n[... WebFetch stopped after {len(raw):,} response bytes "
                "at its configured byte bound or elapsed collection budget ...]"
            )
        return output
    except ImportError:
        return "Error: httpx not installed — run: pip install httpx"
    except Exception as e:
        return f"Error: {e}"


def _websearch(
    query: str,
    max_bytes: int = _DEFAULT_WEB_FETCH_MAX_BYTES,
    max_seconds: int | float = _DEFAULT_WEB_MAX_SECONDS,
) -> str:
    try:
        import httpx
        byte_limit = max(1, int(max_bytes or _DEFAULT_WEB_FETCH_MAX_BYTES))
        seconds = _coerce_max_seconds(max_seconds)
        deadline = time.monotonic() + seconds
        url = "https://html.duckduckgo.com/html/"
        raw, source_truncated, _headers, encoding, error = _stream_bounded_identity_bytes(
            httpx, url, params={"q": query},
            headers={
                "User-Agent": "Mozilla/5.0 (compatible)",
                "Accept-Encoding": "identity",
            },
            max_bytes=byte_limit, deadline=deadline,
        )
        if error:
            return error
        assert raw is not None
        parser = _DuckDuckGoResultParser()
        parser.feed(raw.decode(encoding, errors="replace"))
        parser.close()
        output = "\n\n".join(
            f"**{result['title']}**\n{result['link']}\n{result['snippet']}"
            for result in parser.results
        ) or "No results found"
        if source_truncated:
            output += (
                f"\n\n[... WebSearch stopped after {len(raw):,} response bytes "
                "at its configured byte bound or elapsed collection budget ...]"
            )
        return output
    except ImportError:
        return "Error: httpx not installed — run: pip install httpx"
    except Exception as e:
        return f"Error: {e}"
