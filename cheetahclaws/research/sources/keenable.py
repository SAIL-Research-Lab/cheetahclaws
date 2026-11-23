"""Keenable Search API — web search from Keenable's own index.

Opt-in. Runs only when KEENABLE_API_KEY is set (keyed endpoint), or when
KEENABLE_KEYLESS=1 / config `keenable_keyless: true` opts into the keyless
public endpoint (shared per-IP limit, no account). Otherwise it skips itself,
like the other optional sources. Keenable logs queries on its default data
policy with or without a key: https://docs.keenable.ai/data-privacy

`time_range` isn't forwarded; the ranker's recency weighting still applies.
"""
from __future__ import annotations

import os

from ..http import post_json
from ..types import Result
from . import SourceSkipped, SourceSpec, register

_ENDPOINT = "https://api.keenable.ai/v1/search"
_PUBLIC_ENDPOINT = "https://api.keenable.ai/v1/search/public"
_TITLE = "CheetahClaws"
_TRUTHY = {"1", "true", "yes", "on"}


def _keyless_opt_in(config: dict) -> bool:
    flag = config.get("keenable_keyless")
    if flag is None:
        flag = os.environ.get("KEENABLE_KEYLESS", "")
    return str(flag).strip().lower() in _TRUTHY


def search(query: str, limit: int = 20, config: dict | None = None,
           time_range=None) -> list[Result]:
    config = config or {}
    key = config.get("keenable_api_key") or os.environ.get("KEENABLE_API_KEY")
    if key:
        url, headers = _ENDPOINT, {"X-API-Key": key}
    elif _keyless_opt_in(config):
        url, headers = _PUBLIC_ENDPOINT, {"X-Keenable-Title": _TITLE}
    else:
        raise SourceSkipped("KEENABLE_API_KEY not set (or set KEENABLE_KEYLESS=1)")

    data = post_json(url, {"query": query, "max_results": min(limit, 20)},
                     headers=headers)

    out: list[Result] = []
    for item in data.get("results") or []:
        title = (item.get("title") or "").strip()
        link = (item.get("url") or "").strip()
        if not title or not link:
            continue
        snippet = (item.get("snippet") or item.get("description") or "")[:500]
        out.append(Result(
            source="keenable",
            title=title,
            url=link,
            snippet=snippet,
            domain="web",
        ))
    return out


register(SourceSpec(
    name="keenable",
    domains=["web"],
    tier="optional",
    search=search,
    requires_env=["KEENABLE_API_KEY"],
    description="Keenable web search (optional, KEENABLE_API_KEY or KEENABLE_KEYLESS=1)",
))
