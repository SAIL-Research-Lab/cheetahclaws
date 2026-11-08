"""tools_fs.py — File-system tool implementations: Read, Write, Edit, MultiEdit, Glob.

Editing guarantees (shared with tools/patch.py's ApplyPatch):
  * read-before-edit + stale-file detection, scoped per session
    (config ``edit_require_read``, default true; set false to disable)
  * the file's encoding/BOM and line-ending style are preserved; non-UTF-8
    legacy files only accept ASCII edits; binary files are refused
  * writes are atomic (temp file + fsync + os.replace, mode bits kept)
"""
from __future__ import annotations

import bisect
import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cheetahclaws.tools.file_state import (
    DecodedText, EncodingError,
    atomic_write_bytes, check_insertable, decode_file_bytes, dominant_newline,
    encode_text, looks_binary, normalize_newlines, tracker_for_config,
)


# A Read call should never materialize an arbitrarily large file (or even an
# arbitrarily long single line) before the agent can apply its output cap.
_LINE_SCAN_BYTES = 8 * 1024
_DEFAULT_READ_MAX_BYTES = 256 * 1024
_DEFAULT_READ_SCAN_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_READ_MAX_OUTPUT_CHARS = 50_000


def _read_preserving_newlines(p: Path) -> str:
    """Read a text file without newline translation.

    Path.read_text gained a `newline=` parameter only in Python 3.14; the
    project supports 3.10+, so we use open() which has accepted `newline=`
    since the pathlib API was introduced.
    """
    with p.open(encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


# ── Diff helpers ──────────────────────────────────────────────────────────

def generate_unified_diff(old: str, new: str, filename: str,
                           context_lines: int = 3) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
        n=context_lines,
    )
    return "".join(diff)


def maybe_truncate_diff(diff_text: str, max_lines: int = 80) -> str:
    lines = diff_text.splitlines()
    if len(lines) <= max_lines:
        return diff_text
    shown     = lines[:max_lines]
    remaining = len(lines) - max_lines
    return "\n".join(shown) + f"\n\n[... {remaining} more lines ...]"


# ── Read ─────────────────────────────────────────────────────────────────

def _read_logical_line(handle, capture_bytes: int | None, scan_remaining: int):
    """Read one newline-preserving binary line with strict byte budgets.

    Reading bytes rather than ``TextIOWrapper.readline(size)`` prevents a
    UTF-8-heavy line from turning a character limit into a several-times-larger
    byte read.  Any bytes after a line ending are rewound, so a CRLF split at a
    chunk boundary is never exposed as a spurious blank line.
    """
    chunks: list[bytes] = []
    captured = 0
    scanned = 0

    while True:
        remaining = scan_remaining - scanned
        if remaining <= 0:
            return b"".join(chunks), False, False, scanned, False, True

        request_bytes = min(_LINE_SCAN_BYTES, remaining)
        if capture_bytes is not None:
            capture_remaining = capture_bytes - captured
            if capture_remaining <= 0:
                return b"".join(chunks), False, False, scanned, True, False
            request_bytes = min(request_bytes, capture_remaining)
        piece = handle.read(request_bytes)
        if not piece:
            return b"".join(chunks), bool(chunks), True, scanned, False, False

        cr_index = piece.find(b"\r")
        lf_index = piece.find(b"\n")
        newline_index = min(
            (idx for idx in (cr_index, lf_index) if idx >= 0),
            default=-1,
        )
        take = len(piece) if newline_index < 0 else newline_index + 1
        is_cr = newline_index >= 0 and piece[newline_index:newline_index + 1] == b"\r"
        if is_cr and take < len(piece) and piece[take:take + 1] == b"\n":
            take += 1

        tail = piece[take:]
        if tail:
            # ``handle`` is a regular binary file, so this only moves its
            # cursor back over bytes already read in the small bounded chunk.
            handle.seek(-len(tail), 1)
        selected = piece[:take]
        if capture_bytes is not None:
            chunks.append(selected)
            captured += len(selected)
        scanned += len(selected)

        if newline_index >= 0:
            if is_cr and take == len(piece) and piece[take - 1:take] == b"\r":
                # A *bare* CR at the end of a chunk may start a CRLF whose LF
                # was split into the next read. Probe only in that case — a
                # complete CRLF already consumed its LF (last byte is b"\n"),
                # so probing there would swallow a following blank line and
                # shift every later line number.  Probe only when the caller
                # still has budget to retain that final LF.
                can_probe = (
                    scanned < scan_remaining
                    and (capture_bytes is None or captured < capture_bytes)
                )
                if can_probe:
                    next_byte = handle.read(1)
                    if next_byte == b"\n":
                        if capture_bytes is not None:
                            chunks.append(next_byte)
                        scanned += 1
                        captured += 1
                    elif next_byte:
                        handle.seek(-1, 1)
                else:
                    # The caller stopped exactly at CR. Treat this as an
                    # incomplete line rather than later splitting CRLF into
                    # a blank logical line.
                    return (
                        b"".join(chunks), False, False, scanned,
                        capture_bytes is not None and captured >= capture_bytes,
                        scanned >= scan_remaining,
                    )
            return b"".join(chunks), True, False, scanned, False, False

        if capture_bytes is not None and captured >= capture_bytes:
            return b"".join(chunks), False, False, scanned, True, False
        if scanned >= scan_remaining:
            return b"".join(chunks), False, False, scanned, False, True


