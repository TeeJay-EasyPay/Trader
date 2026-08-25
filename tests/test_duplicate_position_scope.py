"""2026-08-25, Founder-directed: what counts as a "duplicate" position for a BUY.

Measured on the live Kraken account that morning: the wallet held 14 coins, of which only
3 were AI-managed trades (BCH, GRT, AAVE). The other 11 are the Founder's own pre-existing
holdings -- this system did not open them, does not manage them, and must never sell them.

Judging duplicates by wallet contents banned the AI from 14 of its 19 allowed pairs,
leaving it shopping in 5. That is why GRT was proposed and rejected seven times in a single
night (02:09, 02:36, 02:49, 03:02, 03:15, 03:43, 04:08) and why two trades were placed in a
full day. The AI was not short of ideas; it had almost nowhere to put them.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.guardrails import validate_trade_proposal
from ai_trader.models import AccountContext, GuardrailConfig, Position, TradeProposal


def _proposal(symbol="ETH", side="buy"):
    return TradeProposal(
        symbol=symbol, side=side, entry_price=100.0, stop_loss=95.0, take_profit=110.0,
        position_size=1, risk_percentage=0.01, confidence_score=0.9,
        news_summary="n", market_sentiment_summary="m", technical_summary="t",
        plain_english_reasoning="r", asset_type="crypto", exchange="KRAKEN",
    ).normalized()


def _account(held_symbols):
    return AccountContext(
        equity=5000.0,
        daily_realized_pnl=0.0,
        open_positions=[
            Position(symbol=symbol, qty=1.0, market_value=100.0, unrealized_pl=0.0)
            for symbol in held_symbols
        ],
    )


class DuplicatePositionScopeTests(unittest.TestCase):
    def test_a_founder_holding_no_longer_blocks_an_ai_entry(self):
        """The case that cost a day of trading: the wallet holds ETH because the Founder
        bought it, and the AI has no ETH trade of its own."""
        account = _account(["ETH", "ADA", "SOL", "XRP"])

        result = validate_trade_proposal(
            _proposal("ETH"), account, GuardrailConfig(), ai_managed_symbols={"BCH", "GRT", "AAVE"},
        )

        self.assertNotIn("duplicate_open_position", result.failures)

    def test_the_ai_still_cannot_open_a_second_trade_in_its_own_position(self):
        """The check still does its real job -- this is not permission to stack."""
        account = _account(["ETH", "BCH"])

        result = validate_trade_proposal(
            _proposal("BCH"), account, GuardrailConfig(), ai_managed_symbols={"BCH", "GRT", "AAVE"},
        )

        self.assertIn("duplicate_open_position", result.failures)

    def test_wallet_based_behaviour_is_unchanged_when_no_ai_symbols_are_supplied(self):
        """Callers that cannot tell which trades are AI-managed must behave exactly as
        before -- this widens the rule only where the caller knows enough to apply it."""
        account = _account(["ETH"])

        result = validate_trade_proposal(_proposal("ETH"), account, GuardrailConfig())

        self.assertIn("duplicate_open_position", result.failures)

    def test_selling_still_reads_the_real_wallet(self):
        """You can only sell what is actually there, whoever put it there. Scoping the
        sell check to AI-managed symbols would let the system try to sell a coin it does
        not hold -- the opposite mistake."""
        config = GuardrailConfig()
        self.assertFalse(config.allow_short_selling, "this test assumes shorting stays off")
        account = _account(["ETH"])

        # Held in the wallet but not AI-managed: selling is still permitted.
        held = validate_trade_proposal(
            _proposal("ETH", side="sell"), account, config, ai_managed_symbols=set(),
        )
        self.assertNotIn("short_selling_disabled", held.failures)

        # Not held at all: still refused, regardless of AI-managed scope.
        missing = validate_trade_proposal(
            _proposal("DOT", side="sell"), account, config, ai_managed_symbols={"DOT"},
        )
        self.assertIn("short_selling_disabled", missing.failures)

    def test_the_position_count_limit_is_untouched(self):
        """This widens where the AI may look, never how much it may hold. The real
        concentration control must still bind."""
        config = GuardrailConfig()
        account = _account([f"C{index}" for index in range(config.max_open_positions + 1)])

        result = validate_trade_proposal(
            _proposal("ETH"), account, config, ai_managed_symbols=set(),
        )

        self.assertIn("maximum_open_positions_exceeded", result.failures)


if __name__ == "__main__":
    unittest.main()
