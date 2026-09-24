"""Explicit, reviewable contract for evidence comparability.

Operational source files change for logging, telemetry and query efficiency.  Hashing those
files made valid experiments restart even when their economic behaviour was identical.
Only this contract represents result-affecting semantics.  A change to trading decisions,
risk, prices, costs or the simulator must deliberately update the matching value here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


BASELINE_BEHAVIOUR_CONTRACT = {
    "contract_version": "paired-shadow-behaviour-v1",
    "eligibility": "recorded-pre-experiment-eligibility",
    "direction": "long-only",
    "entry": "next-verified-daily-bar-open-with-slippage",
    "exit": "stop-first-if-daily-bar-crosses-stop-and-target",
    "positioning": "cash-risk-and-five-position-cap",
    "costs": "broker-specific-frozen-bps-per-leg",
    "maximum_holding_days": 10,
    "market_data": "completed-unadjusted-source-vetted-daily-bars",
    "simulator": "daily-bar-paired-v2",
}


EVIDENCE_PROFILES = {
    # A provisional finding is useful research, never adoption authority.  Final gates
    # remain deliberately much larger and account for each market's calendar/cadence.
    "alpaca": {
        "provisional_opportunities": 15,
        "provisional_independent_days": 7,
        "provisional_symbol_days": 10,
        "final_opportunities": 45,
        "final_independent_days": 15,
        "final_symbol_days": 30,
    },
    "kraken": {
        "provisional_opportunities": 20,
        "provisional_independent_days": 7,
        "provisional_symbol_days": 12,
        "final_opportunities": 60,
        "final_independent_days": 21,
        "final_symbol_days": 40,
    },
}

# Fewer simultaneous hypotheses reduce multiple-comparison noise and make each result
# easier to interpret. Existing tests above the limit finish; only new starts are bounded.
MAX_ACTIVE_PER_BROKER = 3


def baseline_fingerprint(contract: dict | None = None) -> str:
    value = contract or BASELINE_BEHAVIOUR_CONTRACT
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evidence_profile(broker: str) -> dict:
    if broker not in EVIDENCE_PROFILES:
        raise ValueError(f"No evidence profile for {broker!r}")
    return deepcopy(EVIDENCE_PROFILES[broker])
