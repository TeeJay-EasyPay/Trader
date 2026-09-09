"""September 9 audit regressions: no live database, broker, or AI calls."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_trader.api import LocalApiService
from ai_trader import production_evidence, strategy_performance
from ai_trader.learning_readiness import assess_learning_readiness, readiness_from_outcomes
from ai_trader.proposal_context import _serialize_historical_analogues


def test_real_closed_loop_outcomes_reach_prompt_with_fee_basis():
    text = _serialize_historical_analogues({
        "comparable_cases": 1,
        "similar_historical_situations": [{
            "symbol": "TEST", "broker": "kraken",
            "result_context_json": json.dumps({"profit_loss": 1.2, "gross_realized_pnl": 1.2,
                                                "net_realized_pnl": -0.4}),
        }],
    })
    assert "net_realized_pnl=-0.4" in text
    assert "gross_realized_pnl=1.2" in text
    assert "broker=kraken" in text
    assert "outcome=win" not in text


def test_missing_net_result_is_not_invented_and_zero_is_preserved():
    def serialize(result):
        return _serialize_historical_analogues({"comparable_cases": 1,
            "similar_historical_situations": [{"symbol": "TEST", "result_context_json": json.dumps(result)}]})
    assert "net result unavailable" in serialize({"profit_loss": 1})
    assert "net_realized_pnl=0" in serialize({"profit_loss": 1, "net_realized_pnl": 0})
    assert "pnl=0" in serialize({"pnl": 0, "outcome": "break_even"})


def test_scheduled_self_assessment_has_no_standup_callback_dependency():
    service = SimpleNamespace(settings=SimpleNamespace(
        db_path=Path("unused.sqlite3"), openai_api_key=None,
    ))
    with patch("ai_trader.api.input_inventory", return_value={"feeds": []}) as inventory, \
         patch("ai_trader.api.record_self_assessment", return_value={"status": "openai_not_configured"}) as record:
        assert LocalApiService.run_self_assessment(service)["status"] == "openai_not_configured"
    inventory.assert_called_once()
    assert record.call_args.kwargs["inventory"] == {"feeds": []}


def test_scheduled_self_assessment_success_uses_one_inventory_and_ai_call():
    service = SimpleNamespace(settings=SimpleNamespace(
        db_path=Path("unused.sqlite3"), openai_api_key="test-only", openai_reasoning_model="test",
    ))
    with patch("ai_trader.api.input_inventory", return_value={"feeds": []}) as inventory, \
         patch("ai_trader.api.OpenAIReadOnlyExplainer") as explainer, \
         patch("ai_trader.api._record_daily_checkin") as checkin, \
         patch("ai_trader.api.record_self_assessment", return_value={"status": "answered"}):
        explainer.return_value.answer.return_value = "Insufficient evidence."
        assert LocalApiService.run_self_assessment(service)["status"] == "answered"
    inventory.assert_called_once()
    explainer.return_value.answer.assert_called_once()
    checkin.assert_called_once()


def test_snapshot_query_returns_only_latest_per_broker_with_tie_break(tmp_path):
    queries = []
    def capture(_db, batch, **kwargs):
        queries.extend(sql for sql, _values in batch)
        return [[] for _ in batch]
    with patch.object(production_evidence, "_query_batch", side_effect=capture):
        production_evidence._load_founder_evidence_rows(tmp_path / "unused", since="2026", trade_limit=10)
    query = next(sql for sql in queries if "FROM PRODUCTION_BROKER_SNAPSHOTS" in sql)
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(production_evidence.SQLITE_SCHEMA)
        for index in range(25):
            conn.execute("""INSERT INTO PRODUCTION_BROKER_SNAPSHOTS
                (idempotency_key,captured_at,broker,connection_status,positions_json,payload_json)
                VALUES (?,?,?,?,?,?)""", (str(index), "2026-09-09", "alpaca", "ok", "[]", json.dumps({"index": index})))
        conn.execute("""INSERT INTO PRODUCTION_BROKER_SNAPSHOTS
            (idempotency_key,captured_at,broker,connection_status,positions_json,payload_json)
            VALUES ('quiet','2026-09-01','kraken','ok','[]','{"quiet":true}')""")
        rows = [dict(row) for row in conn.execute(query)]
        assert len(rows) == 2
        assert rows[0]["broker"] == "alpaca"
        assert json.loads(rows[0]["payload_json"])["index"] == 24
        assert rows[1]["broker"] == "kraken"
        conn.execute("DELETE FROM PRODUCTION_BROKER_SNAPSHOTS WHERE broker='kraken'")
        assert len(conn.execute(query).fetchall()) == 1
        conn.execute("DELETE FROM PRODUCTION_BROKER_SNAPSHOTS")
        assert conn.execute(query).fetchall() == []


def test_strategy_reuses_outcome_read_without_weakening_readiness(tmp_path):
    db = tmp_path / "learning.sqlite3"
    stamp = datetime.now(timezone.utc).isoformat()
    rows = [("TEST", float(i - 2), 101.0, stamp, stamp) for i in range(5)]
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE PERFORMANCE_ATTRIBUTION
            (symbol TEXT,profit_loss REAL,exit_price REAL,closed_at TEXT,created_at TEXT,
             proposal_id TEXT,entry_price REAL,quantity REAL)""")
        conn.execute("CREATE TABLE TRADE_AUDIT (proposal_id TEXT,event_type TEXT,payload_json TEXT)")
        for i, row in enumerate(rows):
            conn.execute("INSERT INTO PERFORMANCE_ATTRIBUTION VALUES (?,?,?,?,?,?,?,?)", (*row,str(i),100,1))
            conn.execute("INSERT INTO TRADE_AUDIT VALUES (?,'agent_proposal',?)",
                         (str(i), json.dumps({"proposal": {"strategy_id": "test", "stop_loss": 98}})))
    assert assess_learning_readiness(db) == readiness_from_outcomes(rows)
    queries = []
    def traced_connect(path):
        conn = sqlite3.connect(path)
        conn.set_trace_callback(queries.append)
        return conn
    with patch.object(strategy_performance, "connect", side_effect=traced_connect):
        record = strategy_performance.strategy_records(db)["test"]
    assert record.sample_size == 5
    assert record.win_rate == 0.4
    assert record.average_r == 0
    assert len([q for q in queries if "FROM PERFORMANCE_ATTRIBUTION" in q]) == 1
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE PERFORMANCE_ATTRIBUTION SET exit_price=NULL")
    queries.clear()
    with patch.object(strategy_performance, "connect", side_effect=traced_connect):
        assert strategy_performance.strategy_records(db) == {}
    assert not any("FROM TRADE_AUDIT" in q for q in queries)
