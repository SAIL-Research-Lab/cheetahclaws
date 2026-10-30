"""tools/file_state.py — encoding-safe file I/O and per-session file-state tracking.

Three building blocks shared by Write / Edit / MultiEdit / ApplyPatch:

* ``decode_file_bytes`` / ``encode_text`` — detect a file's encoding (UTF-8
  with or without BOM, UTF-16/32 with BOM, or a byte-exact Latin-1 fallback
  for legacy 8-bit files) so an edit never silently transcodes a file or
  introduces U+FFFD replacement characters.  Binary files are refused.
* ``atomic_write_bytes`` — temp file in the same directory + fsync +
  ``os.replace``, preserving permission bits (and owner where possible).
* ``FileStateTracker`` — remembers, per session, the (mtime_ns, size, sha256)
  of each file at the agent's last Read/Write/Edit so edits can require a
  prior Read and refuse to clobber a file that changed on disk since.
"""
from __future__ import annotations

import codecs
import hashlib
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── Encoding detection ────────────────────────────────────────────────────

class EncodingError(Exception):
    """Raised when a file cannot be safely decoded/encoded for editing."""


# Order matters: the UTF-32-LE BOM begins with the UTF-16-LE BOM.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# Encoding label used for byte-exact round-tripping of non-UTF-8 8-bit text.
LEGACY_ENCODING = "latin-1"

_BINARY_SNIFF_BYTES = 8192


@dataclass
class DecodedText:
    """A decoded text file plus everything needed to re-encode it faithfully."""
    text: str
    encoding: str          # codec used for the body (without BOM)
    bom: bytes = b""       # BOM to re-emit, if the original had one

    @property
    def is_legacy(self) -> bool:
        """True when the file is not Unicode and was decoded byte-exactly as
        Latin-1.  Only ASCII may be inserted into such files safely."""
        return self.encoding == LEGACY_ENCODING

    def describe(self) -> str:
        if self.is_legacy:
            return "non-UTF-8 8-bit text"
        return self.encoding + (" with BOM" if self.bom else "")


def looks_binary(data: bytes) -> bool:
    """Heuristic: NUL bytes in the first chunk of a non-UTF-16/32 file."""
    return b"\x00" in data[:_BINARY_SNIFF_BYTES]


def decode_file_bytes(data: bytes) -> DecodedText:
    """Decode ``data`` without loss or raise :class:`EncodingError`."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            try:
                return DecodedText(data[len(bom):].decode(enc), enc, bom)
            except UnicodeDecodeError as e:
                raise EncodingError(
                    f"file starts with a {enc} byte-order mark but is not "
                    f"valid {enc} ({e.reason} at byte {e.start + len(bom)})"
                ) from e
    try:
        return DecodedText(data.decode("utf-8"), "utf-8")
    except UnicodeDecodeError:
        pass
    if looks_binary(data):
        raise EncodingError("file appears to be binary (contains NUL bytes)")
    # Latin-1 maps every byte to exactly one code point, so this always
    # round-trips byte-for-byte.  ``encode_text`` keeps it honest by only
    # allowing ASCII to be introduced (see check_insertable).
    return DecodedText(data.decode(LEGACY_ENCODING), LEGACY_ENCODING)


def encode_text(text: str, decoded: DecodedText) -> bytes:
    """Encode ``text`` back using the original file's encoding and BOM."""
    try:
        return decoded.bom + text.encode(decoded.encoding)
    except UnicodeEncodeError as e:
        raise EncodingError(
            f"cannot encode {text[e.start:e.end]!r} as {decoded.describe()}"
        ) from e


def check_insertable(new_text: str, decoded: DecodedText, original: str = "") -> Optional[str]:
    """Return an error message if ``new_text`` cannot be safely written into
    a file with ``decoded``'s encoding, else None."""
    if "\ufffd" in new_text and "\ufffd" not in original:
        return ("Error: the new text contains U+FFFD replacement characters "
                "(\ufffd), which usually means it was copied from a lossy view "
                "of a non-UTF-8 file. Refusing to write them into the file.")
    if decoded.is_legacy and not new_text.isascii():
        return ("Error: this file is not valid UTF-8 (legacy 8-bit encoding "
                "such as Latin-1/GBK/Shift-JIS). Only ASCII text can be "
                "inserted without corrupting it; non-ASCII old_string/new_string "
                "cannot be matched or encoded safely. Edit it with a tool that "
                "knows its encoding (e.g. iconv via Bash) instead.")
    return None


def read_text_file(path: str | os.PathLike) -> tuple[bytes, DecodedText]:
    """Read and decode a file for editing.  Raises EncodingError / OSError."""
    data = Path(path).read_bytes()
    return data, decode_file_bytes(data)


# ── Line endings ──────────────────────────────────────────────────────────

