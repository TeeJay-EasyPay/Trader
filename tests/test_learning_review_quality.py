from ai_trader.experience_engine import classify_trade_review

GOOD = {"guardrails_passed": True, "strongest_argument_for": "Evidence supports entry", "strongest_argument_against": "Downside remains"}


def test_net_loss_is_not_rescued_by_gross_profit():
    result = classify_trade_review({"profit_loss": 2, "net_realized_pnl": -1, "net_r": -0.1}, GOOD)
    assert result['outcome_classification'] == 'Good decision, poor outcome'


def test_missing_arguments_are_unknown_not_a_bad_decision():
    result = classify_trade_review({"net_realized_pnl": 1}, {"strategy_id": "test"})
    assert result['decision_assessment'] == 'unknown'
    assert result['net_outcome_assessment'] == 'good'


def test_unknown_fees_and_gross_only_cannot_claim_net_success():
    assert classify_trade_review({"profit_loss": 2}, GOOD)['net_outcome_assessment'] == 'unknown'
    assert classify_trade_review({"net_realized_pnl": 2, "fees_status": "unavailable"}, GOOD)['net_outcome_assessment'] == 'unknown'


def test_zero_net_does_not_fall_back_to_positive_gross_or_r():
    assert classify_trade_review({"net_realized_pnl": 0, "profit_loss": 2, "net_r": 1}, GOOD)['net_outcome_assessment'] == 'breakeven'


def test_explicit_guardrail_failure_is_distinct_from_missing_evidence():
    assert classify_trade_review({"net_realized_pnl": 2}, {"guardrails_passed": False})['decision_assessment'] == 'poor'


def test_nested_decision_evidence_and_malformed_context():
    nested = {"guardrails": {"passed": True}, "intelligence": {"committee": GOOD}}
    assert classify_trade_review({"net_realized_pnl": 1}, nested)['decision_assessment'] == 'good'
    for committee in [None, "unavailable", []]:
        assert classify_trade_review({}, {"intelligence": {"committee": committee}})['decision_assessment'] == 'unknown'


def test_nonfinite_results_are_not_evidence_of_success():
    for value in [float('nan'), float('inf'), '-inf']:
        assert classify_trade_review({"net_realized_pnl": value}, GOOD)['net_outcome_assessment'] == 'unknown'


def test_legacy_zero_aggregate_fees_cannot_override_explicitly_missing_cost_evidence(tmp_path):
    from ai_trader.operational_truth import calculate_execution_costs
    result = calculate_execution_costs(tmp_path / 'costs.db', proposal_id='p', broker='alpaca',
        symbol='AAPL', intended_entry_price=100, actual_average_entry_price=100,
        broker_fee=0, exchange_fee=0, payload={'fees_status': 'unavailable'})
    assert result['fee_status'] == 'unavailable'
    assert result['total_trading_cost'] is None
