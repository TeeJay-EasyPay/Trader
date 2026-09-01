"""Moving a setting's home must not move its value.

2026-09-01, P3 of the "one home per decision" work.

P3 gives the trading numbers that only ever lived in Render a home in the database. The one
thing that must not happen is a value changing on the way across -- that would be a silent
strategy change disguised as a refactor, which is the exact failure mode this whole project
exists to stop.

So the live Render values at the time of the move are written down here as a fixture, and
these tests assert the seeded database defaults equal them. If someone later edits a default
in foundation.py believing it to be inert, this fails and says which one.

NOTHING READS THESE ROWS YET. Readers move in P4. Seeding first means the values are in place
and provably identical before any code depends on them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ai_trader.decision_registry import BROKER_POLICY, RISK_POLICY, resolve_all
from ai_trader.foundation import (
    DEFAULT_BROKER_POLICIES,
    DEFAULT_RISK_POLICIES,
    initialize_foundation_schema,
)

# Read off the two Render services on 2026-09-01, before anything was moved.
LIVE_ON_RENDER = {
    "KRAKEN_MAX_ORDER_GBP": 50.0,
    "KRAKEN_MIN_ORDER_GBP": 2.0,
    "KRAKEN_TRADING_ALLOCATION_GBP": 500.0,
    "KRAKEN_BUY_ONLY_ENTRIES": True,
    "KRAKEN_LIMIT_ENTRIES_ENABLED": True,
    "KRAKEN_LIMIT_ENTRY_TIMEOUT_SECONDS": 600,
    "KRAKEN_MAX_OPEN_TRADES": 5,
    "ALLOW_SHORT_SELLING": False,
    "CRYPTO_RISK_PER_TRADE_PCT": 0.01,
}

# The worker's list. The web service holds a different one -- see the note in foundation.py.
LIVE_KRAKEN_PAIRS = (
    "AAVEGBP,ADAGBP,ALGOGBP,ATOMGBP,BCHGBP,DOTGBP,ETHGBP,FILGBP,GRTGBP,KSMGBP,"
    "LINKGBP,LTCGBP,MINAGBP,SANDGBP,SOLGBP,SUIGBP,XBTGBP,XLMGBP,XRPGBP"
)


@pytest.fixture()
def db():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "policy.db"
        initialize_foundation_schema(path)
        yield path


def _kraken(key):
    return DEFAULT_BROKER_POLICIES["kraken"][key][0]


def test_the_kraken_numbers_seeded_at_their_live_values():
    assert _kraken("max_trade_absolute_gbp") == LIVE_ON_RENDER["KRAKEN_MAX_ORDER_GBP"]
    assert _kraken("minimum_order_gbp") == LIVE_ON_RENDER["KRAKEN_MIN_ORDER_GBP"]
    assert _kraken("trading_allocation_gbp") == LIVE_ON_RENDER["KRAKEN_TRADING_ALLOCATION_GBP"]
    assert _kraken("buy_only_entries") == LIVE_ON_RENDER["KRAKEN_BUY_ONLY_ENTRIES"]
    assert _kraken("limit_entries_enabled") == LIVE_ON_RENDER["KRAKEN_LIMIT_ENTRIES_ENABLED"]
    assert _kraken("limit_entry_timeout_seconds") == LIVE_ON_RENDER["KRAKEN_LIMIT_ENTRY_TIMEOUT_SECONDS"]
    assert _kraken("maximum_concurrent_positions") == LIVE_ON_RENDER["KRAKEN_MAX_OPEN_TRADES"]


def test_the_global_numbers_seeded_at_their_live_values():
    assert DEFAULT_RISK_POLICIES["allow_short_selling"][0] == LIVE_ON_RENDER["ALLOW_SHORT_SELLING"]
    assert DEFAULT_RISK_POLICIES["crypto_risk_per_trade_pct"][0] == LIVE_ON_RENDER["CRYPTO_RISK_PER_TRADE_PCT"]


def test_the_coin_list_is_the_worker_list():
    """The worker places the orders, so its list is the real one. Getting this wrong would
    silently add or remove coins the AI may buy."""
    assert _kraken("allowed_pairs") == LIVE_KRAKEN_PAIRS
    assert "AAVEGBP" in _kraken("allowed_pairs")
    assert "XDGGBP" not in _kraken("allowed_pairs"), "that pair is only on the web service"


def test_the_registry_resolves_them_from_the_database(db):
    """Each new decision must actually come out of the database, not fall to its default."""
    registry = resolve_all(db, broker="kraken")
    for name in (
        "minimum_order_gbp", "trading_allocation_gbp", "buy_only_entries",
        "limit_entries_enabled", "limit_entry_timeout_seconds", "allowed_pairs",
    ):
        assert registry[name].source == BROKER_POLICY, f"{name} did not resolve from BROKER_POLICIES"
    for name in ("allow_short_selling", "crypto_risk_per_trade_pct"):
        assert registry[name].source == RISK_POLICY, f"{name} did not resolve from RISK_POLICIES"


def test_the_seeded_values_survive_a_round_trip(db):
    """Written as strings, read back typed. A boolean stored as 'true' must not come back as
    the string 'true', which is truthy either way and would hide the bug."""
    registry = resolve_all(db, broker="kraken")
    assert registry["trading_allocation_gbp"].value == 500.0
    assert registry["limit_entry_timeout_seconds"].value == 600
    assert registry["buy_only_entries"].value is True
    assert registry["allow_short_selling"].value is False
    assert registry["allowed_pairs"].value.startswith("AAVEGBP,")


def test_kraken_settings_do_not_leak_to_another_broker(db):
    """Alpaca must not inherit Kraken's pot or coin list."""
    registry = resolve_all(db, broker="alpaca")
    assert registry["allowed_pairs"].value == ""
    assert registry["trading_allocation_gbp"].value == 500.0  # falls to the code default
    assert registry["trading_allocation_gbp"].source != BROKER_POLICY
