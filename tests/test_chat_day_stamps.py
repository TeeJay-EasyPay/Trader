"""The Ask card must show past conversations, and say when each one happened.

2026-09-06, Founder-directed, two faults in one card:

  "the ask trader card only shows the last conversations once a question is asked. so I can't
   see what you asked it unless I ask another question."

  "there should be some sort of time indication in the chat. so I can see what conversation
   happened when... something like in WhatsApp."

The first was a one-word gate: the block rendered on `messages.length`, the turns from the
CURRENT session, while storedTurns -- the history, fetched from /ask-history on mount and
merged one line below -- could never be reached. The history existed, was loaded, and was
invisible.

The logic is exercised through node rather than asserted as source text, because a date
boundary is exactly the kind of thing that reads correctly and behaves wrongly.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHAT_BUBBLES = REPO / "mobile" / "lib" / "chatBubbles.js"
ASK_SCREEN = REPO / "mobile" / "screens" / "Ask.js"


def _node(script: str) -> dict:
    result = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr[:400])
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class DayStampTests(unittest.TestCase):
    def test_relative_words_for_the_days_a_person_thinks_in(self):
        out = _node(
            "const {dayStampFor} = require(" + json.dumps(str(CHAT_BUBBLES)) + ");"
            "const now = new Date('2026-09-06T12:00:00Z');"
            "console.log(JSON.stringify({"
            "  today: dayStampFor('2026-09-06T09:00:00Z', now),"
            "  yesterday: dayStampFor('2026-09-05T22:00:00Z', now),"
            "  older: dayStampFor('2026-09-01T10:00:00Z', now),"
            "  lastYear: dayStampFor('2025-12-24T10:00:00Z', now),"
            "  missing: dayStampFor(null, now),"
            "  rubbish: dayStampFor('not a date', now)"
            "}));"
        )
        self.assertEqual(out["today"], "Today")
        self.assertEqual(out["yesterday"], "Yesterday")
        self.assertIn("September", out["older"])
        self.assertIn("2025", out["lastYear"], "a different year must carry the year")
        self.assertIsNone(out["missing"])
        self.assertIsNone(out["rubbish"], "a wrong date is worse than none")

    def test_one_stamp_per_day_above_that_day_s_newest_exchange(self):
        """Exchanges are newest-first, so reading down goes backwards in time. Each day's label
        sits above that day's newest exchange, and an undated exchange gets no invented stamp."""
        out = _node(
            "const {withDayStamps} = require(" + json.dumps(str(CHAT_BUBBLES)) + ");"
            "const now = new Date('2026-09-06T12:00:00Z');"
            "const ex = ["
            "  [{key:'a', createdAt:'2026-09-06T09:00:00Z'}],"
            "  [{key:'b', createdAt:'2026-09-06T08:00:00Z'}],"
            "  [{key:'c', createdAt:'2026-09-05T20:00:00Z'}],"
            "  [{key:'d', createdAt:null}]"
            "];"
            "console.log(JSON.stringify(withDayStamps(ex, now).map("
            "  (i) => i.type === 'stamp' ? '[' + i.label + ']' : i.exchange[0].key)));"
        )
        self.assertEqual(out, ["[Today]", "a", "b", "[Yesterday]", "c", "d"])


class AskCardHistoryTests(unittest.TestCase):
    def test_the_conversation_is_not_gated_on_this_session_alone(self):
        body = ASK_SCREEN.read_text(encoding="utf-8")
        self.assertIn("messages.length || storedTurns.length", body,
                      "stored history must render without a new question being asked first")

    def test_history_is_still_fetched_when_the_card_mounts(self):
        """The gate fix is worthless if nothing loads the history in the first place."""
        body = ASK_SCREEN.read_text(encoding="utf-8")
        self.assertIn("/ask-history", body)
        self.assertIn("setStoredTurns", body)


if __name__ == "__main__":
    unittest.main()
