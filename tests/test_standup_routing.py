"""Who gets spoken to in the standup, and what a write-up is allowed to claim.

2026-09-07, Founder-directed: a three-way standup with him, the trading AI and Claude, where
he can direct a question at one of them, the two can talk to each other, and the conclusions
are written up for Claude Code to implement.

Everything here is stubbed. The routing decisions are pure functions precisely so they can be
proven without spending money, and the endpoint is exercised with fake speakers so the ordering
and the budget can be tested without two real model calls per assertion.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.standup import (
    BOTH,
    CLAUDE,
    DEFAULT_EXCHANGE_BUDGET,
    TRADER,
    ACTIONS_INSTRUCTION,
    detect_addressee,
    other_speaker,
    should_reply_to_peer,
    transcript_for,
)


class AddressingTests(unittest.TestCase):
    """"in a three way conversation how would any participant know it is the one being spoken
    to?" -- the Founder, 2026-09-07. This is the answer."""

    def test_a_leading_name_wins_outright(self):
        self.assertEqual(detect_addressee("Claude, why is that slow?"), CLAUDE)
        self.assertEqual(detect_addressee("ChatGPT, what did you see?"), TRADER)

    def test_a_name_mentioned_once_anywhere_routes_there(self):
        self.assertEqual(detect_addressee("what does the trader think about fees"), TRADER)
        self.assertEqual(detect_addressee("can Claude check that in the code"), CLAUDE)

    def test_naming_the_other_participant_does_not_steal_the_question(self):
        """"there may be times I explore a topic with Claude while chatgpt listens." A question
        FOR Claude that happens to mention the trader must still reach Claude."""
        self.assertEqual(
            detect_addressee("Claude, what did the trader mean by that?"), CLAUDE
        )

    def test_an_unaddressed_remark_continues_with_whoever_was_speaking(self):
        """Conversations have continuity. Asking both to answer every aside doubles the noise
        and doubles the bill."""
        self.assertEqual(detect_addressee("why though?", last_ai_speaker=CLAUDE), CLAUDE)
        self.assertEqual(detect_addressee("why though?", last_ai_speaker=TRADER), TRADER)

    def test_with_nobody_yet_speaking_it_opens_to_both(self):
        self.assertEqual(detect_addressee("morning, where are we?"), BOTH)

    def test_a_one_to_one_mode_has_nobody_else_to_route_to(self):
        """"maybe have a way of just chatting with chatgpt or Claude separately as well."
        Naming the absent one must not redirect the question into an empty room."""
        self.assertEqual(detect_addressee("what does Claude think?", mode=TRADER), TRADER)
        self.assertEqual(detect_addressee("ask the trader", mode=CLAUDE), CLAUDE)


class PeerExchangeTests(unittest.TestCase):
    """The budget is the rule that matters most: two agreeable models will ping-pong until
    someone stops them, and every turn is a real bill."""

    def test_the_two_may_answer_each_other_in_a_standup(self):
        self.assertTrue(should_reply_to_peer(mode=BOTH, turns_used=0, peer_said_something=True))

    def test_a_one_to_one_conversation_has_no_peer(self):
        self.assertFalse(should_reply_to_peer(mode=CLAUDE, turns_used=0, peer_said_something=True))
        self.assertFalse(should_reply_to_peer(mode=TRADER, turns_used=0, peer_said_something=True))

    def test_silence_is_not_answered(self):
        self.assertFalse(should_reply_to_peer(mode=BOTH, turns_used=0, peer_said_something=False))

    def test_the_exchange_is_bounded_and_the_floor_returns_to_the_founder(self):
        self.assertFalse(should_reply_to_peer(
            mode=BOTH, turns_used=DEFAULT_EXCHANGE_BUDGET,
            budget=DEFAULT_EXCHANGE_BUDGET, peer_said_something=True))

    def test_a_zero_budget_stops_them_talking_to_each_other_entirely(self):
        self.assertFalse(should_reply_to_peer(
            mode=BOTH, turns_used=0, budget=0, peer_said_something=True))

    def test_the_peer_is_the_other_one(self):
        self.assertEqual(other_speaker(CLAUDE), TRADER)
        self.assertEqual(other_speaker(TRADER), CLAUDE)


