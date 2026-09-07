"""Speaking should start a conversation, not a single question.

2026-09-07, Founder-directed: "I then need to click on the microphone icon to ask the next
question. isn't there a way... so that I can speak and have a conversation with chatgpt in the
app. that way I can fully understand from it what it's doing and thinking."

Everything needed was already shipped -- expo-av records, the server transcribes, the server
speaks, expo-av plays. The only missing piece was intent: nothing re-opened the microphone
when the reply finished. So this is a loop, not a new capability, and needs no native module
and no rebuild, which matters because the app updates over the air.

The risk in a loop is that it never stops. These tests are mostly about STOPPING.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPOKEN = REPO / "mobile" / "lib" / "spokenReply.js"
ASK = REPO / "mobile" / "screens" / "Ask.js"


def _node(script: str):
    result = subprocess.run([shutil.which("node"), "-e", script],
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr[:400])
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class ListenAgainTests(unittest.TestCase):
    def _call(self, **kwargs):
        return _node(
            "const {shouldListenAgain} = require(" + json.dumps(str(SPOKEN)) + ");"
            "console.log(JSON.stringify(shouldListenAgain(" + json.dumps(kwargs) + ")));"
        )

    def test_a_voice_conversation_continues_by_itself(self):
        self.assertTrue(self._call(handsFree=True, spokenOk=True, questionUnderstood=True))

    def test_typing_never_opens_the_microphone(self):
        """Typing has never made it speak, and must not make it listen."""
        self.assertFalse(self._call(handsFree=False, spokenOk=True, questionUnderstood=True))

    def test_silence_ends_the_conversation_rather_than_looping(self):
        """A phone left on a desk would otherwise record silence, fail to transcribe it, and
        try again indefinitely."""
        self.assertFalse(self._call(handsFree=True, spokenOk=True, questionUnderstood=False))

    def test_it_does_not_listen_when_the_reply_never_played(self):
        """Without the spoken cue he has no way to know it is his turn, so re-opening the
        microphone would be listening at someone unaware of it."""
        self.assertFalse(self._call(handsFree=True, spokenOk=False, questionUnderstood=True))


class ConversationExitTests(unittest.TestCase):
    """Every way out of the loop must exist in the screen. A loop with one exit is a trap."""

    def setUp(self):
        self.body = ASK.read_text(encoding="utf-8")

    def test_the_microphone_button_ends_the_conversation_without_submitting(self):
        """Mid-conversation the button means STOP, not SUBMIT -- submitting would send
        whatever silence was captured while he reached for the phone."""
        self.assertIn("cancelRecording", self.body)
        self.assertIn("if (handsFreeRef.current) {", self.body)

    def test_a_failed_or_empty_transcription_stops_it(self):
        self.assertGreaterEqual(self.body.count("handsFreeRef.current = false"), 4)

    def test_leaving_the_screen_stops_it(self):
        self.assertIn("askMountedRef.current = false", self.body)
        self.assertIn("askMountedRef.current &&", self.body)

    def test_the_refs_are_declared_before_the_functions_that_read_them(self):
        """They were originally declared below their callers. Legal, because those functions
        only run on a tap, but a trap for the next edit."""
        declared = self.body.index("const handsFreeRef")
        for user in ("const stopRecording", "const toggleVoice"):
            self.assertLess(declared, self.body.index(user), user + " reads it before declaration")


if __name__ == "__main__":
    unittest.main()
