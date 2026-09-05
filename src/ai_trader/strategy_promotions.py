"""Founder-authorised strategy promotions, recorded in code rather than typed into the database.

WHY THIS FILE EXISTS
--------------------
Kraken executes in `micro_live` mode. Every strategy the crypto path actually assigns
(`range_trading`, `pullback`, `momentum`) sat at the Sprint 6 bootstrap default of `Paper`,
so every Kraken trade was refused with `strategy_entitlement_blocked: Strategy is not
permitted for micro_live execution`. Measured live on 2026-09-04: LTC and XRP cleared the
research bar, the liquidity markdown, every guardrail, the AI reviewer and capital
allocation (GBP 25.00 approved each) -- and died at this gate.

THE STAGE WAS NEVER EARNED. Checked before changing anything: not one of the 16 strategies
carried a `sample_size`, `expectancy`, `win_rate`, `profit_factor` or `max_drawdown`.
`STRATEGY_PROMOTION_DECISIONS` held 0 rows and `STRATEGY_BACKTEST_RESULTS` held 0 rows.
Every strategy carried the same seeded sentence -- "allowed for paper/shadow/manual testing
only until promoted on governed evidence", source "Sprint 6 bootstrap". So `Paper` was not a
judgement that these strategies are unproven and risky; it was an untouched default. The one
exception, `crypto_trend_following_2r`, had been set to Micro Live by hand with no promotion
record and its evidence text still saying paper-only -- which is precisely the "hand-set value
nobody can explain later" problem this file exists to avoid repeating.

THE FOUNDER'S REASONING, in his words: market regimes rotate, so "the trends or the
strategies that are winning may not be winning tomorrow". Promote them all and let the
existing per-proposal fit scoring decide which one is used, rather than pre-selecting a
subset that suits today's regime. That is why this is a list of eleven and not one:
`crypto_trend_following_2r` is a TREND strategy, and on 2026-09-04 crypto trend scores ran
0.40-0.55 (flat), so it lost the scoring contest every time while range/pullback/momentum won.
Promoting only the already-approved one would have left the funnel at zero trades.

WHY THIS IS NOT A LOOSENING OF RISK. The entitlement gate is one layer among many, and every
other one is untouched: the 0.70 confidence bar, the 7-day trend gate, the 24h range-position
gate, the BTC regime gate, the re-entry cooldown, the fee hurdle, the liquidity `avoid` veto,
the AI reviewer, `validate_trade_proposal`, capital allocation (GBP 25 of a GBP 50 ceiling,
5 concurrent positions, GBP 500 allocation) and the risk sentinel.

WHAT IS STILL MISSING. Demotion on live evidence. The maturity ladder's real value is not
blocking untested strategies -- it is automatically pulling one that starts losing real money,
and that does not exist yet. Until it does, promotion is one-way. This is tracked in
`governance/BACKLOG.md`.

`swing_continuation` and `volatility_expansion` are included deliberately. Both are permitted
for crypto in STRATEGY_MATURITY_REGISTRY and in STRATEGY_REGISTRY, but `_candidate_strategy_ids`
in trading_intelligence.py never offered them to a crypto proposal -- a third disagreement
between two sources of truth. That list is corrected alongside this promotion.

Idempotent by construction: a strategy already carrying `micro_live` is left alone and no
duplicate decision row is written, so this is safe to run on every boot.
"""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect
from .models import utc_now_iso

# The eleven strategies the crypto path can actually select. Equity-only strategies
# (`quality_growth`, `value_pullback`) are deliberately excluded: both are fundamentals-driven
# -- "quality company", "value zones" -- which does not translate to a coin, and the asset-type
# check would refuse them anyway.
FOUNDER_AUTHORISED_CRYPTO_MICRO_LIVE: tuple[str, ...] = (
    "crypto_trend_following_2r",
    "crypto_infrastructure_trend",
    "trend_following",
    "momentum",
    "pullback",
    "breakout",
    "range_trading",
    "mean_reversion",
    "institutional_accumulation",
    "swing_continuation",
    "volatility_expansion",
)

