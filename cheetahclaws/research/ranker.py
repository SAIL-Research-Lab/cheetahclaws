"""Cross-source engagement normalization.

Different sources report engagement on wildly different scales:
    - HackerNews points: 1 — 5000+
    - GitHub stars:      1 — 200000+
    - Reddit upvotes:    1 — 300000+
    - Semantic Scholar citations: 0 — 100000+
    - arXiv has no engagement, but recency is a proxy

The ranker normalizes each source to a 0—1 score via log scaling against
a calibrated per-source reference point, then blends with a recency
bonus. Results are sorted in place.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .types import Result

# Per-source calibration: value at which engagement_score → 1.0.
# Tuned so that "legitimately viral" content clusters near 1.0 and the
# median piece of content sits around 0.3—0.5.
_CALIBRATION: dict[str, float] = {
    "hackernews":        500.0,
    "github":            5000.0,
    "reddit":            2000.0,
    "semantic_scholar":  100.0,
    "arxiv":             1.0,       # no signal → flat 0.5, recency does the work
    "openalex":          100.0,
    "serply_scholar":    100.0,
    "google_news":       1.0,
    "polymarket":        10000.0,   # USD volume
    "sec_edgar":         1.0,
    "tavily":            1.0,
    "brave":             1.0,
    "stackoverflow":     100.0,
    "huggingface":       100.0,     # upvotes + comments
    "alphaxiv":          1.0,       # no native engagement → recency wins
    "zhihu":             500.0,     # 赞 count
    "twitter":           2000.0,    # likes + 3×retweets + replies + 2×quotes
    "bilibili":          5000.0,    # blended: plays/100 + 2*likes + danmu/2 + comments/2
    "weibo":             1000.0,    # attitudes + 2*reposts + comments
    "xiaohongshu":       3000.0,    # likes + comments + collects
}


def rank(results: list[Result]) -> list[Result]:
    """Populate engagement_score on each result and sort descending.

    Returns the same list (mutated) so callers can chain.
    """
    now = datetime.now(timezone.utc)
    for r in results:
        eng = _normalize_engagement(r)
        rec = _recency_bonus(r.published, now)
        r.engagement_score = round(0.7 * eng + 0.3 * rec, 4)
    results.sort(key=lambda x: x.engagement_score, reverse=True)
    return results


def _normalize_engagement(r: Result) -> float:
    cap = _CALIBRATION.get(r.source, 100.0)
    if r.engagement_raw <= 0:
        return 0.5 if cap == 1.0 else 0.0
    return min(1.0, math.log1p(r.engagement_raw) / math.log1p(cap))


def _recency_bonus(published: str, now: datetime) -> float:
    """Return 1.0 for today, decaying exponentially (half-life ~14 days)."""
    if not published:
        return 0.3
    dt = _parse_date(published)
    if dt is None:
        return 0.3
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return 0.5 ** (age_days / 14.0)


def _parse_date(s: str) -> datetime | None:
    s = s.strip()
    if not s:
        return None
    # Common formats we might see
    fmts = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    # Fallback: try fromisoformat (python 3.11+ handles Z)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def dedupe(results: list[Result]) -> list[Result]:
    """Collapse duplicate URLs, keeping the highest-engagement entry."""
    best: dict[str, Result] = {}
    out: list[Result] = []
    for r in results:
        key = r.url.rstrip("/").lower() if r.url else f"{r.source}::{r.title}"
        if key not in best or r.engagement_raw > best[key].engagement_raw:
            best[key] = r
    for key, r in best.items():
        out.append(r)
    return out
