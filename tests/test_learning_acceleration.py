from copy import deepcopy
from datetime import datetime, timedelta, timezone

from ai_trader import experiments as e
from ai_trader.experiment_contract import BASELINE_BEHAVIOUR_CONTRACT, baseline_fingerprint
from ai_trader.historical_opportunities import generate, RULE_VERSION


def _bars(days=90, *, symbol="ABC"):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = []
    price = 100.0
    for day in range(days):
        opened = start + timedelta(days=day)
        price *= 1.002
        result.append({"symbol": symbol, "start": opened.isoformat(),
            "end": (opened + timedelta(days=1)).isoformat(), "open": price - .2,
            "high": price + 1, "low": price - 1, "close": price,
            "quality": "verified_unadjusted"})
    return result


def test_operational_source_edits_do_not_define_experiment_identity():
    # Regression boundary: baseline identity is an explicit contract, not a hash of
    # experiment_worker.py or other files that routinely change for egress/logging.
    assert e.baseline_fingerprint() == baseline_fingerprint()
    changed = deepcopy(BASELINE_BEHAVIOUR_CONTRACT)
    changed["costs"] = "different-result-affecting-cost-model"
    assert baseline_fingerprint(changed) != e.baseline_fingerprint()


def test_point_in_time_generator_is_labelled_bounded_and_has_no_future_dependency():
    bars = _bars()
    original = deepcopy(bars)
    first = generate(bars, "alpaca")
    assert first and bars == original
    assert all(item["evidence_kind"] == "synthetic_point_in_time_market_rule" for item in first)
    assert all(item["rule_version"] == RULE_VERSION for item in first)
    # Changing a bar after an already-produced opportunity cannot change that opportunity.
    cutoff = first[0]["time"]
    later = deepcopy(bars)
    for item in later:
        if item["start"] > cutoff:
            item.update(open=999, high=1000, low=998, close=999)
    assert generate(later, "alpaca")[0] == first[0]


def test_broker_profiles_expose_provisional_stage_but_keep_larger_final_gate():
    alpaca = e.validate_spec({"broker":"alpaca", "rule_type":"minimum_target_r",
        "threshold":2.5, "evidence_ids":[1], "hypothesis":"Test a broker-specific evidence profile safely."})
    kraken = e.validate_spec({"broker":"kraken", "rule_type":"minimum_target_r",
        "threshold":2.5, "evidence_ids":[1], "hypothesis":"Test a broker-specific evidence profile safely."})
    for spec in (alpaca, kraken):
        assert spec["provisional_opportunities"] < spec["minimum_opportunities"]
        assert spec["provisional_independent_days"] < spec["minimum_independent_days"]
        assert spec["provisional_symbol_days"] < spec["minimum_symbol_days"]
    assert alpaca["minimum_independent_days"] != kraken["minimum_independent_days"]
