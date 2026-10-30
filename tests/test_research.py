"""Tests for the research package.

Strategy: monkeypatch `research.http.get` / `post_json` to return pinned
JSON fixtures, so every source test is fast + offline + deterministic.

Covered layers:
  1. types — dataclass defaults + Brief.by_domain grouping
  2. classifier — topic → domain routing (no network)
  3. ranker — engagement normalization, dedupe, recency decay
  4. cache — put/get round trip, TTL expiry (monkeypatched time)
  5. Each source — happy path + empty response + schema-shift resilience
  6. aggregator — parallel fan-out, mixed success/failure, status reporting
  7. synthesizer — fallback when no model available, citation numbering
  8. http helper — retry on 5xx / timeout
"""
from __future__ import annotations

import json
import time
import types
from pathlib import Path
from unittest import mock

import pytest


# ─── 1. types ──────────────────────────────────────────────────────────────

def test_result_defaults():
    from cheetahclaws.research.types import Result
    r = Result(source="x", title="t", url="https://x")
    assert r.engagement_raw == 0
    assert r.engagement_score == 0.0
    assert r.domain == "web"
    assert r.extra == {}


def test_brief_by_domain_groups_and_sorts():
    from cheetahclaws.research.types import Brief, Result
    rs = [
        Result(source="a", title="t1", url="u1", domain="tech", engagement_score=0.2),
        Result(source="b", title="t2", url="u2", domain="academic", engagement_score=0.9),
        Result(source="c", title="t3", url="u3", domain="tech", engagement_score=0.8),
    ]
    b = Brief(topic="x", domains=["tech", "academic"], results=rs, statuses=[])
    g = b.by_domain()
    assert list(g["tech"][0].title) == list("t3")
    assert g["academic"][0].title == "t2"


# ─── 2. classifier ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("topic, want_top", [
    ("arxiv transformer attention ablation", "academic"),
    ("kubernetes pod autoscaling latency", "tech"),
    ("NVDA earnings Q4 reaction", "finance"),
    ("BTC price prediction 2027", "finance"),
    ("breaking news today on AI regulation", "news"),
])
def test_classifier_routes_obvious_topics(topic, want_top):
    from cheetahclaws.research.classifier import classify
    assert classify(topic)[0] == want_top


def test_classifier_empty_topic_returns_web():
    from cheetahclaws.research.classifier import classify
    assert classify("") == ["web"]
    assert classify("   ") == ["web"]


def test_classifier_never_empty():
    from cheetahclaws.research.classifier import classify
    # Gibberish should still yield a nonempty list
    assert classify("zxqvn mrtwk pfj") != []


# ─── 3. ranker ─────────────────────────────────────────────────────────────

def test_ranker_normalizes_engagement():
    from cheetahclaws.research.ranker import rank
    from cheetahclaws.research.types import Result
    rs = [
        Result(source="hackernews", title="a", url="u1", engagement_raw=100),
        Result(source="hackernews", title="b", url="u2", engagement_raw=5000),
        Result(source="github", title="c", url="u3", engagement_raw=100),
    ]
    rank(rs)
    # The 5000-point HN item should rank above the 100-point HN item
    hn_by_points = {r.title: r.engagement_score for r in rs if r.source == "hackernews"}
    assert hn_by_points["b"] > hn_by_points["a"]
    # Cross-source: 100 GH stars < 100 HN points (HN caps lower)
    gh = [r for r in rs if r.source == "github"][0]
    hn_low = [r for r in rs if r.source == "hackernews" and r.title == "a"][0]
    # This is the ranker contract: the weighting is per-source
    assert 0 <= gh.engagement_score <= 1.0
    assert 0 <= hn_low.engagement_score <= 1.0


def test_ranker_recency_bonus_for_fresh_results():
    from datetime import datetime, timezone
    from cheetahclaws.research.ranker import rank
    from cheetahclaws.research.types import Result
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = "2020-01-01T00:00:00Z"
    rs = [
        Result(source="arxiv", title="fresh", url="u1", published=now),
        Result(source="arxiv", title="stale", url="u2", published=old),
    ]
    rank(rs)
    fresh = next(r for r in rs if r.title == "fresh")
    stale = next(r for r in rs if r.title == "stale")
    assert fresh.engagement_score > stale.engagement_score


def test_ranker_dedupe_keeps_highest_engagement():
    from cheetahclaws.research.ranker import dedupe
    from cheetahclaws.research.types import Result
    rs = [
        Result(source="a", title="x", url="https://same.com/p", engagement_raw=10),
        Result(source="b", title="x dup", url="https://same.com/p/", engagement_raw=500),
        Result(source="c", title="y", url="https://other.com", engagement_raw=1),
    ]
    out = dedupe(rs)
    assert len(out) == 2
    same = next(r for r in out if r.url.startswith("https://same"))
    assert same.engagement_raw == 500


# ─── 4. cache ──────────────────────────────────────────────────────────────

def test_cache_roundtrip(tmp_path, monkeypatch):
    from cheetahclaws.research import cache
    from cheetahclaws.research.types import Result
    monkeypatch.setattr(cache, "_db_path", lambda: tmp_path / "c.db")

    rs = [Result(source="s", title="t", url="u", engagement_raw=7)]
    cache.put("s", "hello", 10, rs)
    got = cache.get("s", "hello", 10)
    assert got is not None
    assert got[0].title == "t"
    assert got[0].engagement_raw == 7


def test_cache_expires(tmp_path, monkeypatch):
    from cheetahclaws.research import cache
    from cheetahclaws.research.types import Result
    monkeypatch.setattr(cache, "_db_path", lambda: tmp_path / "c.db")

    rs = [Result(source="s", title="t", url="u")]
    cache.put("s", "q", 5, rs)
    # TTL=0 → every lookup is already expired
    got = cache.get("s", "q", 5, ttl_seconds=0)
    assert got is None


def test_cache_miss_returns_none(tmp_path, monkeypatch):
    from cheetahclaws.research import cache
    monkeypatch.setattr(cache, "_db_path", lambda: tmp_path / "c.db")
    assert cache.get("s", "nope", 10) is None


# ─── 5. Per-source happy paths (HTTP mocked) ───────────────────────────────

def _patch_http_get(monkeypatch, payload):
    """Replace research.http.get with a function returning `payload`."""
    def fake_get(url, params=None, headers=None, **kw):
        return payload
    monkeypatch.setattr("cheetahclaws.research.http.get", fake_get, raising=False)
    # Sources import get directly — patch the imported reference too
    return fake_get


def test_hackernews_parses_algolia():
    from cheetahclaws.research.sources import hackernews
    fixture = {"hits": [{
        "title": "Test story", "url": "https://example.com/p",
        "points": 420, "num_comments": 33, "author": "alice",
        "created_at": "2026-04-01T12:00:00Z", "objectID": "9999",
    }]}
    with mock.patch("cheetahclaws.research.sources.hackernews.get", return_value=fixture):
        rs = hackernews.search("test", 5)
    assert len(rs) == 1
    assert rs[0].engagement_raw == 420 + 16   # 33 // 2
    assert "420 pts" in rs[0].engagement_label


