"""Explicit decision-time economics; target odds are not confidence scores."""
import math


def number(value):
    try:
        result = float(value) if value is not None else None
        return result if result is not None and math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def decision_economics(*, entry, stop, target, fee_rate, minimum_ratio, probability=None):
    probability = probability or {}
    rate = number(fee_rate)
    risk = abs(entry-stop)
    valid = all(number(v) is not None for v in (entry, stop, target, minimum_ratio)) and entry > 0 and 0 < stop < entry < target
    known = rate is not None and rate > 0
    cost = entry*rate if valid and known else None
    ratio = (target-entry-cost)/(risk+cost) if cost is not None and risk > 0 else None
    gross_expected = number(probability.get('expected_return_r'))
    net_expected = gross_expected-cost/risk if gross_expected is not None and cost is not None and risk > 0 else None
    return {
        'version': 'decision-economics-v1', 'entry_price': entry, 'stop_loss': stop,
        'take_profit': target, 'round_trip_fee_rate': rate,
        'fee_status': 'historical_estimate' if known else 'unavailable',
        'fee_source': 'median_recorded_closed_trade_fees',
        'minimum_net_reward_risk': minimum_ratio, 'net_target_reward_risk': ratio,
        'fee_hurdle_passed': ratio is not None and ratio >= minimum_ratio,
        'model_expected_gross_r': gross_expected, 'model_expected_net_r': net_expected,
        'probability_of_target_reached': None,
        'target_probability_status': 'not_measured',
        'model_probability_of_success': number(probability.get('probability_of_success')),
        'calibration_status': probability.get('calibration_status', 'unavailable'),
        'historical_sample_size': probability.get('historical_sample_size'),
        'assumptions': 'Model expected return uses target/stop scenarios, less an estimated round-trip fee; success probability is not measured target-hit probability. Slippage and partial exits may differ.',
    }


def learning_context(context):
    """Preserve the frozen decision estimate, never recompute it using later outcomes."""
    result = dict(context or {})
    intelligence = result.get('intelligence') or {}
    economics = intelligence.get('decision_economics') if isinstance(intelligence, dict) else None
    if isinstance(economics, dict):
        result['decision_economics'] = economics
        expected = number(economics.get('model_expected_net_r'))
        if expected is not None:
            result['expected_r'] = expected
            result['expected_r_basis'] = 'decision_time_model_after_estimated_fees_not_calibrated_target_odds'
    return result