def count_line_endings(text: str) -> tuple[int, int, int]:
    """Return (crlf, lf_only, cr_only) counts."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    return crlf, lf, cr


def dominant_newline(text: str, default: str = "\n") -> str:
    crlf, lf, cr = count_line_endings(text)
    if crlf == lf == cr == 0:
        return default
    best = max((crlf, "\r\n"), (lf, "\n"), (cr, "\r"), key=lambda t: t[0])
    # Ties prefer LF (the most common, and the historical behaviour).
    if best[0] == lf:
        return "\n"
    return best[1]


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def apply_newline_style(text: str, newline: str) -> str:
    """Convert LF/CRLF line breaks in ``text`` to ``newline``."""
    norm = normalize_newlines(text)
    return norm if newline == "\n" else norm.replace("\n", newline)


# ── Atomic writes ─────────────────────────────────────────────────────────

def _fsync_dir(directory: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def prepare_temp(path: str | os.PathLike, data: bytes) -> tuple[Path, Path]:
    """Write ``data`` to a fresh temp file beside ``path`` (fsynced, with the
    target's permission bits).  Returns (temp_path, final_target).

    Symlinks are followed so the link itself survives and its target is
    updated.  New files get the default ``0o666 & ~umask`` mode because the
    kernel applies the umask to ``os.open``'s mode argument.
    """
    target = Path(path)
    if target.is_symlink():
        target = Path(os.path.realpath(target))
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        st = target.stat()
    except FileNotFoundError:
        st = None

    for attempt in range(100):
        tmp = parent / f".{target.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
        try:
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_BINARY", 0), 0o666)
            break
        except FileExistsError:
            continue
    else:  # pragma: no cover - astronomically unlikely
        raise OSError(f"could not create a temporary file in {parent}")

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if st is not None:
            os.chmod(tmp, st.st_mode & 0o7777)
            if hasattr(os, "chown"):
                try:
                    if (st.st_uid, st.st_gid) != (os.getuid(), os.getgid()):
                        os.chown(tmp, st.st_uid, st.st_gid)
                except OSError:
                    pass  # best effort (non-root cannot give files away)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return tmp, target


def commit_temp(tmp: Path, target: Path) -> None:
    os.replace(tmp, target)
    _fsync_dir(target.parent)


def atomic_write_bytes(path: str | os.PathLike, data: bytes) -> None:
    """Atomically replace ``path`` with ``data`` (temp + fsync + rename)."""
    tmp, target = prepare_temp(path, data)
    try:
        commit_temp(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Per-session file-state tracker ────────────────────────────────────────

# Hashing is skipped above this size; mtime+size alone is then the signal.
_HASH_MAX_BYTES = 32 * 1024 * 1024
_MAX_ENTRIES_PER_SESSION = 4096
_MAX_SESSIONS = 256


@dataclass(frozen=True)
class FileStamp:
    mtime_ns: int
    size: int
    sha256: Optional[str]


def _key(path: str | os.PathLike) -> str:
    return os.path.realpath(os.path.abspath(os.fspath(path)))


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stamp_file(path: str | os.PathLike, data: Optional[bytes] = None) -> Optional[FileStamp]:
    """Stat (and hash) a file; None if it does not exist."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    digest = None
    if data is not None:
        digest = hash_bytes(data)
    elif st.st_size <= _HASH_MAX_BYTES:
        try:
            with open(path, "rb") as f:
                digest = hash_bytes(f.read())
        except OSError:
            digest = None
    return FileStamp(st.st_mtime_ns, st.st_size, digest)


class FileStateTracker:
    """LRU map realpath → FileStamp for one session."""

    def __init__(self, max_entries: int = _MAX_ENTRIES_PER_SESSION):
        self._entries: "OrderedDict[str, FileStamp]" = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_entries

    def record(self, path, data: Optional[bytes] = None) -> None:
        stamp = stamp_file(path, data)
        key = _key(path)
        with self._lock:
            if stamp is None:
                self._entries.pop(key, None)
                return
            self._entries[key] = stamp
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def forget(self, path) -> None:
        with self._lock:
            self._entries.pop(_key(path), None)

    def get(self, path) -> Optional[FileStamp]:
        with self._lock:
            return self._entries.get(_key(path))

    def check(self, path, data: Optional[bytes] = None) -> tuple[str, Optional[FileStamp], Optional[FileStamp]]:
        """Classify ``path`` as 'ok', 'unread' or 'stale'.

        Returns (status, recorded_stamp, current_stamp).  A file whose mtime
        changed but whose content hash did not (e.g. ``touch``) is 'ok'.
        """
        recorded = self.get(path)
        if recorded is None:
            return "unread", None, None
        try:
            st = os.stat(path)
        except OSError:
            return "ok", recorded, None   # vanished: nothing to clobber
        if st.st_mtime_ns == recorded.mtime_ns and st.st_size == recorded.size:
            return "ok", recorded, None
        current = stamp_file(path, data)
        if (current is not None and recorded.sha256 is not None
                and current.sha256 == recorded.sha256):
            self.record(path, data)   # refresh mtime so later checks are cheap
            return "ok", recorded, current
        return "stale", recorded, current


_trackers: "OrderedDict[str, FileStateTracker]" = OrderedDict()
_trackers_lock = threading.Lock()


def get_tracker(session_id: Optional[str]) -> FileStateTracker:
    """Return the tracker for ``session_id`` (created on first use)."""
    sid = session_id or "default"
    with _trackers_lock:
        tr = _trackers.get(sid)
        if tr is None:
            tr = FileStateTracker()
            _trackers[sid] = tr
            while len(_trackers) > _MAX_SESSIONS:
                _trackers.popitem(last=False)
        else:
            _trackers.move_to_end(sid)
        return tr


def session_id_from_config(config: Optional[dict]) -> str:
    return str((config or {}).get("_session_id") or "default")


def tracker_for_config(config: Optional[dict]) -> FileStateTracker:
    return get_tracker(session_id_from_config(config))


def drop_session(session_id: str) -> None:
    with _trackers_lock:
        _trackers.pop(session_id or "default", None)


def reset_all_trackers() -> None:
    """Forget every session's file state (tests)."""
    with _trackers_lock:
        _trackers.clear()
