"""A conversation, not a series of interrogations.

2026-09-04, Founder-directed: "I want to be able to talk to the app like I'm talking to you or
I'm talking to chat GPT where it's an actual conversation. Otherwise, if it's just gonna read
basic data for me, what is the whole point of it?"

Two separate faults produced what he objected to, and only one of them was the tone.

  1. THE INSTRUCTION ASKED FOR A REPORT. It said "be concise, practical, and clear" and handed
     over the whole context as JSON, which produced headings, bullet lists and a recital of
     every available number. Concise was never the problem -- reading like a report rather than
     a reply was.

  2. THERE WAS NO MEMORY, and this was the larger half. Every question arrived completely
     alone: just the question and a data snapshot, with none of the previous turns. So "what
     about crypto?" had nothing to say what "what about" referred to, and every question had to
     be self-contained. That is the actual difference between this and a conversation.

These tests pin both. They assert the shape of the prompt rather than the model's output,
because what the model writes is not deterministic -- but what it is ASKED for is, and that is
the part that was wrong.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ai_trader.ai import OpenAIReadOnlyExplainer
from ai_trader.conversations import initialize_conversation_schema, record_turn


def _captured_prompt(question="am I up today", context=None, history=None):
    """The prompt the explainer would send, without contacting OpenAI."""
    explainer = OpenAIReadOnlyExplainer("sk-test", "gpt-4.1", timeout_seconds=5)
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        raise RuntimeError("stop here -- the prompt is what matters")

    with mock.patch("ai_trader.ai.urlopen", _fake_urlopen):
        try:
            explainer.answer(question, context or {"balances": {}}, history=history)
        except Exception:  # noqa: BLE001 - expected; the fake always raises
            pass
    return json.loads(captured["body"]["input"])


# --------------------------------------------------------------------------
# 1. It is asked for a conversation
# --------------------------------------------------------------------------
def test_it_is_told_to_answer_the_question_first():
    instruction = _captured_prompt()["instruction"].lower()
    assert "first sentence" in instruction


def test_it_is_told_not_to_produce_bullet_lists():
    """What the Founder actually saw: headings, bullets and a recital of numbers."""
    instruction = _captured_prompt()["instruction"].lower()
    assert "bullet" in instruction
    assert "prose" in instruction


def test_it_is_told_not_to_open_with_a_disclaimer():
    """Every answer began "I can answer from stored AI Trader evidence, but I am read-only" --
    a preamble nobody asked for, on a question about whether he was up today."""
    instruction = _captured_prompt()["instruction"].lower()
    assert "never open with what you are" in instruction


def test_the_read_only_rule_survives_the_rewrite():
    """The tone changed; the truthfulness rules did not. This is the one that keeps a chatty
    answer from claiming it placed a trade."""
    instruction = _captured_prompt()["instruction"].lower()
    assert "never place trades" in instruction
    assert "claim that you performed any action" in instruction


def test_the_currency_rule_survives_the_rewrite():
    """Kraken is pounds, Alpaca is dollars, and they must never be added together. A friendly
    answer that totals two currencies is worse than a stiff one that does not."""
    instruction = _captured_prompt()["instruction"]
    assert "Kraken is GBP" in instruction and "Alpaca is USD" in instruction


def test_it_is_allowed_to_be_short():
    """Padding a one-line answer is its own kind of report-writing."""
    instruction = _captured_prompt()["instruction"].lower()
    assert "one-line answer" in instruction


# --------------------------------------------------------------------------
# 2. It remembers what was already said
# --------------------------------------------------------------------------
def test_the_previous_turns_travel_with_the_question():
    history = [
        {"who": "founder", "said": "am I up today"},
        {"who": "you", "said": "Kraken is up 79.68 pounds."},
    ]
    prompt = _captured_prompt(question="what about crypto?", history=history)
    assert prompt["conversation_so_far"] == history


def test_the_model_is_told_how_to_use_the_history():
    """Carrying the turns is not enough -- it has to be told that "why?" refers to the last
    answer rather than being an unanswerable question."""
    instruction = _captured_prompt(history=[{"who": "founder", "said": "hi"}])["instruction"].lower()
    assert "conversation_so_far" in instruction
    assert "resolve" in instruction
    assert "why?" in instruction


def test_a_first_question_carries_no_history_and_no_extra_instruction():
    """The very first question of a conversation must not be told to resolve references
    against turns that do not exist."""
    prompt = _captured_prompt(history=[])
    assert prompt["conversation_so_far"] == []
    assert "conversation_so_far is what the two of you" not in prompt["instruction"]


def test_an_ambiguous_follow_up_is_answered_rather_than_bounced_back():
    """Being asked to rephrase is exactly what makes something feel like a form, not a chat."""
    instruction = _captured_prompt(history=[{"who": "founder", "said": "hi"}])["instruction"].lower()
    assert "rather than asking him to rephrase" in instruction


# --------------------------------------------------------------------------
# 3. The history stays small
# --------------------------------------------------------------------------
def test_the_history_is_bounded_and_trimmed():
    from ai_trader.api import _ASK_HISTORY_CHARS, _ASK_HISTORY_TURNS, _ask_conversation_history

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "chat.db"
        initialize_conversation_schema(db)
        for n in range(30):
            record_turn(db, conversation_id="c1", role="founder", text=f"question {n} " + "x" * 2000)
        history = _ask_conversation_history(db, {})

    assert len(history) <= _ASK_HISTORY_TURNS, "the transcript must not crowd out the evidence"
    for turn in history:
        assert len(turn["said"]) <= _ASK_HISTORY_CHARS + 3


def test_losing_the_history_never_costs_the_answer():
    """A conversation without its history is slightly worse. No answer at all is much worse."""
    from ai_trader.api import _ask_conversation_history

    with tempfile.TemporaryDirectory() as tmp:
        assert _ask_conversation_history(Path(tmp), {}) == []


def test_the_two_speakers_are_distinguishable_in_the_history():
    """"you" and "founder" rather than raw role names, so the model reads it as a dialogue."""
    from ai_trader.api import _ask_conversation_history

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "chat.db"
        initialize_conversation_schema(db)
        record_turn(db, conversation_id="c1", role="founder", text="am I up")
        record_turn(db, conversation_id="c1", role="assistant", text="yes, by 79.68 pounds")
        history = _ask_conversation_history(db, {})

    assert [t["who"] for t in history] == ["founder", "you"]
