"""Knowing when someone has finished speaking, and letting them take it back.

2026-09-07, Founder-directed:

    "I also don't want to click on a send button each time. I want the app to detect a long
     pause and then just respond rather than clicking on the select button. also there should
     be an x button if I want to cancel the transcription or my voice in case I get it wrong"

Both are about the same thing: he talks to this app, and every button between him and a reply
turns a conversation back into a form.

The judgement is exercised through node rather than asserted as source text, because the two
ways of getting it wrong are behavioural and opposite -- cutting him off mid-thought loses what
he was saying, and never firing leaves him talking into a recorder that has stopped listening
for the end.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAUSE = REPO / "mobile" / "lib" / "speechPause.js"
HOOK = REPO / "mobile" / "lib" / "useVoiceCapture.js"
SCREEN = REPO / "mobile" / "screens" / "Standup.js"

# A reading every 200ms: five per second, matching how the recorder reports.
STEP_MS = 200
TALKING = -20      # normal speech
QUIET = -60        # room tone


def _node(script: str):
    result = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip())
    return json.loads(result.stdout)


def _fires_at(readings):
    """The reading index at which it decides he has finished, or None."""
    return _node(
        "const {initialPauseState, nextPauseState} = require('./mobile/lib/speechPause.js');"
        f"const readings = {json.dumps(readings)};"
        "let s = initialPauseState(); let at = null;"
        "readings.forEach((m, i) => {"
        f"  s = nextPauseState(s, {{metering: m, sinceLastMs: {STEP_MS}}});"
        "  if (s.shouldSubmit && at === null) at = i;"
        "});"
        "console.log(JSON.stringify({at}));"
    )["at"]


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class PauseDetectionTests(unittest.TestCase):
    def test_a_silent_room_never_submits(self):
        """A phone on a desk is silent from the first millisecond. Without the speech-first
        rule this would fire instantly, every time, on nothing."""
        self.assertIsNone(_fires_at([QUIET] * 40))

    def test_speaking_then_stopping_submits(self):
        """Two seconds of talking, then quiet. It should fire about two seconds after he
        stops -- not immediately, and not never."""
        fired = _fires_at([TALKING] * 10 + [QUIET] * 20)
        self.assertIsNotNone(fired, "he finished speaking and it never noticed")
        # Speech ends at index 9; the pause is 2s, which is ten readings.
        self.assertGreaterEqual(fired, 18)
        self.assertLessEqual(fired, 22, "it waited too long after he stopped")

    def test_a_gap_between_sentences_does_not_cut_him_off(self):
        """The failure that would actually annoy him: thinking mid-sentence and being
        submitted. A short gap is a breath, not a full stop."""
        readings = [TALKING] * 10 + [QUIET] * 5 + [TALKING] * 10 + [QUIET] * 20
        fired = _fires_at(readings)
        self.assertIsNotNone(fired)
        self.assertGreater(fired, 25, "it submitted during the gap, mid-sentence")

    def test_a_single_noise_is_not_a_sentence(self):
        """A door closing is a spike. It must not submit an otherwise empty recording."""
        self.assertIsNone(_fires_at([TALKING] + [QUIET] * 30))

    def test_hardware_that_cannot_measure_sound_never_fires(self):
        """Some devices ignore metering. Silently refusing to submit would be far worse than
        the button he already has, so this only ever adds to it."""
        self.assertIsNone(_fires_at([None] * 40))
        self.assertIsNone(_fires_at(["not a number"] * 40))

    def test_quiet_speech_still_counts_as_speech(self):
        """Cutting someone off for talking softly is the failure that would annoy him most."""
        self.assertIsNotNone(_fires_at([-40] * 10 + [QUIET] * 20))

    def test_the_thresholds_are_sane(self):
        out = _node(
            "const p = require('./mobile/lib/speechPause.js');"
            "console.log(JSON.stringify({pause: p.PAUSE_MS, speech: p.MIN_SPEECH_MS, db: p.SILENCE_DB}));"
        )
        self.assertGreaterEqual(out["pause"], 1200, "shorter than this and it clips sentences")
        self.assertLessEqual(out["pause"], 3000, "longer and he is left waiting")
        self.assertGreater(out["speech"], 0)
        self.assertLess(out["db"], 0, "sound level is dBFS, always negative")


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class ListeningLabelTests(unittest.TestCase):
    def test_it_says_the_button_is_still_there_when_nothing_can_be_measured(self):
        """If auto-send cannot work on this device, he must be told to tap instead."""
        out = _node(
            "const p = require('./mobile/lib/speechPause.js');"
            "console.log(JSON.stringify({label: p.listeningLabel(p.initialPauseState(), 3)}));"
        )
        self.assertIn("tap to send", out["label"])

    def test_it_signals_that_it_is_about_to_send(self):
        out = _node(
            "const p = require('./mobile/lib/speechPause.js');"
            "console.log(JSON.stringify({label: p.listeningLabel("
            "{metered: true, heardSpeechMs: 800, silentMs: 900}, 9)}));"
        )
        self.assertIn("sending when you stop", out["label"])


class CancelTests(unittest.TestCase):
    """"there should be an x button if I want to cancel the transcription or my voice in case I
    get it wrong." Cancelling has to mean the words never arrive -- not that they arrive a
    moment later, into a conversation he has already backed out of."""

    def test_the_screen_offers_a_way_out(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("voice.cancel()", source)
        self.assertIn("standupCancel", source)

    def test_it_is_offered_while_recording_and_while_transcribing(self):
        """Both are moments where he can already tell it has gone wrong."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("voice.isRecording || voice.isBusy", source)

    def test_cancelling_abandons_a_transcription_already_in_flight(self):
        hook = HOOK.read_text(encoding="utf-8")
        cancel = hook[hook.index("const cancel = useCallback"):]
        self.assertIn("ticketRef.current += 1", cancel[:400])

    def test_an_abandoned_transcription_says_nothing(self):
        hook = HOOK.read_text(encoding="utf-8")
        self.assertIn("const abandoned = ()", hook)
        self.assertIn("if (abandoned()) return;", hook)

    def test_the_cancel_button_is_not_the_same_colour_as_end_conversation(self):
        """Two red buttons side by side is how someone ends the wrong thing."""
        styles = (REPO / "mobile" / "styles.js").read_text(encoding="utf-8")
        cancel = styles[styles.index("standupCancel: {"):]
        cancel = cancel[:cancel.index("},")]
        end = styles[styles.index("standupEnd: {"):]
        end = end[:end.index("},")]
        self.assertNotEqual(
            cancel[cancel.index("backgroundColor"):cancel.index("backgroundColor") + 40],
            end[end.index("backgroundColor"):end.index("backgroundColor") + 40],
        )


class RecorderWiringTests(unittest.TestCase):
    def test_metering_is_switched_on(self):
        """Without it the recorder reports no sound level and the pause can never be detected."""
        hook = HOOK.read_text(encoding="utf-8")
        self.assertIn("isMeteringEnabled: true", hook)

    def test_the_detector_drives_the_stop(self):
        hook = HOOK.read_text(encoding="utf-8")
        self.assertIn("nextPauseState", hook)
        self.assertIn("stopRef.current()", hook)

    def test_the_hint_tells_him_he_can_just_talk(self):
        """It used to say "tap the microphone to speak, or type something to send", which is
        the button he asked to be rid of."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("it sends when you stop", source)


if __name__ == "__main__":
    unittest.main()