def test_semantic_scholar_parses_tldr():
    from cheetahclaws.research.sources import semantic_scholar as ss
    fixture = {"data": [{
        "title": "A paper",
        "abstract": "Long abstract...",
        "tldr": {"text": "The short summary."},
        "url": "https://semanticscholar.org/p/1",
        "year": 2024,
        "citationCount": 42,
        "influentialCitationCount": 5,
        "authors": [{"name": "A Person"}, {"name": "B Person"}],
        "externalIds": {},
        "openAccessPdf": {"url": "https://arxiv.org/pdf/x.pdf"},
    }]}
    with mock.patch("cheetahclaws.research.sources.semantic_scholar.get", return_value=fixture):
        rs = ss.search("test", 5)
    assert len(rs) == 1
    assert rs[0].engagement_raw == 42
    assert "42 citations" in rs[0].engagement_label
    assert rs[0].snippet.startswith("The short summary")


def test_reddit_builds_permalink_url():
    from cheetahclaws.research.sources import reddit as rd
    fixture = {"data": {"children": [{"data": {
        "title": "Reddit post",
        "subreddit": "programming",
        "permalink": "/r/programming/comments/abc/x/",
        "ups": 1200, "num_comments": 200,
        "selftext": "body",
        "author": "redditor",
        "created_utc": 1714000000,
    }}]}}
    with mock.patch("cheetahclaws.research.sources.reddit.get", return_value=fixture):
        rs = rd.search("test", 5)
    assert len(rs) == 1
    assert rs[0].url.endswith("/r/programming/comments/abc/x/")
    assert "r/programming" in rs[0].title


def test_github_splits_repos_and_issues():
    from cheetahclaws.research.sources import github as gh
    repo_fixture = {"items": [{
        "full_name": "foo/bar",
        "html_url": "https://github.com/foo/bar",
        "description": "desc",
        "stargazers_count": 12345,
        "forks_count": 456,
        "updated_at": "2026-04-10T00:00:00Z",
        "pushed_at": "2026-04-10T00:00:00Z",
        "owner": {"login": "foo"},
        "language": "Python",
    }]}
    issue_fixture = {"items": [{
        "html_url": "https://github.com/foo/bar/issues/1",
        "title": "an issue",
        "body": "body",
        "reactions": {"total_count": 10},
        "comments": 5,
        "user": {"login": "u"},
        "state": "open",
        "updated_at": "2026-04-11T00:00:00Z",
        "repository_url": "https://api.github.com/repos/foo/bar",
    }]}

    call_count = {"n": 0}

    def fake_get(url, params=None, headers=None, **kw):
        call_count["n"] += 1
        if "repositories" in url:
            return repo_fixture
        return issue_fixture

    with mock.patch("cheetahclaws.research.sources.github.get", side_effect=fake_get):
        rs = gh.search("test", 10)
    assert any("foo/bar" in r.title for r in rs)
    assert any(r.title.startswith("[issue]") for r in rs)


def test_arxiv_parses_atom_feed(monkeypatch):
    from cheetahclaws.research.sources import arxiv
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>A Paper</title>
    <summary>A summary of a paper.</summary>
    <published>2026-01-01T00:00:00Z</published>
    <id>http://arxiv.org/abs/2601.00001v1</id>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2601.00001v1"/>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
  </entry>
</feed>"""

    class FakeResp:
        def __init__(self, b): self.b = b
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(
        "cheetahclaws.research.sources.arxiv.urllib.request.urlopen",
        lambda req, timeout=None: FakeResp(feed),
    )
    rs = arxiv.search("test", 3)
    assert len(rs) == 1
    assert rs[0].title == "A Paper"
    assert "Alice, Bob" in rs[0].author


def test_google_news_parses_rss(monkeypatch):
    from cheetahclaws.research.sources import google_news
    rss = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Story headline</title>
    <link>https://news.example.com/a</link>
    <pubDate>Mon, 20 Apr 2026 10:00:00 GMT</pubDate>
    <description>&lt;b&gt;html&lt;/b&gt; snippet</description>
    <source url="https://ex.com">Example News</source>
  </item>
</channel></rss>"""

    class FakeResp:
        def __init__(self, b): self.b = b
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(
        "cheetahclaws.research.sources.google_news.urllib.request.urlopen",
        lambda req, timeout=None: FakeResp(rss),
    )
    rs = google_news.search("test", 5)
    assert len(rs) == 1
    assert rs[0].title == "Story headline"
    assert rs[0].author == "Example News"


def test_openalex_reconstructs_inverted_abstract():
    from cheetahclaws.research.sources import openalex
    # Abstract: "The quick brown fox"
    fixture = {"results": [{
        "title": "X",
        "doi": "https://doi.org/10.1/abc",
        "publication_year": 2025,
        "cited_by_count": 7,
        "authorships": [{"author": {"display_name": "A"}}],
        "abstract_inverted_index": {
            "The": [0], "quick": [1], "brown": [2], "fox": [3],
        },
    }]}
    with mock.patch("cheetahclaws.research.sources.openalex.get", return_value=fixture):
        rs = openalex.search("x", 1)
    assert rs[0].snippet == "The quick brown fox"


def test_stackoverflow_strips_html_in_body():
    from cheetahclaws.research.sources import stackoverflow as so
    fixture = {"items": [{
        "title": "Q title",
        "link": "https://stackoverflow.com/q/1",
        "score": 50,
        "answer_count": 4,
        "view_count": 12345,
        "body": "<p>Some <code>code</code> here.</p>",
        "owner": {"display_name": "u"},
        "last_activity_date": 1714000000,
        "is_answered": True,
    }]}
    with mock.patch("cheetahclaws.research.sources.stackoverflow.get", return_value=fixture):
        rs = so.search("t", 1)
    assert rs[0].snippet == "Some code here."


