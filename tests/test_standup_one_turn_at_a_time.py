"""A standup you can interrupt, and replies that stay with the question that asked for them.

2026-09-07, Founder-reported after using it:

    "I asked a question... the transcribing went on for quite a while, so much so that we just
     stopped it. Then I clicked on the trader button, and I spoke to ChatGPT... and then I
     started getting messages from both trader and ChatGPT. And then they started talking
     amongst themselves. So I think right now, this whole thing isn't in full control."

Everything he describes follows from one design fault. A "both" turn ran the ENTIRE exchange
inside one request -- trader, Claude, then up to four peer replies. Six model calls at 30-60
seconds each is three to six minutes, against a client that gives up at four minutes; the
server carried on regardless, and its replies arrived long after he had switched to Trader and
asked something else. Two AIs answering a question he had not asked them, in a mode where they
are not even supposed to talk to each other.

So: one reply per request, the caller decides whether to ask for the next, and a question that
has been abandoned cannot deliver its answers into the conversation that replaced it.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ai_trader.standup import BOTH, CLAUDE, DEFAULT_EXCHANGE_BUDGET, TRADER  # noqa: E402

SCREEN = REPO / "mobile" / "screens" / "Standup.js"


def _service(tmp: str, said):
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

    def _fake(who):
        def speak(history, prompt):
            said.append((who, prompt))
            return {"text": f"{who} says something", "status": "answered", "model": "stub"}
        return speak

    service._trader_turn = _fake(TRADER)
    service._claude_turn = _fake(CLAUDE)
    return service


class OneReplyPerRequestTests(unittest.TestCase):
    def test_asking_for_one_reply_returns_exactly_one(self):
        """The wait is one answer long instead of six."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _service(tmp, said).run_standup_turn(
                {"message": "morning, where are we?", "max_replies": 1}
            )
            self.assertEqual(len(result["turns"]), 1)
            self.assertEqual(len(said), 1, "only one model was called")

    def test_it_says_who_should_speak_next(self):
        """Without this the caller cannot know whether the floor has come back to him, which is
        the only state in which the app should stop waiting."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _service(tmp, said).run_standup_turn(
                {"message": "morning, where are we?", "max_replies": 1}
            )
            self.assertEqual(result["turns"][0]["speaker"], TRADER)
            self.assertEqual(result["next_speaker"], CLAUDE, "the opening still owes Claude")

    def test_the_exchange_can_be_walked_one_turn_at_a_time(self):
        """The whole conversation, fetched a reply at a time, must produce the same speakers in
        the same order as running it all at once."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            service = _service(tmp, said)
            speakers = []
            body = {"message": "morning, where are we?", "max_replies": 1}
            for _ in range(8):
                result = service.run_standup_turn(body)
                speakers.extend(turn["speaker"] for turn in result["turns"])
                if not result.get("next_speaker"):
                    break
                body = {
                    "continue_as": result["next_speaker"],
                    "max_replies": 1,
                    "exchange_used": result["exchange_used"],
                    "opening_left": result["opening_left"],
                }
            self.assertEqual(speakers, [TRADER, CLAUDE, TRADER, CLAUDE])

    def test_the_floor_comes_back_to_the_founder(self):
        """It must end. A next_speaker that never becomes None is an app that waits forever."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            service = _service(tmp, said)
            body = {"message": "morning", "max_replies": 1}
            for _ in range(10):
                result = service.run_standup_turn(body)
                if not result.get("next_speaker"):
                    break
                body = {
                    "continue_as": result["next_speaker"],
                    "max_replies": 1,
                    "exchange_used": result["exchange_used"],
                    "opening_left": result["opening_left"],
                }
            self.assertIsNone(result.get("next_speaker"))

    def test_a_continuation_does_not_record_the_founder_speaking_again(self):
        """He said one thing. A continuation is the other participant answering it, not him
        repeating himself into the transcript."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            service = _service(tmp, said)
            service.run_standup_turn({"message": "just the once", "max_replies": 1})
            service.run_standup_turn({"continue_as": CLAUDE, "max_replies": 1, "exchange_used": 0})
            history = service.standup_history(conversation_id="standup")["turns"]
            founder_turns = [t for t in history if t["speaker"] == "founder"]
            self.assertEqual(len(founder_turns), 1)

    def test_a_continuation_needs_no_message(self):
        """It carries no new words, so requiring one would make the second turn impossible."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _service(tmp, said).run_standup_turn(
                {"continue_as": TRADER, "max_replies": 1}
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["turns"][0]["speaker"], TRADER)

    def test_an_empty_request_with_no_speaker_is_still_refused(self):
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _service(tmp, said).run_standup_turn({"message": "   "})
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(said, [])

    def test_a_one_to_one_conversation_never_names_the_other_one_next(self):
        """He was in Trader mode when two AIs started answering. In a one-to-one conversation
        there is no next speaker, ever."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _service(tmp, said).run_standup_turn(
                {"message": "what do you see?", "mode": TRADER, "max_replies": 1}
            )
            self.assertEqual(result["turns"][0]["speaker"], TRADER)
            self.assertIsNone(result["next_speaker"])

    def test_omitting_max_replies_still_runs_the_whole_exchange(self):
        """Scripts and tests want the whole thing in one call; only the app wants it in pieces."""
        said = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _service(tmp, said).run_standup_turn({"message": "morning"})
            self.assertGreater(len(result["turns"]), 1)


