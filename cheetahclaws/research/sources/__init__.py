"""Source registry. Each source module exposes:
    search(query: str, limit: int, config: dict | None = None,
           time_range: "TimeRange | None" = None) -> list[Result]

`time_range` is best-effort: sources translate it to their native date
filter (arXiv `submittedDate:[...]`, HN `numericFilters=created_at_i>...`,
GitHub `pushed:>...`, etc.). Sources that can't honor it should return
results anyway — the ranker's recency weighting still biases output.

Sources raise on hard errors; the aggregator catches and reports them as
SourceStatus(ok=False). Sources may also skip themselves by raising
SourceSkipped (e.g. missing API key), which is reported as skipped
rather than failed.

Sources are tiered:
    TIER_FREE      — zero-config, always queried unless disabled
    TIER_OPTIONAL  — requires an API key; silently skipped without it

Domain assignment decides which sources run for a given domain filter:
    academic → arxiv, semantic_scholar, openalex  (+ google_scholar, serply_scholar when available)
    tech     → hackernews, github, stackoverflow
    finance  → polymarket, sec_edgar
    news     → google_news
    social   → reddit, hackernews
    web      → tavily, brave  (+ google_news as a free fallback)
"""
from __future__ import annotations

from typing import Callable

from ..types import Domain, Result


class SourceSkipped(Exception):
    """Raised by a source when it can't run (missing key, unsupported query)."""


# (name, domains covered, tier, search function) — populated below after imports
SOURCES: dict[str, "SourceSpec"] = {}


class SourceSpec:
    def __init__(
        self,
        name: str,
        domains: list[Domain],
        tier: str,
        search: Callable[[str, int, dict | None], list[Result]],
        requires_env: list[str] | None = None,
        description: str = "",
    ):
        self.name = name
        self.domains = domains
        self.tier = tier  # "free" | "optional"
        self.search = search
        self.requires_env = requires_env or []
        self.description = description


def register(spec: SourceSpec) -> None:
    SOURCES[spec.name] = spec


def sources_for_domains(domains: list[Domain]) -> list[SourceSpec]:
    """Union of sources whose domain list intersects the requested domains."""
    out: dict[str, SourceSpec] = {}
    wanted = set(domains)
    for spec in SOURCES.values():
        if set(spec.domains) & wanted:
            out[spec.name] = spec
    return list(out.values())


# Register all shipped sources. Done as imports-with-side-effects so each
# source module is self-contained.
from . import arxiv as _arxiv                    # noqa: E402, F401
from . import semantic_scholar as _ss            # noqa: E402, F401
from . import openalex as _oa                    # noqa: E402, F401
from . import hackernews as _hn                  # noqa: E402, F401
from . import github as _gh                      # noqa: E402, F401
from . import reddit as _rd                      # noqa: E402, F401
from . import stackoverflow as _so               # noqa: E402, F401
from . import google_news as _gn                 # noqa: E402, F401
from . import polymarket as _pm                  # noqa: E402, F401
from . import sec_edgar as _sec                  # noqa: E402, F401
from . import tavily as _tv                      # noqa: E402, F401
from . import brave as _bv                       # noqa: E402, F401
from . import huggingface_papers as _hf          # noqa: E402, F401
from . import alphaxiv as _ax                    # noqa: E402, F401
from . import zhihu as _zh                       # noqa: E402, F401
from . import twitter as _tw                     # noqa: E402, F401
from . import google_scholar as _gs               # noqa: E402, F401
from . import bilibili as _bili                   # noqa: E402, F401
from . import weibo as _wb                        # noqa: E402, F401
from . import xiaohongshu as _xhs                 # noqa: E402, F401
from . import serply_scholar as _sps              # noqa: E402, F401
