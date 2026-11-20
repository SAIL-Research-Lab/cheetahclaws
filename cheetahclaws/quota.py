"""
quota.py — Per-session and per-day token / cost quota enforcement.

check_quota() is called before each API request.  When a limit would be
exceeded it raises QuotaExceeded so the agent can surface the error cleanly
instead of making a billable call.

Config keys (all optional; None / 0 = no limit):
  session_token_budget  int    max tokens (in+out) per session
  session_cost_budget   float  max USD per session
  daily_token_budget    int    max tokens today (all sessions in this process)
  daily_cost_budget     float  max USD today (all sessions in this process)

Daily counters are stored in ~/.cheetahclaws/quota/YYYY-MM-DD.json.
Thread-safe within a single process; no cross-process locking.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class QuotaExceeded(Exception):
    """Raised before an API call when a configured budget would be exceeded.

    Carries which cap broke (``key`` / ``scope`` / ``unit`` / ``limit``) so the
    REPL can suggest raising *that* cap in the right unit instead of a generic,
    possibly-wrong hint."""
    def __init__(self, reason: str, *, key=None, scope=None, unit=None, limit=None):
        super().__init__(reason)
        self.reason = reason
        self.key = key          # config key, e.g. "session_token_budget"
        self.scope = scope      # "session" | "daily"
        self.unit = unit        # "tok" | "usd"
        self.limit = limit      # the breached limit value


# ── In-memory counters (per session, reset on session end) ─────────────────

_lock          = threading.Lock()
_sess_tokens:  dict[str, int]   = {}   # session_id → total tokens
_sess_cost:    dict[str, float] = {}   # session_id → total cost (USD)


# ── Daily file helpers ─────────────────────────────────────────────────────

def _quota_dir() -> Path:
    from cheetahclaws.config import CONFIG_DIR
    d = CONFIG_DIR / "quota"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _load_daily() -> tuple[int, float]:
    """Return (tokens, cost) from today's on-disk record. Lock must be held."""
    p = _quota_dir() / f"{_today_key()}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data.get("tokens", 0)), float(data.get("cost", 0.0))
    except Exception:
        return 0, 0.0


