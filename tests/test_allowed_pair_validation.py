"""2026-08-22: the Founder widened KRAKEN_ALLOWED_PAIRS from 3 pairs to 10, but four of them
-- BTCGBP (Kraken calls Bitcoin XBT), BNBGBP, TRXGBP, HBARGBP -- are not real Kraken GBP
pairs. Nothing anywhere said so, so 40% of the AI's search universe silently did nothing and
a deliberate widening delivered 6 tradeable coins instead of 10.

This was the fourth setting in one day that looked applied and was quietly inert, so the
check exists to make the failure visible rather than something discovered by accident.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.broker_adapters import KrakenAdapter


REAL_PAIRS = {
    "result": {
        "XXBTZGBP": {"altname": "XBTGBP", "status": "online"},
        "XETHZGBP": {"altname": "ETHGBP", "status": "online"},
        "SOLGBP": {"altname": "SOLGBP", "status": "online"},
        "ADAGBP": {"altname": "ADAGBP", "status": "online"},
        "DELISTEDGBP": {"altname": "DELISTEDGBP", "status": "delisted"},
    }
}


def adapter_with(pairs_env, response=REAL_PAIRS, raises=None):
    adapter = KrakenAdapter()

    def fake_public(path):
        if raises:
            raise raises
        return response

    adapter._public_request = fake_public
    return adapter, mock.patch.dict(os.environ, {"KRAKEN_ALLOWED_PAIRS": pairs_env})


class UnlistableAllowedPairTests(unittest.TestCase):
    def test_it_names_exactly_the_pairs_kraken_does_not_list(self):
        adapter, env = adapter_with("XBTGBP,ETHGBP,BTCGBP,BNBGBP,TRXGBP,HBARGBP")
        with env:
            self.assertEqual(
                adapter.unlistable_allowed_pairs(),
                ["BNBGBP", "BTCGBP", "HBARGBP", "TRXGBP"],
                "These are the four the Founder actually had configured and that silently did nothing.",
            )

    def test_a_fully_valid_list_reports_an_empty_list_not_none(self):
        """Empty means 'checked, all real'. None means 'could not check'. Collapsing the two
        would turn a broken check into a false all-clear."""
        adapter, env = adapter_with("XBTGBP,ETHGBP,SOLGBP,ADAGBP")
        with env:
            self.assertEqual(adapter.unlistable_allowed_pairs(), [])

    def test_kraken_canonical_names_are_accepted_as_well_as_altnames(self):
        adapter, env = adapter_with("XXBTZGBP,XETHZGBP")
        with env:
            self.assertEqual(adapter.unlistable_allowed_pairs(), [])

    def test_a_delisted_pair_counts_as_not_tradeable(self):
        adapter, env = adapter_with("XBTGBP,DELISTEDGBP")
        with env:
            self.assertEqual(adapter.unlistable_allowed_pairs(), ["DELISTEDGBP"])

    def test_a_failed_lookup_returns_none_rather_than_a_false_all_clear(self):
        adapter, env = adapter_with("XBTGBP,BNBGBP", raises=RuntimeError("kraken down"))
        with env:
            self.assertIsNone(adapter.unlistable_allowed_pairs())

    def test_an_empty_response_returns_none_rather_than_condemning_every_pair(self):
        adapter, env = adapter_with("XBTGBP,ETHGBP", response={"result": {}})
        with env:
            self.assertIsNone(
                adapter.unlistable_allowed_pairs(),
                "An empty pair list means the lookup failed, not that every configured pair is fake.",
            )

    def test_the_pair_list_is_fetched_once_per_adapter_not_once_per_check(self):
        adapter = KrakenAdapter()
        calls = []

        def counting(path):
            calls.append(path)
            return REAL_PAIRS

        adapter._public_request = counting
        with mock.patch.dict(os.environ, {"KRAKEN_ALLOWED_PAIRS": "XBTGBP,BNBGBP"}):
            adapter.unlistable_allowed_pairs()
            adapter.unlistable_allowed_pairs()
            adapter.unlistable_allowed_pairs()
        self.assertEqual(len(calls), 1, "Pair listings do not change within a process lifetime.")

    def test_the_panel_helper_never_raises_on_an_adapter_without_the_method(self):
        from ai_trader.application.broker_service import _kraken_unlistable_allowed_pairs

        class Bare:
            pass

        class Exploding:
            def unlistable_allowed_pairs(self):
                raise RuntimeError("boom")

        self.assertIsNone(_kraken_unlistable_allowed_pairs(Bare()))
        self.assertIsNone(_kraken_unlistable_allowed_pairs(Exploding()))


if __name__ == "__main__":
    unittest.main()
