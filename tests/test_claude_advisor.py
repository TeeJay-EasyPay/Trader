"""Claude as a standup participant: it must check, must not write, and must not run away.

2026-09-07, Founder-directed. Verified against the real API on the trading AI's own claim from
2026-09-06 -- "CRYPTO_MARKET_DATA ... if that is the price source used for decisions, it should
prevent a new entry". Claude made 14 tool calls and answered:

    "I searched all 139 source files for that table name... There is no query anywhere that
     reads it. No trading decision can be using it, because nothing reads it."

Which is the conclusion that took Claude Code an hour of manual digging the day before. It also
flagged its own uncertainty ("I should flag that as corroboration rather than proof -- I can
read the code as it runs but not its history") and named what it could not see.

These tests hold the structure that made that possible: the tools it is offered, the ceiling on
how long it may dig, and the fact that none of it can write.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader import claude_advisor
from ai_trader.evidence_tools import TOOL_SPECS


class ToolSurfaceTests(unittest.TestCase):
    def test_claude_is_offered_exactly_the_read_tools(self):
        """The definitions are built from the same specs the dispatcher uses, so a description
        can never advertise a tool that does not exist."""
        offered = {tool["name"] for tool in claude_advisor._tool_definitions()}
        self.assertEqual(offered, {spec["name"] for spec in TOOL_SPECS})
        self.assertEqual(offered, {"search_source", "read_source_file", "query_database"})

    def test_no_tool_can_change_anything(self):
        for tool in claude_advisor._tool_definitions():
            self.assertNotIn("write", tool["name"])
            self.assertNotIn("edit", tool["name"])
            self.assertNotIn("deploy", tool["name"])


class GuardrailTests(unittest.TestCase):
    def test_an_unconfigured_deployment_says_so_instead_of_failing(self):
        import os

        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            result = claude_advisor.ask_claude([{"role": "user", "content": "hello"}])
            self.assertEqual(result["status"], "not_configured")
            self.assertIn("ANTHROPIC_API_KEY", result["answer"])
        finally:
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved

    def test_the_lookup_loop_is_bounded(self):
        """Each iteration is a model call plus tool results, so this bounds the wait and the
        bill. Reaching it is REPORTED -- a truncated investigation presented as a finished one
        is the failure this whole file exists to prevent."""
        self.assertGreater(claude_advisor.MAX_TOOL_ITERATIONS, 1)
        self.assertLessEqual(claude_advisor.MAX_TOOL_ITERATIONS, 25)

    def test_a_model_that_never_stops_asking_is_cut_off_and_says_so(self):
        """Stubbed rather than called: a model that keeps requesting tools forever is exactly
        the case that must not hang or quietly answer anyway, and it cannot be provoked
        reliably against the real API."""
        import os
        from types import SimpleNamespace

        class _AlwaysAsksForMore:
            """Returns a tool_use response every time, forever."""

            class messages:
                @staticmethod
                def create(**_kwargs):
                    return SimpleNamespace(
                        stop_reason="tool_use",
                        model="stub",
                        content=[SimpleNamespace(
                            type="tool_use", id="t1", name="search_source",
                            input={"pattern": "anything"},
                        )],
                        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                    )

        saved_env = os.environ.get("ANTHROPIC_API_KEY")
        saved_client = claude_advisor._client
        os.environ["ANTHROPIC_API_KEY"] = "stub-key"
        claude_advisor._client = lambda: _AlwaysAsksForMore()
        try:
            result = claude_advisor.ask_claude(
                [{"role": "user", "content": "hello"}], max_iterations=3
            )
            self.assertEqual(result["status"], "tool_limit_reached")
            self.assertIn("ran out of lookups", result["answer"])
            self.assertEqual(len(result["tool_calls"]), 3, "every attempt is still reported")
        finally:
            claude_advisor._client = saved_client
            if saved_env is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = saved_env


class SystemPromptTests(unittest.TestCase):
    def test_it_is_told_to_check_before_claiming(self):
        prompt = claude_advisor.SYSTEM_PROMPT.lower()
        self.assertIn("use them", prompt)
        self.assertIn("look first", prompt)

    def test_it_is_licensed_to_say_it_cannot_tell(self):
        """That sentence has already been worth more than several confident answers."""
        self.assertIn("cannot tell from what I can see", claude_advisor.SYSTEM_PROMPT)

    def test_it_is_told_what_it_cannot_see(self):
        """The container carries src, governance and knowledge only. Claude must know that, or
        it will read the absence of a test as the absence of testing."""
        prompt = claude_advisor.SYSTEM_PROMPT
        self.assertIn("no tests", prompt)
        self.assertIn("git history", prompt)

    def test_it_is_told_it_cannot_change_anything(self):
        self.assertIn("You cannot change anything", claude_advisor.SYSTEM_PROMPT)

    def test_it_is_told_to_disagree_with_evidence(self):
        """Disagreement that names its evidence is the most useful thing in the standup."""
        self.assertIn("Disagree with the trader", claude_advisor.SYSTEM_PROMPT)

    def test_it_is_told_the_founder_wants_plain_english(self):
        self.assertIn("plain English", claude_advisor.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
