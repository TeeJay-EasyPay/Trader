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


if __name__ == "__main__":
    unittest.main()
