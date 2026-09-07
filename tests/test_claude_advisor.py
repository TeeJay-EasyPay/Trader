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
            # The ceiling means "stop looking", not "give up". Caught on the first real
            # standup: Claude made TWENTY-ONE lookups on a broad question, hit the ceiling and
            # returned a canned apology -- all that evidence gathered and thrown away, which is
            # worse than not looking, because it costs the money and produces nothing.
            self.assertEqual(result["status"], "answered_at_lookup_limit")
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

class LookupCeilingTests(unittest.TestCase):
    """Hitting the ceiling must mean "stop looking", not "give up".

    2026-09-07, caught on the very first real standup. Asked a broad opening question, Claude
    made TWENTY-ONE lookups, hit the ceiling, and returned a canned apology. Every one of those
    lookups was paid for and then discarded -- worse than not looking at all, because it costs
    the money and produces nothing.
    """

    def test_the_final_summary_call_offers_no_tools(self):
        """If it could still request evidence in the last call, the ceiling would not be one.
        With nothing offered it must answer from what it has, or say what is missing."""
        import inspect

        source = inspect.getsource(claude_advisor.ask_claude)
        tail = source[source.index("You have used all the lookups"):]
        self.assertNotIn("tools=", tail, "the final call must offer no tools")

    def test_it_is_asked_to_name_what_it_could_not_establish(self):
        import inspect

        source = inspect.getsource(claude_advisor.ask_claude)
        self.assertIn("say plainly which part you could", source)
        self.assertIn("Do not ask for more", source)


