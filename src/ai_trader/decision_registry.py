"""Every trading decision, declared exactly once.

2026-09-01, P2 of the "one home per decision" work, Founder-directed after he asked whether
the app is too complicated: "so can you do P1, P2 and P3 in one go one after the other?"

WHY THIS EXISTS. Ask the app today what the minimum confidence is and there is no single
answer -- seven pieces of code each work it out for themselves, from different places. The
same is true of the position cap, the stop distance and the trade size. Measured before this
was written: 55 settings read from the environment, 29 of which are not set on either Render
service (so a literal in models.py silently rules), and 25 declared in render.yaml that are
not live anywhere. Three separate changes in one week were made, were real, and had no
effect, because something else was the actual authority.

WHAT IT DOES NOT DO YET. Nothing reads from this module. That is deliberate. If the registry
were built and switched on in one step, a single wrong value would quietly change what the
app trades and, on this week's evidence, might go unnoticed for days. So it is built dormant
and tests/test_decision_registry_parity.py asserts that for every decision below the registry
answers EXACTLY what the running code answers today. Two useful outcomes: they all match and
the registry is proven before it has any power, or one disagrees and that is another bug
found for free. It is a second speedometer, read against the first before the old one comes
out.

THE PRECEDENCE FIELD IS THE FINDING. Reading load_trading_policy closely, three different
resolution rules are in use at once:

  * most values      database first, environment as fallback
  * some values      database first, a bare literal as fallback
  * min_ai_confidence  ENVIRONMENT ONLY -- the database row was ignored entirely

Nothing announced which pattern applied where; you had to read the constructor. Each entry
below states its chain explicitly, so the inconsistency is visible rather than latent. P3
moves the storage; this module does not change the answers.

2026-09-02: the third pattern is gone. The Founder moved the confidence bar into the database
("it's not an environment variable"), so every trading number now reads database-first with
Render as a fallback. The live row was set to the value already in MIN_CONFIDENCE_SCORE
BEFORE the reader was switched, so moving the home could not move the bar.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import connect
from .foundation import _parse_value, _policy_map, initialize_foundation_schema

# ---------------------------------------------------------------------------
# Where a value may come from, most authoritative first when listed in a chain.
# ---------------------------------------------------------------------------
BROKER_POLICY = "broker_policy"      # BROKER_POLICIES, per broker
RISK_POLICY = "risk_policy"          # RISK_POLICIES
INVESTMENT_POLICY = "investment_policy"  # INVESTMENT_POLICIES
GUARDRAIL_ENV = "guardrail_env"      # GuardrailConfig, populated from Render
AUTOTRADE_ENV = "autotrade_env"      # AutoTradeConfig, populated from Render
CODE_DEFAULT = "code_default"        # a literal in this file

# Where a decision SHOULD live once P3 is done. Not used to resolve anything yet; it is the
# target state, and the thing P3 acts on.
IN_DATABASE = "database"             # a number the strategy uses
IN_RENDER = "render"                 # permission to spend real money, or machinery


@dataclass(frozen=True)
class Decision:
    """One trading decision and everything needed to resolve it."""

    name: str
    kind: str                        # float | int | bool
    summary: str                     # plain English, for the app to show the Founder
    precedence: tuple[str, ...]      # first source that holds a value wins
    default: Any
    policy_attr: str | None = None   # matching TradingPolicy field, for the parity test
    risk_key: str | None = None
    investment_key: str | None = None
    broker_key: str | None = None    # set when a broker may override
    env_attr: str | None = None      # attribute name on GuardrailConfig/AutoTradeConfig
    belongs_in: str = IN_DATABASE


@dataclass(frozen=True)
class Resolved:
    """A value and, just as importantly, where it came from."""

    name: str
    value: Any
    source: str
    broker: str | None = None

    @property
    def provenance(self) -> str:
        """One line the app can show, so a number can be asked who set it."""
        readable = {
            BROKER_POLICY: f"broker setting for {self.broker}",
            RISK_POLICY: "risk policy in the database",
            INVESTMENT_POLICY: "investment policy in the database",
            GUARDRAIL_ENV: "Render environment",
            AUTOTRADE_ENV: "Render environment",
            CODE_DEFAULT: "built-in default",
        }
        return readable.get(self.source, self.source)


# ---------------------------------------------------------------------------
# The register. One entry per decision. Nothing else may define one.
# ---------------------------------------------------------------------------
DECISIONS: tuple[Decision, ...] = (
    Decision(
        name="min_ai_confidence", kind="float", default=0.75,
        summary="How sure the AI must be before a trade is allowed.",
        # 2026-09-02: was the odd one out -- environment only, database row ignored. The
        # Founder moved it ("it's not an environment variable"), so it now reads like every
        # other trading number, with Render kept only as a fallback if the row is missing.
        precedence=(INVESTMENT_POLICY, GUARDRAIL_ENV, CODE_DEFAULT),
        policy_attr="min_ai_confidence", investment_key="minimum_overall_confidence",
        env_attr="min_confidence_score",
    ),
    Decision(
        name="max_concurrent_positions", kind="int", default=3,
        summary="How many trades may be open at once.",
        precedence=(BROKER_POLICY, RISK_POLICY, GUARDRAIL_ENV, CODE_DEFAULT),
        policy_attr="max_concurrent_positions", risk_key="maximum_concurrent_positions",
        broker_key="maximum_concurrent_positions", env_attr="max_open_positions",
    ),
    Decision(
        name="min_stop_loss_pct", kind="float", default=0.0,
        summary="The tightest a stop may be set. Below this it triggers on ordinary price noise.",
        precedence=(BROKER_POLICY, RISK_POLICY, CODE_DEFAULT),
        policy_attr="min_stop_loss_pct", risk_key="minimum_stop_loss_pct",
        broker_key="minimum_stop_loss_pct",
    ),
    Decision(
        name="min_reward_risk", kind="float", default=0.0,
        summary="The least a trade may aim to win for each pound it risks.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="min_reward_risk", risk_key="minimum_reward_risk",
    ),
    Decision(
        name="default_stop_loss_pct", kind="float", default=0.03,
        summary="How far below the buy price the stop normally sits.",
        precedence=(RISK_POLICY, AUTOTRADE_ENV, CODE_DEFAULT),
        policy_attr="default_stop_loss_pct", risk_key="default_stop_loss_pct",
        env_attr="default_stop_loss_pct",
    ),
    Decision(
        name="max_stop_loss_pct", kind="float", default=0.05,
        summary="The widest a stop may be set.",
        precedence=(RISK_POLICY, AUTOTRADE_ENV, CODE_DEFAULT),
        policy_attr="max_stop_loss_pct", risk_key="maximum_stop_loss_pct",
        env_attr="max_stop_loss_pct",
    ),
    Decision(
        name="risk_per_trade_pct", kind="float", default=0.01,
        summary="How much of the account one trade may put at risk.",
        precedence=(RISK_POLICY, GUARDRAIL_ENV, CODE_DEFAULT),
        policy_attr="risk_per_trade_pct", risk_key="risk_per_trade_pct",
        env_attr="max_risk_per_trade_pct",
    ),
    Decision(
        name="max_daily_loss_pct", kind="float", default=0.03,
        summary="How much may be lost in a day before trading stops.",
        precedence=(RISK_POLICY, GUARDRAIL_ENV, CODE_DEFAULT),
        policy_attr="max_daily_loss_pct", risk_key="maximum_daily_loss_pct",
        env_attr="max_daily_loss_pct",
    ),
    Decision(
        name="max_weekly_loss_pct", kind="float", default=0.06,
        summary="How much may be lost in a week before trading stops.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_weekly_loss_pct", risk_key="maximum_weekly_loss_pct",
    ),
    Decision(
        name="max_monthly_loss_pct", kind="float", default=0.10,
        summary="How much may be lost in a month before trading stops.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_monthly_loss_pct", risk_key="maximum_monthly_loss_pct",
    ),
    Decision(
        name="max_drawdown_pct", kind="float", default=0.15,
        summary="How far below its peak the account may fall before trading stops.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_drawdown_pct", risk_key="maximum_drawdown_pct",
    ),
    Decision(
        name="max_capital_allocation_pct", kind="float", default=0.25,
        summary="How much of the account may be at work at once.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_capital_allocation_pct", risk_key="maximum_capital_allocation_pct",
    ),
    Decision(
        name="max_concurrent_exposure_pct", kind="float", default=0.30,
        summary="Total exposure allowed across open positions.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_concurrent_exposure_pct", risk_key="maximum_concurrent_exposure_pct",
    ),
    Decision(
        name="max_position_size_pct", kind="float", default=0.05,
        summary="The largest one position may be, as a share of the account.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_position_size_pct", risk_key="maximum_position_size_pct",
    ),
    Decision(
        name="crypto_max_position_size_pct", kind="float", default=0.10,
        summary="The largest one crypto position may be, as a share of the crypto pot.",
        precedence=(RISK_POLICY, AUTOTRADE_ENV, CODE_DEFAULT),
        policy_attr="crypto_max_position_size_pct",
        risk_key="crypto_maximum_position_size_pct", env_attr="crypto_max_trade_pct",
    ),
    Decision(
        name="max_trade_pct_of_available_cash", kind="float", default=0.20,
        summary="The largest share of spare cash one trade may use.",
        precedence=(BROKER_POLICY, RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_trade_pct_of_available_cash",
        risk_key="max_trade_pct_of_available_cash", broker_key="max_trade_pct_of_available_cash",
    ),
    Decision(
        name="max_trade_absolute_gbp", kind="float", default=0.0,
        summary="A hard ceiling in pounds on any one trade. Zero means no ceiling.",
        precedence=(BROKER_POLICY, RISK_POLICY, CODE_DEFAULT),
        policy_attr="max_trade_absolute_gbp", risk_key="max_trade_absolute_gbp",
        broker_key="max_trade_absolute_gbp",
    ),
    Decision(
        name="min_investment_policy_fit", kind="float", default=0.85,
        summary="How well a company must match the Founder's permitted universe.",
        precedence=(INVESTMENT_POLICY, AUTOTRADE_ENV, CODE_DEFAULT),
        policy_attr="min_investment_policy_fit",
        investment_key="minimum_investment_policy_score", env_attr="min_philosophy_fit",
    ),
    Decision(
        name="take_profit_required", kind="bool", default=True,
        summary="Whether every trade must carry a target as well as a stop.",
        precedence=(BROKER_POLICY, RISK_POLICY, CODE_DEFAULT),
        policy_attr="take_profit_required", risk_key="take_profit_required",
        broker_key="take_profit_required",
    ),
    Decision(
        name="trailing_stop_enabled", kind="bool", default=False,
        summary="Whether the stop follows the price up.",
        precedence=(BROKER_POLICY, RISK_POLICY, CODE_DEFAULT),
        policy_attr="trailing_stop_enabled", risk_key="trailing_stop_enabled",
        broker_key="trailing_stop_enabled",
    ),
    Decision(
        name="trailing_stop_pct", kind="float", default=0.02,
        summary="How far behind the price a trailing stop follows.",
        precedence=(BROKER_POLICY, RISK_POLICY, CODE_DEFAULT),
        policy_attr="trailing_stop_pct", risk_key="trailing_stop_pct",
        broker_key="trailing_stop_pct",
    ),
    Decision(
        name="equities_leverage_multiplier", kind="float", default=1.0,
        summary="Borrowing allowed on shares. 1.0 is cash only.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="equities_leverage_multiplier", risk_key="equities_leverage_multiplier",
    ),
    Decision(
        name="emergency_shutdown_balance", kind="float", default=0.0,
        summary="The account value at which everything stops.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        policy_attr="emergency_shutdown_balance", risk_key="emergency_shutdown_balance",
    ),
    # ------------------------------------------------------------------
    # P3, 2026-09-01. Decisions that had NO database home at all until now -- they were read
    # straight from Render by broker_service.py and broker_adapters.py. They have no
    # TradingPolicy field, so policy_attr is None and the parity test checks them against the
    # seeded value rather than against load_trading_policy.
    #
    # Their readers still read Render. P4 moves those over. Until then these entries prove the
    # home exists and holds the right number.
    # ------------------------------------------------------------------
    Decision(
        name="minimum_order_gbp", kind="float", default=2.0,
        summary="The smallest order the exchange will accept, in pounds.",
        precedence=(BROKER_POLICY, CODE_DEFAULT),
        broker_key="minimum_order_gbp",
    ),
    Decision(
        name="trading_allocation_gbp", kind="float", default=500.0,
        summary="The pot the AI may trade with, kept apart from the Founder's own holdings.",
        precedence=(BROKER_POLICY, CODE_DEFAULT),
        broker_key="trading_allocation_gbp",
    ),
    Decision(
        name="buy_only_entries", kind="bool", default=True,
        summary="Whether new positions are always buys.",
        precedence=(BROKER_POLICY, CODE_DEFAULT),
        broker_key="buy_only_entries",
    ),
    Decision(
        name="limit_entries_enabled", kind="bool", default=True,
        summary="Whether to enter with a patient order to earn the lower fee.",
        precedence=(BROKER_POLICY, CODE_DEFAULT),
        broker_key="limit_entries_enabled",
    ),
    Decision(
        name="limit_entry_timeout_seconds", kind="int", default=600,
        summary="How long a patient entry waits before giving up.",
        precedence=(BROKER_POLICY, CODE_DEFAULT),
        broker_key="limit_entry_timeout_seconds",
    ),
    Decision(
        name="allowed_pairs", kind="str", default="",
        summary="The coins the AI may buy on this exchange.",
        precedence=(BROKER_POLICY, CODE_DEFAULT),
        broker_key="allowed_pairs",
    ),
    Decision(
        name="allow_short_selling", kind="bool", default=False,
        summary="Whether the AI may bet on a price falling.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        risk_key="allow_short_selling",
    ),
    Decision(
        name="crypto_risk_per_trade_pct", kind="float", default=0.01,
        summary="How much of the crypto pot one crypto trade may risk.",
        precedence=(RISK_POLICY, CODE_DEFAULT),
        risk_key="crypto_risk_per_trade_pct",
    ),
)

BY_NAME: dict[str, Decision] = {d.name: d for d in DECISIONS}


def _coerce(kind: str, value: Any) -> Any:
    if kind == "float":
        return float(value)
    if kind == "int":
        return int(value)
    if kind == "bool":
        return bool(value)
    return value


def _read_policies(db_path: Path) -> dict[str, Any]:
    """The raw material, read exactly as load_trading_policy reads it."""
    initialize_foundation_schema(db_path)
    import sqlite3

    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        risk = _policy_map(conn, "RISK_POLICIES")
        investment = _policy_map(conn, "INVESTMENT_POLICIES")
        broker: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
            "SELECT broker, policy_key, policy_value, value_type FROM BROKER_POLICIES WHERE active = 1"
        ):
            broker.setdefault(str(row["broker"]).lower(), {})[str(row["policy_key"])] = _parse_value(
                row["policy_value"], row["value_type"]
            )
    return {"risk": risk, "investment": investment, "broker": broker}


def resolve(
    decision: Decision | str,
    *,
    policies: dict[str, Any],
    guardrails: Any = None,
    auto_trade: Any = None,
    broker: str | None = None,
) -> Resolved:
    """Walk the declared chain and return the first source that holds a value.

    Returns the SOURCE as well as the value. That is the point of the whole exercise: a
    number that cannot say where it came from is a number nobody can check.
    """
    d = decision if isinstance(decision, Decision) else BY_NAME[decision]
    broker_key = str(broker or "").strip().lower()

    for source in d.precedence:
        if source == BROKER_POLICY and d.broker_key and broker_key:
            found = (policies.get("broker") or {}).get(broker_key, {})
            if d.broker_key in found and str(found[d.broker_key]).strip() not in ("", "None"):
                return Resolved(d.name, _coerce(d.kind, found[d.broker_key]), source, broker_key)
        elif source == RISK_POLICY and d.risk_key:
            risk = policies.get("risk") or {}
            if d.risk_key in risk and risk[d.risk_key] is not None:
                return Resolved(d.name, _coerce(d.kind, risk[d.risk_key]), source, broker_key or None)
        elif source == INVESTMENT_POLICY and d.investment_key:
            inv = policies.get("investment") or {}
            if d.investment_key in inv and inv[d.investment_key] is not None:
                return Resolved(d.name, _coerce(d.kind, inv[d.investment_key]), source, broker_key or None)
        elif source == GUARDRAIL_ENV and d.env_attr and guardrails is not None:
            value = getattr(guardrails, d.env_attr, None)
            if value is not None:
                return Resolved(d.name, _coerce(d.kind, value), source, broker_key or None)
        elif source == AUTOTRADE_ENV and d.env_attr and auto_trade is not None:
            value = getattr(auto_trade, d.env_attr, None)
            if value is not None:
                return Resolved(d.name, _coerce(d.kind, value), source, broker_key or None)
        elif source == CODE_DEFAULT:
            return Resolved(d.name, _coerce(d.kind, d.default), source, broker_key or None)

    return Resolved(d.name, _coerce(d.kind, d.default), CODE_DEFAULT, broker_key or None)


def resolve_all(
    db_path: Path, *, guardrails: Any = None, auto_trade: Any = None, broker: str | None = None
) -> dict[str, Resolved]:
    """Every decision at once, for the parity test and for showing the Founder."""
    policies = _read_policies(db_path)
    return {
        d.name: resolve(d, policies=policies, guardrails=guardrails, auto_trade=auto_trade, broker=broker)
        for d in DECISIONS
    }