def _save_daily(tokens: int, cost: float) -> None:
    """Persist today's cumulative usage. Lock must be held."""
    p = _quota_dir() / f"{_today_key()}.json"
    try:
        p.write_text(
            json.dumps({"tokens": tokens, "cost": cost}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── Public API ─────────────────────────────────────────────────────────────

def check_quota(session_id: str, config: dict,
                projected_tokens: int = 0, projected_cost: float = 0.0) -> None:
    """
    Raise QuotaExceeded if any configured limit is (or would be) reached.
    Call this BEFORE making an API request.

    ``projected_tokens`` / ``projected_cost`` estimate the pending request's
    INPUT. When given, the cap also fires if the *next* call would cross it —
    stopping before the (billable) call instead of letting one large tool-heavy
    turn overshoot the budget. With both at 0 the behaviour is the original
    "already spent ≥ limit" check, so existing callers are unaffected.
    """
    lim_st = config.get("session_token_budget") or 0
    lim_sc = config.get("session_cost_budget")  or 0.0
    lim_dt = config.get("daily_token_budget")   or 0
    lim_dc = config.get("daily_cost_budget")    or 0.0

    # Fast path: no limits configured
    if not any((lim_st, lim_sc, lim_dt, lim_dc)):
        return

    with _lock:
        st = _sess_tokens.get(session_id, 0)
        sc = _sess_cost.get(session_id, 0.0)
        dt, dc = _load_daily()

    pt = max(0, int(projected_tokens or 0))
    pc = max(0.0, float(projected_cost or 0.0))

    # For each cap: a hard stop when already reached, else a pre-call stop when
    # the projected next request would cross it (overshoot stays ≈ 0). Each raise
    # tags which cap broke so the REPL can suggest raising it in the right unit.
    specs = [
        ("session_token_budget", "session", "tok", lim_st, st, pt),
        ("session_cost_budget",  "session", "usd", lim_sc, sc, pc),
        ("daily_token_budget",   "daily",   "tok", lim_dt, dt, pt),
        ("daily_cost_budget",    "daily",   "usd", lim_dc, dc, pc),
    ]
    for key, scope, unit, lim, used, proj in specs:
        if not lim:
            continue
        label = f"{scope.capitalize()} {'token' if unit == 'tok' else 'cost'} budget"
        if unit == "tok":
            caps = f"{lim:,}"
            reached_amt, proj_amt, tail = f"{used:,}", f"{used + proj:,}", " tokens"
        else:
            caps = f"${lim:.4f}"
            reached_amt, proj_amt, tail = f"${used:.4f}", f"${used + proj:.4f}", ""
        if used >= lim:
            raise QuotaExceeded(f"{label} reached ({reached_amt}/{caps}{tail})",
                                key=key, scope=scope, unit=unit, limit=lim)
        if used + proj >= lim:
            raise QuotaExceeded(f"{label} would be exceeded by the next request "
                                f"(~{proj_amt}/{caps}{tail})",
                                key=key, scope=scope, unit=unit, limit=lim)


def output_room(session_id: str, config: dict,
                projected_tokens: int = 0, projected_cost: float = 0.0) -> int | None:
    """Max output tokens this call may emit before any configured budget is hit,
    given the projected input already counted. ``None`` when no token/cost cap
    constrains the output. Used to clamp ``max_tokens`` so one response can't
    blow past a cap (cost caps convert via the model's per-output-token price)."""
    u = get_usage(session_id)
    pt = max(0, int(projected_tokens or 0))
    pc = max(0.0, float(projected_cost or 0.0))
    rooms: list[int] = []
    if config.get("session_token_budget"):
        rooms.append(int(config["session_token_budget"]) - u["session_tokens"] - pt)
    if config.get("daily_token_budget"):
        rooms.append(int(config["daily_token_budget"]) - u["daily_tokens"] - pt)
    try:
        from cheetahclaws.providers import model_rates
        _ic, oc = model_rates(config.get("model", ""))
    except Exception:
        oc = 0.0
    if oc and oc > 0:
        if config.get("session_cost_budget"):
            rooms.append(int((float(config["session_cost_budget"]) - u["session_cost"] - pc)
                             * 1_000_000 / oc))
        if config.get("daily_cost_budget"):
            rooms.append(int((float(config["daily_cost_budget"]) - u["daily_cost"] - pc)
                             * 1_000_000 / oc))
    if not rooms:
        return None
    return max(0, min(rooms))


def record_usage(session_id: str, model: str, in_tokens: int, out_tokens: int,
                 cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> None:
    """
    Record token usage after a successful API call.
    Updates in-memory session counters and the on-disk daily record.

    Cached tokens count toward budgets too: Anthropic reports them outside
    input_tokens, but they are real processed input (billed at 0.1x read /
    1.25x write) — ignoring them would let cached sessions sail past both
    token and cost caps.
    """
    from cheetahclaws.providers import calc_cost
    tokens = in_tokens + out_tokens + cache_read_tokens + cache_write_tokens
    cost   = calc_cost(model, in_tokens, out_tokens,
                       cache_read_tokens, cache_write_tokens)

    with _lock:
        _sess_tokens[session_id] = _sess_tokens.get(session_id, 0) + tokens
        _sess_cost[session_id]   = _sess_cost.get(session_id, 0.0) + cost
        dt, dc = _load_daily()
        _save_daily(dt + tokens, dc + cost)

    from cheetahclaws import logging_utils as _log
    _log.info("usage_recorded",
              session_id=session_id,
              model=model,
              in_tokens=in_tokens,
              out_tokens=out_tokens,
              session_tokens=_sess_tokens[session_id],
              session_cost_usd=round(_sess_cost[session_id], 6))


def get_usage(session_id: str) -> dict:
    """Return current usage stats for a session (for /quota status command)."""
    with _lock:
        dt, dc = _load_daily()
        return {
            "session_tokens": _sess_tokens.get(session_id, 0),
            "session_cost":   _sess_cost.get(session_id, 0.0),
            "daily_tokens":   dt,
            "daily_cost":     dc,
        }


def reset_session(session_id: str) -> None:
    """Clear in-memory counters for a session that has ended."""
    with _lock:
        _sess_tokens.pop(session_id, None)
        _sess_cost.pop(session_id, None)


# ── User-facing helpers (for the /budget command, --budget flag, warnings) ──

# Maps a parsed budget kind+scope to its config key.
BUDGET_KEYS = {
    ("tokens", "session"): "session_token_budget",
    ("cost",   "session"): "session_cost_budget",
    ("tokens", "daily"):   "daily_token_budget",
    ("cost",   "daily"):   "daily_cost_budget",
}


def parse_budget(s: str) -> tuple[str, float]:
    """Parse a human budget string into ``(kind, value)``.

    Cost (``kind="cost"``) when prefixed ``$`` or suffixed ``usd``/``$``
    (e.g. ``$5``, ``5usd`` → ``("cost", 5.0)``); otherwise a token count with
    optional ``k``/``m`` suffix (``200k`` → ``("tokens", 200000)``,
    ``1.5m`` → ``("tokens", 1500000)``). Raises ``ValueError`` on bad input.
    """
    raw = s.strip().lower().replace(",", "").replace(" ", "")
    if not raw:
        raise ValueError("empty budget")
    is_cost = False
    if raw.startswith("$"):
        is_cost, raw = True, raw[1:]
    elif raw.endswith("usd"):
        is_cost, raw = True, raw[:-3]
    elif raw.endswith("$"):
        is_cost, raw = True, raw[:-1]
    mult = 1.0
    if raw.endswith("k"):
        mult, raw = 1_000, raw[:-1]
    elif raw.endswith("m"):
        mult, raw = 1_000_000, raw[:-1]
    try:
        num = float(raw) * mult
    except ValueError:
        raise ValueError(f"can't parse budget: {s!r}")
    if num <= 0:
        raise ValueError("budget must be a positive number")
    return ("cost", round(num, 4)) if is_cost else ("tokens", int(num))


def fmt_amount(value: float, unit: str) -> str:
    """Compact rendering of a budget amount: ``$1.83`` for cost, ``124k`` for tokens."""
    if unit == "usd":
        return f"${value:,.2f}"
    value = int(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m".replace(".0m", "m")
    if value >= 1_000:
        return f"{value / 1_000:.1f}k".replace(".0k", "k")
    return str(value)


def usage_vs_limits(session_id: str, config: dict) -> list[dict]:
    """Return the four budget rows with current usage, limit, and percent.

    Each row: ``{key, label, scope, unit, used, limit, pct}`` where ``limit`` is
    ``None`` (unlimited) and ``pct`` is ``None`` when no limit is set.
    """
    u = get_usage(session_id)
    spec = [
        ("session_cost_budget",  "Session cost",   "session", "usd", u["session_cost"]),
        ("session_token_budget", "Session tokens", "session", "tok", u["session_tokens"]),
        ("daily_cost_budget",    "Daily cost",     "daily",   "usd", u["daily_cost"]),
        ("daily_token_budget",   "Daily tokens",   "daily",   "tok", u["daily_tokens"]),
    ]
    rows = []
    for key, label, scope, unit, used in spec:
        limit = config.get(key) or None
        pct = (used / limit * 100) if limit else None
        rows.append({"key": key, "label": label, "scope": scope, "unit": unit,
                     "used": used, "limit": limit, "pct": pct})
    return rows


def warnings(session_id: str, config: dict) -> list[tuple[str, str]]:
    """Return ``(level, message)`` for any budget at ≥80% (``warn``) / ≥95%
    (``crit``) but not yet exhausted. Empty when nothing is close. Used by the
    REPL to warn before the hard stop arrives."""
    out: list[tuple[str, str]] = []
    for r in usage_vs_limits(session_id, config):
        if not r["limit"] or r["pct"] is None or r["pct"] >= 100 or r["pct"] < 80:
            continue
        level = "crit" if r["pct"] >= 95 else "warn"
        out.append((level,
                    f"{r['label']} at {r['pct']:.0f}% "
                    f"({fmt_amount(r['used'], r['unit'])} / "
                    f"{fmt_amount(r['limit'], r['unit'])})"))
    return out
