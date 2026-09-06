"""A question must never start a trading cycle, however long the message.

2026-09-06 incident, caused by me. I asked the trading AI a daily check-in through the live
/ask-ai-trader endpoint and it replied "Starting a full cycle now." It had matched the
cycle_all pattern on the words "do you have everything" -- "do", within twenty characters,
"everything" -- inside the sentence "Do you have everything you need... on Kraken?".

That sentence is plainly a question and ends in a question mark. But detect_action tested the
WHOLE MESSAGE: first word, last character. The message began "Daily check-in." and ended
"...rather than guessing.", so the guard was skipped entirely and every pattern was then
searched across the whole blob.

No trade resulted, because research produced no proposal on that cycle. That was luck. The
failure runs in the dangerous direction -- an unrecognised question is treated as consent to
trade -- and the Founder writes in long multi-sentence messages, so it was never an edge case.

The fix judges each sentence on its own grammar. These cases are the contract.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.voice_actions import detect_action

# The message that actually started a cycle on 2026-09-06, shortened but with the fatal
# sentence intact and in place.
THE_INCIDENT = (
    "Daily check-in. Do you have everything you need -- the data, the market news, the "
    "evidence -- to make good and profitable trading decisions on Alpaca and on Kraken? "
    "Then tell me what extra you need. Be specific and rank them."
)


class QuestionsMustNotAct(unittest.TestCase):
    def test_the_message_that_started_a_cycle_no_longer_does(self):
        self.assertIsNone(detect_action(THE_INCIDENT))

    def test_a_question_is_still_a_question_without_punctuation(self):
        """Whisper returns speech with no question mark, so the interrogative opener carries
        the weight for voice input."""
        self.assertIsNone(detect_action("do you have everything you need"))
        self.assertIsNone(detect_action("why did it not run a cycle"))

    def test_a_question_about_the_past_never_triggers_a_new_one(self):
        self.assertIsNone(detect_action("What did it do overnight? Did anything trigger a cycle?"))
        self.assertIsNone(detect_action("Are you checking positions correctly? I want to know."))


class InstructionsMustStillAct(unittest.TestCase):
    """The guard must not be so cautious that a real instruction stops working. Every one of
    these is a sentence the Founder actually uses."""

    def test_a_plain_instruction(self):
        self.assertEqual(detect_action("run a full cycle"), "cycle_all")
        self.assertEqual(detect_action("check our positions"), "reconcile")

    def test_a_polite_request_is_an_instruction(self):
        self.assertEqual(detect_action("can you run a cycle?"), "cycle_all")
        self.assertEqual(detect_action("please run the crypto cycle"), "cycle_crypto")

    def test_an_instruction_after_a_greeting_still_acts(self):
        """The reason for splitting cuts both ways: an instruction in the SECOND sentence used
        to work only by accident, and must keep working on purpose."""
        self.assertEqual(detect_action("Good morning. Please run a full cycle now."), "cycle_all")
        self.assertEqual(detect_action("Morning. Run a full cycle please."), "cycle_all")


if __name__ == "__main__":
    unittest.main()