MICRO_LIVE_STAGE = "Micro Live"
MICRO_LIVE_MODE = "micro_live"

_REASON = (
    "Founder-authorised 2026-09-04. Kraken executes in micro_live mode, but every strategy the "
    "crypto path assigns sat at the Sprint 6 bootstrap default of Paper, so every Kraken trade was "
    "refused as strategy_entitlement_blocked. That stage was never earned: no strategy carried any "
    "sample_size, expectancy, win_rate, profit_factor or max_drawdown, and both "
    "STRATEGY_PROMOTION_DECISIONS and STRATEGY_BACKTEST_RESULTS were empty. Founder's reasoning: "
    "market regimes rotate, so the strategy winning today may not win tomorrow -- promote them all "
    "and let the existing per-proposal fit scoring choose. Every other risk layer is unchanged. "
    "Demotion on live evidence is not yet built and is the outstanding half of this."
)

_EVIDENCE_NOTE = (
    "Promoted on Founder authorisation, not on recorded performance evidence -- there was none to "
    "read. See src/ai_trader/strategy_promotions.py for the full reasoning and what is still missing."
)


def _json_list(raw: Any) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def apply_founder_crypto_micro_live_promotions(db_path: Path) -> dict[str, Any]:
    """Promote the Founder-authorised crypto strategies to Micro Live, once, with a record.

    Returns a summary rather than raising: a promotion failure must never stop the worker
    booting, matching how every other startup seed in cli.py behaves.
    """
    # Both tables are owned by other modules: the registry by sprint6, the decision log by
    # production_spine. Ensure both rather than assume a boot order -- imported here rather than
    # at module scope because both of those import from this package's lower layers.
    from .production_spine import initialize_production_spine_schema
    from .sprint6 import initialize_sprint6_schema

    initialize_sprint6_schema(db_path)
    initialize_production_spine_schema(db_path)

    promoted: list[str] = []
    already: list[str] = []
    missing: list[str] = []
    now = utc_now_iso()

    with closing(connect(db_path)) as conn:
        for strategy_id in FOUNDER_AUTHORISED_CRYPTO_MICRO_LIVE:
            row = conn.execute(
                "SELECT current_stage, permitted_modes_json FROM STRATEGY_MATURITY_REGISTRY WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
            if row is None:
                missing.append(strategy_id)
                continue
            modes = _json_list(row[1])
            if MICRO_LIVE_MODE in modes and str(row[0]) == MICRO_LIVE_STAGE:
                already.append(strategy_id)
                continue
            before = str(row[0])
            with conn:
                conn.execute(
                    """
                    UPDATE STRATEGY_MATURITY_REGISTRY
                    SET current_stage = ?, permitted_modes_json = ?, approval_authority = ?,
                        evidence_json = ?, updated_at = ?
                    WHERE strategy_id = ?
                    """,
                    (
                        MICRO_LIVE_STAGE,
                        json.dumps(sorted(set(modes) | {MICRO_LIVE_MODE})),
                        "Founder",
                        json.dumps({"plain_english": _EVIDENCE_NOTE, "source": "Founder authorisation 2026-09-04"},
                                   sort_keys=True),
                        now,
                        strategy_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO STRATEGY_PROMOTION_DECISIONS (
                        created_at, strategy_id, current_stage, proposed_stage, decision,
                        evidence_gate_status, reason, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now, strategy_id, before, MICRO_LIVE_STAGE, "approved",
                        "bypassed_no_recorded_evidence", _REASON,
                        json.dumps(
                            {
                                "basis": "founder_authorisation",
                                "performance_evidence": "none_recorded",
                                "scope": "kraken/crypto",
                                "demotion_mechanism": "not_yet_implemented",
                            },
                            sort_keys=True,
                        ),
                    ),
                )
            promoted.append(strategy_id)

    return {
        "promoted": promoted,
        "already_micro_live": already,
        "not_registered": missing,
        "status": "applied" if promoted else "no_change",
    }
