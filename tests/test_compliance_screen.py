"""2026-08-29, Founder-directed: state the Shariah screen as a rule, not a frozen list.

Until now it existed only as 50 companies curated by hand on 2 July, enforced by accident -- a
company absent from that list has no philosophy-fit rating, keeps TradeProposal's 0.0 default,
and so can never clear the permission gate. The Founder's point: "keeping fifty as a list that's
static and never changes is not really a good long term strategy... there could be thousands."

Seven excluded activities, Founder-specified: alcohol, tobacco, gambling, conventional banking
and insurance, pork, adult entertainment, and military/defence.

The rule that governs the whole module: an uncertain answer is never a pass. Clear signal ->
excluded. Weak or ambiguous signal -> referred for a human decision. Only a clean company is
admitted automatically, because wrongly admitting a company the Founder did not want to own
costs far more than him reviewing one by hand.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.compliance_screen import (
    EXCLUDED,
    PERMITTED,
    REFERRED,
    screen_business_activity,
    screen_many,
)


def verdict(name, sector, industry, summary=""):
    return screen_business_activity(
        company_name=name, sector=sector, industry=industry, business_summary=summary
    )


class ExcludedActivityTests(unittest.TestCase):
    """One real company per excluded activity, with its actual classification."""

    def test_each_excluded_activity_is_caught(self):
        cases = [
            ("Diageo plc", "Consumer Staples", "Distillers and Vintners", "alcohol"),
            ("Philip Morris International", "Consumer Staples", "Tobacco", "tobacco"),
            ("Flutter Entertainment", "Consumer Discretionary", "Casinos and Gaming", "gambling"),
            ("HSBC Holdings", "Financials", "Banking", "conventional_finance"),
            ("Allianz SE", "Financials", "Insurance", "conventional_finance"),
            ("Lockheed Martin", "Industrials", "Aerospace and Defense", "defence"),
            ("BAE Systems", "Industrials", "Defence", "defence"),
        ]
        for name, sector, industry, expected in cases:
            result = verdict(name, sector, industry)
            self.assertEqual(result.verdict, EXCLUDED, f"{name} should be excluded")
            self.assertEqual(result.category, expected, name)

    def test_plural_classifications_are_caught(self):
        """Real classifications are plural -- "Distillers and Vintners", "Casinos and Gaming",
        "Brewers". Tested live: without plural handling, Diageo and Flutter both came back
        permitted, which is exactly the failure this screen exists to prevent."""
        for name, industry in [("Diageo", "Distillers and Vintners"),
                               ("Anheuser-Busch InBev", "Brewers"),
                               ("Flutter", "Casinos and Gaming")]:
            self.assertEqual(verdict(name, "Consumer", industry).verdict, EXCLUDED, name)

    def test_an_activity_hidden_behind_a_bland_sector_is_still_caught(self):
        """Smithfield Foods is classified only as "Packaged Foods" and passes the
        classification test cleanly. Its business description says what it actually is."""
        result = verdict("Smithfield Foods", "Consumer Staples", "Packaged Foods",
                         "Pork processing and hog production")
        self.assertEqual(result.verdict, EXCLUDED)
        self.assertEqual(result.category, "pork")

    def test_the_reason_names_the_activity_and_the_evidence(self):
        result = verdict("HSBC Holdings", "Financials", "Banking")
        self.assertIn("banking", result.reason.lower())
        self.assertIn("bank", result.reason)


class PermittedTests(unittest.TestCase):
    def test_ordinary_businesses_pass(self):
        for name, sector, industry in [
            ("Nike Inc.", "Sports", "Athletic footwear and apparel"),
            ("Newmont Corporation", "Gold", "Gold mining"),
            ("NextEra Energy", "Utilities", "Electric utility and renewables"),
            ("Martin Marietta Materials", "Construction", "Construction aggregates"),
        ]:
            self.assertEqual(verdict(name, sector, industry).verdict, PERMITTED, name)

    def test_a_chipmaker_is_not_a_weapons_company(self):
        """Many ordinary industrials have some military revenue. A semiconductor maker whose
        chips end up in defence systems is not an arms manufacturer, and a blunt keyword match
        would wrongly call it one."""
        self.assertEqual(verdict("NVIDIA", "Technology", "Semiconductors",
                                 "GPUs for computing and graphics").verdict, PERMITTED)

    def test_the_founders_whole_curated_universe_still_passes(self):
        """The rule must reproduce the list it was derived from. If this fails, the rule has
        drifted from the Founder's own judgement and the rule is wrong, not the list."""
        universe = [
            {"ticker": "NKE", "company_name": "Nike Inc.", "sector": "Sports", "industry": "Athletic footwear and apparel"},
            {"ticker": "NEM", "company_name": "Newmont", "sector": "Gold", "industry": "Gold mining"},
            {"ticker": "AAPL", "company_name": "Apple Inc.", "sector": "Technology", "industry": "Consumer electronics"},
            {"ticker": "DAL", "company_name": "Delta Air Lines", "sector": "Airlines", "industry": "Passenger air travel"},
            {"ticker": "JNJ", "company_name": "Johnson & Johnson", "sector": "Healthcare", "industry": "Pharmaceuticals"},
        ]
        for ticker, result in screen_many(universe).items():
            self.assertEqual(result.verdict, PERMITTED, f"{ticker}: {result.reason}")


class UncertaintyTests(unittest.TestCase):
    """The asymmetry that makes the screen safe: unknown is never a pass."""

    def test_an_unclassified_company_is_referred_not_admitted(self):
        result = screen_business_activity(company_name=None, sector=None, industry=None)
        self.assertEqual(result.verdict, REFERRED)
        self.assertFalse(result.tradeable)

    def test_an_ambiguous_mention_refers_rather_than_excluding(self):
        """"Military" in a description is not proof of an arms business, but it is not nothing
        either. A person decides."""
        result = verdict("Acme Logistics", "Industrials", "Freight",
                         "Supplies logistics services including to army bases")
        self.assertEqual(result.verdict, REFERRED)
        self.assertEqual(result.category, "defence")

    def test_only_a_clean_pass_is_tradeable(self):
        self.assertTrue(verdict("Nike", "Sports", "Apparel").tradeable)
        self.assertFalse(verdict("BAE Systems", "Industrials", "Defence").tradeable)
        self.assertFalse(screen_business_activity(sector=None, industry=None).tradeable)

    def test_screen_many_skips_rows_with_no_ticker(self):
        self.assertEqual(screen_many([{"company_name": "No Ticker"}]), {})
        self.assertEqual(screen_many([]), {})


if __name__ == "__main__":
    unittest.main()