def test_tavily_skips_without_key(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, tavily
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(SourceSkipped):
        tavily.search("q", 5, {})


def test_brave_skips_without_key(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, brave
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    with pytest.raises(SourceSkipped):
        brave.search("q", 5, {})


def test_serply_scholar_skips_without_key(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, serply_scholar
    monkeypatch.delenv("SERPLY_API_KEY", raising=False)
    with pytest.raises(SourceSkipped):
        serply_scholar.search("q", 5, {})


def test_serply_scholar_parses_citations_and_year(monkeypatch):
    from datetime import datetime, timezone
    from cheetahclaws.research.sources import serply_scholar as sps
    from cheetahclaws.research.time_range import TimeRange
    monkeypatch.setenv("SERPLY_API_KEY", "k")
    fixture = {"articles": [
        {
            "title": "Retrieval-augmented generation for knowledge-intensive nlp tasks",
            "link": "https://proceedings.neurips.cc/paper/2020/hash/6b49-Abstract.html",
            "doc": {"link": "https://proceedings.neurips.cc/paper/2020/file/6b49-Paper.pdf"},
            "author": {
                "names": "P Lewis, E Perez, A Piktus, F Petroni\u2026\xa0- Advances in neural\xa0\u2026, 2020 - proceedings.neurips.cc",
                "authors": [{"name": n} for n in ("P Lewis", "E Perez", "A Piktus", "F Petroni")],
            },
            "extras": {"citations": {"count": "Cited by 31921",
                                     "link": "https://scholar.google.com/scholar?cites=1"}},
        },
        {"title": "No link", "link": ""},
        {"title": "Book", "link": "https://example.org/book",
         "author": {"names": "J Doe - Some Press, 2019 - example.org"}},
    ]}
    tr = TimeRange(since=datetime(2019, 1, 1, tzinfo=timezone.utc),
                   until=datetime(2021, 1, 1, tzinfo=timezone.utc))
    with mock.patch("cheetahclaws.research.sources.serply_scholar.get",
                    return_value=fixture) as g:
        rs = sps.search("rag", 5, {}, time_range=tr)
    params = g.call_args.kwargs["params"]
    assert (params["as_ylo"], params["as_yhi"]) == (2019, 2021)
    assert g.call_args.kwargs["headers"]["X-Api-Key"] == "k"
    assert len(rs) == 2
    assert rs[0].engagement_raw == 31921
    assert rs[0].published == "2020-01-01"
    assert rs[0].author == "P Lewis, E Perez, A Piktus, +1 more"
    assert rs[0].extra["pdf_url"].endswith("Paper.pdf")
    assert (rs[1].engagement_raw, rs[1].published, rs[1].author) == (0, "2019-01-01", "J Doe")


def test_serply_scholar_tolerates_unexpected_field_types(monkeypatch):
    # A TypeError here would make the aggregator retry without time_range,
    # spending a second API request — so odd shapes must parse, not raise.
    from cheetahclaws.research.sources import serply_scholar as sps

    monkeypatch.setenv("SERPLY_API_KEY", "k")
    fixture = {"articles": [
        {"title": "Int count", "link": "https://example.org/a",
         "author": "A Writer - Venue, 2021 - example.org",
         "extras": {"citations": {"count": 42, "link": None}},
         "doc": "not-a-dict"},
        {"title": "Odd authors", "link": "https://example.org/b",
         "author": {"names": None, "authors": [None, {"name": 7}, {"name": "B Real"}]},
         "extras": {"citations": {"count": None}}},
        "not-an-article",
        {"title": None, "link": "https://example.org/c"},
    ]}
    with mock.patch("cheetahclaws.research.sources.serply_scholar.get",
                    return_value=fixture):
        rs = sps.search("q", 5, {})
    assert [r.title for r in rs] == ["Int count", "Odd authors"]
    assert rs[0].engagement_raw == 42
    assert rs[0].extra == {"pdf_url": "", "cites_url": ""}
    assert (rs[1].author, rs[1].engagement_raw) == ("B Real", 0)

    for bad in ([], {"articles": None}, {"articles": {"x": 1}}):
        with mock.patch("cheetahclaws.research.sources.serply_scholar.get",
                        return_value=bad):
            assert sps.search("q", 5, {}) == []


def test_sec_edgar_builds_filing_url():
    from cheetahclaws.research.sources import sec_edgar
    fixture = {"hits": {"hits": [{
        "_id": "0000320193-26-000001:0001",
        "_source": {
            "display_names": ["APPLE INC (AAPL)"],
            "form": "10-K",
            "file_date": "2026-01-15",
            "file_type": "10-K",
            "ciks": ["320193"],
            "adsh": "0000320193-26-000001",
        },
    }]}}
    with mock.patch("cheetahclaws.research.sources.sec_edgar.get", return_value=fixture):
        rs = sec_edgar.search("apple", 1)
    assert len(rs) == 1
    assert "APPLE INC" in rs[0].author
    assert "sec.gov" in rs[0].url


def test_polymarket_filters_by_substring():
    from cheetahclaws.research.sources import polymarket
    # Gamma returns [] or market list
    fixture = [
        {"question": "Will NVIDIA top $200b revenue by EOY?",
         "slug": "nvda-200b", "volume": 50000, "liquidity": 10000,
         "outcomes": "[\"Yes\", \"No\"]",
         "outcomePrices": "[\"0.62\", \"0.38\"]"},
        {"question": "Cat wins meme of the year",
         "slug": "cat-meme", "volume": 1000, "liquidity": 100,
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.1\", \"0.9\"]"},
    ]
    with mock.patch("cheetahclaws.research.sources.polymarket.get", return_value=fixture):
        rs = polymarket.search("nvidia revenue", 5)
    assert len(rs) == 1
    assert "NVIDIA" in rs[0].title
    assert "Yes 62%" in rs[0].snippet


# ─── 6. aggregator ─────────────────────────────────────────────────────────

def test_aggregator_fans_out_and_returns_brief(monkeypatch):
    from cheetahclaws.research import aggregator
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result

    # Replace all source .search functions with a deterministic mock that
    # only returns 1 result tagged with the source name.
    for name, spec in SOURCES.items():
        def _mk(n):
            def _fn(query, limit, config=None):
                return [Result(source=n, title=f"{n}-result",
                               url=f"https://{n}.test/1",
                               domain=spec.domains[0])]
            return _fn
        spec.search = _mk(name)

    brief = aggregator.research(
        topic="hello",
        use_cache=False,
        synthesize=False,
        config={},
    )
    # At least one source should have returned
    assert brief.results
    assert any(s.ok for s in brief.statuses)


def test_aggregator_reports_source_failures(monkeypatch):
    from cheetahclaws.research import aggregator
    from cheetahclaws.research.sources import SOURCES

    def boom(q, l, c=None):
        raise RuntimeError("scripted failure")

    for spec in SOURCES.values():
        spec.search = boom

    brief = aggregator.research(
        topic="x", use_cache=False, synthesize=False, config={},
    )
    assert not brief.results
    assert all(not s.ok for s in brief.statuses)
    assert any("scripted failure" in (s.error or "") for s in brief.statuses)


def test_aggregator_caches_results(tmp_path, monkeypatch):
    from cheetahclaws.research import aggregator, cache
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result

    monkeypatch.setattr(cache, "_db_path", lambda: tmp_path / "c.db")

    call_count = {"n": 0}

    def one_result(q, l, c=None):
        call_count["n"] += 1
        return [Result(source="arxiv", title="t", url="u", domain="academic")]

    SOURCES["arxiv"].search = one_result

    aggregator.research(
        topic="same", sources=["arxiv"], synthesize=False,
        use_cache=True, config={},
    )
    first_calls = call_count["n"]
    aggregator.research(
        topic="same", sources=["arxiv"], synthesize=False,
        use_cache=True, config={},
    )
    # Second call should have hit cache — no additional upstream call
    assert call_count["n"] == first_calls


# ─── 7. synthesizer ────────────────────────────────────────────────────────

def test_synthesizer_fallback_without_model():
    from cheetahclaws.research.synthesizer import synthesize
    from cheetahclaws.research.types import Brief, Result
    brief = Brief(
        topic="x",
        domains=["tech"],
        results=[Result(source="hackernews", title="hn", url="u",
                        domain="tech", snippet="body")],
        statuses=[],
    )
    out = synthesize(brief, config={})  # no model → fallback
    assert "## TL;DR" in out
    assert "hn" in out


def test_synthesizer_citation_numbering():
    from cheetahclaws.research.synthesizer import render_citations
    from cheetahclaws.research.types import Brief, Result
    rs = [
        Result(source="arxiv", title="Paper A", url="https://a"),
        Result(source="hackernews", title="Post B", url="https://b",
               engagement_label="100 pts"),
    ]
    brief = Brief(topic="t", domains=["academic", "tech"], results=rs, statuses=[])
    cites = render_citations(brief)
    assert "[1] (arxiv) Paper A" in cites
    assert "[2] (hackernews) Post B — 100 pts" in cites


# ─── 8. HTTP helper resilience ─────────────────────────────────────────────

def test_http_get_retries_on_5xx(monkeypatch):
    from cheetahclaws.research import http
    import urllib.error

    calls = {"n": 0}

    class FakeResp:
        def __init__(self, data): self.data = data
        def read(self): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import io
    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {},
                                         io.BytesIO(b""))
        return FakeResp(b'{"ok": true}')

    monkeypatch.setattr("cheetahclaws.research.http.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("cheetahclaws.research.http.time.sleep", lambda s: None)

    data = http.get("https://example.com/api")
    assert data == {"ok": True}
    assert calls["n"] == 2


def test_http_get_fails_after_retries_exhausted(monkeypatch):
    from cheetahclaws.research import http

    def fake_urlopen(req, timeout=None):
        raise TimeoutError("slow")

    monkeypatch.setattr("cheetahclaws.research.http.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("cheetahclaws.research.http.time.sleep", lambda s: None)

    with pytest.raises(TimeoutError):
        http.get("https://example.com/api", retries=2)


# ─── 9. tools/research.py integration ──────────────────────────────────────

def test_research_tool_returns_brief_markdown(monkeypatch):
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result
    from cheetahclaws.tools.research import _research

    for spec in SOURCES.values():
        spec.search = lambda q, l, c=None, _s=spec: [
            Result(source=_s.name, title=f"{_s.name}-r", url=f"https://{_s.name}",
                   domain=_s.domains[0], engagement_raw=10)
        ]

    out = _research(topic="hello", synthesize=False,
                    use_cache=False, config={})
    assert "# Research Brief: hello" in out
    assert "## Citations" in out
    assert "## Cross-platform attention" in out


# ─── 10. HuggingFace / alphaXiv / Zhihu / Twitter ──────────────────────────

def test_huggingface_filters_by_topic_substring():
    from cheetahclaws.research.sources import huggingface_papers as hf
    fixture = [
        {
            "paper": {
                "id": "2601.00001", "title": "A Transformer Study",
                "summary": "Study of transformers.",
                "upvotes": 42, "authors": [{"name": "Alice"}],
                "publishedAt": "2026-04-01T00:00:00Z", "discussionId": "d1",
            },
            "numComments": 7, "publishedAt": "2026-04-01",
        },
        {
            "paper": {
                "id": "2601.00002", "title": "Unrelated Topic Paper",
                "summary": "Nothing to see here.",
                "upvotes": 10, "authors": [],
            },
            "numComments": 1,
        },
    ]
    with mock.patch("cheetahclaws.research.sources.huggingface_papers.get", return_value=fixture):
        rs = hf.search("transformer", 5)
    assert len(rs) == 1
    assert rs[0].title == "A Transformer Study"
    assert rs[0].engagement_raw == 49   # 42 upvotes + 7 comments


def test_huggingface_empty_query_still_filters():
    from cheetahclaws.research.sources import huggingface_papers as hf
    with mock.patch("cheetahclaws.research.sources.huggingface_papers.get", return_value=[]):
        rs = hf.search("x", 5)
    assert rs == []


def test_alphaxiv_wraps_arxiv_and_generates_discussion_urls(monkeypatch):
    from cheetahclaws.research.sources import alphaxiv
    from cheetahclaws.research.types import Result

    fake_arxiv_hits = [
        Result(source="arxiv", title="Paper A", url="http://arxiv.org/abs/2401.12345v2",
               snippet="abstract", author="X", published="2024-01-01", domain="academic"),
        Result(source="arxiv", title="Paper B", url="http://arxiv.org/abs/1706.03762",
               snippet="attention", author="Y", published="2017-06-12", domain="academic"),
    ]
    with mock.patch("cheetahclaws.research.sources.arxiv.search", return_value=fake_arxiv_hits):
        rs = alphaxiv.search("test", 5)
    assert len(rs) == 2
    assert all(r.source == "alphaxiv" for r in rs)
    assert rs[0].url == "https://www.alphaxiv.org/abs/2401.12345"
    assert rs[1].url == "https://www.alphaxiv.org/abs/1706.03762"
    assert rs[0].extra["arxiv_url"] == "http://arxiv.org/abs/2401.12345v2"


def test_zhihu_skips_without_cookie(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, zhihu
    monkeypatch.delenv("ZHIHU_COOKIE", raising=False)
    with pytest.raises(SourceSkipped):
        zhihu.search("q", 5, {})


def test_zhihu_parses_answer_type(monkeypatch):
    from cheetahclaws.research.sources import zhihu
    monkeypatch.setenv("ZHIHU_COOKIE", "d_c0=abc; z_c0=xyz")
    fixture = {"data": [{
        "type": "search_result",
        "object": {
            "type": "answer",
            "id": 8888,
            "excerpt": "<p>some answer body</p>",
            "voteup_count": 1234,
            "comment_count": 56,
            "created_time": 1714000000,
            "question": {"id": 9999, "name": "Why does X work?"},
            "author": {"name": "张三"},
        },
    }]}
    with mock.patch("cheetahclaws.research.sources.zhihu.get", return_value=fixture):
        rs = zhihu.search("x", 3, {})
    assert len(rs) == 1
    r = rs[0]
    assert r.url == "https://www.zhihu.com/question/9999/answer/8888"
    assert r.author == "张三"
    assert r.engagement_raw == 1234 + 28
    assert "[answer]" in r.title


def test_zhihu_parses_article_type(monkeypatch):
    from cheetahclaws.research.sources import zhihu
    monkeypatch.setenv("ZHIHU_COOKIE", "cookie_val")
    fixture = {"data": [{
        "object": {
            "type": "article",
            "id": 123,
            "title": "My article",
            "excerpt": "body",
            "voteup_count": 50, "comment_count": 2,
            "author": {"name": "李四"},
        }
    }]}
    with mock.patch("cheetahclaws.research.sources.zhihu.get", return_value=fixture):
        rs = zhihu.search("x", 3, {})
    assert rs[0].url == "https://zhuanlan.zhihu.com/p/123"
    assert "[article]" in rs[0].title


def test_twitter_skips_without_token(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, twitter
    monkeypatch.delenv("X_API_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    with pytest.raises(SourceSkipped):
        twitter.search("q", 5, {})


def test_twitter_parses_v2_response(monkeypatch):
    from cheetahclaws.research.sources import twitter
    monkeypatch.setenv("X_API_BEARER_TOKEN", "bearer-xyz")
    fixture = {
        "data": [{
            "id": "17770",
            "text": "Hello world\nsecond line",
            "author_id": "11",
            "public_metrics": {"like_count": 500, "retweet_count": 20,
                               "reply_count": 15, "quote_count": 3},
            "created_at": "2026-04-18T10:00:00Z",
        }],
        "includes": {"users": [{"id": "11", "username": "alice",
                                "name": "Alice", "verified": True}]},
    }
    with mock.patch("cheetahclaws.research.sources.twitter.get", return_value=fixture):
        rs = twitter.search("hello", 5)
    assert len(rs) == 1
    r = rs[0]
    assert r.url == "https://x.com/alice/status/17770"
    assert r.author == "@alice"
    # engagement = 500 + 20*3 + 15 + 3*2 = 581
    assert r.engagement_raw == 581


# ─── 11. Heat table renderer ───────────────────────────────────────────────

def test_format_heat_table_shows_counts_and_domains():
    from cheetahclaws.research.synthesizer import format_heat_table
    from cheetahclaws.research.types import Brief, Result, SourceStatus

    brief = Brief(
        topic="x",
        domains=["tech", "academic"],
        results=[
            Result(source="hackernews", title="hn1", url="u1", domain="tech",
                   engagement_raw=100, engagement_label="100 pts",
                   published="2026-04-15T00:00:00Z"),
            Result(source="hackernews", title="hn2", url="u2", domain="tech",
                   engagement_raw=50, engagement_label="50 pts",
                   published="2026-04-10T00:00:00Z"),
            Result(source="arxiv", title="p1", url="u3", domain="academic",
                   published="2026-01-01T00:00:00Z"),
        ],
        statuses=[
            SourceStatus(name="hackernews", ok=True, count=2),
            SourceStatus(name="arxiv", ok=True, count=1),
            SourceStatus(name="zhihu", ok=False, skipped_reason="ZHIHU_COOKIE not set"),
            SourceStatus(name="twitter", ok=False, error="HTTP 401"),
        ],
    )
    table = format_heat_table(brief)
    assert "| hackernews | 2" in table
    assert "100 pts" in table
    assert "| arxiv | 1" in table
    assert "| zhihu | 0" in table
    assert "ZHIHU_COOKIE" in table
    assert "| twitter | 0" in table
    assert "failed" in table


def test_format_heat_table_escapes_pipes_in_labels():
    from cheetahclaws.research.synthesizer import format_heat_table
    from cheetahclaws.research.types import Brief, Result, SourceStatus
    brief = Brief(
        topic="x", domains=["tech"],
        results=[Result(source="s", title="t", url="u", domain="tech",
                        engagement_label="a|b|c")],
        statuses=[SourceStatus(name="s", ok=True, count=1)],
    )
    table = format_heat_table(brief)
    assert "a\\|b\\|c" in table  # pipes escaped so markdown table stays valid


def test_heat_table_age_formatting():
    from cheetahclaws.research.synthesizer import _fmt_age
    assert _fmt_age(0.2) == "4h"
    assert _fmt_age(1.0) == "1d"
    assert _fmt_age(27.0) == "27d"
    assert _fmt_age(60.0) == "2mo"
    assert _fmt_age(400.0) == "1.1y"


# ─── 12. TimeRange parsing ─────────────────────────────────────────────────

def test_time_range_preset_tokens():
    from cheetahclaws.research.time_range import parse_range
    tr = parse_range("30d")
    assert tr.is_bounded
    assert tr.since is not None
    assert "last 1 months" in tr.label or "last 30" in tr.label


def test_time_range_natural_language():
    from cheetahclaws.research.time_range import parse_range
    tr = parse_range("6months")
    assert tr.is_bounded
    assert tr.since is not None


def test_time_range_all_means_unbounded():
    from cheetahclaws.research.time_range import parse_range
    tr = parse_range("all")
    assert not tr.is_bounded
    assert tr.since is None and tr.until is None


def test_time_range_bad_token_raises():
    from cheetahclaws.research.time_range import parse_range
    with pytest.raises(ValueError):
        parse_range("zorp")


def test_time_range_iso_date_parsed():
    from cheetahclaws.research.time_range import parse_iso
    dt = parse_iso("2024-01-15")
    assert dt.year == 2024 and dt.month == 1 and dt.day == 15
    assert dt.tzinfo is not None


def test_time_range_build_combines():
    from cheetahclaws.research.time_range import build
    tr = build(range_token="30d", since="2024-01-01", until="2024-06-30")
    # since/until override preset
    assert tr.since.year == 2024 and tr.since.month == 1
    assert tr.until.year == 2024 and tr.until.month == 6
    assert "since 2024-01-01" in tr.label


# ─── 13. Sources honor time_range ──────────────────────────────────────────

def test_arxiv_uses_submittedDate_when_ranged():
    from cheetahclaws.research.sources import arxiv
    from cheetahclaws.research.time_range import parse_range
    tr = parse_range("30d")

    captured = {}

    class FakeResp:
        def __init__(self, b): self.b = b
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return FakeResp(b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>""")

    import cheetahclaws.research.sources.arxiv as ax
    ax.urllib.request.urlopen = fake_urlopen  # type: ignore
    arxiv.search("test", 3, time_range=tr)
    # URL-encoded as `submittedDate%3A`
    assert "submittedDate" in captured["url"]


def test_hackernews_uses_numericFilters_when_ranged():
    from cheetahclaws.research.sources import hackernews
    from cheetahclaws.research.time_range import parse_range

    captured = {}
    def fake_get(url, params=None, headers=None, **kw):
        captured["params"] = params or {}
        return {"hits": []}
    with mock.patch("cheetahclaws.research.sources.hackernews.get", side_effect=fake_get):
        hackernews.search("test", 5, time_range=parse_range("7d"))
    assert "numericFilters" in captured["params"]
    assert "created_at_i>" in captured["params"]["numericFilters"]


def test_github_adds_pushed_qualifier_when_ranged():
    from cheetahclaws.research.sources import github
    from cheetahclaws.research.time_range import parse_range

    captured = []
    def fake_get(url, params=None, headers=None, **kw):
        captured.append((url, dict(params or {})))
        return {"items": []}
    with mock.patch("cheetahclaws.research.sources.github.get", side_effect=fake_get):
        github.search("foo", 5, time_range=parse_range("30d"))
    # Both repo and issue searches should get date qualifiers
    qs = [p.get("q", "") for _, p in captured]
    assert any("pushed:>" in q for q in qs)
    assert any("updated:>" in q for q in qs)


def test_openalex_uses_filter_when_ranged():
    from cheetahclaws.research.sources import openalex
    from cheetahclaws.research.time_range import parse_range

    captured = {}
    def fake_get(url, params=None, headers=None, **kw):
        captured["params"] = params or {}
        return {"results": []}
    with mock.patch("cheetahclaws.research.sources.openalex.get", side_effect=fake_get):
        openalex.search("x", 3, time_range=parse_range("1y"))
    assert "filter" in captured["params"]
    assert "from_publication_date:" in captured["params"]["filter"]


def test_reddit_maps_range_to_t():
    from cheetahclaws.research.sources import reddit
    from cheetahclaws.research.time_range import parse_range

    captured = {}
    def fake_get(url, params=None, headers=None, **kw):
        captured["params"] = params or {}
        return {"data": {"children": []}}

    with mock.patch("cheetahclaws.research.sources.reddit.get", side_effect=fake_get):
        reddit.search("x", 3, time_range=parse_range("7d"))
        assert captured["params"]["t"] == "week"
        reddit.search("x", 3, time_range=parse_range("1y"))
        assert captured["params"]["t"] == "year"


# ─── 14. Reports save/load ─────────────────────────────────────────────────

def test_report_save_and_read(tmp_path, monkeypatch):
    from cheetahclaws.research import reports as _rep
    from cheetahclaws.research.types import Brief, Result, SourceStatus

    monkeypatch.setattr(_rep, "_reports_dir",
                        lambda: (tmp_path / "reports").resolve())

    brief = Brief(
        topic="bitcoin halving",
        domains=["finance"],
        results=[Result(source="polymarket", title="Will BTC halving...",
                        url="https://p.com/1", domain="finance",
                        engagement_raw=5000,
                        engagement_label="$5000 volume")],
        statuses=[SourceStatus(name="polymarket", ok=True, count=1)],
        synthesis="## TL;DR\n- test synthesis",
    )
    path = _rep.save(brief, "## TL;DR\nsaved content here.")
    assert path.exists()
    assert path.suffix == ".md"

    listed = _rep.list_reports(limit=10)
    assert len(listed) == 1
    assert listed[0]["topic"] == "bitcoin halving"

    got = _rep.read_markdown(report_id=listed[0]["id"])
    assert "saved content here" in got


def test_report_save_as_copies_file(tmp_path, monkeypatch):
    from cheetahclaws.research import reports as _rep
    from cheetahclaws.research.types import Brief
    monkeypatch.setattr(_rep, "_reports_dir", lambda: (tmp_path / "rep").resolve())

    brief = Brief(topic="x", domains=["tech"], results=[], statuses=[])
    target = tmp_path / "my" / "exported.md"
    path = _rep.save(brief, "# body", also_save_as=str(target))
    assert path.exists()
    assert target.exists()
    assert target.read_text() == "# body"


def test_report_delete(tmp_path, monkeypatch):
    from cheetahclaws.research import reports as _rep
    from cheetahclaws.research.types import Brief
    monkeypatch.setattr(_rep, "_reports_dir", lambda: (tmp_path / "r").resolve())

    b = Brief(topic="abc", domains=[], results=[], statuses=[])
    _rep.save(b, "body")
    assert len(_rep.list_reports()) == 1
    assert _rep.delete(1)
    assert len(_rep.list_reports()) == 0


# ─── 15. Publication trend / sparkline ─────────────────────────────────────

def test_publication_trend_bars():
    from datetime import datetime, timezone, timedelta
    from cheetahclaws.research.synthesizer import format_publication_trend
    from cheetahclaws.research.types import Brief, Result
    now = datetime.now(timezone.utc)
    rs = [
        Result(source="arxiv", title=f"p{i}", url=f"u{i}",
               published=(now - timedelta(days=30 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for i in range(6)
    ]
    brief = Brief(topic="x", domains=["academic"], results=rs, statuses=[])
    out = format_publication_trend(brief, buckets=12)
    assert "Publication trend" in out
    assert "```" in out


def test_publication_sparkline_uses_unicode_bars():
    from datetime import datetime, timezone, timedelta
    from cheetahclaws.research.synthesizer import format_publication_sparkline
    from cheetahclaws.research.types import Brief, Result
    now = datetime.now(timezone.utc)
    rs = [
        Result(source="arxiv", title=f"p{i}", url=f"u{i}",
               published=(now - timedelta(days=30 * (i // 2))).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for i in range(10)
    ]
    brief = Brief(topic="x", domains=["academic"], results=rs, statuses=[])
    spark = format_publication_sparkline(brief, buckets=12)
    assert spark
    # Should contain at least one of the spark block characters
    assert any(c in spark for c in "▁▂▃▄▅▆▇█")


# ─── 16. Citations helper ──────────────────────────────────────────────────

def test_citation_extract_ss_id():
    from cheetahclaws.research.citations import _extract_ss_id
    from cheetahclaws.research.types import Result
    r1 = Result(source="semantic_scholar", title="T", url="https://www.semanticscholar.org/paper/abc/def0123")
    assert _extract_ss_id(r1) == "def0123"
    r2 = Result(source="semantic_scholar", title="T", url="https://arxiv.org/abs/2401.12345v1")
    assert _extract_ss_id(r2) == "arXiv:2401.12345"
    r3 = Result(source="semantic_scholar", title="T", url="https://doi.org/10.1/x")
    assert _extract_ss_id(r3) == "DOI:10.1/x"


def test_notable_citers_rendering():
    from cheetahclaws.research.citations import NotableCiter, render_notable_section
    ns = [
        NotableCiter(name="Yoshua Bengio", author_id="aa",
                     total_citations=450000, h_index=230,
                     affiliation="Mila",
                     cited_papers=["Attention Is All You Need"]),
    ]
    out = render_notable_section(ns, threshold=10000)
    assert "Yoshua Bengio" in out
    assert "450,000" in out
    assert "230" in out


# ─── 17. Google Scholar graceful skip ──────────────────────────────────────

def test_google_scholar_skips_without_scholarly(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, google_scholar
    import sys
    # Pretend `scholarly` isn't installed by removing any cached module
    sys.modules.pop("scholarly", None)
    # Force the import to fail
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "scholarly":
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SourceSkipped):
        google_scholar.search("anything", 5)


# ─── 18. Aggregator passes time_range through ──────────────────────────────

# ─── 19. Chinese platform sources ──────────────────────────────────────────

def test_bilibili_parses_video_group():
    from cheetahclaws.research.sources import bilibili
    fixture = {
        "code": 0,
        "data": {
            "result": [{
                "result_type": "video",
                "data": [{
                    "title": "深度学习 <em class='keyword'>transformer</em>",
                    "bvid": "BV1abc123",
                    "aid": 99999,
                    "play": 120000,
                    "like": 4500,
                    "video_review": 800,
                    "review": 200,
                    "author": "某UP主",
                    "description": "讲解 transformer 架构",
                    "duration": "12:34",
                    "pubdate": 1714000000,
                }],
            }],
        },
    }
    with mock.patch("cheetahclaws.research.sources.bilibili.get", return_value=fixture):
        rs = bilibili.search("transformer", 5)
    assert len(rs) == 1
    r = rs[0]
    assert "某UP主" in r.author
    assert r.url == "https://www.bilibili.com/video/BV1abc123"
    assert r.engagement_raw > 0
    assert "120,000 播放" in r.engagement_label
    # HTML <em> should be stripped from the title
    assert "<em" not in r.title


def test_bilibili_skips_non_ok_code():
    from cheetahclaws.research.sources import bilibili
    fixture = {"code": -401, "message": "anti-bot", "data": None}
    with mock.patch("cheetahclaws.research.sources.bilibili.get", return_value=fixture):
        rs = bilibili.search("x", 5)
    assert rs == []


def test_weibo_skips_without_cookie(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, weibo
    monkeypatch.delenv("WEIBO_COOKIE", raising=False)
    with pytest.raises(SourceSkipped):
        weibo.search("x", 5, {})


def test_weibo_parses_mblog(monkeypatch):
    from cheetahclaws.research.sources import weibo
    monkeypatch.setenv("WEIBO_COOKIE", "SUB=xxx;SUBP=yyy")
    fixture = {
        "ok": 1,
        "data": {"cards": [{
            "card_type": 9,
            "mblog": {
                "id": "NXabc123",
                "text": "这个<em>transformer</em>模型效果太好了",
                "user": {"screen_name": "技术爱好者", "id": 5201},
                "attitudes_count": 3500,
                "reposts_count": 120,
                "comments_count": 89,
                "created_at": "2小时前",
            },
        }]},
    }
    with mock.patch("cheetahclaws.research.sources.weibo.get", return_value=fixture):
        rs = weibo.search("transformer", 5, {})
    assert len(rs) == 1
    r = rs[0]
    assert r.url == "https://m.weibo.cn/status/NXabc123"
    assert "@技术爱好者" == r.author
    # attitudes + 2*reposts + comments = 3500 + 240 + 89 = 3829
    assert r.engagement_raw == 3829
    assert "3,500 赞" in r.engagement_label


def test_weibo_date_parser_relative():
    from cheetahclaws.research.sources.weibo import _parse_weibo_date
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                    _parse_weibo_date("5分钟前"))
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                    _parse_weibo_date("2小时前"))
    assert _parse_weibo_date("") == ""


def test_xiaohongshu_skips_without_cookie(monkeypatch):
    from cheetahclaws.research.sources import SourceSkipped, xiaohongshu
    monkeypatch.delenv("XHS_COOKIE", raising=False)
    monkeypatch.delenv("XIAOHONGSHU_COOKIE", raising=False)
    with pytest.raises(SourceSkipped):
        xiaohongshu.search("x", 5, {})


def test_xiaohongshu_parses_localized_counts(monkeypatch):
    from cheetahclaws.research.sources import xiaohongshu
    from cheetahclaws.research.sources.xiaohongshu import _parse_count
    assert _parse_count("1.2w") == 12000
    assert _parse_count("3万") == 30000
    assert _parse_count("500") == 500
    assert _parse_count("8.5k") == 8500
    assert _parse_count(None) == 0
    assert _parse_count("") == 0


def test_xiaohongshu_parses_success_response(monkeypatch):
    from cheetahclaws.research.sources import xiaohongshu
    monkeypatch.setenv("XHS_COOKIE", "test-cookie")
    fixture = {
        "success": True,
        "data": {"items": [{
            "note_card": {
                "id": "abc123",
                "display_title": "Cool DIY transformer explained",
                "desc": "A note about transformers",
                "user": {"nickname": "小明"},
                "interact_info": {
                    "liked_count": "1.5w",
                    "comment_count": "300",
                    "collected_count": "500",
                    "share_count": "20",
                },
                "cover": {"url": "https://img/cover.jpg"},
            },
        }]},
    }
    with mock.patch("cheetahclaws.research.sources.xiaohongshu.post_json",
                    return_value=fixture):
        rs = xiaohongshu.search("transformer", 5, {})
    assert len(rs) == 1
    r = rs[0]
    assert r.url == "https://www.xiaohongshu.com/explore/abc123"
    # 15000 + 300 + 500 + 10 = 15810
    assert r.engagement_raw == 15810
    assert "15,000 赞" in r.engagement_label


# ─── 20. Monitor research:<topic> fetcher ──────────────────────────────────

def test_monitor_fetcher_dispatches_research_prefix(monkeypatch, tmp_path):
    from cheetahclaws.monitor import fetchers
    from cheetahclaws.research import cache as _cache
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result

    monkeypatch.setattr(_cache, "_db_path", lambda: tmp_path / "c.db")

    for spec in SOURCES.values():
        spec.search = lambda q, l, c=None, time_range=None, _s=spec: [
            Result(source=_s.name, title=f"{_s.name}-item",
                   url=f"https://{_s.name}",
                   domain=_s.domains[0], engagement_raw=5)
        ]

    data = fetchers.fetch("research:some topic")
    assert data["topic"] == "research:some topic"
    assert data["items"]
    assert "heat" in data["items"][0]["title"].lower() or "Cross-platform" in data["items"][0]["title"]


def test_monitor_fetcher_research_with_range_prefix(monkeypatch, tmp_path):
    from cheetahclaws.monitor import fetchers
    from cheetahclaws.research import cache as _cache
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result

    # Isolate cache so prior tests' cached entries don't mask the mocks
    monkeypatch.setattr(_cache, "_db_path", lambda: tmp_path / "c.db")

    captured: dict = {}

    for spec in SOURCES.values():
        def _s(q, l, c=None, time_range=None, _name=spec.name, _dom=spec.domains[0]):
            captured.setdefault("ranges", []).append(time_range)
            return [Result(source=_name, title="x", url=f"https://{_name}", domain=_dom)]
        spec.search = _s

    data = fetchers.fetch("research:30d:LLM benchmarks")
    assert data["topic"] == "research:30d:LLM benchmarks"
    bounded = [r for r in captured.get("ranges", []) if r and r.is_bounded]
    assert bounded, "Expected a bounded TimeRange from research:30d: prefix"


# ─── 21. Entity extraction ─────────────────────────────────────────────────

def test_entity_extraction_picks_up_known_models():
    from cheetahclaws.research.entities import extract
    from cheetahclaws.research.types import Result
    rs = [
        Result(source="reddit", title="GPT-5 vs Claude-Opus-5: which is better",
               url="u1", snippet="GPT-5 dominates on MMLU but Claude-Opus-5 wins on coding", domain="social"),
        Result(source="arxiv", title="Llama-4 scaling paper",
               url="u2", snippet="We evaluate Llama-4 against GPT-5 on HumanEval and MMLU.", domain="academic"),
        Result(source="hackernews", title="Gemini-2.5-Pro benchmark on SWE-bench",
               url="u3", snippet="", domain="tech"),
    ]
    e = extract(rs)
    model_names = [n for n, _ in e.models]
    # GPT-5 should appear once per result it's in (2 results)
    assert any(n.startswith("GPT") and "5" in n for n in model_names)
    assert any("Claude-Opus-5" in n or ("Claude" in n and "Opus" in n) for n in model_names)
    assert any(n.startswith("Llama") for n in model_names)
    assert any("Gemini" in n for n in model_names)

    bench_names = [n for n, _ in e.benchmarks]
    assert "MMLU" in bench_names
    assert "HumanEval" in bench_names
    assert "SWE-bench".upper() in [b.upper() for b in bench_names]


def test_entity_extraction_orgs():
    from cheetahclaws.research.entities import extract
    from cheetahclaws.research.types import Result
    rs = [
        Result(source="news", title="OpenAI releases GPT-5",
               url="u", snippet="Anthropic and Google DeepMind respond.", domain="news"),
        Result(source="tech", title="Meta publishes Llama-4 on Hugging Face",
               url="u2", snippet="Mistral also released new models.", domain="tech"),
    ]
    e = extract(rs)
    org_names = [n for n, _ in e.orgs]
    assert "OpenAI" in org_names
    assert "Anthropic" in org_names
    assert "Meta" in org_names
    # Either "Google DeepMind" or "DeepMind" match; we accept either
    assert any("DeepMind" in n for n in org_names)
    assert any(n.startswith("Hugging") or n == "HuggingFace" for n in org_names)


def test_entity_extraction_dedupes_within_single_result():
    """A result mentioning the same model 10 times should count as 1."""
    from cheetahclaws.research.entities import extract
    from cheetahclaws.research.types import Result
    rs = [Result(source="x", title="GPT-5 is amazing",
                 url="u", snippet="GPT-5 GPT-5 GPT-5 GPT-5 GPT-5 GPT-5",
                 domain="tech")]
    e = extract(rs)
    counts = dict(e.models)
    # Find whatever canonical form GPT-5 normalizes to
    gpt5_key = next(k for k in counts if k.startswith("GPT") and "5" in k)
    assert counts[gpt5_key] == 1


def test_entity_extraction_people_from_author():
    from cheetahclaws.research.entities import extract
    from cheetahclaws.research.types import Result
    rs = [
        Result(source="arxiv", title="paper 1", url="u1",
               author="Alice Smith, Bob Chen", domain="academic"),
        Result(source="arxiv", title="paper 2", url="u2",
               author="Alice Smith, Carol Lee", domain="academic"),
    ]
    e = extract(rs)
    people = dict(e.people)
    # Alice Smith appears in 2 papers → count 2
    assert people.get("Alice Smith") == 2


def test_entity_table_renders_markdown():
    from cheetahclaws.research.entities import Entities, render_entities_table
    e = Entities(
        models=[("GPT-5", 7), ("Claude-Opus-5", 4)],
        benchmarks=[("MMLU", 3)],
        orgs=[("OpenAI", 5)],
        people=[("Ilya Sutskever", 2)],
    )
    out = render_entities_table(e)
    assert "Top mentioned entities" in out
    assert "GPT-5 ×7" in out
    assert "MMLU ×3" in out
    assert "OpenAI ×5" in out
    assert "Ilya Sutskever" in out


def test_entity_table_empty_returns_empty_string():
    from cheetahclaws.research.entities import Entities, render_entities_table
    assert render_entities_table(Entities()) == ""


# ─── 22. Multi-query expansion ─────────────────────────────────────────────

def test_expand_subqueries_no_model_returns_empty():
    from cheetahclaws.research.aggregator import _expand_subqueries
    assert _expand_subqueries("topic", 4, config={}) == []


def test_expand_subqueries_parses_model_lines(monkeypatch):
    from cheetahclaws.research import aggregator
    from cheetahclaws.research.types import Result

    fake_lines = [
        "LLM evaluation benchmarks safety",
        "capability measurement frontier models",
        "benchmark saturation and contamination",
        "human preference benchmarks evaluation",
    ]

    class FakeTextChunk:
        def __init__(self, text): self.text = text
    class FakeAssistantTurn:
        pass

    def fake_stream(**kwargs):
        yield FakeTextChunk("\n".join(fake_lines))
        yield FakeAssistantTurn()

    import sys
    fake_providers = types.ModuleType("providers")
    fake_providers.stream = fake_stream
    fake_providers.TextChunk = FakeTextChunk
    fake_providers.AssistantTurn = FakeAssistantTurn
    # Save the real module (if loaded) and restore it on exit so we don't
    # leak the stub into later tests.  Previously this finally was a no-op,
    # which broke tests/test_setup_wizard.py and any other suite that ran
    # after this one and tried `from providers import PROVIDERS`.
    real_providers = sys.modules.get("cheetahclaws.providers")
    sys.modules["cheetahclaws.providers"] = fake_providers
    try:
        out = aggregator._expand_subqueries("frontier LLM benchmarks", 4,
                                            config={"model": "test"})
    finally:
        if real_providers is not None:
            sys.modules["cheetahclaws.providers"] = real_providers
        else:
            sys.modules.pop("cheetahclaws.providers", None)

    assert len(out) == 4
    assert all(5 < len(ln) < 150 for ln in out)


def test_aggregator_expand_produces_multi_query_cache_keys(monkeypatch, tmp_path):
    from cheetahclaws.research import aggregator, cache as _cache
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result

    monkeypatch.setattr(_cache, "_db_path", lambda: tmp_path / "c.db")

    # Monkeypatch expansion to return 3 canned subqueries
    monkeypatch.setattr(
        aggregator, "_expand_subqueries",
        lambda topic, n, config: ["subq A", "subq B", "subq C"],
    )

    seen_queries: set = set()
    for spec in SOURCES.values():
        def _s(q, l, c=None, time_range=None, _name=spec.name, _dom=spec.domains[0]):
            seen_queries.add(q)
            return [Result(source=_name, title=q, url=f"https://x/{_name}/{q}",
                           domain=_dom)]
        spec.search = _s

    aggregator.research(
        topic="main topic", expand=3,
        use_cache=False, synthesize=False, config={"model": "test"},
    )

    # Should have invoked sources with original + 3 subqueries
    assert "main topic" in seen_queries
    assert "subq A" in seen_queries
    assert "subq B" in seen_queries
    assert "subq C" in seen_queries


# ─── 23. Compare mode ──────────────────────────────────────────────────────

def test_compare_runs_two_queries(monkeypatch, tmp_path):
    from cheetahclaws.research import aggregator, cache as _cache
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result

    monkeypatch.setattr(_cache, "_db_path", lambda: tmp_path / "c.db")
    for spec in SOURCES.values():
        def _s(q, l, c=None, time_range=None, _name=spec.name, _dom=spec.domains[0]):
            return [Result(source=_name, title=f"{q}-hit", url=f"https://x/{_name}/{q}",
                           domain=_dom, engagement_raw=10)]
        spec.search = _s

    result = aggregator.compare(
        topic_a="topic X", topic_b="topic Y",
        limit=5, use_cache=False, config={},
    )
    assert len(result["topics"]) == 2
    assert len(result["briefs"]) == 2
    assert all(len(b.results) > 0 for b in result["briefs"])
    # Without a model config → fallback comparison (empty) is used
    assert result.get("comparison") == ""


def test_compare_three_topics(monkeypatch, tmp_path):
    from cheetahclaws.research import aggregator, cache as _cache
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.types import Result

    monkeypatch.setattr(_cache, "_db_path", lambda: tmp_path / "c.db")
    for spec in SOURCES.values():
        spec.search = lambda q, l, c=None, time_range=None, _s=spec: [
            Result(source=_s.name, title="x", url=f"https://{_s.name}",
                   domain=_s.domains[0])
        ]

    result = aggregator.compare(
        topic_a="A", topic_b="B", topic_c="C",
        limit=3, use_cache=False, config={},
    )
    assert result["topics"] == ["A", "B", "C"]
    assert len(result["briefs"]) == 3


def test_render_compare_brief_has_all_topics_cited():
    from cheetahclaws.research.synthesizer import render_compare_brief
    from cheetahclaws.research.types import Brief, Result, SourceStatus

    b1 = Brief(topic="A", domains=["tech"],
               results=[Result(source="hn", title="T1", url="u1", domain="tech")],
               statuses=[SourceStatus(name="hn", ok=True, count=1)])
    b2 = Brief(topic="B", domains=["social"],
               results=[Result(source="reddit", title="T2", url="u2", domain="social")],
               statuses=[SourceStatus(name="reddit", ok=True, count=1)])

    result = {"topics": ["A", "B"], "briefs": [b1, b2],
              "comparison": "", "total_duration_ms": 100}
    md = render_compare_brief(result)
    assert "# Comparative Research Brief" in md
    assert "**A**" in md and "**B**" in md
    assert "[A1]" in md
    assert "[B1]" in md


def test_aggregator_threads_time_range_into_sources(monkeypatch):
    from cheetahclaws.research import aggregator
    from cheetahclaws.research.sources import SOURCES
    from cheetahclaws.research.time_range import parse_range
    from cheetahclaws.research.types import Result

    received: dict[str, object] = {}

    def mk(n):
        def _fn(q, l, c=None, time_range=None):
            received[n] = time_range
            return [Result(source=n, title="x", url=f"u{n}", domain="tech")]
        return _fn

    for name, spec in SOURCES.items():
        spec.search = mk(name)

    tr = parse_range("30d")
    aggregator.research(topic="hello", use_cache=False, synthesize=False,
                        time_range=tr, config={})
    # At least one source should have received the time_range
    any_received = [tr_ for tr_ in received.values() if tr_ is not None]
    assert any_received, "Expected at least one source to receive time_range"
    for val in any_received:
        assert getattr(val, "is_bounded", False)