class TranscriptTests(unittest.TestCase):
    def test_each_participant_sees_its_own_words_as_its_own(self):
        turns = [
            {"speaker": "founder", "text": "where are we?"},
            {"speaker": TRADER, "text": "fees are eating the edge"},
            {"speaker": CLAUDE, "text": "I checked; fees are 5.8% of rejections"},
        ]
        seen = transcript_for(CLAUDE, turns)
        self.assertEqual(seen[-1]["role"], "assistant")
        self.assertIn("5.8%", seen[-1]["content"])

    def test_the_peer_is_labelled_so_it_is_not_mistaken_for_oneself(self):
        """Without the label a model reads the peer's answer as its own earlier words and
        agrees with itself."""
        turns = [{"speaker": TRADER, "text": "fees are eating the edge"}]
        seen = transcript_for(CLAUDE, turns)
        self.assertEqual(seen[0]["role"], "user")
        self.assertIn("The trader said", seen[0]["content"])
        self.assertIn("Claude said", transcript_for(TRADER, [{"speaker": CLAUDE, "text": "no"}])[0]["content"])

    def test_both_participants_see_the_whole_conversation(self):
        """"there may be times I explore a topic with Claude while chatgpt listens after which
        it also joins in if asked" -- listening only works if it was given the transcript."""
        turns = [
            {"speaker": "founder", "text": "Claude, is that right?"},
            {"speaker": CLAUDE, "text": "no, and here is why"},
        ]
        self.assertEqual(len(transcript_for(TRADER, turns)), 1, "folded into one user turn")
        self.assertIn("here is why", transcript_for(TRADER, turns)[0]["content"])

    def test_empty_turns_are_dropped(self):
        self.assertEqual(transcript_for(CLAUDE, [{"speaker": TRADER, "text": "   "}]), [])


class ActionsInstructionTests(unittest.TestCase):
    """"when we conclude Claude would document the actions for you to develop."

    The value of the handoff is not that a second Claude checks the first -- it is the same
    model, and a wrong conclusion would be implemented just as cheerfully. It is that writing
    the decision down is where vagueness shows up.
    """

    def test_every_action_must_carry_a_way_to_verify_it(self):
        self.assertIn("verify", ACTIONS_INSTRUCTION)
        self.assertIn("Every action needs a verify step", ACTIONS_INSTRUCTION)

    def test_unsettled_discussion_may_not_be_recorded_as_a_decision(self):
        """"An open question recorded as a decision is how wrong work gets done."""
        self.assertIn("DISCUSSED BUT NOT SETTLED", ACTIONS_INSTRUCTION)

    def test_an_empty_list_is_an_allowed_answer(self):
        """Otherwise the model invents tidy actions to fill the shape, which is how a
        conversation that concluded nothing produces a morning of work."""
        self.assertIn("Empty actions is a valid answer", ACTIONS_INSTRUCTION)

    def test_confidence_is_required_and_the_reason_is_recorded(self):
        self.assertIn("confidence", ACTIONS_INSTRUCTION)
        self.assertIn("2026-09-06", ACTIONS_INSTRUCTION,
                      "the day three of four findings turned out to be artefacts")


