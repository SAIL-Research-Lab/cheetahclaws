"""tools/patch.py — ApplyPatch: Codex-style multi-file patches, applied atomically.

Accepted format (the one OpenAI Codex models are trained on)::

    *** Begin Patch
    *** Add File: path/to/new.py
    +line one
    +line two
    *** Delete File: path/to/old.py
    *** Update File: path/to/file.py
    *** Move to: path/to/renamed.py        (optional)
    @@ def some_function():                (optional anchor line)
     context line
    -removed line
    +added line
    *** End of File                        (optional: hunk is at EOF)
    *** End Patch

Guarantees:
  * all-or-nothing: every hunk of every file is located and the new contents
    computed in memory first; if anything fails, no file is touched.  Writes
    are staged as fsynced temp files and renamed into place; a failure while
    renaming rolls back the files already replaced.
  * context matching is exact first, then tolerant to trailing whitespace,
    then to leading/trailing whitespace, then to Unicode punctuation look-
    alikes.  An ambiguous match (several equally good locations) is an error
    rather than a guess — add an ``@@`` anchor line to disambiguate.
  * encoding/BOM, line-ending style and missing-final-newline are preserved
    as in Edit; read-before-edit applies to updated files.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from cheetahclaws.tools.file_state import (
    DecodedText, commit_temp, dominant_newline, prepare_temp, tracker_for_config,
    check_insertable,
)
from cheetahclaws.tools.fs import (
    EditError, FilePlan, _load_existing, check_fresh, generate_unified_diff,
    maybe_truncate_diff, normalize_newlines, record_file_state,
)


# ── Parsing ───────────────────────────────────────────────────────────────

BEGIN = "*** Begin Patch"
END = "*** End Patch"
ADD = "*** Add File: "
DELETE = "*** Delete File: "
UPDATE = "*** Update File: "
MOVE = "*** Move to: "
EOF_MARK = "*** End of File"


@dataclass
class Hunk:
    anchor: Optional[str] = None
    # (" ", text) context, ("-", text) removed, ("+", text) added — in order
    ops: list[tuple[str, str]] = field(default_factory=list)
    eof: bool = False
    line_no: int = 0            # line in the patch where the hunk starts

    @property
    def old(self) -> list[str]:
        return [t for k, t in self.ops if k != "+"]

    @property
    def new(self) -> list[str]:
        return [t for k, t in self.ops if k != "-"]


@dataclass
class FileOp:
    kind: str                   # "add" | "delete" | "update"
    path: str
    move_to: Optional[str] = None
    add_lines: list[str] = field(default_factory=list)
    hunks: list[Hunk] = field(default_factory=list)


class PatchError(EditError):
    pass


def _is_header(line: str) -> bool:
    return line.startswith((ADD, DELETE, UPDATE)) or line.strip() == END


def parse_patch(patch: str) -> list[FileOp]:
    """Parse patch text into FileOps.  Raises PatchError."""
    if not isinstance(patch, str) or not patch.strip():
        raise PatchError("Error: patch is empty")
    lines = patch.replace("\r\n", "\n").split("\n")
    # Be lenient about wrappers such as ``apply_patch <<'EOF'`` / ``EOF``.
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == BEGIN)
    except StopIteration:
        raise PatchError(f"Error: patch must start with '{BEGIN}'") from None
    try:
        end = max(i for i, l in enumerate(lines) if l.strip() == END)
    except ValueError:
        raise PatchError(f"Error: patch must end with '{END}'") from None
    if end <= start:
        raise PatchError(f"Error: '{END}' appears before '{BEGIN}'")

    ops: list[FileOp] = []
    i = start + 1
    while i < end:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith(ADD):
            op = FileOp("add", line[len(ADD):].strip())
            i += 1
            while i < end and not _is_header(lines[i]):
                l = lines[i]
                if l.startswith("+"):
                    op.add_lines.append(l[1:])
                elif l == "" and (i + 1 >= end or _is_header(lines[i + 1])):
                    pass   # tolerate a blank separator line before the next header
                else:
                    raise PatchError(
                        f"Error: patch line {i + 1}: lines of '{ADD}{op.path}' "
                        f"must start with '+', got: {l[:80]!r}")
                i += 1
            ops.append(op)
        elif line.startswith(DELETE):
            ops.append(FileOp("delete", line[len(DELETE):].strip()))
            i += 1
        elif line.startswith(UPDATE):
            op = FileOp("update", line[len(UPDATE):].strip())
            i += 1
            if i < end and lines[i].startswith(MOVE):
                op.move_to = lines[i][len(MOVE):].strip()
                i += 1
            cur: Optional[Hunk] = None
            while i < end and not _is_header(lines[i]):
                l = lines[i]
                if l.startswith("@@"):
                    if cur is not None and (cur.ops or cur.anchor is not None):
                        op.hunks.append(cur)
                    anchor = l[2:].strip()
                    # "@@ -1,3 +1,4 @@" style (unified diff) carries no anchor
                    if re.fullmatch(r"-\d+(,\d+)? \+\d+(,\d+)? @@.*", anchor):
                        tail = anchor.split("@@", 1)[1].strip()
                        anchor = tail
                    cur = Hunk(anchor=anchor or None, line_no=i + 1)
                elif l.strip() == EOF_MARK:
                    if cur is None:
                        raise PatchError(f"Error: patch line {i + 1}: '{EOF_MARK}' outside a hunk")
                    cur.eof = True
                else:
                    if cur is None:
                        cur = Hunk(line_no=i + 1)
                    if l.startswith(" ") or l == "":
                        cur.ops.append((" ", l[1:]))
                    elif l.startswith("-"):
                        cur.ops.append(("-", l[1:]))
                    elif l.startswith("+"):
                        cur.ops.append(("+", l[1:]))
                    else:
                        raise PatchError(
                            f"Error: patch line {i + 1}: hunk lines must start with "
                            f"' ', '-' or '+', got: {l[:80]!r}")
                i += 1
            if cur is not None and cur.ops:
                op.hunks.append(cur)
            if not op.hunks and not op.move_to:
                raise PatchError(f"Error: '{UPDATE}{op.path}' has no hunks")
            ops.append(op)
        else:
            raise PatchError(
                f"Error: patch line {i + 1}: expected '{ADD}', '{DELETE}' or "
                f"'{UPDATE}' header, got: {line[:80]!r}")
    if not ops:
        raise PatchError("Error: patch contains no file operations")
    for op in ops:
        if not op.path:
            raise PatchError("Error: a file operation is missing its path")
    return ops


# ── Path handling ────────────────────────────────────────────────────────

def _base_dir(config: Optional[dict]) -> Path:
    base = (config or {}).get("_worktree_cwd")
    return Path(base) if base else Path.cwd()


def resolve_path(path: str, config: Optional[dict]) -> Path:
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = _base_dir(config) / p
    return Path(os.path.normpath(str(p)))


def patch_paths(patch: str, config: Optional[dict] = None) -> list[str]:
    """Every absolute path a patch would create, modify, delete or move to.

    Returns [] if the patch does not parse (the tool itself will report why).
    Used by the permission layer and checkpoint hooks.
    """
    try:
        ops = parse_patch(patch)
    except PatchError:
        return []
    out: list[str] = []
    for op in ops:
        for raw in (op.path, op.move_to):
            if raw:
                s = str(resolve_path(raw, config))
                if s not in out:
                    out.append(s)
    return out


def describe_patch(patch: str, config: Optional[dict] = None) -> str:
    """One-line summary like 'M a.py, A b.py, D c.py' for permission prompts."""
    try:
        ops = parse_patch(patch)
    except PatchError:
        return "(unparseable patch)"
    parts = []
    for op in ops:
        tag = {"add": "A", "delete": "D", "update": "M"}[op.kind]
        if op.move_to:
            parts.append(f"R {op.path} → {op.move_to}")
        else:
            parts.append(f"{tag} {op.path}")
    return ", ".join(parts)


# ── Matching ─────────────────────────────────────────────────────────────

_PUNCT = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2015": "-", "\u2212": "-", "\u2018": "'", "\u2019": "'", "\u201a": "'",
    "\u201b": "'", "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2009": " ", "\u202f": " ",
})

_LEVELS = (
    ("exact", lambda s: s),
    ("ignoring trailing whitespace", lambda s: s.rstrip()),
    ("ignoring leading/trailing whitespace", lambda s: s.strip()),
    ("ignoring whitespace and Unicode punctuation", lambda s: s.strip().translate(_PUNCT)),
)


def _seek(lines: list[str], pattern: list[str], start: int, eof: bool
          ) -> tuple[list[int], str]:
    """Return (match indices at the first fuzz level that matches, level)."""
    n = len(pattern)
    if n == 0:
        return [], ""
    if n > len(lines):
        return [], ""
    for name, norm in _LEVELS:
        pat = [norm(p) for p in pattern]
        normed = [norm(l) for l in lines]
        if eof:
            j = len(lines) - n
            if j >= start and normed[j:j + n] == pat:
                return [j], name
        hits = [j for j in range(start, len(lines) - n + 1) if normed[j:j + n] == pat]
        if hits:
            return hits, name
    return [], ""


_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r|$)")


def _split_lines(text: str) -> tuple[list[str], list[str]]:
    """Split into (contents, endings); the final line may have ending ''."""
    contents, endings = [], []
    for m in _LINE_RE.finditer(text):
        chunk = m.group(0)
        if chunk == "":
            break
        if chunk.endswith("\r\n"):
            contents.append(chunk[:-2]); endings.append("\r\n")
        elif chunk.endswith(("\n", "\r")):
            contents.append(chunk[:-1]); endings.append(chunk[-1])
        else:
            contents.append(chunk); endings.append("")
    return contents, endings


def _apply_hunks(path_label: str, text: str, hunks: list[Hunk]) -> str:
    contents, endings = _split_lines(text)
    file_nl = dominant_newline(text)
    cursor = 0
    repls: list[tuple[int, int, list[tuple[str, str]]]] = []
    for h_i, h in enumerate(hunks, 1):
        where = f"{path_label} hunk {h_i} (patch line {h.line_no})"
        if h.anchor is not None:
            hits, _ = _seek(contents, [h.anchor], cursor, False)
            if not hits:
                raise PatchError(f"Error: {where}: anchor line not found: {h.anchor!r}")
            cursor = hits[0] + 1
        ops = list(h.ops)
        old = [t for k, t in ops if k != "+"]
        if not old:
            # Pure insertion: right after the anchor, else at end of file.
            at = cursor if h.anchor is not None else len(contents)
            repls.append((at, 0, ops))
            continue
        hits, level = _seek(contents, old, cursor, h.eof)
        if not hits and ops[-1] == (" ", ""):
            # Trailing blank context often stands for the file's final newline.
            ops = ops[:-1]
            old = [t for k, t in ops if k != "+"]
            hits, level = _seek(contents, old, cursor, h.eof) if old else ([], "")
        if not hits:
            preview = "\n".join(old[:8]) + ("\n…" if len(old) > 8 else "")
            raise PatchError(
                f"Error: {where}: could not find the expected lines"
                f"{' after line ' + str(cursor) if cursor else ''}:\n{preview}\n"
                "Re-read the file and regenerate the hunk with exact context.")
        if len(hits) > 1:
            raise PatchError(
                f"Error: {where}: context matches {len(hits)} locations (lines "
                f"{', '.join(str(x + 1) for x in hits[:10])}; matched {level}). "
                "Add more context lines or an '@@ <unique line>' anchor.")
        repls.append((hits[0], len(old), ops))
        cursor = hits[0] + len(old)

    for start, length, ops in sorted(repls, key=lambda r: r[0], reverse=True):
        old_end = [e for e in endings[start:start + length] if e]
        nl = dominant_newline("".join(old_end), file_nl) if old_end else file_nl
        out_c: list[str] = []
        out_e: list[Optional[str]] = []
        oi = start
        for kind, text in ops:
            if kind == " ":
                # Context keeps the file's exact bytes (the patch's copy may
                # differ in whitespace after fuzzy matching).
                out_c.append(contents[oi]); out_e.append(endings[oi]); oi += 1
            elif kind == "-":
                oi += 1
            else:
                out_c.append(text); out_e.append(None)
        if length and out_e and out_e[-1] is None:
            # The region's last line was replaced: inherit its terminator
            # (keeps a missing final newline missing).
            out_e[-1] = endings[start + length - 1]
        if length == 0 and start > 0 and start == len(contents) and endings[start - 1] == "":
            endings[start - 1] = nl   # appending after an unterminated last line
        resolved = [e if e is not None else nl for e in out_e]
        for i in range(len(resolved) - 1):
            if resolved[i] == "":
                resolved[i] = nl      # a line that is no longer last needs a break
        if length and resolved and endings[start + length - 1] == "":
            resolved[-1] = ""         # region ended the file without a newline
        contents[start:start + length] = out_c
        endings[start:start + length] = resolved
    return "".join(c + e for c, e in zip(contents, endings))


# ── Planning / committing ────────────────────────────────────────────────

def plan_patch(patch: str, config: Optional[dict] = None,
               *, check_state: bool = False) -> list[FilePlan]:
    """Compute every file change in ``patch`` without writing anything."""
    ops = parse_patch(patch)
    plans: list[FilePlan] = []
    seen: set[str] = set()

    def _claim(p: Path) -> None:
        key = os.path.realpath(p)
        if key in seen:
            raise PatchError(f"Error: {p} appears in more than one file operation")
        seen.add(key)

    for op in ops:
        p = resolve_path(op.path, config)
        _claim(p)
        if op.kind == "add":
            if p.exists():
                raise PatchError(
                    f"Error: cannot Add File {op.path}: it already exists. Use "
                    f"'{UPDATE}{op.path}' (or Delete File then Add File).")
            body = "\n".join(op.add_lines) + ("\n" if op.add_lines else "")
            bad = check_insertable(body, DecodedText("", "utf-8"))
            if bad:
                raise PatchError(bad)
            plans.append(FilePlan(p, None, "", body, DecodedText("", "utf-8")))
        elif op.kind == "delete":
            if not p.exists():
                raise PatchError(f"Error: cannot Delete File {op.path}: file not found")
            if p.is_dir():
                raise PatchError(f"Error: cannot Delete File {op.path}: is a directory")
            data = p.read_bytes()
            try:
                _, decoded = _load_existing(p)
                old_text = decoded.text
            except EditError:
                decoded, old_text = DecodedText("", "utf-8"), "(binary file)\n"
            if check_state:
                check_fresh(p, config, data, must_have_read=False)
            plans.append(FilePlan(p, data, old_text, "", decoded, delete=True))
        else:
            if not p.exists():
                raise PatchError(f"Error: cannot Update File {op.path}: file not found")
            data, decoded = _load_existing(p)
            if check_state:
                check_fresh(p, config, data)
            for h in op.hunks:
                bad = check_insertable("\n".join(h.new), decoded, decoded.text) or (
                    check_insertable("\n".join(h.old), decoded, decoded.text)
                    if decoded.is_legacy else None)
                if bad:
                    raise PatchError(bad.replace("Error: ", f"Error: {op.path}: ", 1))
            new_text = _apply_hunks(op.path, decoded.text, op.hunks) if op.hunks else decoded.text
            if op.move_to:
                dest = resolve_path(op.move_to, config)
                if os.path.realpath(dest) != os.path.realpath(p):
                    _claim(dest)
                    if dest.exists():
                        raise PatchError(f"Error: cannot Move to {op.move_to}: it already exists")
                    plans.append(FilePlan(dest, None, decoded.text, new_text, decoded, move_from=p))
                    plans.append(FilePlan(p, data, decoded.text, "", decoded, delete=True,
                                          note="moved"))
                    continue
            plans.append(FilePlan(p, data, decoded.text, new_text, decoded))
    return plans


def _rollback(done: list[FilePlan]) -> None:
    """Best-effort undo of already-applied plans (newest first)."""
    from cheetahclaws.tools.file_state import atomic_write_bytes
    for plan in reversed(done):
        try:
            if plan.delete or plan.old_data is not None:
                atomic_write_bytes(plan.path, plan.old_data or b"")
            else:
                plan.path.unlink(missing_ok=True)   # created by this patch
        except Exception:
            pass


def commit_plans(plans: list[FilePlan], config: Optional[dict]) -> None:
    """Stage every write as a temp file, then rename all, then delete.
    Rolls back on failure so the tree is left as it was."""
    staged: list[tuple[FilePlan, Path, Path]] = []
    try:
        for plan in plans:
            if plan.delete:
                continue
            tmp, target = prepare_temp(plan.path, plan.new_bytes())
            staged.append((plan, tmp, target))
    except Exception as e:
        for _, tmp, _t in staged:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise PatchError(f"Error: could not stage changes ({e}); no files were modified") from e

    done: list[FilePlan] = []
    remaining = list(staged)
    try:
        while remaining:
            plan, tmp, target = remaining[0]
            commit_temp(tmp, target)
            remaining.pop(0)
            done.append(plan)
        for plan in plans:
            if plan.delete:
                plan.path.unlink()
                done.append(plan)
    except Exception as e:
        for _, tmp, _t in remaining:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        _rollback(done)
        raise PatchError(f"Error: applying patch failed ({e}); changes were rolled back") from e

    tracker = tracker_for_config(config)
    for plan in plans:
        if plan.delete:
            tracker.forget(plan.path)
        else:
            record_file_state(plan.path, config)


def _plan_diff(plan: FilePlan, base: Path) -> str:
    def rel(p: Path) -> str:
        try:
            return os.path.relpath(p, base)
        except ValueError:
            return str(p)
    old = normalize_newlines(plan.old_text)
    new = normalize_newlines(plan.new_text)
    if plan.delete and plan.note == "moved":
        return ""
    if plan.move_from is not None:
        head = f"rename {rel(plan.move_from)} → {rel(plan.path)}\n"
        return head + generate_unified_diff(old, new, rel(plan.path))
    if plan.delete:
        return f"deleted {rel(plan.path)}\n" + generate_unified_diff(old, "", rel(plan.path))
    return generate_unified_diff(old, new, rel(plan.path))


def preview_patch(patch: str, config: Optional[dict] = None) -> str:
    plans = plan_patch(patch, config)
    base = _base_dir(config)
    return "".join(_plan_diff(p, base) for p in plans)


_RESULT_DIFF_MAX_LINES = 400


def apply_patch(patch: str, config: Optional[dict] = None) -> str:
    """Tool entry point.  Returns a model-facing result string."""
    try:
        plans = plan_patch(patch, config, check_state=True)
        commit_plans(plans, config)
    except EditError as e:
        msg = str(e)
        if "rolled back" not in msg and "no files were modified" not in msg:
            msg += "\nNo files were modified (ApplyPatch is all-or-nothing)."
        return msg
    except Exception as e:
        return f"Error: {e}\nNo files were modified."
    try:
        from cheetahclaws.tool_registry import clear_tool_cache
        clear_tool_cache()
    except Exception:
        pass
    base = _base_dir(config)
    summary = []
    for plan in plans:
        if plan.move_from is not None:
            summary.append(f"R {plan.move_from} → {plan.path}")
        elif plan.delete:
            if plan.note != "moved":
                summary.append(f"D {plan.path}")
        elif plan.is_new:
            summary.append(f"A {plan.path}")
        else:
            summary.append(f"M {plan.path}")
    diff = "".join(_plan_diff(p, base) for p in plans)
    out = "Success. Updated the following files:\n" + "\n".join(summary)
    if diff:
        out += "\n\n" + maybe_truncate_diff(diff, _RESULT_DIFF_MAX_LINES)
    return out
