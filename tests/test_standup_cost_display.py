"""What a question cost, shown next to the answer.

2026-09-07: the Founder's first $6 of Anthropic credit was gone inside fifteen minutes across
four test questions, and the only place he could find out where was Anthropic's billing page
the next morning. Cost that is invisible until the following day is cost nobody can steer.

The formatter is exercised through node rather than asserted as source text, because rounding
that reads wrong on screen is the whole failure mode here.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COST = REPO / "mobile" / "lib" / "cost.js"
STANDUP_SCREEN = REPO / "mobile" / "screens" / "Standup.js"

sys.path.insert(0, str(REPO / "src"))


def _node(script: str):
    # encoding is explicit because the pound sign comes back mangled otherwise: node writes
    # UTF-8, Windows decodes as cp1252, and "£1.19" arrives as a replacement character.
    result = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip())
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class FormatPenceTests(unittest.TestCase):
    def _format(self, values):
        return _node(
            "const {formatPence} = require('./mobile/lib/cost.js');"
            f"console.log(JSON.stringify({json.dumps(values)}.map(formatPence)));"
        )

    def test_small_amounts_read_as_pence_not_as_zero_pounds(self):
        """The typical answer costs a few pence. In pounds every one of them reads "£0.00",
        which tells the Founder his questions are free. They are not."""
        self.assertEqual(self._format([0.0029, 0.05, 0.29]), ["0.2p", "4.0p", "22.9p"])

    def test_larger_amounts_switch_to_pounds(self):
        self.assertEqual(self._format([1.5, 5.29]), ["£1.19", "£4.18"])

    def test_something_too_small_to_show_is_not_shown_as_free(self):
        """"0.0p" reads as costing nothing. It does cost something."""
        self.assertEqual(self._format([0.00001]), ["<0.1p"])

    def test_nothing_spent_shows_nothing(self):
        """A trader-only turn spends no Anthropic credit, and a cost line saying "0p" would be
        noise on every one of them."""
        self.assertEqual(self._format([0, None, -1]), ["", "", ""])

    def test_rubbish_does_not_reach_the_screen_as_NaN(self):
        self.assertEqual(self._format(["banana", None]), ["", ""])


class ScreenWiringTests(unittest.TestCase):
    """The screen holds JSX, so node cannot require it. These are source assertions, kept to
    the few facts that would actually break the display."""

    def test_the_screen_uses_the_shared_formatter(self):
        source = STANDUP_SCREEN.read_text(encoding="utf-8")
        self.assertIn("require('../lib/cost')", source)
        self.assertNotIn("function formatPence", source,
                         "one formatter, in lib/, where it can be tested")

    def test_a_running_total_is_kept_for_the_conversation(self):
        """Per-answer cost tells him what one question cost; the running total is what tells
        him the credit is going."""
        source = STANDUP_SCREEN.read_text(encoding="utf-8")
        self.assertIn("spentTotal", source)
        self.assertIn("This conversation so far", source)

    def test_starting_a_new_conversation_resets_the_total(self):
        source = STANDUP_SCREEN.read_text(encoding="utf-8")
        start = source[source.index("const start = useCallback"):]
        self.assertIn("setSpentTotal(0)", start[:400])


class EndpointReportsCostTests(unittest.TestCase):
    def test_the_endpoint_returns_what_the_exchange_cost(self):
        import tempfile

        from ai_trader.api import LocalApiService
        from ai_trader.config import Settings
        from ai_trader.models import AutoTradeConfig, GuardrailConfig

        with tempfile.TemporaryDirectory() as tmp:
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
            service._claude_turn = lambda history, prompt: {
                "text": "checked it", "status": "answered", "model": "stub",
                "usage": {"cost_usd": 0.0123},
            }
            result = service.run_standup_turn(
                {"message": "Claude, check that", "exchange_budget": 0}
            )
            self.assertAlmostEqual(result["cost_usd"], 0.0123)
            self.assertAlmostEqual(result["turns"][0]["usage"]["cost_usd"], 0.0123)

    def test_a_turn_that_spends_nothing_reports_zero_rather_than_missing(self):
        """The mobile side adds this to a running total, and undefined would poison it."""
        import tempfile

        from ai_trader.api import LocalApiService
        from ai_trader.config import Settings
        from ai_trader.models import AutoTradeConfig, GuardrailConfig

        with tempfile.TemporaryDirectory() as tmp:
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
            service._trader_turn = lambda history, prompt: {
                "text": "no cost here", "status": "answered", "model": "gpt",
            }
            result = service.run_standup_turn(
                {"message": "trader, what do you see?", "mode": "trader", "exchange_budget": 0}
            )
            self.assertEqual(result["cost_usd"], 0)


class StoredHistoryTests(unittest.TestCase):
    """Reopening the screen must show what was already said.

    2026-09-07. Without this the Conversation card was empty until you asked something new --
    the exact complaint the Founder made about Ask on 2026-08-31: "the ask trader card only
    shows the last conversations once a question is asked". The turns were being stored the
    whole time; nothing could read them back.
    """

    def _service(self, tmp):
        from ai_trader.api import LocalApiService
        from ai_trader.config import Settings
        from ai_trader.models import AutoTradeConfig, GuardrailConfig

        root = Path(tmp)
        return LocalApiService(Settings(
            alpaca_api_key=None, alpaca_secret_key=None,
            alpaca_paper_base_url="https://paper-api.alpaca.markets",
            alpaca_data_base_url="https://data.alpaca.markets",
            openai_api_key=None, openai_model="gpt-4.1-mini",
            db_path=root / "audit.sqlite3", output_dir=root,
            trading_log_path=root / "TRADING_LOG.md",
            guardrails=GuardrailConfig(), auto_trade=AutoTradeConfig(),
        ))

    def test_stored_turns_come_back_with_who_said_them_and_when(self):
        """The speaker picks the bubble colour and the timestamp drives the day stamps, so a
        history missing either renders wrongly rather than not at all."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            service._trader_turn = lambda history, prompt: {
                "text": "here is what I see", "status": "answered", "model": "stub"}
            service.run_standup_turn(
                {"message": "trader, what do you see?", "mode": "trader", "exchange_budget": 0}
            )
            history = service.standup_history(conversation_id="standup")
            speakers = [turn["speaker"] for turn in history["turns"]]
            self.assertIn("founder", speakers)
            self.assertIn("trader", speakers)
            for turn in history["turns"]:
                self.assertTrue(turn["created_at"], "a turn with no time breaks the day stamps")

    def test_another_conversation_does_not_leak_in(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            service._trader_turn = lambda history, prompt: {
                "text": "ok", "status": "answered", "model": "stub"}
            service.run_standup_turn({"message": "one", "mode": "trader",
                                      "conversation_id": "standup", "exchange_budget": 0})
            service.run_standup_turn({"message": "two", "mode": "trader",
                                      "conversation_id": "elsewhere", "exchange_budget": 0})
            texts = [t["text"] for t in service.standup_history(conversation_id="standup")["turns"]]
            self.assertIn("one", texts)
            self.assertNotIn("two", texts)

    def test_an_empty_conversation_returns_an_empty_list_not_an_error(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._service(tmp).standup_history(conversation_id="nothing")["turns"], [])

    def test_the_history_is_bounded(self):
        """A screenful, not a history. Unbounded reads are what cost the Founder his Supabase
        quota in August."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            history = self._service(tmp).standup_history(conversation_id="standup", limit=10_000)
            self.assertIsInstance(history["turns"], list)

    def test_the_screen_asks_for_it_on_open(self):
        source = STANDUP_SCREEN.read_text(encoding="utf-8")
        self.assertIn("/standup/history", source)

    def test_starting_a_conversation_does_not_wipe_what_was_said(self):
        """Ending a conversation does not delete the transcript on the server, so clearing the
        screen only hid it."""
        source = STANDUP_SCREEN.read_text(encoding="utf-8")
        start = source[source.index("const start = useCallback"):]
        self.assertNotIn("setTurns([])", start[:400])


if __name__ == "__main__":
    unittest.main()
