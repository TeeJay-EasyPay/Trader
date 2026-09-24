import json
import sqlite3
from pathlib import Path

from ai_trader.broker_learning_packet import broker_learning_packets
from ai_trader.shadow_settlement import (
    AlpacaSettlementAdapter, KrakenSettlementAdapter, SETTLEMENT_SCHEMA_VERSION,
)


def test_broker_adapters_share_contract_but_not_market_or_cost_rules():
    kraken = KrakenSettlementAdapter().normalize({
        "shadow_trade_id": 1, "intended_broker": "kraken", "asset_type": "crypto",
        "symbol": "XRP", "intended_entry": 1, "stop_loss": .9, "take_profit": 1.2,
        "quantity": 10, "simulated_costs_json": '{"round_trip_fee_pct":0.01}',
    })
    alpaca = AlpacaSettlementAdapter().normalize({
        "shadow_trade_id": 2, "intended_broker": "alpaca", "asset_type": "equity",
        "symbol": "AAPL", "intended_entry": 100, "stop_loss": 95, "take_profit": 110,
        "quantity": 10, "simulated_costs_json": '{}',
    })
    assert kraken.schema_version == alpaca.schema_version == SETTLEMENT_SCHEMA_VERSION
    assert (kraken.market_symbol, kraken.currency, kraken.asset_class) == ("XRPGBP", "GBP", "crypto")
    assert (alpaca.market_symbol, alpaca.currency, alpaca.asset_class) == ("AAPL", "USD", "equity")
    assert KrakenSettlementAdapter().cost_r(kraken, .1) != AlpacaSettlementAdapter().cost_r(alpaca, 5)


def test_incompatible_broker_asset_schema_fails_closed():
    try:
        AlpacaSettlementAdapter().normalize({"intended_broker": "alpaca", "asset_type": "crypto",
            "symbol": "AAPL", "intended_entry": 100, "stop_loss": 95, "take_profit": 110})
    except ValueError as exc:
        assert "not supported" in str(exc)
    else:
        raise AssertionError("Cross-asset shadow record was accepted")


def test_compact_packets_keep_brokers_currencies_and_legacy_cohorts_separate(tmp_path: Path):
    db = tmp_path / "packets.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE LOGICAL_TRADES(logical_trade_id TEXT PRIMARY KEY,broker TEXT,terminal INTEGER,
          gross_pnl REAL,net_pnl REAL,broker_fee REAL,exchange_fee REAL,closed_at TEXT,
          average_exit_price REAL,exit_filled_quantity REAL);
        CREATE TABLE CLOSED_LOOP_LEARNING_RUNS(learning_run_id INTEGER PRIMARY KEY,logical_trade_id TEXT,
          status TEXT,experience_id INTEGER,review_id INTEGER,created_at TEXT);
        INSERT INTO LOGICAL_TRADES VALUES
          ('a-old','alpaca',1,5,4.9,.1,0,'2026-09-20T10:00:00+00:00',100,1),
          ('a-new','alpaca',1,3,2.9,.1,0,'2026-09-23T10:00:00+00:00',101,2),
          ('a-estimated','alpaca',1,2,NULL,NULL,NULL,'2026-09-23T11:00:00+00:00',102,10),
          ('k-new','kraken',1,-2,-3,.5,.5,'2026-09-23T11:00:00+00:00',1,10);
        INSERT INTO CLOSED_LOOP_LEARNING_RUNS VALUES
          (1,'a-new','completed',10,20,'2026-09-23T12:00:00+00:00'),
          (2,'k-new','completed',11,21,'2026-09-23T12:30:00+00:00'),
          (3,'a-estimated','completed',12,22,'2026-09-23T12:45:00+00:00');
        """)
    packet = broker_learning_packets(db)
    assert packet["brokers"]["alpaca"]["currency"] == "USD"
    assert packet["brokers"]["kraken"]["currency"] == "GBP"
    assert packet["brokers"]["alpaca"]["cohort"]["legacy_trades_retained_for_account_history"] == 1
    assert packet["brokers"]["alpaca"]["coverage"]["workflows_completed"] == 2
    assert packet["brokers"]["alpaca"]["coverage"]["evidence_complete_learning_loops"] == 1
    estimate = packet["brokers"]["alpaca"]["estimated_after_cost_results"]
    assert estimate["status"] == "estimated_not_broker_attributed"
    assert estimate["individual_results_estimated"] == 1
    assert estimate["actual_costs_known"] is False
    assert packet["brokers"]["kraken"]["after_cost_results"]["net_pnl"] == -3


def test_egress_hot_paths_are_projected_and_budgeted():
    worker = Path("src/ai_trader/experiment_worker.py").read_text()
    intelligence = Path("src/ai_trader/trading_intelligence.py").read_text()
    telemetry = Path("src/ai_trader/db_telemetry.py").read_text()
    experience = Path("src/ai_trader/experience_engine.py").read_text()
    assert "SELECT * FROM RULE_EXPERIMENTS WHERE status='shadow_running'" not in worker
    assert "'{}' AS payload_json" in intelligence
    assert "daily_row_value_budget_bytes" in telemetry and "family_breaches" in telemetry
    assert "ORDER BY experience_id DESC LIMIT 20" in experience


def test_learning_api_rebuilds_a_same_day_legacy_scorecard_shape():
    source = Path("src/ai_trader/experiment_api.py").read_text()
    assert "not isinstance(founder_learning.get('brokers'), dict)" in source
