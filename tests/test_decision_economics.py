from ai_trader.decision_economics import decision_economics, learning_context
from ai_trader.technical_discretion import clears_fee_hurdle


def test_unknown_fees_block_new_candidate():
    for rate in (0, -1, float('nan'), float('inf')):
        assert not clears_fee_hurdle(entry_price=100, stop_loss=95, take_profit=110, round_trip_fee_pct=rate)


def test_decision_snapshot_keeps_probability_honest_and_deducts_costs():
    evidence = decision_economics(entry=100, stop=95, target=110, fee_rate=.016,
        minimum_ratio=1, probability={'expected_return_r': .8, 'probability_of_success': .6})
    assert evidence['fee_hurdle_passed']
    assert abs(evidence['model_expected_net_r'] - .48) < 1e-9
    assert evidence['probability_of_target_reached'] is None
    assert evidence['model_probability_of_success'] == .6
    ctx = learning_context({'intelligence': {'decision_economics': evidence}})
    assert ctx['expected_r'] == evidence['model_expected_net_r']
    assert 'expected_r' not in learning_context({'intelligence': {'probability': {'expected_return_r': .8}}})
