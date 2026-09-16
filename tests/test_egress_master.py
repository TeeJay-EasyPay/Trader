import json
from pathlib import Path
from unittest.mock import patch
from ai_trader import production_evidence as p, db_telemetry as meter


def test_schema_cache_has_explicit_partition():
    source=Path("src/ai_trader/database.py").read_text()
    assert 'partition=("schema", table.lower())' in source


def test_worker_no_longer_fetches_ui_detail():
    source=Path("src/ai_trader/experiment_worker.py").read_text()
    assert "exp.detail(db" not in source
    assert "exp._load(conn, r[0])" in source


def test_common_refresh_inputs_read_once():
    rows=([],[],[{"broker":"alpaca","payload_json":"{}"}],[],[],[],[],[])
    with patch.object(p,"_accepted_order_count",return_value=0) as accepted, \
         patch.object(p,"open_managed_exits",return_value=[]) as exits, \
         patch.object(p,"daily_trading_plan_status",return_value={}) as plan:
        shared={}
        for period in ("24h","1h","7d","30d"):
            p._assemble_founder_evidence_payload(rows,period=period,db_path=Path("unused"),shared_inputs=shared)
        assert accepted.call_count==exits.call_count==plan.call_count==1
        p._assemble_founder_evidence_payload(rows,period="24h",db_path=Path("unused"))
        assert accepted.call_count==2


def test_telemetry_no_values_and_bounded(tmp_path,monkeypatch):
    monkeypatch.setattr(meter,"local_path",lambda:tmp_path/"meter.sqlite3")
    monkeypatch.setattr(meter,"_pending",{})
    label=meter.family("SELECT payload_json FROM decision_journal WHERE id=%s")
    assert label=="SELECT:decision_journal"
    for n in range(200):
        meter.record("table"+str(n),rows=1,row_bytes=5)
    assert len(meter._pending)<=65
    meter.flush()
    import sqlite3
    with sqlite3.connect(tmp_path/"meter.sqlite3") as c:
        counts=[json.loads(r[0]) for r in c.execute("select counts from usage")]
    assert sum(r["row_bytes"] for r in counts)==1000


def test_meter_binary_and_json_sizes():
    assert meter.size(memoryview(b"1234"))==4
    assert meter.size({"x":False})==len('{"x":false}')

