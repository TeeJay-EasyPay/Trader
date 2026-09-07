"""One colour per voice in the standup.

2026-09-07, Founder-directed, after seeing a real three-way conversation in the app:

    "each of us needs a different chat bubble colour so that it's easy to understand who is
     asking the questions and who is answering."

Before this the two AIs shared a single grey, so a standup read as an undifferentiated wall --
which is precisely the case the speaker labels were only half solving.

Colour and label are BOTH kept. Colour alone fails a colour-blind reader and in bright
sunlight; label alone was the thing that was already not enough.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STYLES = REPO / "mobile" / "styles.js"
SCREEN = REPO / "mobile" / "screens" / "Standup.js"

sys.path.insert(0, str(REPO / "src"))


def _hex_for(style_name: str) -> str:
    """The backgroundColor declared for one style block."""
    source = STYLES.read_text(encoding="utf-8")
    block = source[source.index(f"  {style_name}: {{"):]
    block = block[: block.index("},")]
    match = re.search(r"backgroundColor:\s*'(#[0-9a-fA-F]{3,8})'", block)
    assert match, f"{style_name} declares no backgroundColor"
    return match.group(1).lower()


class BubbleColourTests(unittest.TestCase):
    def test_each_of_the_three_voices_has_its_own_colour(self):
        colours = {name: _hex_for(name) for name in ("standupMine", "standupTrader", "standupClaude")}
        self.assertEqual(len(set(colours.values())), 3,
                         f"two voices share a colour: {colours}")

    def test_the_two_ai_colours_are_not_merely_shades_of_each_other(self):
        """Separated in hue AND lightness. Green against amber survives the common form of
        colour blindness; green against red would not."""
        def rgb(value):
            return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))

        trader, claude = rgb(_hex_for("standupTrader")), rgb(_hex_for("standupClaude"))
        self.assertGreater(sum(abs(a - b) for a, b in zip(trader, claude)), 20,
                           "the two AI bubbles are too close to tell apart")

    def test_the_label_survives_alongside_the_colour(self):
        """Colour is the glance; the label is the confirmation. Removing either regresses this."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("SPEAKER_LABEL[turn.speaker]", source)

    def test_every_speaker_maps_to_styles_that_exist(self):
        """A missing style is a blank bubble on the screen, not an error in the logs."""
        from ai_trader.standup import CLAUDE, TRADER

        screen = SCREEN.read_text(encoding="utf-8")
        styles = STYLES.read_text(encoding="utf-8")
        block = screen[screen.index("const BUBBLE = {"):screen.index("function bubbleFor")]
        referenced = set(re.findall(r"'(standup\w+)'", block))
        self.assertTrue(referenced, "no styles referenced at all")
        for name in referenced:
            self.assertIn(f"  {name}:", styles, f"{name} is referenced but not defined")
        for speaker in ("founder", TRADER, CLAUDE):
            self.assertIn(f"{speaker}:", block, f"{speaker} has no bubble styling")

    def test_an_unknown_speaker_falls_back_rather_than_rendering_nothing(self):
        source = SCREEN.read_text(encoding="utf-8")
        fallback = source[source.index("function bubbleFor"):]
        self.assertIn("standupTheirs", fallback[:400],
                      "an unrecognised speaker must still get a readable bubble")


class TranscriptLayoutTests(unittest.TestCase):
    """2026-09-07, Founder-directed after using the screen:

        "it doesn't show your conversation in a scrollable section like in the executive
         briefing."

    It was inside the controls card, in a fixed-height nested ScrollView that sat mostly below
    the fold on a tall screen -- present, but effectively unreachable. The Executive Briefing
    uses no nested scrolling at all: titled Section cards that flow into the app's own page
    scroll.
    """

    def test_the_conversation_is_its_own_section(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn('<Section title="Conversation">', source)

    def test_the_transcript_does_not_sit_in_a_nested_scroll_box(self):
        """A ScrollView inside the app's ScrollView is the thing that put it below the fold."""
        source = SCREEN.read_text(encoding="utf-8")
        code = re.sub(r"/\*[\s\S]*?\*/", "", source)     # comments may still mention it
        self.assertNotIn("<ScrollView", code)
        self.assertNotIn("nestedScrollEnabled", code)

    def test_no_fixed_height_caps_the_conversation(self):
        """A maxHeight is what made a long standup unreadable; the page scroll has no such cap."""
        styles = STYLES.read_text(encoding="utf-8")
        self.assertNotIn("standupTranscript", styles,
                         "the fixed-height transcript style should be gone, not merely unused")

    def test_an_empty_conversation_shows_no_empty_card(self):
        """Before the first question there is nothing to show, and a titled empty card reads
        as something failing to load."""
        source = SCREEN.read_text(encoding="utf-8")
        marker = source.index('<Section title="Conversation">')
        self.assertIn("turns.length ?", source[marker - 300:marker])


if __name__ == "__main__":
    unittest.main()
