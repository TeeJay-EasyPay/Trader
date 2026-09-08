"""The reviewer can approve a smaller position without changing research eligibility."""
import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from ai_trader.agent import _apply_crypto_review
from ai_trader.ai import _review_from_response_text
from ai_trader.foundation import calculate_capital_allocation, load_trading_policy
from ai_trader.models import AutoTradeConfig, GuardrailConfig, TradeProposal
from ai_trader.orchestrator import InvestmentOrchestrator, _order_request
from test_crypto_ai_review import FakeReviewer, _run
from test_orchestrator import KrakenExchangeMinimumOrderTests


def review(**changes):
    return {"proceed": True, "confidence": 0.54, "size_fraction": 0.5,
            "reasoning": "Proceed with a smaller entry.", "concerns": [], **changes}


def test_research_review_storage_allocation_and_order_quantity(tmp_path):
    baseline = _run(tmp_path / "baseline.db", min_confidence=0.7)[0]
    reviewed = _run(tmp_path / "reviewed.db", FakeReviewer(review()), min_confidence=0.7)[0]
    assert reviewed.confidence_score == baseline.confidence_score
    assert reviewed.reviewer_confidence == 0.54
    assert reviewed.reviewer_size_fraction == 0.5
    restored = TradeProposal.from_dict(json.loads(json.dumps(reviewed.to_dict())))
    policy = load_trading_policy(tmp_path / "allocation.db", auto_trade=AutoTradeConfig(), guardrails=GuardrailConfig())
    full = calculate_capital_allocation(tmp_path / "allocation.db", baseline, policy, account_equity=1000)
    small = calculate_capital_allocation(tmp_path / "allocation.db", restored, policy, account_equity=1000)
    assert small["approved_notional"] == pytest.approx(full["approved_notional"] * 0.5)
    assert small["risk_amount"] == pytest.approx(full["risk_amount"] * 0.5)
    assert small["policy_ceiling_notional"] == full["policy_ceiling_notional"]
    order = _order_request(restored, small["approved_notional"])
    assert order.quantity == pytest.approx(full["approved_quantity"] * 0.5)
    assert order.stop_loss == baseline.stop_loss
    assert order.take_profit == baseline.take_profit


def test_candidate_at_floor_can_receive_an_explicit_size_reduction(tmp_path):
    baseline = replace(_run(tmp_path / "base.db", min_confidence=0.7)[0], confidence_score=0.7)
    reviewed = _apply_crypto_review(baseline, review())
    assert reviewed.confidence_score == 0.7
    assert reviewed.reviewer_size_fraction == 0.5


def test_explicit_decline_still_stops_new_contract(tmp_path):
    assert _run(tmp_path / "audit.db", FakeReviewer(review(proceed=False)), min_confidence=0.7) == []


def test_reviewer_cannot_rescue_failed_research_or_fee_gate(tmp_path):
    reviewer = FakeReviewer(review(confidence=1.0))
    assert _run(tmp_path / "research.db", reviewer, min_confidence=0.95) == []
    assert reviewer.received_candidate is None
    assert _run(tmp_path / "fees.db", reviewer, min_confidence=0.7, round_trip_fee_pct=0.2) == []
    assert reviewer.received_candidate is None


@pytest.mark.parametrize("fraction", [0, -1, 1.1, None, True, "invalid", float("nan"), float("inf")])
def test_invalid_explicit_size_is_a_decline_not_unreviewed_fallback(fraction):
    parsed = _review_from_response_text(json.dumps(review(size_fraction=fraction)))
    assert parsed is not None
    assert parsed["proceed"] is False


def test_new_contract_roundtrips_and_does_not_coerce_false_string():
    assert _review_from_response_text(json.dumps(review()))["size_fraction"] == 0.5
    assert _review_from_response_text(json.dumps(review(proceed="false")))["proceed"] is False


@pytest.mark.parametrize("missing", ["reasoning", "proceed"])
def test_incomplete_sizing_review_cannot_fall_back_to_full_size(missing):
    payload = review()
    del payload[missing]
    parsed = _review_from_response_text(json.dumps(payload))
    assert parsed is not None
    assert parsed["proceed"] is False


