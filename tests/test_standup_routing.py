"""Who speaks next in a three-way standup, and when the two AIs stop talking to each other.

2026-09-07, Founder-directed:

    "the conversation should basically be free flowing.... there may be times I explore a topic
     or item in the conversation with Claude for example while chatgpt listens after which it
     also joins in if asked and likewise for me with chatgpt"
    "yes but also happy for Claude and chatgpt to speak to each other as well"

The routing is only worth testing because getting it wrong is invisible: a misrouted question
still gets an answer, just from the wrong participant, and nobody notices except that the
conversation feels stupid.

The exchange budget is the part with money attached. Two agreeable models will ping-pong
politely for as long as they are allowed to, and every turn is billed.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.standup import (
    BOTH,
    CLAUDE,
    DEFAULT_EXCHANGE_BUDGET,
    PEER_EXCHANGE_INSTRUCTION,
    TRADER,
    detect_addressee,
    other_speaker,
    should_reply_to_peer,
    transcript_for,
)


class AddressingTests(unittest.TestCase):
    def test_a_leading_name_wins_outright(self):
        """How people actually address someone in a room."""
        self.assertEqual(detect_addressee("Claude, why is that slow?"), CLAUDE)
        self.assertEqual(detect_addressee("ChatGPT, what would change your mind?"), TRADER)
        self.assertEqual(detect_addressee("Hey Claude, can you check that?"), CLAUDE)

    def test_the_founders_own_words_for_the_trader_all_route_there(self):
        """He calls it chatgpt, ChatGPT and the trader. A router fussy about names drops half
        the conversation."""
        for phrasing in ("chatgpt, why?", "ChatGPT, why?", "chat gpt, why?", "the trader, why?"):
            self.assertEqual(detect_addressee(phrasing), TRADER, phrasing)

    def test_one_name_anywhere_still_routes(self):
        self.assertEqual(detect_addressee("what did the trader mean by stale?"), TRADER)
        self.assertEqual(detect_addressee("does claude agree with that"), CLAUDE)

    def test_a_follow_up_stays_with_whoever_was_speaking(self):
        """This is what lets him explore a topic with one while the other listens."""
        self.assertEqual(detect_addressee("and why is that", last_ai_speaker=CLAUDE), CLAUDE)
        self.assertEqual(detect_addressee("and why is that", last_ai_speaker=TRADER), TRADER)

    def test_naming_both_or_neither_opens_it_up(self):
        self.assertEqual(detect_addressee("Claude and ChatGPT, discuss it"), BOTH)
        self.assertEqual(detect_addressee("can you both look at the fees"), BOTH)
        self.assertEqual(detect_addressee("so what now"), BOTH)

    def test_a_one_to_one_conversation_has_nobody_to_route_to(self):
        """In 'just chat with Claude' mode, mentioning the trader must not silently hand the
        question to someone who is not in the room."""
        self.assertEqual(detect_addressee("what did the trader mean?", mode=CLAUDE), CLAUDE)
        self.assertEqual(detect_addressee("does claude agree?", mode=TRADER), TRADER)


class ExchangeBudgetTests(unittest.TestCase):
    """The failure mode here is not a wrong answer. It is two models being endlessly agreeable
    while the Founder watches and pays."""

    def test_the_peer_may_reply_while_the_budget_holds(self):
        self.assertTrue(should_reply_to_peer(mode=BOTH, turns_used=0, peer_said_something=True))
        self.assertTrue(should_reply_to_peer(mode=BOTH, turns_used=3, budget=4, peer_said_something=True))

    def test_the_floor_returns_to_the_founder_when_the_budget_runs_out(self):
        self.assertFalse(should_reply_to_peer(mode=BOTH, turns_used=4, budget=4, peer_said_something=True))
        self.assertFalse(should_reply_to_peer(mode=BOTH, turns_used=99, peer_said_something=True))

    def test_a_one_to_one_conversation_has_no_peer_exchange(self):
        self.assertFalse(should_reply_to_peer(mode=CLAUDE, turns_used=0, peer_said_something=True))
        self.assertFalse(should_reply_to_peer(mode=TRADER, turns_used=0, peer_said_something=True))

    def test_nothing_said_means_nothing_to_reply_to(self):
        self.assertFalse(should_reply_to_peer(mode=BOTH, turns_used=0, peer_said_something=False))

    def test_the_budget_allows_a_disagreement_and_an_answer_to_it(self):
        """Two turns each: enough to disagree and respond, not enough to hold a seminar."""
        self.assertGreaterEqual(DEFAULT_EXCHANGE_BUDGET, 2)
        self.assertLessEqual(DEFAULT_EXCHANGE_BUDGET, 6)

    def test_the_stop_rule_forbids_filling_silence(self):
        """Without it, a model asked 'anything to add?' always finds something to add."""
        self.assertIn("Reply ONLY if you have something substantive", PEER_EXCHANGE_INSTRUCTION)
        self.assertIn("do not find something to add", PEER_EXCHANGE_INSTRUCTION)

    def test_the_two_are_each_others_peer(self):
        self.assertEqual(other_speaker(CLAUDE), TRADER)
        self.assertEqual(other_speaker(TRADER), CLAUDE)


class TranscriptTests(unittest.TestCase):
    TURNS = [
        {"speaker": "founder", "text": "Why no trades?"},
        {"speaker": TRADER, "text": "The price feed is stale."},
        {"speaker": CLAUDE, "text": "Nothing reads that table."},
    ]

    def test_each_participant_sees_its_own_words_as_its_own(self):
        claude_view = transcript_for(CLAUDE, self.TURNS)
        self.assertEqual(claude_view[-1]["role"], "assistant")
        self.assertIn("Nothing reads that table", claude_view[-1]["content"])

        trader_view = transcript_for(TRADER, self.TURNS)
        self.assertEqual(trader_view[1]["role"], "assistant")
        self.assertIn("price feed is stale", trader_view[1]["content"])

    def test_the_peer_is_labelled_so_nobody_agrees_with_itself(self):
        """Unlabelled, a model reads the peer's answer as its own earlier words."""
        self.assertIn("[The trader said]", transcript_for(CLAUDE, self.TURNS)[0]["content"])
        self.assertIn("[Claude said]", transcript_for(TRADER, self.TURNS)[-1]["content"])

    def test_both_see_everything(self):
        """That is what lets one listen while the other is explored, then join in usefully."""
        for who in (CLAUDE, TRADER):
            blob = " ".join(m["content"] for m in transcript_for(who, self.TURNS))
            self.assertIn("Why no trades?", blob)
            self.assertIn("price feed is stale", blob)
            self.assertIn("Nothing reads that table", blob)

    def test_consecutive_same_role_turns_are_merged(self):
        """The Founder's question and the peer's answer are one piece of context, not two
        separate remarks."""
        view = transcript_for(CLAUDE, self.TURNS)
        roles = [m["role"] for m in view]
        self.assertEqual(roles, list(dict.fromkeys(roles)) if len(roles) == len(set(roles)) else roles)
        for earlier, later in zip(view, view[1:]):
            self.assertNotEqual(earlier["role"], later["role"], "adjacent roles must alternate")

    def test_empty_turns_are_dropped(self):
        view = transcript_for(CLAUDE, [{"speaker": "founder", "text": "   "}])
        self.assertEqual(view, [])


if __name__ == "__main__":
    unittest.main()
