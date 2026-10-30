"""Google Scholar via the Serply API — real citation counts without scraping.

Needs SERPLY_API_KEY (https://serply.io). Silently skips without a key.
Unlike the `scholarly`-based google_scholar source, this one goes through
a hosted API, so it is not CAPTCHA-prone and answers in ~1-2 s.
"""
from __future__ import annotations

import os
import re

from ..http import get
from ..types import Result
from . import SourceSkipped, SourceSpec, register

_ENDPOINT = "https://api.serply.io/v1/scholar"
# The byline reads "P Lewis, E Perez… - Advances in neural…, 2020 - neurips.cc"
_BYLINE_YEAR = re.compile(r",\s*((?:19|20)\d{2})\s*(?:-|$)")


def _year(byline: str) -> str:
    m = _BYLINE_YEAR.search(byline)
    return m.group(1) if m else ""


def search(query: str, limit: int = 10, config: dict | None = None,
           time_range=None) -> list[Result]:
    key = (
        (config or {}).get("serply_api_key")
        or os.environ.get("SERPLY_API_KEY")
    )
    if not key:
        raise SourceSkipped("SERPLY_API_KEY not set")

    headers = {"X-Api-Key": key, "Accept": "application/json"}
    params = {"q": query, "num": min(limit, 20)}
    # Scholar's own year filter, passed through by Serply
    if time_range and time_range.is_bounded:
        if time_range.since:
            params["as_ylo"] = time_range.since.year
        if time_range.until:
            params["as_yhi"] = time_range.until.year

    data = get(_ENDPOINT, params=params, headers=headers)

    out: list[Result] = []
    for item in data.get("articles") or []:
        title = (item.get("title") or "").strip()
        url = (item.get("link") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        author = item.get("author") or {}
        byline = (author.get("names") or item.get("description") or "")
        byline = byline.replace("\xa0", " ").strip()
        names = [a.get("name") for a in author.get("authors") or [] if a.get("name")]
        if names:
            author_str = ", ".join(names[:3])
            if len(names) > 3:
                author_str += f", +{len(names) - 3} more"
        else:
            author_str = byline.split(" - ")[0].rstrip("\u2026 ")
        year = _year(byline)

        extras = item.get("extras") or {}
        cited = extras.get("citations") or {}
        digits = re.sub(r"\D", "", cited.get("count") or "")
        num_citations = int(digits) if digits else 0

        out.append(Result(
            source="serply_scholar",
            title=title,
            url=url,
            snippet=byline[:500],
            author=author_str,
            published=f"{year}-01-01" if year else "",
            engagement_raw=num_citations,
            engagement_label=f"{num_citations:,} citations (Scholar)",
            domain="academic",
            extra={
                "pdf_url": (item.get("doc") or {}).get("link") or "",
                "cites_url": cited.get("link") or "",
            },
        ))
        if len(out) >= limit:
            break
    return out


register(SourceSpec(
    name="serply_scholar",
    domains=["academic"],
    tier="optional",
    search=search,
    requires_env=["SERPLY_API_KEY"],
    description="Google Scholar via Serply — citation counts, no scraping (optional, SERPLY_API_KEY)",
))
