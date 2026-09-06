"""Multi-call jobs must not run on the budget meant for single-query work.

2026-09-06. This trap has now caught SIX jobs, and the sixth was doing real damage:

    forecast-refresh              one OpenAI call per symbol
    daily-report                  heavy multi-table queries
    daily-learning                the same, plus a calibration recompute
    benchmark-research-refresh    4 web-grounded OpenAI calls
    external-intelligence-refresh many sequential HTTP calls
    crypto-universe-refresh       3 CoinGecko calls + the whole universe written
    crypto-candle-refresh         ONE Kraken OHLC call per symbol, 30-40 symbols

The failure is silent and self-sustaining: the job claims its scheduling bucket, dies on the
shared 180s timeout, and cannot retry until the next bucket. Nothing raises. It simply never
completes, run after run, and everything downstream quietly reads stale data.

crypto-candle-refresh had timed out 232 times, last completing 2026-08-27 -- ten days. Its own
event log shows "1 symbol(s)" per run. And technical_trend_score is computed from those
candles, while the gate that reads it accounted for 723 of 961 rejections in 24 hours. The
largest single reason the system refused to trade was being decided on ten-day-old candles.

This test is the cheap check that a job which fans out never silently lands on the default.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

CLI = Path(__file__).resolve().parents[1] / "src" / "ai_trader" / "cli.py"

# Every job whose work is many calls rather than one query. Adding a fan-out job means adding
# it here as well, which is the point.
MULTI_CALL_JOBS = (
    "premarket-equity",
    "market-open-equity",
    "market-close-equity",
    "crypto-research",
    "daily-report",
    "daily-learning",
    "benchmark-research-refresh",
    "external-intelligence-refresh",
    "self-assessment",
    "crypto-universe-refresh",
    "crypto-candle-refresh",
)


class JobBudgetTests(unittest.TestCase):
    def test_every_fan_out_job_gets_the_research_budget(self):
        body = CLI.read_text(encoding="utf-8")
        match = re.search(r"if job_name in \{([^}]*)\}", body, re.DOTALL)
        self.assertIsNotNone(match, "the research-budget job set could not be located")
        listed = match.group(1)
        missing = [job for job in MULTI_CALL_JOBS if f'"{job}"' not in listed]
        self.assertEqual(
            missing, [],
            "these fan-out jobs would run on the 180s default and time out silently: "
            + ", ".join(missing),
        )

    def test_the_research_budget_is_meaningfully_larger_than_the_default(self):
        """A budget that is not actually bigger would make the whole list decorative."""
        import re as _re

        body = Path(__file__).resolve().parents[1].joinpath(
            "src", "ai_trader", "config.py").read_text(encoding="utf-8")
        research = int(_re.search(r"research_job_timeout_seconds: int = (\d+)", body).group(1))
        default = int(_re.search(r"worker_job_timeout_seconds: int = (\d+)", body).group(1))
        self.assertGreater(
            research, default * 2,
            "the research budget must be substantially larger than the shared default, "
            "or the list of jobs assigned to it is decorative",
        )


if __name__ == "__main__":
    unittest.main()