@pytest.mark.parametrize("minimum", [0.1, 3.5])
def test_exchange_or_configured_minimum_cannot_raise_reviewed_amount(tmp_path, minimum):
    fixture = KrakenExchangeMinimumOrderTests()
    adapter = fixture.FakeKrakenAdapter(exchange_minimum=minimum)
    orchestrator = InvestmentOrchestrator(db_path=tmp_path / "audit.db", adapters=[adapter])
    p = replace(fixture._small_crypto_proposal(), reviewer_size_fraction=0.1, reviewer_confidence=0.54)
    with patch.dict("os.environ", {"KRAKEN_MIN_ORDER_GBP": "1", "KRAKEN_MAX_ORDER_GBP": "5"}):
        decision = orchestrator.evaluate_recommendation(p, fixture._small_equity_context(), auto_execute=True)
    assert "reviewer_reduced_size_below_kraken_minimum" in decision.rejection_reason
    assert adapter.submitted_requests == []


def test_size_reduction_is_recorded_with_both_scores(tmp_path):
    from ai_trader.database import connect
    from contextlib import closing
    db = tmp_path / "audit.db"
    _run(db, FakeReviewer(review()), min_confidence=0.7)
    with closing(connect(db)) as conn:
        row = conn.execute("SELECT payload_json FROM execution_events WHERE event_type='ai_review_sizing_decision'").fetchone()
    evidence = json.loads(row[0])
    assert evidence["proceed"] is True
    assert evidence["research_confidence"] >= 0.7
    assert evidence["reviewer_confidence"] == 0.54
    assert evidence["size_fraction"] == 0.5


@pytest.mark.parametrize("contract", ["explicit_sizing_v1", "legacy_confidence", "unreviewed"])
def test_every_review_path_records_its_contract(tmp_path, contract):
    from contextlib import closing
    from ai_trader.database import connect
    payload = review()
    if contract == "legacy_confidence":
        del payload["size_fraction"]
    db = tmp_path / "audit.db"
    _run(db, None if contract == "unreviewed" else FakeReviewer(payload), min_confidence=0.7)
    with closing(connect(db)) as conn:
        rows = conn.execute("SELECT payload_json FROM execution_events WHERE event_type='ai_review_contract'").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0])["contract"] == contract


def test_review_application_failure_skips_only_failed_symbol(tmp_path):
    from contextlib import closing
    from ai_trader.agent import propose_crypto_trades
    from ai_trader.audit import AuditDatabase
    from ai_trader.database import connect
    from ai_trader.foundation import initialize_foundation_schema
    from test_crypto_ai_review import FakeAdapter, _account, _seed_score
    db = tmp_path / "audit.db"
    initialize_foundation_schema(db)
    for symbol in ("BTC", "ETH"):
        _seed_score(db, symbol)
    completed = []

    def apply(proposal, response):
        if proposal.symbol == "BTC":
            raise ValueError("injected application failure")
        return _apply_crypto_review(proposal, response)

    with patch("ai_trader.agent._apply_crypto_review", side_effect=apply):
        proposals = propose_crypto_trades(
            db, FakeAdapter(), ["BTC", "ETH"], _account(), GuardrailConfig(), AuditDatabase(db, None),
            min_confidence=0.7, requested_notional=5, default_stop_loss_pct=0.02,
            reviewer=FakeReviewer(review()), on_symbol_complete=lambda symbol, rows: completed.append((symbol, rows)),
        )
    assert [p.symbol for p in proposals] == ["ETH"]
    assert ("BTC", []) in completed
    assert proposals[0].reviewer_size_fraction == 0.5
    with closing(connect(db)) as conn:
        rows = conn.execute("SELECT payload_json FROM execution_events WHERE event_type='agent_no_trade'").fetchall()
    failures = [json.loads(row[0]) for row in rows if json.loads(row[0]).get("reason") == "ai_review_application_failed"]
    assert len(failures) == 1
    assert failures[0]["symbol"] == "BTC"
    assert failures[0]["contract"] == "explicit_sizing_v1"
