import sqlite3
from pathlib import Path

from ai_trader.alpaca_costs import (
    alpaca_fee_periods,
    estimate_alpaca_round_trip_cost,
    record_alpaca_fee_activities,
)
from ai_trader.alpaca_protection import verify_alpaca_protection
from ai_trader.canonical_trades import initialize_canonical_trade_schema


def test_fee_ledger_is_idempotent_and_period_net_uses_actual_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATABASE_BACKEND", "sqlite")
    db = tmp_path / "fees.sqlite3"
    rows = [
        {"id": "fee-1", "date": "2026-09-15", "created_at": "2026-09-15T10:00:00Z",
         "activity_sub_type": "REG", "net_amount": "-0.03", "currency": "USD"},
        {"id": "fee-2", "date": "2026-09-15", "created_at": "2026-09-15T10:00:00Z",
         "activity_sub_type": "TAF", "net_amount": "-0.01", "currency": "USD"},
    ]
    assert record_alpaca_fee_activities(db, rows)["inserted"] == 2
    assert record_alpaca_fee_activities(db, rows)["inserted"] == 0
    periods = alpaca_fee_periods(db, now_epoch=1789473600)
    assert periods["day"]["recorded_account_fees"] == 0.04
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ALPACA_ACCOUNT_FEES").fetchone()[0] == 2


def test_published_alpaca_fee_estimate_is_pennies_not_crypto_rate():
    result = estimate_alpaca_round_trip_cost(sell_notional=1000, quantity=10)
    assert result["estimated_round_trip_fee_usd"] == 0.04
    assert result["components"]["commission"] == 0


def test_continuous_protection_writes_only_on_change(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATABASE_BACKEND", "sqlite")
    db = Path(tmp_path) / "protection.sqlite3"
    initialize_canonical_trade_schema(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO LOGICAL_TRADES "
            "(logical_trade_id,proposal_id,broker,symbol,side,state,intended_quantity,original_stop,"
            "entry_filled_quantity,exit_filled_quantity,remaining_quantity,decision_context_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", "p1", "alpaca", "AAPL", "buy", "entry_filled", 2, 95, 2, 0, 2, "{}", "now", "now"),
        )
        conn.execute(
            "INSERT INTO LOGICAL_TRADE_EVENTS "
            "(logical_trade_id,stage,event_source,event_time,broker_order_id,reason,payload_json,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("t1", "entry_order_linked", "broker_submission", "now", "entry-1", "linked", "{}", "key-1"),
        )
        conn.commit()
    orders = [{"id": "stop-1", "parent_order_id": "entry-1", "type": "stop", "status": "new",
               "qty": "2", "stop_price": "95"}]
    first = verify_alpaca_protection(db, orders)
    second = verify_alpaca_protection(db, orders)
    gap = verify_alpaca_protection(db, [{**orders[0], "status": "canceled"}])
    assert first["protected"] == 1 and first["changed"] == 1
    assert second["protected"] == 1 and second["changed"] == 0
    assert gap["gaps"] == 1 and gap["changed"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ALPACA_PROTECTION_EVENTS").fetchone()[0] == 2


def test_protection_detects_undersized_stop_and_accepts_active_successor(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATABASE_BACKEND", "sqlite")
    db = Path(tmp_path) / "replacement.sqlite3"
    initialize_canonical_trade_schema(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO LOGICAL_TRADES "
            "(logical_trade_id,proposal_id,broker,symbol,side,state,intended_quantity,original_stop,"
            "entry_filled_quantity,exit_filled_quantity,remaining_quantity,decision_context_json,created_at,updated_at) "
            "VALUES ('t2','p2','alpaca','MSFT','buy','entry_filled',3,90,3,0,3,'{}','now','now')"
        )
        conn.execute(
            "INSERT INTO LOGICAL_TRADE_EVENTS "
            "(logical_trade_id,stage,event_source,event_time,broker_order_id,reason,payload_json,idempotency_key) "
            "VALUES ('t2','entry_order_linked','broker_submission','now','entry-2','linked','{}','key-2')"
        )
        conn.commit()
    undersized = {"id": "old-stop", "parent_order_id": "entry-2", "type": "stop", "status": "new", "qty": "1", "stop_price": "90"}
    assert verify_alpaca_protection(db, [undersized])["gaps"] == 1
    successor = {"id": "new-stop", "parent_order_id": "entry-2", "type": "stop", "status": "accepted", "qty": "3", "stop_price": "90"}
    result = verify_alpaca_protection(db, [{**undersized, "status": "replaced"}, successor])
    assert result["protected"] == 1