class ExchangeBudgetTests(unittest.TestCase):
    def test_the_budget_is_short_enough_to_stay_a_conversation(self):
        """Four peer turns on top of the opening two is six model calls for one question --
        minutes of silence, which he experienced as the app having hung."""
        self.assertLessEqual(DEFAULT_EXCHANGE_BUDGET, 2)
        self.assertGreaterEqual(DEFAULT_EXCHANGE_BUDGET, 1, "they must still be able to disagree")


class StaleReplyTests(unittest.TestCase):
    """The app side: a question he gave up on must not deliver its answers into the next one."""

    def _screen(self) -> str:
        return SCREEN.read_text(encoding="utf-8")

    def test_each_question_is_stamped_and_late_replies_are_dropped(self):
        source = self._screen()
        self.assertIn("exchangeRef", source)
        self.assertIn("const stale = ()", source)
        self.assertIn("if (stale()) return;", source)

    def test_ending_the_conversation_abandons_work_in_flight(self):
        source = self._screen()
        end = source[source.index("const end = useCallback"):]
        self.assertIn("exchangeRef.current += 1", end[:500])

    def test_changing_mode_abandons_work_in_flight(self):
        """Switching from Standup to Trader is him saying "not that, this". The previous
        question's replies must not arrive into the new conversation."""
        source = self._screen()
        self.assertIn("}, [mode]);", source)
        block = source[source.index("useEffect(() => {\n    exchangeRef.current += 1;"):]
        self.assertIn("[mode]", block[:400])

    def test_the_app_asks_for_one_reply_at_a_time(self):
        source = self._screen()
        self.assertIn("max_replies: 1", source)
        self.assertIn("continue_as: next", source)
        self.assertIn("opening_left:", source, "without this the exchange never ends")

    def test_there_is_a_hard_stop_on_how_far_one_question_runs(self):
        """Independent of the server's budget: if it ever kept naming a next speaker, the app
        would still hand the floor back rather than looping."""
        source = self._screen()
        self.assertIn("MAX_TURNS_PER_QUESTION", source)

    def test_the_wait_says_who_and_for_how_long(self):
        """"there was the circular animation on the send button that just kept going, and I
        never got anything back." A spinner cannot be told apart from a hang."""
        source = self._screen()
        self.assertIn("function waitingLine", source)
        self.assertIn("is thinking", source)

    def test_transcribing_counts_up_rather_than_sitting_still(self):
        hook = (REPO / "mobile" / "lib" / "useVoiceCapture.js").read_text(encoding="utf-8")
        block = hook[hook.index("setVoiceState('transcribing')"):]
        self.assertIn("setInterval", block[:900])
        self.assertIn("clearTick()", hook[hook.index("} finally {"):][:200],
                      "the counter must stop however the transcription ends")


if __name__ == "__main__":
    unittest.main()
