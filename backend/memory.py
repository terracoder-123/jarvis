"""
JARVIS Long-Term Memory — SQLite-backed persistent store.

Schema:
    memories(
        id          INTEGER PRIMARY KEY,
        content     TEXT NOT NULL,
        category    TEXT,           -- preference | fact | event | note | identity
        importance  INTEGER,        -- 1 (trivia) to 5 (critical)
        created_at  TEXT,
        last_used   TEXT,
        access_count INTEGER DEFAULT 0
    )

The memory layer is intentionally simple — keyword search + LRU-style ranking.
No embeddings yet; that's a Tier 2 upgrade if recall starts to suffer.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Single shared DB file — survives server restarts.
_DB_PATH = Path(os.getenv("JARVIS_MEMORY_DB", str(
    Path(__file__).resolve().parent.parent / "jarvis_memory.db"
)))

_VALID_CATEGORIES = {"preference", "fact", "event", "note", "identity", "skill"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            content       TEXT NOT NULL,
            category      TEXT DEFAULT 'fact',
            importance    INTEGER DEFAULT 3,
            created_at    TEXT NOT NULL,
            last_used     TEXT NOT NULL,
            access_count  INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(importance DESC);
        CREATE INDEX IF NOT EXISTS idx_mem_created ON memories(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category);

        CREATE TABLE IF NOT EXISTS conversations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT,
            role        TEXT,
            content     TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, created_at);
        """)


_ensure_schema()


# ── Public API ────────────────────────────────────────────────────────────────

def remember(
    content: str,
    category: str = "fact",
    importance: int = 3,
) -> dict[str, Any]:
    """Store a new memory. Deduplicates by exact content match (case-insensitive)."""
    content = (content or "").strip()
    if not content:
        return {"error": "empty memory content"}
    if category not in _VALID_CATEGORIES:
        category = "fact"
    importance = max(1, min(5, int(importance)))
    now = datetime.utcnow().isoformat(timespec="seconds")

    with _connect() as conn:
        # dedupe: case-insensitive exact match → bump importance + access_count instead.
        existing = conn.execute(
            "SELECT id, importance, access_count FROM memories WHERE LOWER(content)=LOWER(?)",
            (content,),
        ).fetchone()
        if existing:
            new_imp = max(existing["importance"], importance)
            conn.execute(
                "UPDATE memories SET importance=?, access_count=access_count+1, last_used=? WHERE id=?",
                (new_imp, now, existing["id"]),
            )
            return {"updated": True, "id": existing["id"], "content": content}

        cur = conn.execute(
            "INSERT INTO memories (content, category, importance, created_at, last_used) "
            "VALUES (?,?,?,?,?)",
            (content, category, importance, now, now),
        )
        return {
            "stored": True,
            "id": cur.lastrowid,
            "content": content,
            "category": category,
            "importance": importance,
        }


def recall(query: str = "", limit: int = 8) -> dict[str, Any]:
    """Search memories by keyword. Empty query → most-important + recent."""
    query = (query or "").strip()
    now = datetime.utcnow().isoformat(timespec="seconds")

    with _connect() as conn:
        if query:
            # tokenise and OR the keywords
            tokens = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
            if not tokens:
                tokens = [query.lower()]
            where = " OR ".join(["LOWER(content) LIKE ?"] * len(tokens))
            params = [f"%{t}%" for t in tokens]
            rows = conn.execute(
                f"""SELECT id, content, category, importance, created_at, access_count
                   FROM memories
                   WHERE {where}
                   ORDER BY importance DESC, access_count DESC, created_at DESC
                   LIMIT ?""",
                (*params, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, content, category, importance, created_at, access_count
                   FROM memories
                   ORDER BY importance DESC, last_used DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        # bump access counters
        if rows:
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE memories SET access_count=access_count+1, last_used=? "
                f"WHERE id IN ({placeholders})",
                (now, *ids),
            )

    return {
        "query": query,
        "count": len(rows),
        "memories": [dict(r) for r in rows],
    }


def forget(query: str) -> dict[str, Any]:
    """Delete memories matching a keyword query. Returns how many were removed."""
    query = (query or "").strip()
    if not query:
        return {"error": "forget needs a query"}

    with _connect() as conn:
        # exact id?
        if query.isdigit():
            cur = conn.execute("DELETE FROM memories WHERE id=?", (int(query),))
            return {"removed": cur.rowcount, "by": "id"}

        cur = conn.execute(
            "DELETE FROM memories WHERE LOWER(content) LIKE ?",
            (f"%{query.lower()}%",),
        )
        return {"removed": cur.rowcount, "by": "content match", "query": query}


def list_all(limit: int = 50) -> dict[str, Any]:
    """Return everything JARVIS knows about the user."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, content, category, importance, created_at, access_count
               FROM memories
               ORDER BY importance DESC, last_used DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return {
        "count": len(rows),
        "memories": [dict(r) for r in rows],
    }


def stats() -> dict[str, Any]:
    """Memory diagnostic — count by category, oldest, newest."""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
        by_cat = {
            r["category"]: r["c"]
            for r in conn.execute(
                "SELECT category, COUNT(*) c FROM memories GROUP BY category"
            ).fetchall()
        }
        oldest = conn.execute(
            "SELECT content, created_at FROM memories ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        newest = conn.execute(
            "SELECT content, created_at FROM memories ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return {
        "total": total,
        "by_category": by_cat,
        "oldest": dict(oldest) if oldest else None,
        "newest": dict(newest) if newest else None,
    }


def top_memories_for_prompt(limit: int = 12) -> list[str]:
    """Return memories formatted for injection into the system prompt.

    Strategy: highest importance first, then most-recently-used. Keeps
    JARVIS feeling continuous without bloating the context window.
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT content, category, importance FROM memories
               ORDER BY importance DESC, last_used DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [r["content"] for r in rows]


def log_turn(session_id: str, role: str, content: str) -> None:
    """Persist a turn for later searching ('what did we discuss last week')."""
    if not content:
        return
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO conversations (session_id, role, content, created_at) "
                "VALUES (?,?,?,?)",
                (session_id, role, content[:4000], now),
            )
    except Exception:
        # Never let logging break the main flow.
        pass


def search_conversations(query: str, limit: int = 6) -> dict[str, Any]:
    """Keyword search across past conversation turns."""
    if not query.strip():
        return {"matches": []}
    with _connect() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at FROM conversations
               WHERE LOWER(content) LIKE ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (f"%{query.lower().strip()}%", limit),
        ).fetchall()
    return {"query": query, "matches": [dict(r) for r in rows]}
