"""Keep what was said, so a conversation can be scrolled back to.

2026-09-03, Founder-directed: "lastly can all the discussions be stored in a table or
somewhere. it is not going to take up a lot of space as it is just text. that way I can scroll
back to previous discussions if I want to."

He is right about the size. A long exchange is a few kilobytes; the app already stores single
rows thirty times larger than that (PRODUCTION_RECOMMENDATION_EVIDENCE averages 30 KB a row).

WHAT THIS DELIBERATELY DOES NOT DO. It does not become another home for anything. The turns are
stored verbatim as text, and nothing reads them back to make a decision -- no confidence score,
no threshold, no evidence. That distinction matters after two days spent removing places where
the same fact lived twice: a transcript is a record of a conversation, not a source of truth
about the account. If a number appears in one of these rows it is a description of what was
said at the time, not something to be believed later.

Kept small on purpose. A rolling cap rather than unbounded growth, because "it is only text" is
exactly how a table quietly becomes the largest one in the database.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect
from .models import utc_now_iso
from .persistence.schema_once import ensure_schema_once

CONVERSATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ASK_CONVERSATION_TURNS (
    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    spoken INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    status TEXT
);

CREATE INDEX IF NOT EXISTS idx_ask_turns_time ON ASK_CONVERSATION_TURNS (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ask_turns_conversation ON ASK_CONVERSATION_TURNS (conversation_id, turn_id);
"""

# Roughly a fortnight of heavy use. Past this the oldest turns are dropped: a transcript is
# worth keeping, but not forever, and an unbounded text table is how egress bills start.
MAX_STORED_TURNS = 2000


def initialize_conversation_schema(db_path: Path) -> None:
    def _init() -> None:
        with closing(connect(db_path)) as conn:
            with conn:
                conn.executescript(CONVERSATION_SCHEMA)

    ensure_schema_once(db_path, "conversations", _init)


def record_turn(
    db_path: Path,
    *,
    conversation_id: str,
    role: str,
    text: str,
    spoken: bool = False,
    model: str | None = None,
    status: str | None = None,
) -> None:
    """Store one side of one exchange. Never raises: losing a transcript must not break Ask."""
    body = str(text or "").strip()
    if not body:
        return
    try:
        initialize_conversation_schema(db_path)
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """INSERT INTO ASK_CONVERSATION_TURNS
                       (created_at, conversation_id, role, text, spoken, model, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (utc_now_iso(), str(conversation_id or "default"), str(role),
                     body, 1 if spoken else 0, model, status),
                )
                _trim(conn)
    except Exception:  # noqa: BLE001 - a transcript is a nicety; answering is not
        return


def _trim(conn: Any) -> None:
    """Keep the newest MAX_STORED_TURNS and drop the rest."""
    try:
        row = conn.execute("SELECT COUNT(*) FROM ASK_CONVERSATION_TURNS").fetchone()
        total = int(row[0] if row else 0)
        if total <= MAX_STORED_TURNS:
            return
        conn.execute(
            """DELETE FROM ASK_CONVERSATION_TURNS WHERE turn_id IN (
                   SELECT turn_id FROM ASK_CONVERSATION_TURNS
                   ORDER BY turn_id ASC LIMIT ?
               )""",
            (total - MAX_STORED_TURNS,),
        )
    except Exception:  # noqa: BLE001
        return


def recent_turns(db_path: Path, *, limit: int = 60) -> list[dict[str, Any]]:
    """The most recent turns, oldest first so the app can render them in order.

    Bounded by design. The app asks for a screenful; nothing needs the whole history at once,
    and returning it would make this the expensive query the rest of this codebase has spent
    the week removing.
    """
    capped = max(1, min(int(limit), 200))
    try:
        initialize_conversation_schema(db_path)
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT turn_id, created_at, conversation_id, role, text, spoken, model, status
                   FROM ASK_CONVERSATION_TURNS ORDER BY turn_id DESC LIMIT ?""",
                (capped,),
            ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    out = [
        {
            "turn_id": row[0], "created_at": row[1], "conversation_id": row[2],
            "role": row[3], "text": row[4], "spoken": bool(row[5]),
            "model": row[6], "status": row[7],
        }
        for row in rows
    ]
    out.reverse()
    return out
