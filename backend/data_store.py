"""
JARVIS Data Store — per-session uploaded file registry.

Files are stored in a temp directory keyed by Socket.IO session ID.
The analytics tools read from here by filename.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# sid -> {filename -> absolute_path}
_session_files: dict[str, dict[str, str]] = {}

_BASE = Path(tempfile.gettempdir()) / "jarvis_uploads"
_BASE.mkdir(parents=True, exist_ok=True)


def save_file(sid: str, filename: str, data: bytes) -> str:
    """Write raw bytes to a temp file. Returns the absolute path."""
    safe_name = Path(filename).name  # strip any directory traversal
    dest = _BASE / sid / safe_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    if sid not in _session_files:
        _session_files[sid] = {}
    _session_files[sid][safe_name] = str(dest)
    return str(dest)


def _scan_disk(sid: str) -> dict[str, str]:
    """Scan the on-disk session folder. Used by the MCP server (different
    process) where the in-memory dict is empty."""
    out: dict[str, str] = {}
    if not sid:
        # No SID? Look for any session folder with files (last-write-wins).
        if _BASE.exists():
            candidates = sorted(
                [p for p in _BASE.iterdir() if p.is_dir()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for cand in candidates:
                files = sorted(cand.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                for f in files:
                    if f.is_file():
                        out[f.name] = str(f)
                if out:
                    return out
        return out
    session_dir = _BASE / sid
    if not session_dir.exists():
        return out
    for f in sorted(session_dir.iterdir(), key=lambda p: p.stat().st_mtime):
        if f.is_file():
            out[f.name] = str(f)
    return out


def list_files(sid: str) -> list[str]:
    """Return filenames uploaded by this session (memory + disk fallback)."""
    mem = _session_files.get(sid, {})
    disk = _scan_disk(sid)
    # disk is the source of truth across processes
    merged = {**mem, **disk}
    return list(merged.keys())


def get_path(sid: str, filename: str) -> str | None:
    """Resolve a filename to its absolute path, or None if unknown."""
    p = _session_files.get(sid, {}).get(filename)
    if p:
        return p
    return _scan_disk(sid).get(filename)


def get_any_path(sid: str) -> tuple[str, str] | None:
    """Return (filename, path) for the most recently uploaded file."""
    files = _session_files.get(sid, {}) or _scan_disk(sid)
    if not files:
        return None
    name = list(files.keys())[-1]
    return name, files[name]


def clear_session(sid: str) -> None:
    """Remove all files for a disconnected session."""
    import shutil
    session_dir = _BASE / sid
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
    _session_files.pop(sid, None)
