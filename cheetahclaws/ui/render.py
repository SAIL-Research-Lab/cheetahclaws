"""
ui/render.py — All terminal rendering for CheetahClaws.

Provides:
  - ANSI color helpers (C, clr, info, ok, warn, err)
  - Rich Markdown streaming (stream_text, flush_response)
  - Spinner management
  - Tool call display (print_tool_start, print_tool_end)
  - Diff rendering (render_diff)
"""
from __future__ import annotations

import re
import sys
import json
import time
import threading

# ── Optional rich for markdown rendering ──────────────────────────────────
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.live import Live
    from rich.segment import Segment, Segments
    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None
    Live = None
    Markdown = None
    Segment = None
    Segments = None

# ── ANSI helpers ───────────────────────────────────────────────────────────

def _rgb(hex_str: str) -> str:
    """Convert '#rrggbb' -> ANSI 24-bit foreground escape."""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


# Curated palettes — each theme defines four semantic roles:
#   accent : info / primary chrome (cyan, blue)
#   ok     : success / diff additions (green) — kept distinct from accent so
#            info() and ok() are visually distinguishable
#   warn   : warnings (yellow, magenta)
#   err    : errors / diff removals (red)
#   code   : Rich Markdown code-block style
# Add new entries here and they show up in `/theme` automatically.
THEMES: dict = {
    "default":     {"accent": "#00D7FF", "ok": "#00FF87", "warn": "#FFAF00", "err": "#FF5F5F", "code": "monokai"},
    "dracula":     {"accent": "#BD93F9", "ok": "#50FA7B", "warn": "#FFB86C", "err": "#FF5555", "code": "dracula"},
    "nord":        {"accent": "#88C0D0", "ok": "#A3BE8C", "warn": "#EBCB8B", "err": "#BF616A", "code": "nord"},
    "gruvbox":     {"accent": "#FABD2F", "ok": "#B8BB26", "warn": "#FE8019", "err": "#FB4934", "code": "gruvbox-dark"},
    "solarized":   {"accent": "#268BD2", "ok": "#859900", "warn": "#B58900", "err": "#DC322F", "code": "solarized-dark"},
    "tokyo-night": {"accent": "#7AA2F7", "ok": "#9ECE6A", "warn": "#E0AF68", "err": "#F7768E", "code": "one-dark"},
    "catppuccin":  {"accent": "#F5C2E7", "ok": "#A6E3A1", "warn": "#FAB387", "err": "#F38BA8", "code": "one-dark"},
    "matrix":      {"accent": "#00FF41", "ok": "#7FFF00", "warn": "#CCFF00", "err": "#FF0000", "code": "monokai"},
    "synthwave":   {"accent": "#FF00FF", "ok": "#39FF14", "warn": "#FFCC00", "err": "#FF3864", "code": "fruity"},
    "midnight":    {"accent": "#00BCD4", "ok": "#76FF03", "warn": "#FFC107", "err": "#FF1744", "code": "dracula"},
    "ocean":       {"accent": "#38BDF8", "ok": "#34D399", "warn": "#FBBF24", "err": "#F87171", "code": "nord"},
    "monokai":     {"accent": "#66D9EF", "ok": "#A6E22E", "warn": "#E6DB74", "err": "#F92672", "code": "monokai"},
    "cheetah":     {"accent": "#FFB000", "ok": "#76FF03", "warn": "#FF6F00", "err": "#D50000", "code": "monokai"},
    "mono":        {"accent": "#E0E0E0", "ok": "#C0C0C0", "warn": "#A0A0A0", "err": "#FFFFFF", "code": "bw"},
    "none":        {"disable_color": True, "code": "default"},
}

# Active code-block style for Rich Markdown rendering. Read by _make_renderable.
CODE_THEME: str = "monokai"