class StandupTurnTests(unittest.TestCase):
    """The endpoint, with both speakers stubbed.

    Real turns cost money and take minutes, and neither is needed to prove the thing that can
    actually break: who speaks, in what order, and when they stop.
    """

    def _service(self, tmp):
        from ai_trader.api import LocalApiService
        from ai_trader.config import Settings
        from ai_trader.models import AutoTradeConfig, GuardrailConfig

        root = Path(tmp)
        service = LocalApiService(Settings(
            alpaca_api_key=None, alpaca_secret_key=None,
            alpaca_paper_base_url="https://paper-api.alpaca.markets",
            alpaca_data_base_url="https://data.alpaca.markets",
            openai_api_key=None, openai_model="gpt-4.1-mini",
            db_path=root / "audit.sqlite3", output_dir=root,
            trading_log_path=root / "TRADING_LOG.md",
            guardrails=GuardrailConfig(), auto_trade=AutoTradeConfig(),
        ))
        self.said = []

        def _fake(who):
            def speak(history, prompt):
                self.said.append((who, prompt))
                return {"text": f"{who} says something", "status": "answered", "model": "stub"}
            return speak

        service._trader_turn = _fake(TRADER)
        service._claude_turn = _fake(CLAUDE)
        return service

    def test_an_empty_message_is_refused_before_anyone_is_paid_to_answer(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn({"message": "   "})
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["turns"], [])
            self.assertEqual(self.said, [], "nobody was asked anything")

    def test_a_directed_question_reaches_only_the_one_addressed(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn(
                {"message": "Claude, why is that slow?", "exchange_budget": 0}
            )
            self.assertEqual(result["addressed"], CLAUDE)
            self.assertEqual([t["speaker"] for t in result["turns"]], [CLAUDE])

    def test_an_opening_remark_reaches_both(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn(
                {"message": "morning, where are we?", "exchange_budget": 0}
            )
            self.assertEqual(result["addressed"], BOTH)
            self.assertEqual([t["speaker"] for t in result["turns"]], [TRADER, CLAUDE])

    def test_the_peer_exchange_is_capped_by_the_budget(self):
        """The stubs always answer, so without the cap this would not terminate. That is the
        point: the budget, not the models' good manners, is what ends the exchange."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn(
                {"message": "morning, where are we?", "exchange_budget": 3}
            )
            self.assertEqual(result["exchange_turns"], 3)
            self.assertEqual([t["speaker"] for t in result["turns"]],
                             [TRADER, CLAUDE, TRADER, CLAUDE, TRADER])

    def test_asking_for_no_exchange_actually_buys_no_exchange(self):
        """A deliberate 0 must not be read as "not supplied". It was: the parse used `or`, so
        a caller asking for silence got four model turns and four bills."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn(
                {"message": "morning, where are we?", "exchange_budget": 0}
            )
            self.assertEqual(result["exchange_turns"], 0)
            self.assertEqual(len(result["turns"]), 2, "both answered once, and stopped")

    def test_an_unreadable_budget_falls_back_rather_than_raising(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn(
                {"message": "morning", "exchange_budget": "lots"}
            )
            self.assertEqual(result["exchange_turns"], DEFAULT_EXCHANGE_BUDGET)

    def test_the_budget_is_capped_even_if_a_caller_asks_for_more(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn(
                {"message": "morning", "exchange_budget": 500}
            )
            self.assertLessEqual(result["exchange_turns"], 8)

    def test_a_one_to_one_conversation_never_pulls_the_other_one_in(self):
        """"maybe have a way of just chatting with chatgpt or Claude separately as well." """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).run_standup_turn(
                {"message": "what do you make of the fees?", "mode": TRADER, "exchange_budget": 4}
            )
            self.assertEqual([t["speaker"] for t in result["turns"]], [TRADER])
            self.assertEqual({who for who, _ in self.said}, {TRADER})

    def test_the_conversation_continues_with_whoever_last_spoke(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            service.run_standup_turn({"message": "Claude, why is that slow?", "exchange_budget": 0})
            result = service.run_standup_turn({"message": "why though?", "exchange_budget": 0})
            self.assertEqual(result["addressed"], CLAUDE)

    def test_nothing_said_is_nothing_to_write_up(self):
        """An empty conversation must not be sent to a model to have actions invented for it."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).write_up_standup_actions({"conversation_id": "empty"})
            self.assertEqual(result["status"], "nothing_to_write_up")
            self.assertEqual(result["actions"], [])


if __name__ == "__main__":
    unittest.main()
