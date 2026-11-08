"""Shared HTTP helper with timeout + retry. stdlib only.

Backoff strategy
================
Transient failures (timeout, 5xx, 429) get retried. The schedule is
intentionally **different for 429** than for other failures, because
429 means "you exceeded the source's rate limit" — a 500 ms wait does
nothing, while a 30 s wait actually clears the bucket on most APIs:

  * 5xx / timeout / connection error
        attempt 0 → 0.5 s   1 → 1 s   2 → 2 s   3 → 4 s

  * 429 (Too Many Requests)
        attempt 0 → 10 s   1 → 30 s   2 → 60 s   3 → 120 s
        ALSO honours a ``Retry-After`` header (seconds or HTTP date)
        when present, capping at 180 s.

Default retry budget: 4 attempts total (was 2).
"""
from __future__ import annotations

import calendar
import email.utils
import json as _json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

DEFAULT_UA = "CheetahClaws-Research/1.0 (+https://github.com/SAIL-Research-Lab/cheetahclaws)"
DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 4   # ↑ from 2 — academic APIs hit 429 routinely
_BACKOFF_429 = (10.0, 30.0, 60.0, 120.0)
_BACKOFF_OTHER = (0.5, 1.0, 2.0, 4.0)
_RETRY_AFTER_CAP = 180.0


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url
        self.body = body


def _parse_retry_after(header_val: Optional[str]) -> Optional[float]:
    """Convert a Retry-After header (seconds or HTTP date) to seconds."""
    if not header_val:
        return None
    val = header_val.strip()
    # Pure-number form (seconds).
    try:
        return float(val)
    except ValueError:
        pass
    # HTTP-date form.
    try:
        parsed = email.utils.parsedate_tz(val)
        if parsed is None:
            return None
        target = calendar.timegm(parsed[:9]) - (parsed[9] or 0)
        delta = target - time.time()
        return max(0.0, delta)
    except Exception:
        return None


def _backoff_seconds(status: Optional[int], attempt: int,
                     retry_after_header: Optional[str] = None) -> float:
    """Pick the right backoff for this attempt.  For 429, prefer the
    server-supplied Retry-After if present (capped at 3 min)."""
    if status == 429:
        ra = _parse_retry_after(retry_after_header)
        if ra is not None:
            return min(ra, _RETRY_AFTER_CAP)
        idx = min(attempt, len(_BACKOFF_429) - 1)
        return _BACKOFF_429[idx]
    idx = min(attempt, len(_BACKOFF_OTHER) - 1)
    return _BACKOFF_OTHER[idx]


def get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    as_json: bool = True,
):
    """GET with retry on transient failures (timeouts, 5xx, 429).

    Returns parsed JSON if as_json=True (default), otherwise raw bytes.
    Raises HttpError on 4xx (non-429), and the last exception after retries.
    """
    if params:
        qs = urllib.parse.urlencode(params, doseq=True)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{qs}"

    hdrs = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if as_json:
                    return _json.loads(raw.decode("utf-8", errors="replace"))
                return raw
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(_backoff_seconds(e.code, attempt, retry_after))
                last_exc = HttpError(e.code, url, body)
                continue
            raise HttpError(e.code, url, body) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(_backoff_seconds(None, attempt))
                continue
            raise
    if last_exc:
        raise last_exc


def post_json(
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
):
    """POST JSON with retry. Returns parsed JSON response."""
    hdrs = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        hdrs.update(headers)

    body = _json.dumps(payload).encode("utf-8")

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return _json.loads(raw.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(_backoff_seconds(e.code, attempt, retry_after))
                last_exc = HttpError(e.code, url, body_text)
                continue
            raise HttpError(e.code, url, body_text) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(_backoff_seconds(None, attempt))
                continue
            raise
    if last_exc:
        raise last_exc