C = {
    "cyan":    "\033[36m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "red":     "\033[31m",
    "blue":    "\033[34m",
    "magenta": "\033[35m",
    "white":   "\033[37m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "reset":   "\033[0m",
}


def apply_theme(name: str) -> bool:
    """Mutate the global ANSI color map in-place to a named theme."""
    global CODE_THEME
    p = THEMES.get(name)
    if not p:
        return False

    # The "none" theme: strip every escape so output is plain text.
    if p.get("disable_color"):
        for k in list(C.keys()):
            C[k] = ""
        CODE_THEME = p.get("code", "default")
        return True

    accent = _rgb(p["accent"])
    ok_col = _rgb(p.get("ok", p["accent"]))
    warn_c = _rgb(p["warn"])
    err_c  = _rgb(p.get("err", "#FF5555"))

    C["cyan"]    = accent
    C["blue"]    = accent
    C["green"]   = ok_col
    C["yellow"]  = warn_c
    C["magenta"] = warn_c
    C["red"]     = err_c
    C["white"]   = "\033[97m"
    C["bold"]    = "\033[1m"
    C["dim"]     = "\033[2m"
    C["reset"]   = "\033[0m"
    CODE_THEME   = p["code"]
    return True

def clr(text: str, *keys: str) -> str:
    return "".join(C[k] for k in keys) + str(text) + C["reset"]

def info(msg: str):   print(clr(msg, "cyan"))
def ok(msg: str):     print(clr(msg, "green"))
def warn(msg: str):   print(clr(f"Warning: {msg}", "yellow"))
def err(msg: str):    print(clr(f"Error: {msg}", "red"), file=sys.stderr)

def _truncate_err_global(s: str, max_len: int = 200) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


# ── Diff rendering ─────────────────────────────────────────────────────────

def render_diff(text: str):
    """Print diff text with ANSI colors: red for removals, green for additions."""
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            print(C["bold"] + line + C["reset"])
        elif line.startswith("+"):
            print(C["green"] + line + C["reset"])
        elif line.startswith("-"):
            print(C["red"] + line + C["reset"])
        elif line.startswith("@@"):
            print(C["cyan"] + line + C["reset"])
        else:
            print(line)

def _has_diff(text: str) -> bool:
    """Check if text contains a unified diff."""
    return "--- a/" in text and "+++ b/" in text


# ── Conversation rendering ─────────────────────────────────────────────────

_accumulated_text: list[str] = []   # buffer text during streaming
_current_live = None                # active Rich Live instance (one at a time)
_RICH_LIVE = False                  # True only in "live" mode (in-place redraw); matches the commit default below
_plain_streaming_response = False   # current response has fallen back from Live
_live_shows_full = False            # True when the live frame holds the whole response (not a tail window)

# ── Adaptive streaming mode ────────────────────────────────────────────────
# Three tiers, chosen per-device (see auto_stream_mode):
#   "live"   — full in-place Rich Live redraw. Best experience, but the
#              cursor-up rewrite breaks on some terminals (Apple Terminal can't
#              erase above the scroll boundary; flaky network PTYs duplicate
#              frames), so it is reserved for terminals known to handle it.
#   "commit" — append-only progressive Markdown. Completed blocks are rendered
#              and printed permanently (never redrawn). Pure append-only: it
#              issues NO cursor-up / erase sequences at all, so it can never
#              leave duplicate frames — correct over SSH / Apple Terminal /
#              pipes / CJK-wide text alike, while still showing rich Markdown
#              block by block. The universal default for non-"live" terminals.
#   "plain"  — raw token stream (only when Rich is unavailable).
# Default to the append-only 'commit' tier (never duplicates frames on any
# terminal). cli.py upgrades to 'live' at startup via auto_stream_mode() only on
# terminals known to support in-place redraw; entry points that never call
# set_stream_mode (web, --print, bridges) thus also stay on the safe tier.
_STREAM_MODE = "commit" if _RICH else "plain"
_commit_idx = 0                     # chars of the response already committed (rendered + printed)


def set_stream_mode(mode: str) -> None:
    """Select the streaming tier ('live' | 'commit' | 'plain')."""
    global _STREAM_MODE, _RICH_LIVE
    if mode not in ("live", "commit", "plain") or not _RICH:
        mode = mode if (mode == "plain") else ("commit" if _RICH else "plain")
    _STREAM_MODE = mode
    _RICH_LIVE = (mode == "live")


def set_rich_live(enabled: bool) -> None:
    """Back-compat shim for the old boolean rich_live config.

    True  → full in-place Live. False → 'commit' (still rich, just append-only
    instead of plain raw tokens, which is a strict UX upgrade over the old
    behaviour). New code should call set_stream_mode / auto_stream_mode."""
    set_stream_mode("live" if (enabled and _RICH) else "commit")


# Terminal emulators known to handle in-place cursor-up redraw reliably, even
# over SSH. Detected via TERM_PROGRAM, TERM, or an emulator-specific env var.
_GOOD_TERM_PROGRAMS = {
    "iTerm.app", "WezTerm", "vscode", "ghostty", "rio", "Tabby", "Hyper",
    "Warp", "kitty",
}


def auto_stream_mode(config: dict | None = None) -> str:
    """Pick the best streaming tier for the current device.

    Priority: explicit config override → capability detection. Capable
    terminals (local TTYs and modern emulators, incl. over SSH) get 'live';
    everything else with Rich gets the safe-but-rich 'commit' tier; only a
    missing Rich install falls all the way back to 'plain'.
    """
    import os as _os
    import platform as _plat

    cfg = config or {}
    explicit = cfg.get("stream_mode")
    if explicit in ("live", "commit", "plain"):
        return explicit
    rl = cfg.get("rich_live")
    if rl is True:
        return "live"
    if rl is False:
        return "commit"

    if not _RICH or console is None:
        return "plain"
    if getattr(console, "is_dumb_terminal", False):
        return "commit"
    # Not a real TTY (piped / redirected / captured): append-only, no cursor games.
    if not getattr(console, "is_terminal", False):
        return "commit"

    term = _os.environ.get("TERM", "") or ""
    term_program = _os.environ.get("TERM_PROGRAM", "") or ""
    is_apple_terminal = (_plat.system() == "Darwin"
                         and term_program in ("Apple_Terminal", ""))
    # tmux / screen rewrite cursor-movement sequences and routinely break
    # in-place redraw even under a capable outer emulator, so the 'live'
    # cursor-up rewrite leaves duplicate frames. Force the safe tier.
    in_multiplexer = (
        bool(_os.environ.get("TMUX"))
        or term.startswith("screen")
        or term.startswith("tmux")
    )
    # Emulators positively known to handle in-place cursor-up redraw reliably.
    modern = (
        term_program in _GOOD_TERM_PROGRAMS
        or "kitty" in term
        or "alacritty" in term
        or bool(_os.environ.get("WT_SESSION"))          # Windows Terminal
        or bool(_os.environ.get("KITTY_WINDOW_ID"))
        or bool(_os.environ.get("ALACRITTY_WINDOW_ID"))
        or bool(_os.environ.get("WEZTERM_PANE"))
    )

    # Allowlist the risky mode: only a positively-identified capable emulator
    # gets 'live'. Everything else — Apple Terminal, tmux/screen, plain xterm,
    # an unknown TERM, an untrusted SSH PTY — gets 'commit', which issues NO
    # cursor movement and so can never duplicate frames on any terminal. This
    # makes an unrecognized terminal fail safe (append-only rich Markdown)
    # instead of failing loud (hundreds of reprinted frames). 'live' is still
    # available on any terminal via explicit `stream_mode=live` config.
    if is_apple_terminal or in_multiplexer:
        return "commit"
    if modern:
        return "live"
    return "commit"

# ── Markdown thematic breaks (`---`) ───────────────────────────────────────
# Models routinely separate sections with a `---` line. Rich renders that as a
# full-width horizontal rule, which lands in the middle of a turn — between
# two tool-summary lines, say — and reads like the app printed a divider.
# Off by default; `markdown_rules=true` brings the rules back.
_MD_RULES = False

_MD_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# A thematic break: 3+ of `*`, `_` or `-`, optionally space-separated.
_MD_THEMATIC_BREAK = re.compile(
    r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,})$")
# A run of bare `-` directly under a paragraph line is a setext H2 underline,
# not a rule — dropping it would silently demote a heading to body text.
_MD_SETEXT_H2 = re.compile(r"^ {0,3}-+[ \t]*$")


def set_markdown_rules(enabled: bool) -> None:
    """Show (True) or drop (False) Markdown `---` horizontal rules."""
    global _MD_RULES
    _MD_RULES = bool(enabled)


def _strip_thematic_breaks(text: str) -> str:
    """Remove Markdown horizontal rules, leaving everything else intact.

    Deliberately conservative: fenced code blocks are copied verbatim (a `---`
    inside a YAML or diff sample is content, not a divider), and a bare `-`
    run under a non-blank line is left alone because CommonMark reads that as
    a setext H2 underline.
    """
    if "-" not in text and "*" not in text and "_" not in text:
        return text
    out: list[str] = []
    fence: str | None = None
    prev_blank = True          # start of text behaves like "after a blank line"
    for line in text.split("\n"):
        if fence is not None:
            out.append(line)
            if line.strip().startswith(fence):
                fence = None
            continue
        m = _MD_FENCE.match(line)
        if m:
            fence = m.group(1)[0] * 3
            out.append(line)
            prev_blank = False
            continue
        if _MD_THEMATIC_BREAK.match(line):
            if not (not prev_blank and _MD_SETEXT_H2.match(line)):
                continue       # a real rule — drop it, keep prev_blank as-is
        out.append(line)
        prev_blank = not line.strip()
    return "\n".join(out)


def _make_renderable(text: str):
    """Return a Rich renderable: Markdown if text contains markup, else plain."""
    if not _MD_RULES:
        text = _strip_thematic_breaks(text)
    if any(c in text for c in ("#", "*", "`", "_", "[")):
        return Markdown(text, code_theme=CODE_THEME)
    return text

def _start_live() -> None:
    """Start a Rich Live block for in-place Markdown streaming (no-op if not Rich)."""
    global _current_live
    if _RICH and _RICH_LIVE and _current_live is None:
        _current_live = Live(console=console, auto_refresh=False,
                             vertical_overflow="visible")
        _current_live.start()

_LIVE_LINE_LIMIT = 80  # cap on Live height; beyond this only a tail window is redrawn


def _live_line_limit() -> int:
    """Return a conservative Live height limit for the current terminal."""
    height = getattr(console, "height", 0) or 0
    if height > 0:
        return min(_LIVE_LINE_LIMIT, max(12, height - 4))
    return _LIVE_LINE_LIMIT


def _cheap_line_estimate(text: str) -> int:
    """Fast per-line wrap estimate (each source line wraps into 1 + len//width
    rows). Used as a cheap gate so short responses skip the precise render."""
    width = max(1, getattr(console, "width", 80) or 80)
    return sum(1 + len(line) // width for line in text.split("\n"))


def _render_to_lines(renderable):
    """Precisely render to terminal lines (wrap- / Markdown-aware), or None on
    failure. Returns a list of segment-lines from `console.render_lines`."""
    if not (_RICH and console is not None):
        return None
    try:
        return console.render_lines(renderable, console.options, pad=False)
    except Exception:
        return None


def _lines_renderable(lines):
    """Wrap a slice of rendered segment-lines back into a Live-updatable
    renderable (used to display only the tail window of a long response)."""
    segments = []
    for i, line in enumerate(lines):
        if i:
            segments.append(Segment.line())
        segments.extend(line)
    return Segments(segments)


def _live_update(renderable, full: bool) -> None:
    """Push a frame to the Live region, starting it if needed. `full` records
    whether this frame shows the entire response or just a tail window, so
    flush_response knows whether it must re-commit the complete output."""
    global _live_shows_full
    if _current_live is None:
        _start_live()
    if _current_live is None:
        # _start_live() no-ops if Live was disabled concurrently; bail rather than
        # dereference None. Defensive only — the single-threaded path never hits it.
        return
    _live_shows_full = full
    _current_live.update(renderable, refresh=True)


def _fall_back_to_plain(renderable) -> None:
    """Stop/clear Live and switch this response to plain streaming. Used only as
    a safety net (precise render failed, or terminal too small to bound a Live
    window) — the tail-window path below normally keeps Live active."""
    global _plain_streaming_response
    _stop_live(clear=True)
    console.print(renderable)
    _accumulated_text.clear()
    _plain_streaming_response = True


def _stop_live(clear: bool = False) -> None:
    """Stop the active Live renderer, optionally clearing its last frame first."""
    global _current_live
    if _current_live is None:
        return
    if clear:
        try:
            _current_live.update("", refresh=True)
        except Exception:
            pass
    _current_live.stop()
    _current_live = None


# ── Commit-mode streaming (append-only progressive Markdown) ────────────────

def _safe_commit_point(text: str, start: int) -> int:
    """Return the index just after the last *completed* block at/after `start`.

    A block ends at a blank line ("\\n\\n") that is NOT inside an unclosed code
    fence. Counting ``` markers in the prefix tells us the fence state, so a
    fenced code block (which may itself contain blank lines) is only ever
    committed as a whole once its closing fence arrives — never rendered
    half-open. Returns `start` when no new complete block is available yet.
    """
    best = start
    i = text.find("\n\n", start)
    while i != -1:
        candidate = i + 2
        if text.count("```", 0, candidate) % 2 == 0:   # fence is closed here
            best = candidate
        i = text.find("\n\n", i + 1)
    return best


def _commit_stream() -> None:
    """Render + permanently print any newly-completed blocks (append-only).

    Issues no cursor movement whatsoever: each completed block is printed once
    and never touched again, so there is no way to leave a duplicate or stale
    frame regardless of terminal, network latency, or wide (CJK/emoji) text. The
    still-incomplete trailing block stays buffered and appears when it closes (or
    at flush); the spinner conveys liveness in the meantime."""
    global _commit_idx
    full = "".join(_accumulated_text)
    point = _safe_commit_point(full, _commit_idx)
    if point > _commit_idx:
        block = full[_commit_idx:point].strip("\n")
        if block.strip():
            try:
                console.print(_make_renderable(block))
            except Exception:
                print(block)
        _commit_idx = point


def _commit_flush() -> None:
    """Render+commit the final trailing block and reset commit state."""
    global _commit_idx
    full = "".join(_accumulated_text)
    tail = full[_commit_idx:].strip("\n")
    if tail.strip():
        try:
            console.print(_make_renderable(tail))
        except Exception:
            print(tail)
    _accumulated_text.clear()
    _commit_idx = 0


def stream_text(chunk: str) -> None:
    """Buffer chunk; update Live in-place when Rich available, else print directly.

    Live's in-place redraw moves the cursor up over the previous frame, which only
    works while that frame fits the viewport. Once the full response would render
    past the terminal height it scrolls into the scrollback the cursor can't reach,
    leaving stale/duplicate frames. To stay correct we keep the Live region bounded:
    a short response is shown in full, but once it would overflow we render the whole
    thing and feed Live only the **last `limit` lines** (a tail window that always
    fits). The complete output is committed once in flush_response(). Plain streaming
    is kept only as a safety net (precise render failed, or terminal too small).

    Tradeoff: while a long response streams in tail-window mode only its most recent
    screenful is visible; the start scrolls out of the Live region and is not yet in
    the scrollback. It is re-committed in full when the response finishes — including
    on Ctrl-C, since the REPL flushes on interrupt — so nothing is ever lost, it is
    just not visible live until completion.

    Mode dispatch: "plain" prints raw tokens, "commit" delegates to the
    append-only progressive-Markdown renderer, and "live" (below) does the
    in-place Rich Live redraw described above.
    """
    if not _RICH or _STREAM_MODE == "plain":
        print(chunk, end="", flush=True)
        return

    if _STREAM_MODE == "commit":
        _accumulated_text.append(chunk)
        _commit_stream()
        return

    if _plain_streaming_response:
        print(chunk, end="", flush=True)
        return

    _accumulated_text.append(chunk)

    if not (_RICH and _RICH_LIVE):
        print(chunk, end="", flush=True)
        return

    full = "".join(_accumulated_text)
    renderable = _make_renderable(full)
    limit = _live_line_limit()
    height = getattr(console, "height", 0) or 0

    # Can't bound a Live window inside the viewport (unknown / tiny terminal) →
    # plain streaming is the only redraw-free option.
    if not height or limit > height:
        _fall_back_to_plain(renderable)
        return

    # Fast path: only when the cheap estimate is so far under the limit that even
    # worst-case Markdown expansion (tables add border rows, blocks add blank lines)
    # cannot overflow the viewport. Correctness must not hinge on this estimate, so
    # the 3x margin is deliberately conservative — anything closer to the limit takes
    # the precise path below, which decides full vs tail window on real line counts.
    if _cheap_line_estimate(full) * 3 < limit:
        _live_update(renderable, full=True)
        return

    # Near/over the limit → render precisely to choose full vs tail window.
    lines = _render_to_lines(renderable)
    if lines is None:
        _fall_back_to_plain(renderable)
    elif len(lines) <= limit:
        _live_update(renderable, full=True)
    else:
        # Tail window: only ever redraw the last `limit` rendered lines, so the
        # Live region never exceeds the viewport and cannot leave stale frames.
        _live_update(_lines_renderable(lines[-limit:]), full=False)

def stream_thinking(chunk: str, verbose: bool):
    if verbose:
        clean_chunk = chunk.replace("\n", " ")
        if clean_chunk:
            print(f"{C['dim']}{clean_chunk}", end="", flush=True)

def flush_response() -> None:
    """Commit buffered text to screen, then reset per-response streaming state."""
    global _plain_streaming_response, _live_shows_full
    if _STREAM_MODE == "commit":
        _commit_flush()
        return
    full = "".join(_accumulated_text)
    _accumulated_text.clear()
    if _current_live is not None:
        if _live_shows_full:
            # Live already holds the complete rendered output — freeze it in place.
            _stop_live()
        else:
            # Live only shows a tail window — clear it and commit the full output.
            _stop_live(clear=True)
            if _RICH and _RICH_LIVE and full.strip():
                console.print(_make_renderable(full))
    elif _RICH and _RICH_LIVE and full.strip():
        console.print(_make_renderable(full))
    else:
        print()  # ensure newline after plain-text stream
    _live_shows_full = False
    _plain_streaming_response = False


# ── Spinner ────────────────────────────────────────────────────────────────

_TOOL_SPINNER_PHRASES = [
    "⚡ Rewriting light speed...",
    "🏁 Winning a race against light...",
    "🤔 Who is Barry Allen?...",
    "🐆 Outrunning the compiler...",
    "💨 Leaving electrons behind...",
    "🌍 Orbiting the codebase...",
    "⏱️ Breaking the sound barrier...",
    "🔥 Faster than a hot reload...",
    "🚀 Terminal velocity reached...",
    "🐾 Claw marks on the stack...",
    "🏎️ Shifting to 6th gear...",
    "⚡ Speed force activated...",
    "🌪️ Blitzing through the AST...",
    "💫 Bending spacetime...",
    "🐆 Cheetah mode engaged...",
]

_DEBATE_SPINNER_PHRASES = [
    "⚔️  Experts taking their positions...",
    "🧠  Experts formulating arguments...",
    "🗣️  Debate in progress...",
    "⚖️  Weighing the evidence...",
    "💡  Building counter-arguments...",
    "🔥  Debate heating up...",
    "📜  Drafting the consensus...",
    "🎯  Finding common ground...",
]

# Rotating "did you know" tips shown beneath the spinner while the model works,
# Claude-Code style. Each references a real CheetahClaws feature/command.
_SPINNER_TIPS = [
    "Use /compact to shrink a long conversation without losing the thread",
    "Run /checkpoint to snapshot the session, then /rewind to jump back",
    "Type /plan to enter plan mode — Claude designs before it edits",
    "Use /ssj for SSJ Developer Mode — a power menu of expert tools",
    "Try /research <topic> to fan out web searches into a cited report",
    "Spawn background helpers with /agent — see them with /agents",
    "Persistent memories live in /memory — search, list, or consolidate",
    "Toggle extended reasoning anytime with /thinking",
    "Check token usage with /context and spend with /cost",
    "Switch models on the fly with /model — no restart needed",
    "Recolor the whole UI with /theme — pick from a dozen palettes",
    "Run /web to open the browser terminal / chat UI in the background",
    "Sync sessions to a GitHub Gist with /cloudsave",
    "Bridge chats with /telegram, /slack, /wechat, or /qq",
    "Summarize any-size PDF or code file with /summarize",
    "Set permission mode with /permissions — auto, accept-all, or manual",
    "Stuck on health? /doctor diagnoses your installation",
    "Paste an image from the clipboard straight to the model with /image",
    "Manage MCP servers live with /mcp reload / add / remove",
    "Drop a CLAUDE.md with /init so Claude learns your project conventions",
]

_tool_spinner_thread = None
_tool_spinner_stop = threading.Event()
_spinner_phrase = ""
_spinner_lock = threading.Lock()
_spinner_start = 0.0           # monotonic timestamp when current spinner began
_spinner_tips_enabled = True   # toggled via set_spinner_tips() (config spinner_tips)
_spinner_tip = ""              # tip currently displayed (rotates while spinning)
_spinner_tokens = 0            # live (estimated) output-token meter shown on the spinner


def set_spinner_tips(enabled: bool) -> None:
    """Called from repl.py to apply the spinner_tips config setting."""
    global _spinner_tips_enabled
    _spinner_tips_enabled = bool(enabled)


def set_spinner_tokens(n: int) -> None:
    """Update the live token counter shown on the spinner line.

    Providers only report real usage at turn end, so during streaming we feed
    a cheap char-based estimate here (see est_tokens). 0 hides the counter.
    """
    global _spinner_tokens
    with _spinner_lock:
        _spinner_tokens = max(0, int(n))


def est_tokens(text: str) -> int:
    """Cheap ~4-chars-per-token estimate for the live meter (not billing)."""
    return max(0, len(text or "") // 4)


def fmt_tokens(n: int) -> str:
    """Compact token count: 1234 -> '1.2k', 980 -> '980'."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(int(n))


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60:02d}s"


def _pick_tip() -> str:
    import random
    return random.choice(_SPINNER_TIPS)


def _run_tool_spinner():
    """Background spinner. Single carriage-return line, plus a Claude-Code-style
    rotating tip line beneath it when attached to a TTY and tips are enabled."""
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    # Tips need cursor up/down moves, which only behave on a real terminal.
    two_line = _spinner_tips_enabled and bool(getattr(sys.stdout, "isatty", lambda: False)())
    while not _tool_spinner_stop.is_set():
        with _spinner_lock:
            phrase = _spinner_phrase
            tip = _spinner_tip
            tokens = _spinner_tokens
        frame = chars[i % len(chars)]
        # Animate the terminal tab title in lock-step with the spinner while a
        # turn is in flight (same thread → no stdout race with the line below).
        if _title_enabled and _title_working:
            _tick_working_title(i)
        elapsed = _fmt_elapsed(time.monotonic() - _spinner_start)
        # Claude-Code-style meta: "(7s · ↓ 435 tokens)". Token part appears
        # only once we've streamed enough to estimate a non-zero count.
        meta = elapsed
        if tokens > 0:
            meta = f"{elapsed} · ↓ {fmt_tokens(tokens)} tokens"
        if two_line:
            # Rotate the tip roughly every 12s.
            if i and i % 120 == 0:
                with _spinner_lock:
                    globals()["_spinner_tip"] = _pick_tip()
                    tip = _spinner_tip
            line1 = f"  {frame} {clr(phrase, 'dim')} {clr('(' + meta + ')', 'dim')}"
            line2 = f"  {clr('⎿  Tip: ' + tip, 'dim')}"
            # Write line1, drop to line2, then climb back up to line1's column 0
            # so the next frame overwrites in place. \033[2K clears each line.
            sys.stdout.write("\r\033[2K" + line1 + "\n\033[2K" + line2 + "\033[1A\r")
        else:
            sys.stdout.write(f"\r\033[2K  {frame} {clr(phrase, 'dim')} {clr('(' + meta + ')', 'dim')}   ")
        sys.stdout.flush()
        i += 1
        _tool_spinner_stop.wait(0.1)

def _start_tool_spinner():
    global _tool_spinner_thread, _spinner_start
    if _tool_spinner_thread and _tool_spinner_thread.is_alive():
        return
    with _spinner_lock:
        global _spinner_phrase, _spinner_tip
        import random
        _spinner_phrase = random.choice(_TOOL_SPINNER_PHRASES)
        _spinner_tip = _pick_tip()
    _spinner_start = time.monotonic()
    _tool_spinner_stop.clear()
    _tool_spinner_thread = threading.Thread(target=_run_tool_spinner, daemon=True)
    _tool_spinner_thread.start()

def _change_spinner_phrase():
    """Change the spinner phrase without stopping it."""
    import random
    with _spinner_lock:
        global _spinner_phrase
        _spinner_phrase = random.choice(_TOOL_SPINNER_PHRASES)

def set_spinner_phrase(phrase: str) -> None:
    """Set a specific spinner phrase (used by SSJ debate mode)."""
    global _spinner_phrase
    with _spinner_lock:
        _spinner_phrase = phrase

def _stop_tool_spinner():
    global _tool_spinner_thread
    if not _tool_spinner_thread:
        return
    _tool_spinner_stop.set()
    _tool_spinner_thread.join(timeout=1)
    _tool_spinner_thread = None
    # Clear the spinner line and, if we drew one, the tip line below it, then
    # leave the cursor at column 0 of the (now blank) spinner line.
    if _spinner_tips_enabled and bool(getattr(sys.stdout, "isatty", lambda: False)()):
        sys.stdout.write("\r\033[2K\n\033[2K\033[1A\r")
    else:
        sys.stdout.write(f"\r{' ' * 50}\r")
    sys.stdout.flush()


# ── Terminal window/tab title (OSC 2) ───────────────────────────────────────
# CheetahClaws never set the terminal title, so the tab showed the shell
# default (user@host: /path). Claude-Code-style, reflect live state instead:
# a pulsing glyph + the current task while the model works, a static badge
# when idle. Only real TTYs get the escape bytes — pipes / CI / dumb terminals
# are left untouched. Animation is driven from the existing spinner thread, so
# no extra thread is spawned; _emit_title de-dupes so the tab is rewritten only
# when the glyph or task actually changes (no per-frame flicker).

_title_enabled  = False
_title_task     = ""      # short label of what the user is currently doing
_title_working  = False   # True between turn start and turn end
_TITLE_PULSE    = "✶✳✻✳"  # glyph cycle shown while working
_last_title_written = None
_title_atexit_registered = False


def _title_supported() -> bool:
    import os as _os
    if _os.environ.get("TERM", "") in ("", "dumb"):
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _title_label() -> str:
    if _title_task:
        return _title_task
    import os as _os
    return _os.path.basename(_os.getcwd()) or "session"


def _emit_title(text: str) -> None:
    global _last_title_written
    if not _title_enabled or text == _last_title_written:
        return
    _last_title_written = text
    try:
        # OSC 0 = set BOTH icon name and window title. Use 0 (not 2) because
        # VS Code's integrated terminal drives its tab label from the icon
        # name (OSC 0/1) and ignores the window-title-only OSC 2 — so OSC 2
        # reaches the terminal but never appears on the tab. OSC 0 is also
        # what virtually every CLI (incl. Claude Code) emits, so it is the
        # most widely honored across VS Code / iTerm2 / Terminal.app. BEL
        # (\a) terminator is invisible to the on-screen line, so it never
        # disturbs the spinner's carriage-return redraw.
        sys.stdout.write(f"\033]0;{text}\a")
        sys.stdout.flush()
    except Exception:
        pass


def _set_idle_title() -> None:
    _emit_title(f"● CheetahClaws — {_title_label()}")


def _tick_working_title(i: int) -> None:
    """Called from the spinner loop each tick; advances the glyph every ~0.4s."""
    glyph = _TITLE_PULSE[(i // 4) % len(_TITLE_PULSE)]
    _emit_title(f"{glyph} CheetahClaws — {_title_label()}")


def clear_terminal_title() -> None:
    """Restore the terminal title on exit (OSC 0 with an empty string), so the
    tab doesn't linger on a stale '● CheetahClaws — …' after the process ends.
    The returning shell prompt then re-sets its own title as usual. Bypasses
    the de-dupe guard so the clear is always sent."""
    global _title_working, _last_title_written
    _title_working = False
    if not _title_enabled:
        return
    try:
        sys.stdout.write("\033]0;\a")
        sys.stdout.flush()
        _last_title_written = ""
    except Exception:
        pass


def set_terminal_title_enabled(enabled: bool) -> None:
    """Apply the terminal_title config setting (auto-off on non-TTYs)."""
    global _title_enabled, _title_atexit_registered
    _title_enabled = bool(enabled) and _title_supported()
    if _title_enabled:
        _set_idle_title()
        # Restore the title on interpreter exit (normal quit, /exit, Ctrl+D,
        # sys.exit). os._exit paths (3x-Ctrl+C force quit) bypass atexit and
        # clear the title explicitly at their call site.
        if not _title_atexit_registered:
            import atexit
            atexit.register(clear_terminal_title)
            _title_atexit_registered = True


def set_task_title(task: str) -> None:
    """Record a short label of the current task (usually the user's prompt).
    Refreshes the idle title immediately when no turn is in flight."""
    global _title_task
    t = " ".join((task or "").split())
    _title_task = (t[:47] + "…") if len(t) > 48 else t
    if not _title_working:
        _set_idle_title()


def terminal_working_start() -> None:
    """Mark the start of a turn — the spinner then animates the title glyph."""
    global _title_working
    _title_working = True


def terminal_working_stop() -> None:
    """Mark a turn done — drop back to the static idle title."""
    global _title_working
    _title_working = False
    _set_idle_title()


# ── Tool call display ──────────────────────────────────────────────────────

# Quiet mode: suppress the per-tool ⚙/✓ lines while a turn runs and instead
# emit a single Claude-Code-style summary line ("Read 1 file, ran 3 shell
# commands") once the turn finishes. Verbose mode always wins and shows
# everything regardless of this flag.
_QUIET = False
_turn_tool_stats: dict[str, int] = {}   # tool name -> times invoked this turn
_turn_tool_order: list[str] = []        # first-seen order, for stable summary


def set_quiet(enabled: bool) -> None:
    """Enable/disable compact (Claude-Code-style) tool display."""
    global _QUIET
    _QUIET = bool(enabled)


def reset_turn_stats() -> None:
    """Clear the per-turn tool counters. Call at the start of every turn."""
    _turn_tool_stats.clear()
    _turn_tool_order.clear()


def _record_tool(name: str) -> None:
    if name not in _turn_tool_stats:
        _turn_tool_order.append(name)
    _turn_tool_stats[name] = _turn_tool_stats.get(name, 0) + 1


# verb, singular-noun, plural-noun used to phrase each tool family in the
# turn summary. Anything not listed falls back to a generic "called X".
_SUMMARY_VERBS = {
    "Read":      ("Read", "file", "files"),
    "Write":     ("wrote", "file", "files"),
    "Edit":      ("edited", "file", "files"),
    "Bash":      ("ran", "shell command", "shell commands"),
    "Glob":      ("ran", "file search", "file searches"),
    "Grep":      ("ran", "search", "searches"),
    "LS":        ("listed", "directory", "directories"),
    "WebFetch":  ("fetched", "URL", "URLs"),
    "WebSearch": ("ran", "web search", "web searches"),
    "Agent":     ("ran", "agent", "agents"),
}


def turn_summary_line():
    """Build a one-line summary of the tools used this turn, or None if idle."""
    if not _turn_tool_order:
        return None
    parts = []
    for name in _turn_tool_order:
        n = _turn_tool_stats.get(name, 0)
        if n <= 0:
            continue
        verb, sing, plur = _SUMMARY_VERBS.get(name, ("called", name, name))
        noun = sing if n == 1 else plur
        parts.append(f"{verb} {n} {noun}")
    if not parts:
        return None
    # Capitalize only the very first verb, like Claude Code does.
    text = ", ".join(parts)
    return text[0].upper() + text[1:]


def print_turn_stats(elapsed_s: float, in_tok: int, out_tok: int,
                     show_input: bool = False) -> None:
    """Print a Claude-Code-style footer with real elapsed time + token usage.

    Uses the true counts from TurnDone (not the live estimate). Shown once at
    the end of a turn in quiet mode, e.g. '✻ Worked for 7.2s · ↓ 435'.

    The input-token count (``↑ …``) is hidden by default — for most turns it is
    dominated by conversation history + tool output and isn't actionable. Set
    ``show_input=True`` (config ``stats_show_input``) to bring it back, giving
    '✻ Worked for 7.2s · ↑ 1.2k · ↓ 435'.
    """
    if in_tok <= 0 and out_tok <= 0:
        return
    el = _fmt_elapsed(elapsed_s)
    up = f" · ↑ {fmt_tokens(in_tok)}" if show_input else ""
    print(clr(f"  ✻ Worked for {el}{up} · ↓ {fmt_tokens(out_tok)}", "dim"),
          flush=True)


def print_turn_summary() -> None:
    """Print a summary of tools used since the last summary, then reset.

    Called both at the tool→text boundary (so the summary sits *above* the
    assistant's reply, like Claude Code) and at turn end (to flush any tools
    that ran after the last text block). Clearing after print keeps repeated
    calls from double-reporting the same tools.
    """
    line = turn_summary_line()
    if line:
        print(clr(f"  {line}", "dim"), flush=True)
    _turn_tool_stats.clear()
    _turn_tool_order.clear()


def _tool_desc(name: str, inputs: dict) -> str:
    if name == "Read":   return f"Read({inputs.get('file_path','')})"
    if name == "Write":  return f"Write({inputs.get('file_path','')})"
    if name == "Edit":   return f"Edit({inputs.get('file_path','')})"
    if name == "Bash":   return f"Bash({inputs.get('command','')[:80]})"
    if name == "Glob":   return f"Glob({inputs.get('pattern','')})"
    if name == "Grep":   return f"Grep({inputs.get('pattern','')})"
    if name == "WebFetch":    return f"WebFetch({inputs.get('url','')[:60]})"
    if name == "WebSearch":   return f"WebSearch({inputs.get('query','')})"
    if name == "Agent":
        atype = inputs.get("subagent_type", "")
        aname = inputs.get("name", "")
        iso   = inputs.get("isolation", "")
        bg    = not inputs.get("wait", True)
        parts = []
        if atype:  parts.append(atype)
        if aname:  parts.append(f"name={aname}")
        if iso:    parts.append(f"isolation={iso}")
        if bg:     parts.append("background")
        suffix = f"({', '.join(parts)})" if parts else ""
        prompt_short = inputs.get("prompt", "")[:60]
        return f"Agent{suffix}: {prompt_short}"
    if name == "SendMessage":
        return f"SendMessage(to={inputs.get('to','')}: {inputs.get('message','')[:50]})"
    if name == "CheckAgentResult": return f"CheckAgentResult({inputs.get('task_id','')})"
    if name == "ListAgentTasks":   return "ListAgentTasks()"
    if name == "ListAgentTypes":   return "ListAgentTypes()"
    if name == "AskUserQuestion":
        questions = inputs.get("questions", [])
        if questions:
            first = questions[0].get("question", "") if isinstance(questions[0], dict) else str(questions[0])
            return f"AskUserQuestion({first[:60]}{'…' if len(first) > 60 else ''})"
        return "AskUserQuestion()"
    return f"{name}({list(inputs.values())[:1]})"


def print_tool_start(name: str, inputs: dict, verbose: bool):
    """Show tool invocation."""
    if name == "AskUserQuestion":
        return
    _record_tool(name)
    # Quiet (non-verbose) mode: stay silent here. The spinner conveys live
    # activity and print_turn_summary() reports the tally at turn end.
    if _QUIET and not verbose:
        set_spinner_phrase(_tool_desc(name, inputs)[:60])
        return
    desc = _tool_desc(name, inputs)
    print(clr(f"  ⚙  {desc}", "dim", "cyan"), flush=True)
    if verbose:
        print(clr(f"     inputs: {json.dumps(inputs, ensure_ascii=False)[:200]}", "dim"))

def print_tool_end(name: str, result: str, verbose: bool):
    if name == "AskUserQuestion":
        return
    # Quiet mode swallows the per-tool result line. Errors still surface so the
    # user isn't left guessing when something failed mid-turn.
    if _QUIET and not verbose:
        rs = str(result or "")
        if rs.startswith("Error") or rs.startswith("Denied"):
            print(clr(f"  ✗ {rs[:120]}", "dim", "red"), flush=True)
        return
    lines = result.count("\n") + 1
    size = len(result)
    summary = f"→ {lines} lines ({size} chars)"
    if not result.startswith("Error") and not result.startswith("Denied"):
        print(clr(f"  ✓ {summary}", "dim", "green"), flush=True)
        if name in ("Edit", "Write") and _has_diff(result):
            parts = result.split("\n\n", 1)
            if len(parts) == 2:
                print(clr(f"  {parts[0]}", "dim"))
                render_diff(parts[1])
    else:
        print(clr(f"  ✗ {result[:120]}", "dim", "red"), flush=True)
    if verbose and not result.startswith("Denied"):
        preview = result[:500] + ("…" if len(result) > 500 else "")
        print(clr(f"     {preview.replace(chr(10), chr(10)+'     ')}", "dim"))
