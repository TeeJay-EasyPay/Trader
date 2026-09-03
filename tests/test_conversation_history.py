"""Keep what was said, so a conversation can be scrolled back to.

2026-09-03, Founder-directed: "can all the discussions be stored in a table or somewhere. it is
not going to take up a lot of space as it is just text. that way I can scroll back to previous
discussions if I want to."

He is right about the size -- a long exchange is a few kilobytes, against a
PRODUCTION_RECOMMENDATION_EVIDENCE row averaging 30 KB. But "it is only text" is also exactly
how a table quietly becomes the largest in the database, which is why there is a cap and why
these tests check it holds.

WHAT THIS MUST NEVER BECOME. Another home for a fact. The turns are stored verbatim and nothing
reads them back to make a decision -- no threshold, no score, no evidence. After two days spent
removing places where the same number lived twice, a transcript has to stay a record of what was
said rather than a source of truth about the account.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ai_trader.conversations import (
    MAX_STORED_TURNS,
    initialize_conversation_schema,
    recent_turns,
    record_turn,
)


@pytest.fixture()
def db():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chat.db"
        initialize_conversation_schema(path)
        yield path


def test_both_sides_of_an_exchange_are_kept(db):
    record_turn(db, conversation_id="c1", role="founder", text="am I up today")
    record_turn(db, conversation_id="c1", role="assistant", text="Kraken is up 5.67 today.")
    turns = recent_turns(db)
    assert [t["role"] for t in turns] == ["founder", "assistant"]
    assert turns[1]["text"] == "Kraken is up 5.67 today."


def test_turns_come_back_oldest_first_so_the_conversation_reads_in_order(db):
    for n in range(5):
        record_turn(db, conversation_id="c1", role="founder", text=f"question {n}")
    texts = [t["text"] for t in recent_turns(db)]
    assert texts == [f"question {n}" for n in range(5)]


def test_it_remembers_whether_a_question_was_spoken(db):
    record_turn(db, conversation_id="c1", role="founder", text="spoken one", spoken=True)
    record_turn(db, conversation_id="c1", role="founder", text="typed one", spoken=False)
    turns = recent_turns(db)
    assert turns[0]["spoken"] is True
    assert turns[1]["spoken"] is False


def test_an_empty_turn_is_not_stored(db):
    """A blank bubble is worse than no bubble, and the acknowledgement path can produce one."""
    record_turn(db, conversation_id="c1", role="founder", text="   ")
    record_turn(db, conversation_id="c1", role="founder", text="")
    assert recent_turns(db) == []


def test_the_table_cannot_grow_without_limit(db):
    """"It is only text" is how a table becomes the biggest one in the database."""
    for n in range(MAX_STORED_TURNS + 40):
        record_turn(db, conversation_id="c1", role="founder", text=f"turn {n}")
    all_turns = recent_turns(db, limit=200)
    assert len(all_turns) == 200
    # The OLDEST are the ones dropped -- scrolling back should reach a wall, not a gap.
    assert all_turns[-1]["text"] == f"turn {MAX_STORED_TURNS + 39}"


def test_reading_is_bounded_even_when_asked_for_everything(db):
    """An unbounded read here would be the expensive query this week was spent removing."""
    for n in range(300):
        record_turn(db, conversation_id="c1", role="founder", text=f"turn {n}")
    assert len(recent_turns(db, limit=10_000)) == 200
    assert len(recent_turns(db, limit=0)) == 1


def test_a_storage_failure_never_breaks_the_answer():
    """Losing a transcript is a nuisance; losing the reply is not.

    The unusable path is a DIRECTORY, not a made-up filename. An earlier version of this test
    used "/nonexistent/nowhere/chat.db", which on Windows resolves to a creatable path and was
    duly created -- so the test proved the opposite of what it claimed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        record_turn(Path(tmp), conversation_id="c1", role="founder", text="this cannot be stored")


def test_reading_an_unusable_database_returns_nothing_rather_than_raising():
    with tempfile.TemporaryDirectory() as tmp:
        assert recent_turns(Path(tmp)) == []


def test_the_model_and_status_are_recorded_for_the_answer(db):
    """So a past answer can be read knowing which model produced it and whether it was a real
    answer or an evidence-only fallback -- the distinction that mattered when Ask invented a
    week of inactivity from an empty section."""
    record_turn(db, conversation_id="c1", role="assistant", text="an answer",
                model="gpt-4.1", status="answered")
    turn = recent_turns(db)[0]
    assert turn["model"] == "gpt-4.1"
    assert turn["status"] == "answered"


def test_nothing_in_the_app_reads_these_turns_to_make_a_decision():
    """The rule that keeps a transcript from becoming a second source of truth.

    Asserted against the source rather than behaviour, because the failure would be someone
    later deciding the stored text is a convenient place to look up what the confidence bar was.
    """
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "ai_trader"
    readers = []
    for path in src.rglob("*.py"):
        if path.name in {"conversations.py"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = re.sub(r"#.*$", "", line)
            if "ASK_CONVERSATION_TURNS" in stripped:
                readers.append(f"{path.name}:{number}")
    assert not readers, (
        f"the transcript is a record of what was said, not a source of truth: {readers}"
    )
