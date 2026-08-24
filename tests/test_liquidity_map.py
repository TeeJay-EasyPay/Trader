import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.liquidity_map import (
    MAX_CONFIDENCE_PENALTY,
    MIN_WALL_DISTANCE_PCT,
    analyse_trade_tape,
    liquidity_map,
    liquidity_map_for_pair,
)


def _side(mid: float, *, below: bool, notional_by_pct: dict[float, float]) -> list[list[str]]:
    """Build book levels placing a given amount of quote-currency money at each distance.

    Prices are nudged a fifth of a band inward so each lands unambiguously inside its
    bucket -- placed exactly on a boundary, floating point drops 3.0% into the 2.5% band
    and the fixture tests arithmetic rather than behaviour.

    Fixtures here carry a full ladder of bands, not just the interesting ones: a wall is
    defined relative to the average band, so a two-band book makes the average so large
    that a genuine wall cannot clear it. Real books quote hundreds of levels.
    """
    rows: list[list[str]] = []
    for pct, notional in notional_by_pct.items():
        offset = pct + 0.2
        price = mid * (1 - offset / 100.0) if below else mid * (1 + offset / 100.0)
        rows.append([f"{price:.6f}", f"{notional / price:.6f}", "1756000000"])
    return rows


def _tape(buy: float, sell: float, price: float = 100.0) -> list[list]:
    return [
        [f"{price}", f"{buy / price}", 1756000000.0, "b", "l", ""],
        [f"{price}", f"{sell / price}", 1756000001.0, "s", "l", ""],
    ]