class CostControlTests(unittest.TestCase):
    """2026-09-07: the Founder's first $6 of credit was gone in fifteen minutes across four
    test questions. The console confirmed it -- $5.29, one day, all Opus 5.

    The cause is structural. A tool loop resends the whole conversation on every iteration, so
    a 21-lookup question does not pay for those tokens once; it pays for them again and again.
    These tests hold the three defences in place, because the failure is silent: nothing breaks,
    the answers stay good, and the money simply goes.
    """

    def _recording_client(self, *, usage=None, always_tools=True):
        """A stub that records exactly what was sent, so the caching can be asserted on."""
        from types import SimpleNamespace

        sent = []

        class _Client:
            class messages:
                @staticmethod
                def create(**kwargs):
                    sent.append(kwargs)
                    return SimpleNamespace(
                        stop_reason="tool_use" if always_tools else "end_turn",
                        model="stub",
                        content=[SimpleNamespace(
                            type="tool_use", id=f"t{len(sent)}", name="search_source",
                            input={"pattern": "anything"},
                        )] if always_tools else [SimpleNamespace(type="text", text="done")],
                        usage=usage or SimpleNamespace(
                            input_tokens=10, output_tokens=5,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0,
                        ),
                    )

        return _Client(), sent

    def _run(self, client, **kwargs):
        import os

        saved_env = os.environ.get("ANTHROPIC_API_KEY")
        saved_client = claude_advisor._client
        os.environ["ANTHROPIC_API_KEY"] = "stub-key"
        claude_advisor._client = lambda: client
        try:
            return claude_advisor.ask_claude([{"role": "user", "content": "hello"}], **kwargs)
        finally:
            claude_advisor._client = saved_client
            if saved_env is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = saved_env

    def test_the_system_prompt_is_sent_as_a_cacheable_block(self):
        """It is identical on every iteration. Paying for it twelve times is pure waste."""
        client, sent = self._recording_client()
        self._run(client, max_iterations=2)
        system = sent[0]["system"]
        self.assertIsInstance(system, list, "a plain string cannot carry a cache breakpoint")
        self.assertEqual(system[-1]["cache_control"], {"type": "ephemeral"})

    def test_the_tool_schemas_carry_a_cache_breakpoint(self):
        client, sent = self._recording_client()
        self._run(client, max_iterations=2)
        self.assertEqual(sent[0]["tools"][-1]["cache_control"], {"type": "ephemeral"})

    def test_the_conversation_so_far_is_marked_cacheable(self):
        """The breakpoint moves forward each iteration, so what it caches is everything before
        the newest exchange -- exactly the part that would otherwise be resent at full price."""
        client, sent = self._recording_client()
        self._run(client, max_iterations=3)
        self.assertGreaterEqual(len(sent), 2)
        for call in sent:
            last = call["messages"][-1]
            blocks = last["content"]
            self.assertIsInstance(blocks, list)
            self.assertEqual(blocks[-1].get("cache_control"), {"type": "ephemeral"})

    def test_marking_never_loses_the_original_content(self):
        """A missed cache hit costs money; a mangled message costs the whole turn."""
        marked = claude_advisor._with_cache_breakpoint([{"role": "user", "content": "hello"}])
        self.assertEqual(marked[0]["content"][0]["text"], "hello")

    def test_an_unmarkable_message_is_left_alone_rather_than_broken(self):
        for awkward in ([], [{"role": "user", "content": ""}], [{"role": "user", "content": None}]):
            self.assertEqual(claude_advisor._with_cache_breakpoint(list(awkward)), awkward)

    def test_a_turn_stops_when_it_costs_too_much(self):
        """The iteration count bounds how MANY times we look. It says nothing about what each
        look costs, which is why it did not stop the overnight burn."""
        from types import SimpleNamespace

        expensive = SimpleNamespace(
            input_tokens=200_000, output_tokens=1_000,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        client, sent = self._recording_client(usage=expensive)
        result = self._run(client, max_iterations=12, max_cost_usd=0.60)
        self.assertEqual(result["status"], "answered_at_cost_limit")
        self.assertLess(len(sent), 12, "it stopped well before the iteration ceiling")

    def test_the_two_kinds_of_stop_are_reported_differently(self):
        """One says the question was too broad; the other says it was too expensive. The
        Founder acts differently on each."""
        client, _ = self._recording_client()
        cheap = self._run(client, max_iterations=2, max_cost_usd=1000.0)
        self.assertEqual(cheap["status"], "answered_at_lookup_limit")

    def test_every_outcome_reports_what_it_spent(self):
        """Cost the Founder cannot see is cost he cannot control -- he had to read it off the
        Anthropic console the morning after."""
        client, _ = self._recording_client(always_tools=False)
        answered = self._run(client, max_iterations=4)
        self.assertEqual(answered["status"], "answered")
        self.assertIn("cost_usd", answered["usage"])
        self.assertIn("cache_read_tokens", answered["usage"])

    def test_cached_and_uncached_input_are_counted_apart(self):
        """They are priced an order of magnitude apart, so a merged total cannot show whether
        the caching is working at all."""
        totals = {"input": 1_000_000, "output": 0, "cache_write": 0, "cache_read": 1_000_000}
        self.assertAlmostEqual(claude_advisor._cost_usd(totals), 5.50, places=2)

    def test_a_cache_read_is_far_cheaper_than_fresh_input(self):
        self.assertLess(claude_advisor.PRICE_PER_MTOK["cache_read"],
                        claude_advisor.PRICE_PER_MTOK["input"] / 5)

    def test_tool_results_are_bounded(self):
        """A result stays in the history for the rest of the turn, so an oversized one is paid
        for on every later iteration too."""
        self.assertLessEqual(claude_advisor.MAX_TOOL_RESULT_CHARS, 12000)
        self.assertGreaterEqual(claude_advisor.MAX_TOOL_RESULT_CHARS, 4000,
                                "too small and the evidence stops being evidence")


class PlainRefusalTests(unittest.TestCase):
    """2026-09-07, found by looking at the actual screen rather than the logs.

    The credit ran out and Claude's bubble in the app showed the Founder this:

        Anthropic rejected the request: Error code: 400 - {'type': 'error', 'error':
        {'type': 'invalid_request_error', 'message': 'Your credit balance is too low...

    He has asked repeatedly for short plain English and no jargon. A raw API payload in a
    conversation bubble is the opposite, and it buries the one sentence he can act on.
    """

    def test_no_credit_says_so_and_says_what_to_do(self):
        answer = claude_advisor._plain_refusal(Exception(
            "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
            "'message': 'Your credit balance is too low to access the Anthropic API.'}}"
        ))
        self.assertIn("run out of credit", answer)
        self.assertIn("Add funds", answer)

    def test_the_raw_payload_never_reaches_the_conversation(self):
        answer = claude_advisor._plain_refusal(Exception(
            "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error'}}"
        ))
        for jargon in ("{", "}", "Error code", "invalid_request_error", "400"):
            self.assertNotIn(jargon, answer, f"{jargon!r} leaked into a Founder-facing message")

    def test_rate_limits_and_overload_are_told_apart(self):
        """They need different actions -- wait a minute, versus try again later."""
        limited = claude_advisor._plain_refusal(Exception("429 rate limit exceeded"))
        overloaded = claude_advisor._plain_refusal(Exception("529 overloaded_error"))
        self.assertNotEqual(limited, overloaded)
        self.assertIn("rate limited", limited)
        self.assertIn("overloaded", overloaded)

    def test_an_unrecognised_failure_still_says_something_useful(self):
        answer = claude_advisor._plain_refusal(TimeoutError("connection timed out"))
        self.assertIn("TimeoutError", answer, "the class name is a short, honest clue")
        self.assertLess(len(answer), 200, "still a sentence, not a stack trace")

    def test_every_message_is_short_enough_to_read_in_a_bubble(self):
        for error in (Exception("credit balance is too low"), Exception("429 rate limit"),
                      Exception("529 overloaded"), Exception("context length exceeded"),
                      ValueError("something else entirely")):
            self.assertLess(len(claude_advisor._plain_refusal(error)), 220)


if __name__ == "__main__":
    unittest.main()
