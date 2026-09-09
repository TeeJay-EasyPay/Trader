"""The Standup screen must be able to hear him.

2026-09-07, Founder-reported, after trying to use it:

    "I clicked start conversation. Nothing gets picked up, and there's no icon that's animated
     that shows me that it's listening... Even if I tried to click send, nothing was working
     because I don't think it could hear me... Then I tried it on the Claude button so directly
     with you, and again, same thing."

Nothing was broken. The screen was built text-only and that was never said out loud, so he
tapped a screen with no microphone on it and had no way to tell whether he was unheard or the
thing had failed. Speaking is how he uses this app; a conversation screen he cannot talk to is
not a conversation screen.
"""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCREEN = REPO / "mobile" / "screens" / "Standup.js"
STYLES = REPO / "mobile" / "styles.js"
HOOK = REPO / "mobile" / "lib" / "useVoiceCapture.js"

sys.path.insert(0, str(REPO / "src"))


def _node(script: str):
    result = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip())
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class VoiceCaptureModuleTests(unittest.TestCase):
    def test_the_hook_loads_without_a_native_recorder_present(self):
        """It is required at module load by the screen, so if merely importing it threw, the
        Standup screen would not render at all."""
        out = _node(
            "const m = require('./mobile/lib/useVoiceCapture.js');"
            "console.log(JSON.stringify({exports: Object.keys(m).sort(), "
            "hook: typeof m.useVoiceCapture}));"
        )
        self.assertEqual(out["exports"], ["loadAudioModules", "useVoiceCapture"])
        self.assertEqual(out["hook"], "function")

    def test_a_missing_native_module_returns_null_rather_than_throwing(self):
        """2026-08-25: an unguarded require took the Executive Briefing down entirely with
        "Cannot find native module 'ExponentAV'". A convenience must never break its screen."""
        out = _node(
            "const m = require('./mobile/lib/useVoiceCapture.js');"
            "console.log(JSON.stringify({value: m.loadAudioModules()}));"
        )
        self.assertIsNone(out["value"])


class ScreenWiringTests(unittest.TestCase):
    def test_the_screen_has_a_microphone(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("useVoiceCapture", source)
        self.assertIn("micButtonLabel", source)

    def test_speaking_submits_without_a_second_tap(self):
        """He asked to "press it and just ask the app something verbally and submit it", so
        speaking IS the submission -- a transcript left sitting in the box would be the same
        dead end he already hit."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("onTranscript:", source)
        block = source[source.index("onTranscript:"):source.index("onProblem:")]
        self.assertIn("sendRef.current(text, { spoken: true })", block)
        self.assertIn("pendingSpeechRef.current = text", block)

    def test_the_recording_state_is_visible_not_just_internal(self):
        """"there's no icon that's animated that shows me that it's listening." Two independent
        signals: the button turns red, and the status line ticks."""
        source = SCREEN.read_text(encoding="utf-8")
        styles = STYLES.read_text(encoding="utf-8")
        self.assertIn("voice.isRecording && styles.standupMicRecording", source)
        self.assertIn("standupMicRecording:", styles)
        self.assertIn("onStatus: setStatusLine", source)

    def test_ending_the_conversation_stops_the_microphone(self):
        """A recorder still running on a closed conversation is the worst failure here.

        Scoped to the whole callback rather than a fixed number of characters: the first
        version counted 400 characters in and broke the moment a comment was added above the
        line it was checking, which is a test measuring the wrong thing.
        """
        source = SCREEN.read_text(encoding="utf-8")
        start = source.index("const end = useCallback")
        end = source[start : source.index("}, [", start)]
        self.assertIn("voice.cancel()", end)

    def test_an_empty_box_explains_itself_instead_of_a_dead_send_button(self):
        """"I clicked send. Nothing happened." Send is disabled with an empty box, which looks
        exactly like a broken button unless something says otherwise.

        Asserted on intent rather than exact wording: the first version pinned the sentence
        itself and broke the moment the hint was reworded to say he can just talk, which is a
        test guarding the words instead of the behaviour.
        """
        source = SCREEN.read_text(encoding="utf-8")
        hint = source[source.index("{!draft.trim() && !voice.isRecording"):]
        hint = hint[:hint.index("</Text>")]
        self.assertIn("microphone", hint.lower())
        self.assertIn("type", hint.lower(), "it must say what to do instead of pressing Send")

    def test_the_placeholder_mentions_speaking(self):
        """The old one said "Say something" while offering no way to say anything."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("Tap the microphone and speak", source)

    def test_the_hook_is_created_before_anything_uses_it(self):
        """A dependency array is evaluated when the callback is created, so a hook declared
        below its user is a ReferenceError on the first render, not a subtle bug."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertLess(source.index("const voice = useVoiceCapture"),
                        source.index("const end = useCallback"))

    def test_ask_is_left_alone_for_now(self):
        """Ask is mounted on the Executive Briefing and voice work has taken that screen down
        once already. The shared hook gets proven on the new screen first."""
        ask = (REPO / "mobile" / "screens" / "Ask.js").read_text(encoding="utf-8")
        self.assertNotIn("useVoiceCapture", ask)


class ComposerLayoutTests(unittest.TestCase):
    """Putting the microphone beside Send broke Send.

    2026-09-07, caught on the device. standupSend had no width: as the only child of a column it
    stretched, and the moment it shared a row it collapsed to its own text width, so the padding
    squeezed "Send" over its own edges. No test looks at whether a word fits inside its box,
    which is why this needed a screenshot.
    """

    def _style_block(self, name: str) -> str:
        source = STYLES.read_text(encoding="utf-8")
        start = source.index(f"  {name}: {{")
        return source[start:source.index("},", start)]

    def test_send_fills_the_row_beside_the_microphone(self):
        self.assertIn("flex: 1", self._style_block("standupSend"))

    def test_the_microphone_keeps_a_fixed_width(self):
        """It is an icon, not a label. Letting it flex would give a 20px glyph half the row."""
        block = self._style_block("standupMic")
        self.assertIn("width:", block)
        self.assertNotIn("flex: 1", block)

    def test_both_buttons_are_the_same_height(self):
        """Different heights in a row read as a rendering fault rather than a design."""
        self.assertIn("height: 48", self._style_block("standupMic"))
        self.assertIn("height: 48", self._style_block("standupSend"))


if __name__ == "__main__":
    unittest.main()