class LiquidityMapTests(unittest.TestCase):
    def test_the_touch_band_is_not_reported_as_a_wall(self):
        """The band against the mid always holds the tightest orders, so it clears the
        wall test on virtually every pair. Measured live on XRPGBP 2026-08-24 this
        produced "a sell wall sits just 0.0% above" -- a ceiling warning that would fire
        on everything, penalising every candidate equally, which is the same as
        penalising none of them. The real wall that day was £471k at +1.5%."""
        mid = 100.0
        book = liquidity_map(
            "XRPGBP",
            bids=_side(mid, below=True, notional_by_pct={
                0.0: 90000, 0.5: 40000, 1.0: 35000, 1.5: 296000, 2.0: 30000, 2.5: 374000, 3.0: 28000, 3.5: 26000,
            }),
            asks=_side(mid, below=False, notional_by_pct={
                0.0: 128000, 0.5: 20000, 1.0: 15000, 1.5: 471000, 2.0: 18000, 2.5: 16000, 3.0: 14000, 3.5: 15000,
            }),
            trades=_tape(50000, 50000),
        )

        self.assertNotIn(0.0, [wall["distance_pct"] for wall in book.ask_walls])
        self.assertEqual(book.nearest_ask_wall_pct, 1.5)
        self.assertTrue(all(wall["distance_pct"] >= MIN_WALL_DISTANCE_PCT for wall in book.bid_walls + book.ask_walls))

    def test_support_floor_stops_at_the_cliff_edge(self):
        """The XRP shape measured live: a shelf of real money down to about -3%, then
        £8.3k, £1.3k, £416. Below the shelf there is nothing to catch a fall, which is a
        different risk to a fall that has to eat a wall -- so the floor is where the
        money stops, not where the deepest quoted level sits."""
        mid = 100.0
        book = liquidity_map(
            "XRPGBP",
            bids=_side(mid, below=True, notional_by_pct={
                0.0: 109000, 0.5: 122000, 1.0: 150000, 1.5: 296000, 2.0: 200000, 2.5: 374000,
                3.0: 8337, 3.5: 1290, 4.0: 518, 5.0: 416,
            }),
            asks=_side(mid, below=False, notional_by_pct={
                0.5: 90000, 1.0: 95000, 1.5: 100000, 2.0: 120000, 3.0: 130000,
            }),
            trades=_tape(50000, 50000),
        )

        self.assertEqual(book.support_floor_pct, 2.5)
        pockets = [pocket["distance_pct"] for pocket in book.air_pockets_below]
        self.assertIn(3.5, pockets)
        self.assertIn(4.0, pockets)
        self.assertNotIn(2.0, pockets, "a band inside the shelf is not an air pocket")

    def test_a_book_with_nothing_underneath_is_stood_aside_from(self):
        mid = 100.0
        book = liquidity_map(
            "THINGBP",
            bids=_side(mid, below=True, notional_by_pct={0.0: 4000, 0.5: 60, 1.0: 50, 1.5: 45, 2.0: 40, 2.5: 35, 3.0: 30}),
            asks=_side(mid, below=False, notional_by_pct={0.5: 5000, 1.5: 5200, 2.5: 5400, 3.5: 5600}),
            trades=_tape(1000, 1000),
        )

        self.assertEqual(book.verdict, "avoid")
        self.assertEqual(book.confidence_penalty, MAX_CONFIDENCE_PENALTY)
        self.assertIn("nothing underneath", book.summary)

    def test_a_clean_book_is_supportive_but_never_adds_confidence(self):
        """Market structure is a risk input, not an invitation. Like the per-coin track
        record, it may only ever subtract."""
        mid = 100.0
        book = liquidity_map(
            "ETHGBP",
            bids=_side(mid, below=True, notional_by_pct={0.5: 90000, 1.5: 95000, 2.5: 100000, 3.5: 98000, 4.5: 96000}),
            asks=_side(mid, below=False, notional_by_pct={0.5: 90000, 1.5: 92000, 3.0: 95000, 4.5: 97000}),
            trades=_tape(60000, 40000),
        )

        self.assertEqual(book.verdict, "supportive")
        self.assertEqual(book.confidence_penalty, 0.0)

    def test_sellers_doing_the_hitting_lowers_conviction(self):
        mid = 100.0
        book = liquidity_map(
            "ADAGBP",
            bids=_side(mid, below=True, notional_by_pct={0.5: 90000, 1.5: 95000, 2.5: 100000, 3.5: 98000, 4.5: 96000}),
            asks=_side(mid, below=False, notional_by_pct={0.5: 90000, 1.5: 92000, 3.0: 95000, 4.5: 97000}),
            trades=_tape(20000, 80000),
        )

        self.assertEqual(book.verdict, "caution")
        self.assertGreater(book.confidence_penalty, 0.0)
        self.assertIn("sellers are the aggressors", book.summary)

    def test_executed_tape_separates_the_aggressor_from_the_resting_side(self):
        """The book is intent and can be withdrawn; the tape is money that committed.
        Reading both is what catches a wall that vanishes before anything trades."""
        tape = analyse_trade_tape(
            [
                ["1.09", "1000", 1756000000.0, "b", "l", ""],   # £1,090 buy
                ["1.08", "500", 1756000001.0, "s", "m", ""],    # £540 sell
                ["1.08", "10", 1756000002.0, "s", "l", ""],     # £10.80, below the large-trade floor
            ],
            large_trade_notional=500.0,
        )

        self.assertAlmostEqual(tape["buy_notional"], 1090.0, places=2)
        self.assertAlmostEqual(tape["sell_notional"], 550.8, places=2)
        self.assertAlmostEqual(tape["aggressor_buy_share"], 0.6643, places=3)
        self.assertEqual(len(tape["large_trades"]), 2, "only trades at or above the floor are large")

    def test_an_unreadable_book_never_blocks_a_trade(self):
        """Market structure is an extra input. Its absence must leave the decision to
        everything else rather than veto by silence."""
        class NoBookAdapter:
            def order_book(self, pair):
                return None

        class NoMethodAdapter:
            pass

        self.assertIsNone(liquidity_map_for_pair(NoBookAdapter(), "XBTGBP"))
        self.assertIsNone(liquidity_map_for_pair(NoMethodAdapter(), "XBTGBP"))

        empty = liquidity_map("XBTGBP", bids=[], asks=[], trades=None)
        self.assertEqual(empty.verdict, "unknown")
        self.assertEqual(empty.confidence_penalty, 0.0)

    def test_malformed_levels_are_dropped_not_trusted(self):
        mid = 100.0
        good = _side(mid, below=True, notional_by_pct={0.5: 90000, 1.5: 95000, 2.5: 100000, 3.5: 98000})
        book = liquidity_map(
            "XBTGBP",
            bids=[*good, ["not-a-number", "5", "1756000000"], ["0", "5", "1756000000"], []],
            asks=_side(mid, below=False, notional_by_pct={0.5: 90000, 1.5: 92000, 3.0: 95000}),
            trades=[["bad"], ["1.0", "1.0", 1756000000.0, "b", "l", ""]],
        )

        self.assertGreater(book.mid_price, 0.0)
        self.assertEqual(book.verdict, "supportive")


if __name__ == "__main__":
    unittest.main()
