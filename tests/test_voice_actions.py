"""What the Founder can make the app DO by speaking, and everything it must refuse to.

2026-08-31, Founder-directed. He asked to interact with the app the way he interacts with me
and chose "speak, plus run safe actions" -- explicitly not full control.

The whole risk of this feature is in one direction. A missed command costs him a repeat. A
hallucinated one spends real API budget and, at the end of a cycle, can transact on a live
Kraken account. So most of these tests assert that something does NOT happen.
"""

from __future__ import annotations

import pytest

from ai_trader.voice_actions import build_actions, detect_action, run_action


@pytest.mark.parametrize(
    "sentence, expected",
    [
        ("run a cycle", "cycle_all"),
        ("start the research cycle", "cycle_all"),
        ("kick off a full cycle", "cycle_all"),
        ("run a crypto cycle", "cycle_crypto"),
        ("start a crypto research scan", "cycle_crypto"),
        # Politeness must not disarm a real instruction -- this is how people actually speak.
        ("can you run a cycle", "cycle_all"),
        ("could you run a crypto cycle", "cycle_crypto"),
        ("please run a cycle", "cycle_all"),
        ("check what we actually hold", "reconcile"),
        ("verify our positions", "reconcile"),
        ("reconcile holdings", "reconcile"),
        ("refresh the prices", "refresh"),
        ("refresh market data", "refresh"),
    ],
)
def test_a_clear_instruction_is_acted_on(sentence, expected):
    assert detect_action(sentence) == expected


@pytest.mark.parametrize(
    "sentence",
    [
        # Questions ABOUT an action, none of which should perform it. Note that most carry no
        # question mark: Whisper frequently returns speech unpunctuated, so the interrogative
        # opener is the load-bearing signal, not the punctuation.
        "why did it not run a cycle",
        "did you run a cycle today",
        "should I run a cycle",
        "what does running a cycle do",
        "how often does the cycle run",
        "when was the last cycle",
        "is the cycle running",
        "was the cycle run this morning",
        "has it run a cycle since lunch",
        # Ordinary questions.
        "am I up or down today",
        "what open positions do I have",
        "why was SOL refused",
    ],
)
def test_a_question_is_answered_never_acted_on(sentence):
    assert detect_action(sentence) is None, f"{sentence!r} must be answered, not performed"


@pytest.mark.parametrize(
    "sentence",
    [
        # Everything with financial authority. None of these has an action, so all fall
        # through to the read-only answer -- the safe direction to fail in.
        "sell my bitcoin",
        "buy some ethereum",
        "close all my positions",
        "change the confidence bar to 0.6",
        "lower the minimum confidence",
        "increase the trade size to 200 pounds",
        "turn off the shariah screen",
        "enable auto trading",
        "disable the fee check",
        "move my allocation to 2000 pounds",
        "approve that trade",
    ],
)
def test_nothing_with_financial_authority_can_be_triggered_by_voice(sentence):
    assert detect_action(sentence) is None, (
        f"{sentence!r} must never be executable by voice -- the Founder chose safe actions "
        "only, and a misheard number on a live Kraken account is a real loss"
    )


def test_empty_or_noise_input_does_nothing():
    """An open mic picks up background speech. Silence must stay silent."""
    for noise in ("", "   ", "um", "...", "hello", "thanks"):
        assert detect_action(noise) is None


class _Service:
    def __init__(self, *, fail: bool = False):
        self.calls: list[str] = []
        self._fail = fail

    def start_cycle_from_voice(self, *, scope="all"):
        self.calls.append(f"cycle:{scope}")
        if self._fail:
            raise RuntimeError("Kraken is unreachable")
        return {"status": "started", "cycle_id": "abc123", "scope": scope}

    def reconcile_open_positions(self, *, broker="kraken"):
        self.calls.append("reconcile")
        return {"status": "ok", "closed": [{"symbol": "BCH"}], "kept": []}

    def refresh_crypto_candle_history(self):
        self.calls.append("refresh")
        return {"status": "ok"}


def test_running_a_cycle_reports_back_in_a_sentence_meant_to_be_heard():
    service = _Service()
    result = run_action(service, "cycle_all")
    assert service.calls == ["cycle:all"]
    assert result["status"] == "action_taken"
    # read_only is stamped by ask_ai_trader, the layer that knows this came from a chat turn;
    # run_action's job is to do the thing and describe it.
    # Spoken, so no ids, no jargon, and it must say what happens next.
    assert "abc123" not in result["answer"]
    assert "cycle" in result["answer"].lower()


def test_a_second_cycle_says_so_rather_than_starting_another():
    class _Busy(_Service):
        def start_cycle_from_voice(self, *, scope="all"):
            self.calls.append("cycle")
            return {"status": "already_running", "cycle_id": "x"}

    result = run_action(_Busy(), "cycle_all")
    assert "already running" in result["answer"].lower()


def test_reconciliation_names_what_it_closed():
    result = run_action(_Service(), "reconcile")
    assert "BCH" in result["answer"]


def test_a_failure_is_spoken_not_swallowed():
    """A voice reply that ends in silence is indistinguishable from a broken app."""
    result = run_action(_Service(fail=True), "cycle_all")
    assert result["status"] == "failed"
    assert result["answer"].strip(), "a failure must still produce something to say"
    assert "unreachable" in result["answer"].lower()


def test_an_unknown_action_key_is_refused_rather_than_guessed():
    result = run_action(_Service(), "sell_everything")
    assert result["status"] == "unknown_action"


def test_every_action_has_an_acknowledgement_written_for_speech():
    for key, action in build_actions(_Service()).items():
        assert action.acknowledgement.strip(), key
        assert action.acknowledgement.endswith((".", "!")), f"{key} should read as a sentence"