def _with_stop_marker(rendered: list[str], marker: str, output_limit: int) -> str:
    """Add a stop marker without letting it exceed the configured output cap."""
    marker = marker[:output_limit]
    if not rendered:
        return marker
    visible = "".join(rendered)
    return visible[:max(0, output_limit - len(marker))] + marker


def _wide_bom_encoding(head: bytes) -> Optional[str]:
    """Codec for UTF-16/32 files identified by their BOM, else None."""
    import codecs
    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
                     (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if head.startswith(bom):
            return enc
    return None


def _read_wide(p: Path, start: int, line_limit: Optional[int],
               scan_limit: int, output_limit: int) -> str:
    """Read a UTF-16/32 (BOM) file.  The byte-oriented line scanner cannot
    split these on b"\\n", so decode a bounded prefix instead."""
    with p.open("rb") as handle:
        data = handle.read(scan_limit + 1)
    truncated = len(data) > scan_limit
    data = data[:scan_limit]
    enc = _wide_bom_encoding(data) or "utf-16"
    bom_len = 4 if enc.startswith("utf-32") else 2
    unit = 4 if enc.startswith("utf-32") else 2
    body = data[bom_len:]
    body = body[:len(body) - (len(body) % unit)]
    text = body.decode(enc, errors="replace" if not truncated else "ignore")
    lines = text.splitlines(keepends=True)
    if truncated and lines:
        lines = lines[:-1]   # last line may be cut mid-way
    selected = lines[start:start + line_limit] if line_limit else lines[start:]
    rendered: list[str] = []
    total = 0
    for i, line in enumerate(selected, start + 1):
        formatted = f"{i:6}\t{line}"
        if total + len(formatted) > output_limit:
            marker = (f"[... Read output capped at {output_limit:,} characters to "
                      "keep memory and model context bounded ...]\n")
            return _with_stop_marker(rendered, "\n" + marker if rendered else marker, output_limit)
        rendered.append(formatted)
        total += len(formatted)
    if truncated and (not line_limit or len(selected) < line_limit):
        marker = (f"[... Read stopped after scanning {scan_limit:,} bytes; "
                  "use a smaller offset or a narrower file ...]\n")
        return _with_stop_marker(rendered, "\n" + marker if rendered else marker, output_limit)
    if not rendered:
        return "(empty file)"
    return "".join(rendered)


def _read(
    file_path: str,
    limit: int = None,
    offset: int = None,
    max_bytes: int = _DEFAULT_READ_MAX_BYTES,
    scan_max_bytes: int = _DEFAULT_READ_SCAN_MAX_BYTES,
    max_output_chars: int = _DEFAULT_READ_MAX_OUTPUT_CHARS,
) -> str:
    """Stream a numbered text slice with bounded I/O and rendered output."""
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    if p.is_dir():
        return f"Error: {file_path} is a directory"
    try:
        start = max(0, int(offset or 0))
        line_limit = int(limit) if limit else None
        byte_limit = max(1, int(max_bytes or _DEFAULT_READ_MAX_BYTES))
        scan_limit = max(1, int(scan_max_bytes or _DEFAULT_READ_SCAN_MAX_BYTES))
        output_limit = max(1, int(max_output_chars or _DEFAULT_READ_MAX_OUTPUT_CHARS))
        rendered: list[str] = []
        rendered_lines = 0
        source_bytes = 0
        scanned_bytes = 0
        rendered_chars = 0
        line_no = 0
        source_budget_hit = False
        scan_budget_hit = False
        output_budget_hit = False

        file_size = p.stat().st_size
        with p.open("rb") as handle:
            head = handle.read(4)
            handle.seek(0)
        if _wide_bom_encoding(head):
            return _read_wide(p, start, line_limit, scan_limit, output_limit)
        with p.open("rb") as handle:
            while True:
                if line_limit is not None and rendered_lines >= line_limit:
                    break
                if source_bytes >= byte_limit:
                    # A size check avoids an extra unbounded text-buffer read
                    # solely to distinguish exact EOF from a longer file.
                    source_budget_hit = handle.tell() < file_size
                    break
                if scanned_bytes >= scan_limit:
                    scan_budget_hit = True
                    break

                if line_no < start:
                    _, ended, eof, consumed, _, scan_hit = _read_logical_line(
                        handle, None, scan_limit - scanned_bytes,
                    )
                    scanned_bytes += consumed
                    if not ended:
                        if scan_hit:
                            scan_budget_hit = True
                        if eof or scan_budget_hit:
                            break
                    else:
                        line_no += 1
                    if eof:
                        break
                    continue

                prefix = f"{line_no + 1:6}\t"
                output_room = output_limit - rendered_chars
                if output_room <= len(prefix):
                    output_budget_hit = True
                    break
                source_remaining = byte_limit - source_bytes
                output_content_room = output_room - len(prefix)
                capture_bytes = min(source_remaining, output_content_room)
                source_constrained = source_remaining <= output_content_room
                raw, ended, eof, consumed, capture_hit, scan_hit = _read_logical_line(
                    handle, max(1, capture_bytes), scan_limit - scanned_bytes,
                )
                scanned_bytes += consumed
                if not raw and eof:
                    break
                # A cap can split a multi-byte codepoint. Dropping only the
                # incomplete tail preserves valid UTF-8 and the byte ceiling.
                text = raw.decode(
                    "utf-8", errors="ignore" if capture_hit or scan_hit else "replace",
                )
                if line_no == 0 and text.startswith("\ufeff"):
                    text = text[1:]   # UTF-8 BOM is not content; never show it
                line_no += 1
                source_bytes += len(raw)
                formatted = prefix + text
                rendered.append(formatted)
                rendered_chars += len(formatted)
                rendered_lines += 1
                if capture_hit:
                    if source_constrained:
                        source_budget_hit = handle.tell() < file_size
                    else:
                        output_budget_hit = True
                    break
                if scan_hit:
                    scan_budget_hit = True
                    break
                if not ended:
                    # EOF after a final line with no terminator is still a
                    # valid logical line; any other incomplete line hit a cap.
                    if not eof:
                        scan_budget_hit = True
                    break

        if scan_budget_hit:
            marker = (
                f"[... Read stopped after scanning {scan_limit:,} bytes; "
                "use a smaller offset or a narrower file ...]\n"
            )
            return _with_stop_marker(rendered, "\n" + marker if rendered else marker, output_limit)
        elif source_budget_hit:
            marker = (
                f"[... Read stopped after {byte_limit:,} source bytes; use "
                "offset and limit to request another line range ...]\n"
            )
            return _with_stop_marker(rendered, "\n" + marker if rendered else marker, output_limit)
        elif output_budget_hit:
            marker = (
                f"[... Read output capped at {output_limit:,} characters to "
                "keep memory and model context bounded ...]\n"
            )
            return _with_stop_marker(rendered, "\n" + marker if rendered else marker, output_limit)
        if not rendered:
            return "(empty file)"
        return "".join(rendered)
    except Exception as e:
        return f"Error: {e}"


# ── Shared edit machinery ────────────────────────────────────────────────
#
# Every mutating tool goes through the same three steps:
#   1. plan   — read + decode the file, compute the new text in memory
#               (pure; raises EditError with a model-facing message)
#   2. check  — read-before-edit / stale-file guard (session-scoped)
#   3. commit — encode with the file's original encoding/BOM and write
#               atomically (temp file + fsync + os.replace)
# ``preview_edit`` reuses step 1 only, so the approval prompt shows exactly
# what would be written.

class EditError(Exception):
    """A model-facing failure; ``str(exc)`` is the full tool result."""


@dataclass
class FilePlan:
    """The computed outcome of an edit to one file (nothing written yet)."""
    path: Path
    old_data: Optional[bytes]        # None → file does not exist yet
    old_text: str
    new_text: str
    decoded: DecodedText
    delete: bool = False             # ApplyPatch "*** Delete File"
    move_from: Optional[Path] = None  # ApplyPatch "*** Move to" source
    note: str = ""                   # extra info for the result string

    @property
    def is_new(self) -> bool:
        return self.old_data is None

    def new_bytes(self) -> bytes:
        return encode_text(self.new_text, self.decoded)


def _load_existing(p: Path) -> tuple[bytes, DecodedText]:
    if p.is_dir():
        raise EditError(f"Error: {p} is a directory")
    try:
        data = p.read_bytes()
    except OSError as e:
        raise EditError(f"Error: {e}") from e
    try:
        return data, decode_file_bytes(data)
    except EncodingError as e:
        raise EditError(
            f"Error: refusing to edit {p}: {e}. Editing it as text would "
            "corrupt it."
        ) from e


def _line_no(text: str, pos: int) -> int:
    """1-based line number of ``pos`` in LF-normalised ``text`` (lone CRs
    count as line breaks too, matching the Read tool's numbering)."""
    head = text[:pos]
    return head.count("\n") + head.count("\r") + 1


def _fmt_lines(nums: list[int], limit: int = 10) -> str:
    shown = ", ".join(str(n) for n in nums[:limit])
    if len(nums) > limit:
        shown += f", … (+{len(nums) - limit} more)"
    return shown


def _find_all(haystack: str, needle: str) -> list[int]:
    out, start = [], 0
    while True:
        i = haystack.find(needle, start)
        if i < 0:
            return out
        out.append(i)
        start = i + len(needle)


def _ws_key(s: str) -> str:
    return " ".join(s.split())


def _whitespace_hint(norm_text: str, old_norm: str) -> str:
    """If ``old_norm`` matches modulo whitespace, describe where (no auto-apply)."""
    old_lines = old_norm.split("\n")
    while old_lines and not old_lines[-1].strip():
        old_lines.pop()
    while old_lines and not old_lines[0].strip():
        old_lines.pop(0)
    if not old_lines:
        return ""
    file_lines = norm_text.split("\n")
    keys = [_ws_key(l) for l in old_lines]
    cands: list[int] = []
    if len(keys) == 1:
        needle = keys[0]
        cands = [i for i, l in enumerate(file_lines) if needle in _ws_key(l)]
    else:
        n = len(keys)
        file_keys = [_ws_key(l) for l in file_lines]
        for i in range(len(file_lines) - n + 1):
            if file_keys[i:i + n] == keys:
                cands.append(i)
    if not cands:
        return ""
    if len(cands) > 1:
        return (f"\nHint: {len(cands)} whitespace-insensitive matches exist "
                f"(lines {_fmt_lines([c + 1 for c in cands])}); check "
                "indentation/tabs and add context.")
    i = cands[0]
    span = file_lines[i:i + max(1, len(old_lines))]
    snippet = "\n".join(span)
    if len(snippet) > 1200:
        snippet = snippet[:1200] + "\n[…]"
    end = i + len(span)
    where = f"line {i + 1}" if end == i + 1 else f"lines {i + 1}-{end}"
    return (f"\nHint: a match ignoring whitespace differences exists at {where} "
            "(not applied). The file's exact text there is:\n"
            f"{snippet}\nRe-issue the edit with old_string copied exactly "
            "(indentation, tabs vs spaces, trailing spaces).")


class _NewlineMap:
    """Map offsets in the CRLF→LF normalised view back to the raw text."""

    def __init__(self, raw: str):
        self.raw = raw
        self.norm = raw.replace("\r\n", "\n")
        # Normalised offset of the "\n" for every CRLF that was collapsed.
        self._cr_at: list[int] = []
        k, start = 0, 0
        while True:
            i = raw.find("\r\n", start)
            if i < 0:
                break
            self._cr_at.append(i - k)
            k += 1
            start = i + 2

    def to_raw(self, n: int) -> int:
        return n + bisect.bisect_left(self._cr_at, n)


_NEWLINE_RE = re.compile(r"\r\n|\n|\r")


def _region_newline(text: str, start: int, end: int, file_default: str) -> str:
    """Line-break style for a replacement of ``text[start:end]``: the
    region's own dominant style, else the terminator of the line it sits on,
    else the file's dominant style."""
    region = text[start:end]
    if "\n" in region or "\r" in region:
        return dominant_newline(region, file_default)
    m = _NEWLINE_RE.search(text, end)
    return m.group(0) if m else file_default


def replace_in_text(text: str, old_string: str, new_string: str,
                    replace_all: bool = False, *, label: str = "") -> str:
    """Replace ``old_string`` in ``text`` preserving line endings.

    Matching is done on a CRLF-normalised view so an LF old_string matches a
    CRLF file; only the matched region is rewritten, and the replacement's
    line breaks adopt the style of the region it replaces (or the file's
    dominant style).  Untouched lines are preserved byte-for-byte.
    Raises EditError with a model-facing message.
    """
    nm = _NewlineMap(text)
    file_nl = dominant_newline(text)
    old_norm = normalize_newlines(old_string)
    if old_norm.startswith("\ufeff") and not nm.norm.startswith("\ufeff"):
        old_norm = old_norm[1:]   # BOM is never part of the decoded text
    new_norm = normalize_newlines(new_string)
    if old_norm == new_norm:
        raise EditError(f"Error: {label}No changes to make: old_string and "
                        "new_string are exactly the same.")
    positions = _find_all(nm.norm, old_norm)
    if not positions:
        raise EditError(
            f"Error: {label}old_string not found in file. Please ensure EXACT "
            "match, including all exact leading spaces/indentation and "
            "trailing newlines." + _whitespace_hint(nm.norm, old_norm)
        )
    if len(positions) > 1 and not replace_all:
        lines = [_line_no(nm.norm, p) for p in positions]
        raise EditError(
            f"Error: {label}old_string appears {len(positions)} times "
            f"(at lines {_fmt_lines(lines)}). Provide more context to make it "
            "unique, or use replace_all=true."
        )
    if not replace_all:
        positions = positions[:1]
    out: list[str] = []
    cursor = 0
    for pos in positions:
        rs, re_ = nm.to_raw(pos), nm.to_raw(pos + len(old_norm))
        nl = _region_newline(text, rs, re_, file_nl)
        out.append(text[cursor:rs])
        out.append(new_norm if nl == "\n" else new_norm.replace("\n", nl))
        cursor = re_
    out.append(text[cursor:])
    return "".join(out)


def plan_edits(file_path: str, edits: list[dict]) -> FilePlan:
    """Apply ``edits`` (dicts with old_string/new_string/replace_all) in
    sequence, all-or-nothing, returning the resulting FilePlan."""
    p = Path(file_path)
    if not edits:
        raise EditError("Error: edits must be a non-empty list")
    exists = p.exists()
    if exists:
        data, decoded = _load_existing(p)
        text = decoded.text
    else:
        data, decoded, text = None, DecodedText("", "utf-8"), ""
    original = text
    multi = len(edits) > 1
    for i, ed in enumerate(edits, 1):
        if not isinstance(ed, dict):
            raise EditError(f"Error: edit {i} must be an object with old_string/new_string")
        old = ed.get("old_string")
        new = ed.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            raise EditError(f"Error: edit {i} requires string old_string and new_string")
        label = f"edit {i}/{len(edits)}: " if multi else ""
        bad = check_insertable(new, decoded, original) or (
            check_insertable(old, decoded, original) if decoded.is_legacy else None)
        if bad:
            raise EditError(bad.replace("Error: ", f"Error: {label}", 1))
        if old == "":
            # Claude-Code-compatible: empty old_string creates/fills an empty file.
            if text.strip() == "" and i == 1:
                text = new if not text else text + new
                continue
            if not exists and i > 1:
                raise EditError(f"Error: {label}old_string is empty")
            raise EditError(
                f"Error: {label}old_string is empty but the file is not. Use "
                "Write to replace the whole file, or give the exact text to replace."
            )
        if not exists and i == 1:
            raise EditError(f"Error: file not found: {file_path}")
        text = replace_in_text(text, old, new, bool(ed.get("replace_all", False)),
                               label=label)
    if multi and data is not None and text == original:
        raise EditError("Error: the edits produce no change to the file.")
    return FilePlan(p, data, original, text, decoded)


def plan_write(file_path: str, content: str) -> FilePlan:
    """Compute a full-file Write while keeping the original encoding/BOM and
    (for LF-only content over a CRLF file) its line-ending style."""
    p = Path(file_path)
    if not isinstance(content, str):
        raise EditError("Error: content must be a string")
    if not p.exists():
        bad = check_insertable(content, DecodedText("", "utf-8"))
        if bad:
            raise EditError(bad)
        return FilePlan(p, None, "", content, DecodedText("", "utf-8"))
    data, decoded = _load_existing(p)
    note = ""
    if decoded.bom and content.startswith("\ufeff"):
        content = content[1:]
    bad = check_insertable(content, DecodedText("", "utf-8"), decoded.text)
    if bad:
        raise EditError(bad)
    if decoded.is_legacy and not content.isascii():
        # The model is replacing the whole file with Unicode text: write it
        # as UTF-8 and say so, rather than mis-encoding it as Latin-1.
        decoded = DecodedText(decoded.text, "utf-8")
        note = " (file was not UTF-8; rewritten as UTF-8)"
    if ("\r" not in content and "\n" in content
            and dominant_newline(decoded.text) == "\r\n"):
        content = content.replace("\n", "\r\n")
    return FilePlan(p, data, decoded.text, content, decoded, note=note)


# ── Read-before-edit / stale-file guard ─────────────────────────────────

def _require_read(config: Optional[dict]) -> bool:
    if config is None:
        return False
    val = config.get("edit_require_read", True)
    if isinstance(val, str):
        return val.strip().lower() not in ("0", "false", "no", "off")
    return bool(val)


def _is_plan_file(path: Path, config: dict) -> bool:
    try:
        from cheetahclaws import runtime
        plan_file = runtime.get_ctx(config).plan_file
    except Exception:
        return False
    return bool(plan_file) and os.path.realpath(plan_file) == os.path.realpath(path)


def _invalidate_read_cache() -> None:
    """A cached Read result could hide a newer on-disk version; drop it so
    the Read the model is about to make goes to disk."""
    try:
        from cheetahclaws.tool_registry import clear_tool_cache
        clear_tool_cache()
    except Exception:
        pass


def check_fresh(path: Path, config: Optional[dict], data: Optional[bytes] = None,
                *, must_have_read: bool = True) -> None:
    """Raise EditError unless the agent's view of ``path`` is current.

    No-op when ``config`` is None (direct library calls) or when the config
    escape hatch ``edit_require_read`` is false.  ``must_have_read=False``
    only enforces staleness for files that were read (used for deletes).
    """
    if not _require_read(config) or not path.exists():
        return
    if _is_plan_file(path, config):
        return
    status, recorded, current = tracker_for_config(config).check(path, data)
    if status == "ok":
        return
    _invalidate_read_cache()
    if status == "unread":
        if not must_have_read:
            return
        raise EditError(
            f"Error: {path} has not been read in this session, so this change "
            "was not applied." + _refusal_view(path, config, data)
        )
    size_info = ""
    if recorded is not None and current is not None and recorded.size != current.size:
        size_info = f" (size {recorded.size} → {current.size} bytes)"
    raise EditError(
        f"Error: {path} has been modified on disk since you last read it"
        f"{size_info} — by the user, a formatter/linter, or another process — "
        "so this change was not applied." + _refusal_view(path, config, data)
    )


def _refusal_view(path: Path, config: Optional[dict], data: Optional[bytes]) -> str:
    """Tail of a read-before-edit refusal that gets the model unstuck.

    A small file's current contents are attached (numbered, as Read shows
    them) and recorded as seen, so the very next attempt — rebuilt from what
    is shown — goes through without a separate Read round-trip.  Weaker
    models otherwise loop on the refusal.  The refused edit itself is never
    applied.  Larger files get the exact Read call to make instead.
    ``edit_refusal_show_file: false`` keeps the plain instruction.
    """
    hint = (f" Call Read(file_path={str(path)!r}) and redo the change based on "
            "its current contents.")
    cfg = config or {}
    limit = cfg.get("edit_refusal_show_file", True)
    if limit is False or str(limit).strip().lower() in ("0", "false", "no", "off"):
        return hint
    max_chars = 20_000 if limit is True else max(0, int(limit))
    try:
        if data is None:
            data = path.read_bytes()
        if len(data) > max_chars or looks_binary(data):
            return hint
        shown = _read(str(path), max_output_chars=max_chars + 4_000)
        if shown.startswith("Error") or "truncated" in shown[-300:]:
            return hint
    except (OSError, ValueError):
        return hint
    record_file_state(path, config, data)
    return (" Its current contents are below (you have now seen them) — redo "
            "the change against these lines:\n\n" + shown)


def record_file_state(path, config: Optional[dict], data: Optional[bytes] = None) -> None:
    """Record that the agent has seen ``path``'s current contents."""
    try:
        tracker_for_config(config).record(path, data)
    except Exception:
        pass


def _commit_plan(plan: FilePlan, config: Optional[dict]) -> bytes:
    data = plan.new_bytes()
    atomic_write_bytes(plan.path, data)
    record_file_state(plan.path, config, data)
    return data


def _display_diff(plan: FilePlan, name: Optional[str] = None) -> str:
    return generate_unified_diff(
        normalize_newlines(plan.old_text), normalize_newlines(plan.new_text),
        name or plan.path.name,
    )


def _line_count(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


# ── Write ─────────────────────────────────────────────────────────────────

def _write(file_path: str, content: str, *, config: Optional[dict] = None) -> str:
    try:
        plan = plan_write(file_path, content)
        check_fresh(plan.path, config, plan.old_data)
        if not plan.is_new and plan.old_data == plan.new_bytes():
            record_file_state(plan.path, config, plan.old_data)
            return f"No changes in {file_path}"
        _commit_plan(plan, config)
        if plan.is_new:
            return f"Created {file_path} ({_line_count(plan.new_text)} lines)"
        diff = _display_diff(plan)
        if not diff:
            return f"File updated — {file_path}: line endings/encoding changed only{plan.note}"
        return f"File updated — {file_path}{plan.note}:\n\n{maybe_truncate_diff(diff)}"
    except EditError as e:
        return str(e)
    except Exception as e:
        return f"Error: {e}"


# ── Edit / MultiEdit ──────────────────────────────────────────────────────

_EDIT_DIFF_MAX_LINES = 400


def _apply_edits(file_path: str, edits: list[dict], config: Optional[dict],
                 header: str) -> str:
    try:
        plan = plan_edits(file_path, edits)
        check_fresh(plan.path, config, plan.old_data)
        _commit_plan(plan, config)
        if plan.is_new:
            return f"Created {file_path} ({_line_count(plan.new_text)} lines)"
        diff = _display_diff(plan)
        return f"{header.format(name=plan.path.name)}:\n\n{maybe_truncate_diff(diff, _EDIT_DIFF_MAX_LINES)}"
    except EditError as e:
        return str(e)
    except Exception as e:
        return f"Error: {e}"


def _edit(file_path: str, old_string: str, new_string: str,
          replace_all: bool = False, *, config: Optional[dict] = None) -> str:
    if old_string != "" and not Path(file_path).exists():
        return f"Error: file not found: {file_path}"
    return _apply_edits(
        file_path,
        [{"old_string": old_string, "new_string": new_string, "replace_all": replace_all}],
        config, "Changes applied to {name}",
    )


def _multi_edit(file_path: str, edits: list, *, config: Optional[dict] = None) -> str:
    if not isinstance(edits, list):
        return "Error: edits must be a list of {old_string, new_string, replace_all?} objects"
    n = len(edits)
    out = _apply_edits(file_path, edits, config,
                       "Changes applied to {name} (" + f"{n} edit{'s' if n != 1 else ''})")
    if out.startswith("Error:"):
        out += "\nNo edits were applied (MultiEdit is all-or-nothing)."
    return out


# ── Preview (for approval prompts) ───────────────────────────────────────

_PREVIEW_MAX_LINES = 200


def preview_edit(tool_name: str, tool_input: dict, config: Optional[dict] = None) -> str:
    """Return a colorless unified diff of what a file-editing tool *would*
    do, without touching the filesystem.

    Supports Write, Edit, MultiEdit and ApplyPatch.  Returns ``""`` for any
    other tool, and the tool's own ``Error: …`` text if the call would fail
    to apply.  Output is truncated to ``config['edit_preview_max_lines']``
    (default 200) lines.  Read-before-edit is *not* evaluated here.
    """
    cfg = config or {}
    inp = tool_input or {}
    try:
        max_lines = int(cfg.get("edit_preview_max_lines", _PREVIEW_MAX_LINES))
    except (TypeError, ValueError):
        max_lines = _PREVIEW_MAX_LINES
    try:
        if tool_name == "Write":
            plan = plan_write(inp.get("file_path", ""), inp.get("content", ""))
            diff = _display_diff(plan, str(plan.path))
            if not diff and not plan.is_new and plan.old_data != plan.new_bytes():
                diff = f"(line endings/encoding of {plan.path} change only)\n"
        elif tool_name == "Edit":
            plan = plan_edits(inp.get("file_path", ""), [{
                "old_string": inp.get("old_string"),
                "new_string": inp.get("new_string"),
                "replace_all": inp.get("replace_all", False),
            }])
            diff = _display_diff(plan, str(plan.path))
        elif tool_name == "MultiEdit":
            edits = inp.get("edits")
            if not isinstance(edits, list):
                return "Error: edits must be a list"
            plan = plan_edits(inp.get("file_path", ""), edits)
            diff = _display_diff(plan, str(plan.path))
        elif tool_name == "ApplyPatch":
            from cheetahclaws.tools.patch import preview_patch
            diff = preview_patch(inp.get("patch") or inp.get("input") or "", cfg)
        else:
            return ""
    except EditError as e:
        return str(e)
    except Exception as e:
        return f"Error: {e}"
    if not diff:
        return "(no changes)"
    return maybe_truncate_diff(diff, max_lines)


# ── Glob ──────────────────────────────────────────────────────────────────

def _glob(pattern: str, path: str = None, cwd: str = None) -> str:
    base = Path(path) if path else (Path(cwd) if cwd else Path.cwd())
    try:
        matches = sorted(base.glob(pattern))
        if not matches:
            return "No files matched"
        return "\n".join(str(m) for m in matches[:500])
    except Exception as e:
        return f"Error: {e}"
