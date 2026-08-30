"""The app must not believe it holds what the exchange says it does not.

2026-08-30, Founder-directed: "how do we ensure no phantom positions open up again... why
can't the app tell the positions are not real. shouldn't it have a check for that?"

There was no such check. Found live: a BCH managed exit open for 8 days at 0.0126 BCH,
against a real Kraken balance of 0.00000005 -- sold long before, never closed out.

The dangerous failure here is the opposite of the one being fixed: closing a REAL position
because a balance read failed would abandon its trailing stop on live money. So the tests
below spend most of their attention on the cases where the check must do nothing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ai_trader.multi_broker import (
    initialize_multi_broker_schema,
    open_managed_exits,
    record_managed_trade_exit,
)
from ai_trader.position_reconciliation import reconcile_open_positions


class _Adapter:
    """Stands in for the Kraken adapter. `balances=None` means the read failed."""

    def __init__(self, balances):
        self._balances = balances
        self.calls = 0

    def get_account(self):
        self.calls += 1
        if self._balances is None:
            raise RuntimeError("Kraken is unreachable")
        return {"balances": self._balances}


def _db(tmp: str) -> Path:
    db_path = Path(tmp) / "recon.db"
    initialize_multi_broker_schema(db_path)
    return db_path


def _open_position(db_path: Path, symbol: str, quantity: float) -> None:
    record_managed_trade_exit(
        db_path,
        broker="kraken",
        symbol=symbol,
        side="buy",
        quantity=quantity,
        entry_order_id=None,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        payload={},
    )


def test_a_position_the_exchange_does_not_hold_is_closed():
    """The live case: the app thinks it holds BCH, Kraken reports dust."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _db(tmp)
        _open_position(db_path, "BCH", 0.0126)
        result = reconcile_open_positions(db_path, _Adapter({"BCH": "0.00000005"}))
        assert len(result["closed"]) == 1, result
        assert result["closed"][0]["symbol"] == "BCH"
        assert open_managed_exits(db_path, "kraken") == [], "the slot must be freed"


def test_a_position_the_exchange_confirms_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _db(tmp)
        _open_position(db_path, "SOL", 0.30)
        result = reconcile_open_positions(db_path, _Adapter({"SOL": "0.3024"}))
        assert result["closed"] == []
        assert len(open_managed_exits(db_path, "kraken")) == 1


def test_an_unreadable_balance_changes_nothing():
    """Unknown is not zero.

    Acting on a failed read would close real positions and abandon their trailing stops on
    live money -- far worse than leaving a stale row for an hour until the next check.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _db(tmp)
        _open_position(db_path, "SOL", 0.30)
        result = reconcile_open_positions(db_path, _Adapter(None))
        assert result["status"] == "skipped"
        assert result["closed"] == []
        assert len(open_managed_exits(db_path, "kraken")) == 1, "a real position must survive"


def test_a_partially_sold_position_is_kept():
    """Most of it is gone but some remains -- that is still a position, not a phantom."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _db(tmp)
        _open_position(db_path, "ETH", 1.0)
        result = reconcile_open_positions(db_path, _Adapter({"ETH": "0.4"}))
        assert result["closed"] == []
        assert len(open_managed_exits(db_path, "kraken")) == 1


def test_a_symbol_missing_from_the_balance_list_entirely_is_closed():
    """Kraken omits zero balances for some assets rather than reporting 0."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _db(tmp)
        _open_position(db_path, "GRT", 50.0)
        result = reconcile_open_positions(db_path, _Adapter({"SOL": "0.3"}))
        assert len(result["closed"]) == 1
        assert result["closed"][0]["symbol"] == "GRT"


def test_it_never_opens_a_position_the_app_did_not_know_about():
    """One-directional by design.

    Kraken is the Founder's personal account. An unexplained balance is his own holding far
    more often than a missed fill, and inventing a managed position over his own coins --
    complete with a trailing stop that would sell them -- is a much worse failure than
    leaving a stale row.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _db(tmp)
        result = reconcile_open_positions(
            db_path, _Adapter({"SHIB": "21460879", "LUNA": "518786", "QNT": "62.1"})
        )
        assert result["closed"] == []
        assert open_managed_exits(db_path, "kraken") == []
        assert result["checked"] == 0


def test_dry_run_reports_without_changing_anything():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _db(tmp)
        _open_position(db_path, "BCH", 0.0126)
        result = reconcile_open_positions(db_path, _Adapter({"BCH": "0"}), dry_run=True)
        assert len(result["closed"]) == 1
        assert len(open_managed_exits(db_path, "kraken")) == 1, "dry run must not close it"
