from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import connect, selected_backend
from .models import TradeProposal, utc_now_iso
from .operational import safe_score
from .technical_discretion import cash_capped_notional, conviction_scaled_notional


FOUNDATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS INVESTMENT_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key TEXT NOT NULL UNIQUE,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS RISK_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key TEXT NOT NULL UNIQUE,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS BROKER_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    policy_key TEXT NOT NULL,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(broker, policy_key)
);

CREATE TABLE IF NOT EXISTS LEARNING_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key TEXT NOT NULL UNIQUE,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CAPITAL_ALLOCATION_HISTORY (
    allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    account_equity REAL NOT NULL,
    requested_notional REAL NOT NULL,
    approved_notional REAL NOT NULL,
    approved_quantity REAL NOT NULL,
    risk_amount REAL NOT NULL,
    policy_snapshot_json TEXT NOT NULL,
    result TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS DUE_DILIGENCE_ASSESSMENTS (
    assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    fundamental_status TEXT NOT NULL,
    technical_status TEXT NOT NULL,
    market_status TEXT NOT NULL,
    macro_status TEXT NOT NULL,
    behavioural_status TEXT NOT NULL,
    investment_policy_status TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    reasoning_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS INVESTMENT_SCORES (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    fundamental_score REAL NOT NULL,
    technical_score REAL NOT NULL,
    market_score REAL NOT NULL,
    macro_score REAL NOT NULL,
    behavioural_score REAL NOT NULL,
    investment_policy_score REAL NOT NULL,
    risk_score REAL NOT NULL,
    overall_confidence REAL NOT NULL,
    reasoning_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS BROKER_DECISIONS (
    broker_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    selected_broker TEXT,
    exchange TEXT NOT NULL,
    broker_healthy INTEGER NOT NULL,
    asset_available INTEGER NOT NULL,
    market_open INTEGER NOT NULL,
    result TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS EXECUTION_DECISIONS (
    execution_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    validation_result TEXT,
    order_id TEXT,
    reason TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_MASTER (
    crypto_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    source TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(symbol, category)
);

CREATE TABLE IF NOT EXISTS CRYPTO_MARKET_DATA (
    market_data_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    price_usd REAL,
    market_cap_usd REAL,
    volume_24h_usd REAL,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_DAILY_UPDATES (
    update_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    update_date TEXT NOT NULL,
    summary TEXT,
    material_change INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_PROJECT_ANALYSIS (
    analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    project_summary TEXT,
    use_case_summary TEXT,
    team_summary TEXT,
    ecosystem_summary TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_TOKENOMICS (
    tokenomics_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supply_summary TEXT,
    utility_summary TEXT,
    emissions_summary TEXT,
    concentration_risk TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_ONCHAIN_METRICS (
    onchain_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    active_addresses REAL,
    transaction_count REAL,
    network_fees_usd REAL,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_SENTIMENT (
    sentiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    sentiment_score REAL,
    sentiment_summary TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_RISK (
    risk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    risk_score REAL,
    custody_risk TEXT,
    liquidity_risk TEXT,
    regulatory_risk TEXT,
    protocol_risk TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_NEWS (
    news_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    published_at TEXT,
    title TEXT,
    summary TEXT,
    source TEXT,
    url TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_BENCHMARK_ALIGNMENT (
    alignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    benchmark_name TEXT,
    alignment_summary TEXT,
    confidence REAL,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_TRADING_HISTORY (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker TEXT,
    side TEXT,
    quantity REAL,
    price REAL,
    notional REAL,
    order_id TEXT,
    result TEXT,
    payload_json TEXT NOT NULL
);
"""


# 2026-08-29, Founder-directed. These seeds are the LAST word on the two gates -- they outrank
# both the code defaults in models.py and the Render environment variables, because
# load_trading_policy reads them first. That precedence is fine; what was not fine is that they
# disagreed with everything else and nobody knew they existed.
#
# minimum_overall_confidence sat at 0.85 while the code and Render both said 0.75, silently
# blocking every buy for a full session (117 rejections) after two other places had already been
# changed to unblock it. Seeded at 0.75 so a fresh database cannot recreate that.
#
# crypto_enabled sat at False while crypto traded live, overridden by the Kraken environment
# approval. Those three env vars (KRAKEN_TRADING_ENABLED / KRAKEN_LIVE_TRADING_APPROVED /
# KRAKEN_SUBMIT_REAL_ORDERS) remain the real-money authority; this no longer contradicts them.
#
# minimum_investment_policy_score stays at 0.85 deliberately and is NOT a tuning knob. It is the
# Shariah screen: only companies on the Founder-curated watchlist carry a rating, so anything
# else keeps TradeProposal's 0.0 default and cannot pass. Lowering this towards zero would
# silently admit companies that were never vetted -- see orchestrator.py's permission check.
DEFAULT_INVESTMENT_POLICIES: dict[str, tuple[Any, str, str]] = {
    "equities_enabled": (True, "boolean", "Permit equity research and paper trading."),
    "crypto_enabled": (True, "boolean", "Permit crypto trading. Real-money submission is separately gated by the Kraken environment approval."),
    "minimum_investment_policy_score": (0.85, "float", "Permission gate: an asset must be in the Founder-approved universe. NOT a quality score - this enforces the Shariah screen."),
    # 2026-08-29, Founder-directed: 0.85 -> 0.75 -> 0.70. The two earlier numbers were both
    # chosen against a score that was not yet a real measurement -- CRYPTO_RESEARCH_SCORES
    # returned exactly 0.850 for every coin, every hour, from 20 July to 26 August (min =
    # avg = max = 0.850 across 495 readings a day). Real scoring began on 27 August with the
    # live Kraken order-book and news-sentiment work, and honest scores run far lower: over
    # the following 56 hourly cycles only 6.6% of readings cleared 0.75, against 23.7% at
    # 0.70. Both bars found ideas in the same 30 of 56 cycles, so this widens the choice
    # within an active hour rather than adding active hours.
    #
    # NOTE: changing this line alone does NOT move a deployment that has already seeded the
    # row -- _seed_policies is INSERT OR IGNORE. Use /admin/set-investment-policy, which
    # exists for exactly this.
    # 2026-08-30, Founder-directed: RENDER now owns the confidence bar
    # (MIN_CONFIDENCE_SCORE), so this row is no longer read by load_trading_policy. It is
    # kept only so existing deployments do not lose a historical record of what it once
    # held; nothing decides a trade from it. Do not reintroduce it as a source -- the whole
    # problem was the same number living in more than one place.
    "minimum_overall_confidence": (0.70, "float", "RETIRED as a source. The live bar is MIN_CONFIDENCE_SCORE in Render."),
}

DEFAULT_RISK_POLICIES: dict[str, tuple[Any, str, str]] = {
    "maximum_capital_allocation_pct": (0.25, "float", "Maximum total capital allocation across open positions."),
    "maximum_position_size_pct": (0.05, "float", "Maximum notional size for one position as a share of equity."),
    "maximum_concurrent_exposure_pct": (0.30, "float", "Maximum concurrent exposure across autonomous positions."),
    "risk_per_trade_pct": (0.01, "float", "Maximum capital at risk per trade."),
    "maximum_daily_loss_pct": (0.03, "float", "Daily loss shutdown threshold."),
    "maximum_weekly_loss_pct": (0.06, "float", "Weekly loss shutdown threshold."),
    "maximum_monthly_loss_pct": (0.10, "float", "Monthly loss shutdown threshold."),
    "emergency_shutdown_balance": (0.0, "float", "Minimum equity before emergency shutdown."),
    # 2026-08-22, Founder-directed: a percentage size guardrail per asset class, so crypto
    # is not capped by the equities ceiling. Seeds at 10% (= GBP 50 on a GBP 500 Kraken
    # allocation). Note this default only seeds a NEW row -- if it is ever changed here,
    # an already-seeded deployment needs an explicit UPDATE via /admin/set-risk-policy.
    "crypto_maximum_position_size_pct": (0.10, "float", "Maximum share of the crypto allocation in one crypto trade."),
    # Seeds OFF at 1.0. Turning leverage on is a deliberate act via /admin/set-risk-policy,
    # never something a deploy switches on quietly -- and it does nothing unless trailing
    # stops are enabled, since the trailing stop is what bounds the loss it creates.
    "equities_leverage_multiplier": (1.0, "float", "Leverage multiplier for equities. 1.0 is cash-only."),
    "default_stop_loss_pct": (0.03, "float", "Default stop loss distance."),
    "maximum_stop_loss_pct": (0.05, "float", "Maximum permitted stop loss distance."),
    # 2026-09-01, Founder-directed after seeing losses on the first day Alpaca could hold
    # more than 5 positions. Only a MAXIMUM stop distance was ever checked, so a stop could
    # be arbitrarily TIGHT and nothing objected. Every one of the nine equity entries that
    # day sat inside the 3% default -- 0.19% to 2.39% -- and the two tightest were the two
    # that lost: JNJ stopped out 91 seconds after entry on a 0.19% stop (inside the normal
    # bid/ask jiggle of a large-cap), LLY after 6m41s on 0.77%. Those are not losing trades,
    # they are trades never given room to be right.
    #
    # 0.5% globally is a floor against the absurd, deliberately well below Kraken's own
    # 1.5% crypto_default_stop_loss_pct so real-money crypto behaviour does not change.
    # Equities get the real floor (1.5%) per broker in DEFAULT_BROKER_POLICIES below.
    "minimum_stop_loss_pct": (0.005, "float", "Minimum permitted stop loss distance. Stops tighter than this sit inside ordinary price noise and are stopped out before the idea can be tested."),
    # Reward must be at least risk. NVDA on the same day was bought risking 3.71 dollars a
    # share to make 2.78 -- a ratio of 0.75, so it had to be right 57% of the time just to
    # break even, and nothing rejected it. Crypto already refuses this via
    # crypto_min_net_reward_risk (1.0, measured AFTER fees); equities had no equivalent.
    #
    # 1.0 here provably cannot reject a Kraken trade that already passed its own gate: net
    # RR >= 1 means reward >= risk + fees, so gross RR is strictly greater than 1.
    "minimum_reward_risk": (1.0, "float", "Minimum reward-to-risk ratio. Below 1.0 the target is nearer than the stop, so wins are smaller than losses."),
    # 2026-09-01, P3. Seeded at the values live on Render at the time of writing
    # (ALLOW_SHORT_SELLING=false, CRYPTO_RISK_PER_TRADE_PCT=0.01) so the home moves and the
    # value does not. Nothing reads these yet -- that is P4.
    "allow_short_selling": (False, "boolean", "Whether the AI may bet on a price falling."),
    "crypto_risk_per_trade_pct": (0.01, "float", "How much of the crypto pot one crypto trade may risk."),
    # 2026-08-19: Founder approved native (Kraken-side) trailing stops so a stop-loss
    # keeps working even if AI Trader's own process is down or Kraken is unreachable --
    # see KrakenBrokerAdapter.place_trailing_stop_order and orchestrator.py's entry hook.
    # This default only seeds a *new* RISK_POLICIES row (see set_risk_policy_value's
    # docstring for why an already-seeded row needs an explicit UPDATE, not a code change).
    "trailing_stop_enabled": (True, "boolean", "Trailing stops require founder approval."),
    "trailing_stop_pct": (0.02, "float", "Trailing stop distance once trailing stops are enabled."),
    # 2026-08-20, Founder-requested: "there should be guard rails on the maximum percentage
    # of the available cash for each trade or max amount." Both are provided. These are a
    # share of *available cash*, which tightens as capital gets deployed -- unlike
    # maximum_position_size_pct, which is a share of total equity and does not. Strictly
    # reducing: see technical_discretion.cash_capped_notional. 0 disables the absolute cap.
    "max_trade_pct_of_available_cash": (0.20, "float", "Maximum share of currently-available cash committed to one trade."),
    "max_trade_absolute_gbp": (0.0, "float", "Hard per-trade cash ceiling; 0 disables the absolute cap."),
    "take_profit_required": (True, "boolean", "Every autonomous trade needs a take profit."),
    "maximum_concurrent_positions": (3, "integer", "Maximum open positions."),
    "maximum_drawdown_pct": (0.15, "float", "Maximum tolerated drawdown before shutdown."),
}

DEFAULT_BROKER_POLICIES: dict[str, dict[str, tuple[Any, str, str]]] = {
    "alpaca": {
        "enabled": (True, "boolean", "Alpaca Paper Trading is the primary equity broker."),
        "paper_or_sandbox_only": (True, "boolean", "Live Alpaca trading is not approved."),
        # 2026-09-01: 5 was the shared cap, sized for Kraken's 25-50 pound positions against
        # a 500 allocation. On a 101,000 dollar paper account holding ~2,500 dollar positions
        # it left 93,000 idle and refused 76 ideas in one night.
        #
        # 10, not more: 10 x 2,500 on a 101,000 account is 24.8%, which is the most the
        # existing maximum_capital_allocation_pct (25%) permits to be at work at once. A
        # first draft used 12 and the test below caught it at 29.7% -- the position count
        # must not be able to authorise more exposure than the allocation guardrail allows.
        "maximum_concurrent_positions": (10, "integer", "Alpaca may hold more positions than Kraken: bigger account, positions far smaller relative to it, and no per-trade commission. Sized to sit inside the 25% capital allocation cap."),
        # 2026-09-01: equities-specific, because the global floor above is deliberately
        # permissive so it cannot disturb Kraken. For shares the Founder's own configured
        # default_stop_loss_pct is 3%; 1.5% is half that, leaving the AI real discretion to
        # tighten a stop on a technical level while making a 0.19% stop impossible.
        "minimum_stop_loss_pct": (0.015, "float", "Equities: a stop nearer than 1.5% is inside ordinary intraday noise for a liquid share."),
    },
    "kraken": {
        "enabled": (False, "boolean", "Kraken execution requires founder approval."),
        "paper_or_sandbox_only": (True, "boolean", "Kraken trading remains disabled unless explicitly approved."),
        # Unchanged, and deliberately so: this is real money, positions are a tenth of the
        # allocation each, and 5 already represents half the sleeve at full size.
        "maximum_concurrent_positions": (5, "integer", "Kraken is real money on a small allocation; the cap stays where the Founder set it."),
        # 2026-09-01, P3 of the "one home per decision" work. These are Kraken's trading
        # numbers, seeded here at EXACTLY the values live on Render at the time of writing so
        # that moving their home cannot move their value:
        #
        #   KRAKEN_MAX_ORDER_GBP=50   KRAKEN_MIN_ORDER_GBP=2   KRAKEN_TRADING_ALLOCATION_GBP=500
        #   KRAKEN_BUY_ONLY_ENTRIES=true   KRAKEN_LIMIT_ENTRIES_ENABLED=True
        #   KRAKEN_LIMIT_ENTRY_TIMEOUT_SECONDS=600
        #
        # NOTHING READS THESE YET. P3 gives each decision a home; P4 points the readers at it.
        # Seeding first means the values are in place and provably identical before any code
        # depends on them, which is the same reason the registry was built dormant.
        "max_trade_absolute_gbp": (50.0, "float", "Largest single Kraken order in pounds."),
        "minimum_order_gbp": (2.0, "float", "Kraken will not accept an order smaller than this."),
        "trading_allocation_gbp": (500.0, "float", "The pot the AI may trade on Kraken, kept apart from the Founder's own holdings."),
        "buy_only_entries": (True, "boolean", "New Kraken positions are always buys; the AI does not open shorts."),
        "limit_entries_enabled": (True, "boolean", "Enter with a patient limit order to earn the lower maker fee."),
        "limit_entry_timeout_seconds": (600, "integer", "How long a patient entry waits before giving up."),
        # The worker's list, deliberately. The two Render services hold DIFFERENT lists (the
        # web service also allows BTCGBP and XDGGBP; the worker also allows AAVEGBP), and the
        # worker is the process that actually places orders, so its list is the real one.
        # Recorded here so there is one answer rather than two. The env drift itself is a
        # separate live defect, still to be fixed.
        "allowed_pairs": (
            "AAVEGBP,ADAGBP,ALGOGBP,ATOMGBP,BCHGBP,DOTGBP,ETHGBP,FILGBP,GRTGBP,KSMGBP,"
            "LINKGBP,LTCGBP,MINAGBP,SANDGBP,SOLGBP,SUIGBP,XBTGBP,XLMGBP,XRPGBP",
            "string",
            "The coins the AI may buy on Kraken.",
        ),
    },
    "coinbase": {
        "enabled": (False, "boolean", "Coinbase execution requires founder approval."),
        "paper_or_sandbox_only": (True, "boolean", "Coinbase trading remains disabled unless explicitly approved."),
    },
}

DEFAULT_LEARNING_POLICIES: dict[str, tuple[Any, str, str]] = {
    "continuous_learning_enabled": (True, "boolean", "Learning cycles may update knowledge tables."),
    "research_frequency_minutes": (60, "integer", "Default continuous due diligence cadence."),
    "ai_may_modify_governance": (False, "boolean", "Governance documents are founder-only."),
}


@dataclass(frozen=True)
class TradingPolicy:
    auto_trading_enabled: bool
    paper_trading_only: bool
    max_capital_allocation_pct: float
    max_position_size_pct: float
    # 2026-08-22, Founder-directed: crypto gets its own percentage ceiling instead of
    # sharing the equities one. max_position_size_pct (5%) was silently overriding the
    # dedicated crypto sizing knob, capping every Kraken trade at GBP 25 no matter what
    # crypto_max_trade_pct said -- the "limits must move together" trap again. Kept as a
    # real RISK_POLICIES value (not a hardcoded constant) so it stays tunable live, exactly
    # like the equities ceiling beside it.
    crypto_max_position_size_pct: float
    # 2026-08-22, Founder-directed: leverage for the Alpaca equities track. 1.0 means off
    # (cash-only), which is the default and what crypto always uses -- Kraken here is spot.
    # Alpaca already reports ~4x buying power against equity, so this decides how much of
    # that the AI is allowed to use, rather than granting anything new.
    equities_leverage_multiplier: float
    max_concurrent_exposure_pct: float
    risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_weekly_loss_pct: float
    max_monthly_loss_pct: float
    emergency_shutdown_balance: float
    min_ai_confidence: float
    min_investment_policy_fit: float
    default_stop_loss_pct: float
    max_stop_loss_pct: float
    trailing_stop_enabled: bool
    trailing_stop_pct: float
    max_trade_pct_of_available_cash: float
    max_trade_absolute_gbp: float
    take_profit_required: bool
    max_concurrent_positions: int
    max_drawdown_pct: float
    crypto_enabled: bool
    equities_enabled: bool
    broker_enabled: dict[str, bool]
    # Defaulted fields must come last in a dataclass, so every field below here has one.
    #
    # Per-broker overrides for max_concurrent_positions. Empty means every broker shares the
    # one number, which is how it behaved before 2026-09-01.
    broker_position_caps: dict[str, int] = field(default_factory=dict)
    # The smallest stop distance and the worst reward:risk shape a trade may have. Both
    # default to permissive values so an older database that predates these rows behaves
    # exactly as it did before, rather than silently refusing everything.
    min_stop_loss_pct: float = 0.0
    min_reward_risk: float = 0.0
    # Per-broker overrides for min_stop_loss_pct, same convention as broker_position_caps:
    # the global value is a floor against the absurd, a broker may demand more.
    broker_min_stop_loss_pct: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_trading_enabled": self.auto_trading_enabled,
            "paper_trading_only": self.paper_trading_only,
            "max_capital_allocation_pct": self.max_capital_allocation_pct,
            "max_position_size_pct": self.max_position_size_pct,
            "crypto_max_position_size_pct": self.crypto_max_position_size_pct,
            "equities_leverage_multiplier": self.equities_leverage_multiplier,
            "max_concurrent_exposure_pct": self.max_concurrent_exposure_pct,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_weekly_loss_pct": self.max_weekly_loss_pct,
            "max_monthly_loss_pct": self.max_monthly_loss_pct,
            "emergency_shutdown_balance": self.emergency_shutdown_balance,
            "min_ai_confidence": self.min_ai_confidence,
            "min_investment_policy_fit": self.min_investment_policy_fit,
            "default_stop_loss_pct": self.default_stop_loss_pct,
            "max_stop_loss_pct": self.max_stop_loss_pct,
            "trailing_stop_enabled": self.trailing_stop_enabled,
            "trailing_stop_pct": self.trailing_stop_pct,
            "max_trade_pct_of_available_cash": self.max_trade_pct_of_available_cash,
            "max_trade_absolute_gbp": self.max_trade_absolute_gbp,
            "take_profit_required": self.take_profit_required,
            "max_concurrent_positions": self.max_concurrent_positions,
            "broker_position_caps": dict(self.broker_position_caps),
            "min_stop_loss_pct": self.min_stop_loss_pct,
            "min_reward_risk": self.min_reward_risk,
            "broker_min_stop_loss_pct": dict(self.broker_min_stop_loss_pct),
            "max_drawdown_pct": self.max_drawdown_pct,
            "crypto_enabled": self.crypto_enabled,
            "equities_enabled": self.equities_enabled,
            "broker_enabled": self.broker_enabled,
        }


_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_SCHEMA_KEYS: set[str] = set()


def _schema_key(db_path: Path) -> str:
    if selected_backend() == "postgres":
        return "postgres"
    return f"sqlite:{Path(db_path).resolve()}"


def initialize_foundation_schema(db_path: Path) -> None:
    """Create schema and seed default policies once per process.

    load_trading_policy called this unconditionally, and evaluate_recommendation calls
    load_trading_policy on every candidate. Hosted evidence (2026-08-01): this single
    call cost ~15s inside a single evaluate_recommendation invocation that took ~65-70s
    total -- the largest identified individual sub-step, likely from _seed_policies
    re-inserting the full default policy set (INSERT OR IGNORE against every row) on
    every call rather than only when the tables are genuinely empty. Same fix pattern
    as kraken_reconciliation, trading_intelligence, multi_broker, and operational --
    this is the 5th occurrence.
    """

    key = _schema_key(db_path)
    if key in _INITIALIZED_SCHEMA_KEYS:
        return
    with _SCHEMA_LOCK:
        if key in _INITIALIZED_SCHEMA_KEYS:
            return
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(db_path)) as conn:
            with conn:
                conn.executescript(FOUNDATION_SCHEMA)
                _seed_policies(conn)
        _INITIALIZED_SCHEMA_KEYS.add(key)


def position_cap_for(policy: Any, broker: str | None) -> int:
    """The position cap that applies to one broker.

    Falls back to the shared cap when a broker has no explicit value, so adding a broker
    never silently grants it more room than intended -- it has to be given a cap on purpose.
    """
    caps = getattr(policy, "broker_position_caps", None) or {}
    key = str(broker or "").strip().lower()
    if key and key in caps:
        return int(caps[key])
    return int(getattr(policy, "max_concurrent_positions", 3))


def min_stop_loss_pct_for(policy: Any, broker: str | None) -> float:
    """The tightest stop one broker may set, as a share of entry price.

    Same convention as position_cap_for, with one deliberate difference: this takes the
    LARGER of the broker value and the global one. The global figure is a floor against the
    absurd that should hold everywhere; a broker may demand more room than that but must
    never be able to quietly ask for less.
    """
    floors = getattr(policy, "broker_min_stop_loss_pct", None) or {}
    shared = float(getattr(policy, "min_stop_loss_pct", 0.0) or 0.0)
    key = str(broker or "").strip().lower()
    if key and key in floors:
        try:
            return max(float(floors[key]), shared)
        except (TypeError, ValueError):
            return shared
    return shared


def reward_risk_ratio(proposal: Any) -> float | None:
    """Reward distance divided by risk distance, or None when it cannot be measured.

    None rather than 0.0 for an unmeasurable shape: a missing take-profit is already caught
    by take_profit_required, and returning a number here would make this check fail a
    proposal for the wrong reason.
    """
    try:
        entry = float(proposal.entry_price)
        stop = float(proposal.stop_loss)
        target = float(proposal.take_profit)
    except (AttributeError, TypeError, ValueError):
        return None
    if entry <= 0 or stop <= 0 or target <= 0:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return abs(target - entry) / risk


def load_trading_policy(db_path: Path, *, auto_trade: Any, guardrails: Any) -> TradingPolicy:
    initialize_foundation_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        investment = _policy_map(conn, "INVESTMENT_POLICIES")
        risk = _policy_map(conn, "RISK_POLICIES")
        brokers = {
            row["broker"]: _parse_value(row["policy_value"], row["value_type"])
            for row in conn.execute(
                "SELECT broker, policy_value, value_type FROM BROKER_POLICIES WHERE policy_key = 'enabled' AND active = 1"
            )
        }
        # 2026-09-01, Founder-directed: "what can we do to increase the number of trades that
        # can be done on alpaca."
        #
        # The position cap was ONE number shared by every broker, and it was set for Kraken
        # -- where a position is 25-50 pounds against a 500 allocation. Applied to Alpaca it
        # meant 5 positions of ~2,500 dollars on a 101,000 dollar account, so the broker that
        # is actually trading sat full with 93,000 dollars idle while 76 ideas were refused
        # overnight on maximum_open_positions_exceeded. The learning data says those are the
        # most expensive refusals we make: 19 of them, and the price moved +3.24% afterwards.
        #
        # Per-broker now, in the table that already exists for per-broker settings. A broker
        # with no explicit value keeps the shared one, so nothing changes by accident.
        broker_position_caps = {
            row["broker"]: _parse_value(row["policy_value"], row["value_type"])
            for row in conn.execute(
                "SELECT broker, policy_value, value_type FROM BROKER_POLICIES "
                "WHERE policy_key = 'maximum_concurrent_positions' AND active = 1"
            )
        }
        broker_min_stop_loss_pct = {
            row["broker"]: _parse_value(row["policy_value"], row["value_type"])
            for row in conn.execute(
                "SELECT broker, policy_value, value_type FROM BROKER_POLICIES "
                "WHERE policy_key = 'minimum_stop_loss_pct' AND active = 1"
            )
        }
    return TradingPolicy(
        auto_trading_enabled=bool(getattr(auto_trade, "enabled", False)),
        paper_trading_only=bool(getattr(guardrails, "paper_trading_only", True)),
        max_capital_allocation_pct=float(risk.get("maximum_capital_allocation_pct", 0.25)),
        max_position_size_pct=float(risk.get("maximum_position_size_pct", 0.05)),
        # Falls back to AutoTradeConfig.crypto_max_trade_pct so the crypto ceiling has ONE
        # authority: set it in models.py and it flows here, rather than a second literal
        # drifting out of step (the exact bug fixed in config.py on 2026-08-22).
        crypto_max_position_size_pct=float(
            risk.get(
                "crypto_maximum_position_size_pct",
                getattr(auto_trade, "crypto_max_trade_pct", 0.10),
            )
        ),
        equities_leverage_multiplier=float(risk.get("equities_leverage_multiplier", 1.0)),
        max_concurrent_exposure_pct=float(risk.get("maximum_concurrent_exposure_pct", 0.30)),
        risk_per_trade_pct=float(risk.get("risk_per_trade_pct", getattr(guardrails, "max_risk_per_trade_pct", 0.01))),
        max_daily_loss_pct=float(risk.get("maximum_daily_loss_pct", getattr(guardrails, "max_daily_loss_pct", 0.03))),
        max_weekly_loss_pct=float(risk.get("maximum_weekly_loss_pct", 0.06)),
        max_monthly_loss_pct=float(risk.get("maximum_monthly_loss_pct", 0.10)),
        emergency_shutdown_balance=float(risk.get("emergency_shutdown_balance", 0.0)),
        # 2026-08-30, Founder-directed: RENDER IS AUTHORITATIVE for the confidence bar.
        #
        # It previously read the INVESTMENT_POLICIES row first, so the same number lived in
        # the database, in MIN_CONFIDENCE_SCORE, and in AUTO_TRADE_MIN_CONFIDENCE -- and
        # whichever one someone edited, at least one of the others disagreed. The Founder
        # manages MIN_CONFIDENCE_SCORE in the Render dashboard and asked for that to win.
        #
        # Every gate in the app reaches its bar through this one line (research, proposal
        # validation, execution, and the reason text shown in the app), so changing the
        # source here changes it everywhere at once and nothing can drift out of step.
        #
        # A note for whoever reads this next: render.yaml is NOT what is running. It declared
        # AUTO_TRADE_MIN_CONFIDENCE (which exists on neither service) and gave
        # MIN_CONFIDENCE_SCORE as 0.85 when both services actually had 0.75. Check the
        # dashboard or the API, never the file.
        min_ai_confidence=float(getattr(guardrails, "min_confidence_score", 0.75)),
        min_investment_policy_fit=float(investment.get("minimum_investment_policy_score", getattr(auto_trade, "min_philosophy_fit", 0.85))),
        default_stop_loss_pct=float(risk.get("default_stop_loss_pct", getattr(auto_trade, "default_stop_loss_pct", 0.03))),
        max_stop_loss_pct=float(risk.get("maximum_stop_loss_pct", getattr(auto_trade, "max_stop_loss_pct", 0.05))),
        trailing_stop_enabled=bool(risk.get("trailing_stop_enabled", False)),
        trailing_stop_pct=float(risk.get("trailing_stop_pct", 0.02)),
        max_trade_pct_of_available_cash=float(risk.get("max_trade_pct_of_available_cash", 0.20)),
        max_trade_absolute_gbp=float(risk.get("max_trade_absolute_gbp", 0.0)),
        take_profit_required=bool(risk.get("take_profit_required", True)),
        max_concurrent_positions=int(risk.get("maximum_concurrent_positions", getattr(guardrails, "max_open_positions", 3))),
        broker_position_caps={k: int(v) for k, v in broker_position_caps.items() if str(v).strip() not in ("", "None")},
        min_stop_loss_pct=float(risk.get("minimum_stop_loss_pct", 0.0) or 0.0),
        min_reward_risk=float(risk.get("minimum_reward_risk", 0.0) or 0.0),
        broker_min_stop_loss_pct={
            k: float(v) for k, v in broker_min_stop_loss_pct.items() if str(v).strip() not in ("", "None")
        },
        max_drawdown_pct=float(risk.get("maximum_drawdown_pct", 0.15)),
        crypto_enabled=bool(investment.get("crypto_enabled", False)) or _kraken_crypto_policy_approved(),
        equities_enabled=bool(investment.get("equities_enabled", True)),
        broker_enabled=brokers,
    )


def set_risk_policy_value(db_path: Path, key: str, value: Any, *, updated_by: str = "founder") -> dict[str, Any]:
    """Directly update an already-seeded RISK_POLICIES row.

    2026-08-16: no writer for RISK_POLICIES existed anywhere in the codebase before
    this. _seed_policies' INSERT OR IGNORE means a code-level change to
    DEFAULT_RISK_POLICIES never reaches a row that's already been seeded -- found the
    hard way while reconciling Kraken's "max open positions" settings: MAX_OPEN_
    POSITIONS and KRAKEN_MAX_OPEN_TRADES (both env vars) were raised from 1/3 to 5,
    but orchestrator.py's auto-execution guardrail reads max_concurrent_positions
    from *this* table via load_trading_policy -- a row seeded at 3 long before
    tonight, untouched by any env var, that kept blocking every Kraken order anyway.
    Only updates a row that already exists; does not silently create a new policy
    key (a typo'd key should fail loudly, not seed a stray row).
    """
    initialize_foundation_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute("SELECT * FROM RISK_POLICIES WHERE policy_key = ?", (key,)).fetchone()
        if existing is None:
            return {"status": "not_found", "policy_key": key}
        previous_value = existing["policy_value"]
        with conn:
            conn.execute(
                "UPDATE RISK_POLICIES SET policy_value = ?, updated_at = ? WHERE policy_key = ?",
                (_stringify(value), utc_now_iso(), key),
            )
    return {
        "status": "updated",
        "policy_key": key,
        "previous_value": previous_value,
        "new_value": _stringify(value),
        "updated_by": updated_by,
    }


def set_investment_policy_value(db_path: Path, key: str, value: Any, *, updated_by: str = "founder") -> dict[str, Any]:
    """Directly update an already-seeded INVESTMENT_POLICIES row.

    2026-08-29: RISK_POLICIES got a writer on 2026-08-16 (above) for exactly this reason,
    but INVESTMENT_POLICIES never did -- even though it holds minimum_overall_confidence,
    the single most-adjusted number in the whole app and the one the Founder has asked to
    change three times. _seed_policies uses INSERT OR IGNORE, so editing
    DEFAULT_INVESTMENT_POLICIES in code does nothing to a deployment that has already
    seeded the row; the only way to move it was raw SQL against production, which is
    exactly the kind of undocumented side channel that makes a value drift out of sync
    with the code that claims to set it.

    Same contract as set_risk_policy_value: updates an existing row only, so a typo'd key
    fails loudly rather than seeding a stray policy nothing reads.
    """
    initialize_foundation_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute("SELECT * FROM INVESTMENT_POLICIES WHERE policy_key = ?", (key,)).fetchone()
        if existing is None:
            return {"status": "not_found", "policy_key": key}
        previous_value = existing["policy_value"]
        with conn:
            conn.execute(
                "UPDATE INVESTMENT_POLICIES SET policy_value = ?, updated_at = ? WHERE policy_key = ?",
                (_stringify(value), utc_now_iso(), key),
            )
    return {
        "status": "updated",
        "policy_key": key,
        "previous_value": previous_value,
        "new_value": _stringify(value),
        "updated_by": updated_by,
    }


def _crypto_theme_view_exists(conn: sqlite3.Connection, symbol: str) -> bool:
    """Whether a CURRENT theme view covers this coin, using the caller's open connection.

    Deliberately not market_themes.current_theme_view, which opens its own connection: this
    runs inside per-proposal scoring, and opening a fresh remote-Postgres connection per
    candidate is the cost class this codebase has had to fix repeatedly.

    Membership is re-derived here rather than stored, because a coin can change narrative when
    its team pivots -- see market_themes.py.
    """
    from .market_themes import CRYPTO, MAX_AGE_HOURS

    target = str(symbol or "").upper().strip()
    if not target:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS[CRYPTO])).isoformat()
    try:
        rows = conn.execute(
            """
            SELECT t.theme FROM CRYPTO_MASTER m
            JOIN MARKET_THEMES t ON t.theme = m.category
            WHERE UPPER(m.symbol) = ? AND m.active = 1
              AND t.last_updated >= ? AND t.current_outlook IS NOT NULL
            LIMIT 1
            """,
            (target, cutoff),
        ).fetchall()
    except Exception:  # noqa: BLE001 - a missing table or column must degrade, not crash
        # Deliberately broad: under Postgres this raises psycopg errors, not
        # sqlite3.OperationalError, and catching only the latter would let a schema problem
        # escape into the caller's own broad handler where it becomes a silent False.
        return False
    return bool(rows)


def _macro_context_available(conn: sqlite3.Connection, proposal: TradeProposal) -> bool:
    try:
        if proposal.asset_type == "crypto":
            # 2026-08-27, Founder-directed. This used to ask "does a research score exist for
            # this coin?", which is circular: it is checked while scoring the coin, so it was
            # always true. A macro dimension that always passes measures nothing -- it was a
            # rubber stamp contributing a full mark to every crypto verdict.
            #
            # Crypto now has real themes (market_themes.py), derived from the categories the
            # app already tracks and refreshed daily from news. Macro context means what it
            # says: a current view exists on the narrative this coin belongs to. A coin whose
            # theme has no current view simply does not get macro counted -- it is not
            # penalised, because unmeasured is not zero.
            return _crypto_theme_view_exists(conn, proposal.symbol)
        company = conn.execute(
            "SELECT sector, industry FROM COMPANY_MASTER WHERE UPPER(ticker) = UPPER(?) LIMIT 1",
            (proposal.symbol,),
        ).fetchone()
        if not company or not (company[0] or company[1]):
            return False
        keywords = {word.lower() for word in f"{company[0] or ''} {company[1] or ''}".split() if len(word) > 3}
        if not keywords:
            return False
        themes = conn.execute("SELECT theme, summary, key_drivers FROM MARKET_THEMES").fetchall()
        for theme_row in themes:
            # 2026-08-24 hosted incident: this iterated the row directly. Under SQLite a
            # row is a tuple, so that yields the three VALUES and matching works. Under
            # Postgres a row is HybridRow, a dict subclass, so iterating yields the three
            # KEYS -- the haystack became the literal string "theme summary key_drivers"
            # and no company keyword could ever match it. Every equity therefore scored
            # macro_status insufficient_data and macro_score 0, which failed due diligence
            # outright AND dragged the seven-part investment score below its minimum, so
            # Alpaca could not trade at all. Silent, backend-specific, and invisible to a
            # test suite that only runs SQLite. Indexed by position because HybridRow
            # deliberately preserves integer indexing, so this reads values on both.
            haystack = " ".join(str(theme_row[index] or "") for index in range(3)).lower()
            if any(keyword in haystack for keyword in keywords):
                return True
        return False
    except sqlite3.OperationalError:
        return False


def _behavioural_context_available(conn: sqlite3.Connection, proposal: TradeProposal) -> bool:
    try:
        if proposal.asset_type == "crypto":
            row = conn.execute(
                "SELECT sentiment FROM CRYPTO_RESEARCH_SCORES WHERE UPPER(symbol) = UPPER(?) ORDER BY score_id DESC LIMIT 1",
                (proposal.symbol,),
            ).fetchone()
            return bool(row and row[0] is not None)
        row = conn.execute(
            "SELECT COUNT(*) FROM BENCHMARK_DAILY_RESEARCH WHERE research_date = ?",
            (date.today().isoformat(),),
        ).fetchone()
        return bool(row and row[0])
    except sqlite3.OperationalError:
        return False


def create_due_diligence_assessment(db_path: Path, proposal: TradeProposal) -> dict[str, Any]:
    p = proposal.normalized()
    with closing(connect(db_path)) as probe_conn:
        macro_available = _macro_context_available(probe_conn, p)
        behavioural_available = _behavioural_context_available(probe_conn, p)
    statuses = {
        "fundamental_status": "completed" if p.news_summary else "incomplete",
        "technical_status": "completed" if p.technical_summary else "incomplete",
        "market_status": "completed" if p.market_sentiment_summary else "incomplete",
        "macro_status": "completed" if macro_available else "insufficient_data",
        "behavioural_status": "completed" if behavioural_available else "insufficient_data",
        "investment_policy_status": "completed" if p.philosophy_fit else "incomplete",
    }
    overall = "completed" if all(value == "completed" for value in statuses.values()) else "incomplete"
    reasoning = {
        "fundamental": p.news_summary,
        "technical": p.technical_summary,
        "market": p.market_sentiment_summary,
        "macro": (
            "Macro review matched against tracked market themes / crypto research scores."
            if macro_available
            else "No macro data source (matching market theme or crypto research score) was found for this symbol."
        ),
        "behavioural": (
            "Behavioural review matched against today's benchmark trader research / crypto sentiment score."
            if behavioural_available
            else "No behavioural data source (benchmark trader activity or crypto sentiment) was found for this symbol today."
        ),
        "investment_policy": f"Policy fit score: {p.philosophy_fit}",
    }
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO DUE_DILIGENCE_ASSESSMENTS (
                    created_at, proposal_id, symbol, asset_type, fundamental_status,
                    technical_status, market_status, macro_status, behavioural_status,
                    investment_policy_status, overall_status, reasoning_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    fundamental_status = excluded.fundamental_status,
                    technical_status = excluded.technical_status,
                    market_status = excluded.market_status,
                    macro_status = excluded.macro_status,
                    behavioural_status = excluded.behavioural_status,
                    investment_policy_status = excluded.investment_policy_status,
                    overall_status = excluded.overall_status,
                    reasoning_json = excluded.reasoning_json
                """,
                (
                    utc_now_iso(),
                    p.proposal_id,
                    p.symbol,
                    p.asset_type,
                    statuses["fundamental_status"],
                    statuses["technical_status"],
                    statuses["market_status"],
                    statuses["macro_status"],
                    statuses["behavioural_status"],
                    statuses["investment_policy_status"],
                    overall,
                    json.dumps(reasoning, sort_keys=True),
                ),
            )
    return {"proposal_id": p.proposal_id, **statuses, "overall_status": overall, "reasoning": reasoning}


def calculate_investment_score(db_path: Path, proposal: TradeProposal) -> dict[str, Any]:
    p = proposal.normalized()
    confidence = float(p.confidence_score or 0.0)
    fundamental = confidence if p.news_summary else 0.0
    technical = (safe_score(p.technical_summary) or confidence) if p.technical_summary else 0.0
    market = (safe_score(p.market_sentiment_summary) or confidence) if p.market_sentiment_summary else 0.0
    with closing(connect(db_path)) as probe_conn:
        macro_available = _macro_context_available(probe_conn, p)
        behavioural_available = _behavioural_context_available(probe_conn, p)
    macro = confidence if macro_available else 0.0
    behavioural = confidence if behavioural_available else 0.0
    policy = float(p.philosophy_fit or 0.0)
    stop_loss_pct = abs(p.entry_price - p.stop_loss) / p.entry_price if p.entry_price else 1.0
    risk = max(0.0, min(1.0, 1.0 - stop_loss_pct))
    # 2026-08-27: average only the dimensions that had a data source, for the same reason
    # already applied to the crypto research score. A missing source scored 0 here and dragged
    # the whole verdict down, which conflates "we checked and it looks bad" with "nobody
    # checked" -- and the two mean opposite things.
    #
    # Measured live, this penalises crypto and nothing else: equities match both a macro and a
    # behavioural source, while every crypto symbol matches behavioural but NOT macro, because
    # MARKET_THEMES has not been refreshed since 2 July. So a crypto proposal was scored as
    # though its macro backdrop had been examined and found worthless. SOL at a real 0.79 came
    # out at 0.7136 and failed the 0.75 policy gate purely on that absent seventh; counting only
    # the six that exist gives 0.8325, which is what the evidence actually supports.
    #
    # Equity scores are unchanged, because all seven dimensions are present for them.
    #
    # The stale themes are a separate, real gap. Not counting an absent measurement is honest;
    # it does not make the measurement exist, and macro remains genuinely unassessed for crypto
    # until that pipeline is fixed.
    components = [fundamental, technical, market, policy, risk]
    if macro_available:
        components.append(macro)
    if behavioural_available:
        components.append(behavioural)
    overall = round(sum(components) / len(components), 4)
    reasoning = {
        "fundamental": "News and company context reviewed." if p.news_summary else "No news/company context supplied.",
        "technical": p.technical_summary or "No technical summary supplied.",
        "market": p.market_sentiment_summary or "No market sentiment summary supplied.",
        "macro": (
            "Matched against tracked market themes / crypto research scores."
            if macro_available
            else "No macro data source found for this symbol - scored zero, not floored."
        ),
        "behavioural": (
            "Matched against today's benchmark trader research / crypto sentiment score."
            if behavioural_available
            else "No behavioural data source found for this symbol today - scored zero, not floored."
        ),
        "investment_policy": "Compared with Founder-approved policy and universe.",
        "risk": f"Stop loss distance is {stop_loss_pct:.4f}.",
    }
    score = {
        "proposal_id": p.proposal_id,
        "symbol": p.symbol,
        "fundamental_score": round(float(fundamental), 4),
        "technical_score": round(float(technical), 4),
        "market_score": round(float(market), 4),
        "macro_score": round(float(macro), 4),
        "behavioural_score": round(float(behavioural), 4),
        "investment_policy_score": round(float(policy), 4),
        "risk_score": round(float(risk), 4),
        "overall_confidence": overall,
        "reasoning": reasoning,
    }
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO INVESTMENT_SCORES (
                    created_at, proposal_id, symbol, fundamental_score, technical_score,
                    market_score, macro_score, behavioural_score, investment_policy_score,
                    risk_score, overall_confidence, reasoning_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    fundamental_score = excluded.fundamental_score,
                    technical_score = excluded.technical_score,
                    market_score = excluded.market_score,
                    macro_score = excluded.macro_score,
                    behavioural_score = excluded.behavioural_score,
                    investment_policy_score = excluded.investment_policy_score,
                    risk_score = excluded.risk_score,
                    overall_confidence = excluded.overall_confidence,
                    reasoning_json = excluded.reasoning_json
                """,
                (
                    utc_now_iso(),
                    p.proposal_id,
                    p.symbol,
                    score["fundamental_score"],
                    score["technical_score"],
                    score["market_score"],
                    score["macro_score"],
                    score["behavioural_score"],
                    score["investment_policy_score"],
                    score["risk_score"],
                    score["overall_confidence"],
                    json.dumps(reasoning, sort_keys=True),
                ),
            )
    return score


def validate_investment_universe(db_path: Path, proposal: TradeProposal, policy: TradingPolicy) -> list[str]:
    p = proposal.normalized()
    failures: list[str] = []
    if p.asset_type in {"stock", "etf"} and not policy.equities_enabled:
        failures.append("equities_disabled_by_policy")
    if p.asset_type == "crypto" and not policy.crypto_enabled:
        failures.append("crypto_disabled_by_policy")
    if p.asset_type == "crypto":
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                "SELECT active FROM CRYPTO_MASTER WHERE UPPER(symbol) = UPPER(?) AND active = 1 LIMIT 1",
                (p.symbol,),
            ).fetchone()
        if row is None:
            failures.append("crypto_not_in_approved_universe")
    return failures


def _kraken_crypto_policy_approved() -> bool:
    return all(
        _bool_env(key)
        for key in (
            "KRAKEN_TRADING_ENABLED",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_SUBMIT_REAL_ORDERS",
        )
    )


def _bool_env(key: str) -> bool:
    value = os.getenv(key)
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


MAX_PERMITTED_LEVERAGE = 4.0


def effective_leverage(policy: Any, asset_type: str) -> float:
    """How much leverage this trade may actually use. 1.0 means cash-only.

    Three deliberate refusals, Founder-directed 2026-08-22:

    1. CRYPTO IS NEVER LEVERAGED. Kraken here is a spot account holding real money; the
       leverage decision was made for the Alpaca equities learning track only.
    2. NO LEVERAGE WITHOUT A TRAILING STOP. The Founder's own framing was leverage "capping
       losses with active trailing stops" -- so the stop is a precondition, not a companion.
       If trailing stops are off, leverage silently reverting to 1.0 is the safe failure.
    3. HARD CEILING. Clamped to MAX_PERMITTED_LEVERAGE regardless of what the policy row
       says, so a fat-fingered value cannot quietly authorise unlimited exposure.
    """
    if str(asset_type or "").lower() == "crypto":
        return 1.0
    if not getattr(policy, "trailing_stop_enabled", False):
        return 1.0
    try:
        requested = float(getattr(policy, "equities_leverage_multiplier", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0
    if requested <= 1.0:
        return 1.0
    return min(requested, MAX_PERMITTED_LEVERAGE)


def calculate_capital_allocation(
    db_path: Path,
    proposal: TradeProposal,
    policy: TradingPolicy,
    *,
    account_equity: float,
    available_cash: float | None = None,
) -> dict[str, Any]:
    p = proposal.normalized()
    requested_notional = max(0.0, p.entry_price * p.position_size)
    # 2026-08-22, Founder-directed: crypto is ceilinged by its own percentage, equities by
    # theirs. Previously both used max_position_size_pct, so the crypto path requested its
    # properly-sized notional (crypto_max_trade_pct of allocation) and then had it cut
    # straight back down here -- every Kraken trade pinned to GBP 25 while the crypto
    # config said GBP 50, with nothing reporting the disagreement.
    position_size_pct = (
        policy.crypto_max_position_size_pct
        if p.asset_type == "crypto"
        else policy.max_position_size_pct
    )
    leverage = effective_leverage(policy, p.asset_type)
    max_position_notional = max(0.0, account_equity * position_size_pct * leverage)
    max_risk_amount = max(0.0, account_equity * policy.risk_per_trade_pct)
    per_unit_risk = abs(p.entry_price - p.stop_loss)
    risk_limited_qty = max_risk_amount / per_unit_risk if per_unit_risk > 0 else 0.0
    risk_limited_notional = risk_limited_qty * p.entry_price
    approved_notional = min(value for value in [requested_notional, max_position_notional, risk_limited_notional] if value >= 0)
    # Phase 5.5 (2026-08-20, Founder-requested): use conviction to decide how much of the
    # already-approved allowance to actually take. Strictly risk-reducing by construction
    # -- conviction_scaled_notional only ever returns between 50% and 100% of what every
    # existing policy check above already approved, so this can never increase exposure,
    # only decline to use the full allowance when the case is weak. Discretion within the
    # mandate, never authority to rewrite it (see technical_discretion.py).
    # Founder-requested guardrail (2026-08-20): cap one trade at a share of the cash that
    # is actually free, and/or a hard amount. Applied BEFORE conviction scaling so the
    # recorded ceiling reflects the true policy limit. Strictly reducing -- it can only
    # lower an already-approved size. `available_cash` falls back to account_equity when a
    # caller has no separate cash figure, which reproduces today's behaviour exactly.
    # The cash cap scales with leverage too, otherwise it would re-impose a cash-only
    # ceiling and silently cancel the leverage granted above. This mirrors how a broker
    # actually works: buying power IS cash x multiplier (Alpaca reports ~4x against this
    # account's equity), so borrowing capacity is what the trade is sized against.
    approved_notional = cash_capped_notional(
        approved_notional=approved_notional,
        available_cash=(account_equity if available_cash is None else available_cash) * leverage,
        max_pct_of_available_cash=policy.max_trade_pct_of_available_cash,
        max_absolute_gbp=policy.max_trade_absolute_gbp,
    )
    ceiling_notional = approved_notional
    approved_notional = conviction_scaled_notional(
        approved_notional=approved_notional,
        confidence=p.confidence_score,
        min_confidence=policy.min_ai_confidence,
    )
    approved_quantity = approved_notional / p.entry_price if p.entry_price > 0 else 0.0
    risk_amount = approved_quantity * per_unit_risk
    result = "approved" if approved_notional > 0 else "rejected"
    notes = None if result == "approved" else "Capital allocation produced zero approved notional."
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO CAPITAL_ALLOCATION_HISTORY (
                    created_at, proposal_id, symbol, asset_type, account_equity,
                    requested_notional, approved_notional, approved_quantity,
                    risk_amount, policy_snapshot_json, result, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    p.proposal_id,
                    p.symbol,
                    p.asset_type,
                    account_equity,
                    requested_notional,
                    approved_notional,
                    approved_quantity,
                    risk_amount,
                    json.dumps(policy.to_dict(), sort_keys=True),
                    result,
                    notes,
                ),
            )
    return {
        "requested_notional": requested_notional,
        "approved_notional": approved_notional,
        "approved_quantity": approved_quantity,
        "risk_amount": risk_amount,
        # The policy ceiling before conviction scaling, so an auditor can always see both
        # what was permitted and what was actually taken -- and confirm the second never
        # exceeds the first.
        "policy_ceiling_notional": ceiling_notional,
        "result": result,
        "notes": notes,
    }


def record_broker_decision(
    db_path: Path,
    proposal: TradeProposal,
    *,
    selected_broker: str | None,
    broker_healthy: bool,
    asset_available: bool,
    market_open: bool,
    result: str,
    reason: str | None,
) -> None:
    p = proposal.normalized()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO BROKER_DECISIONS (
                    created_at, proposal_id, symbol, selected_broker, exchange,
                    broker_healthy, asset_available, market_open, result, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), p.proposal_id, p.symbol, selected_broker, p.exchange, int(broker_healthy), int(asset_available), int(market_open), result, reason),
            )


def record_execution_decision(
    db_path: Path,
    proposal: TradeProposal,
    *,
    decision: str,
    validation_result: str | None,
    order_id: str | None,
    reason: str | None,
) -> None:
    p = proposal.normalized()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO EXECUTION_DECISIONS (
                    created_at, proposal_id, symbol, decision, validation_result,
                    order_id, reason, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), p.proposal_id, p.symbol, decision, validation_result, order_id, reason, json.dumps(p.to_dict(), sort_keys=True)),
            )


def latest_due_diligence(db_path: Path, proposal_id: str) -> dict[str, Any] | None:
    return _latest(db_path, "DUE_DILIGENCE_ASSESSMENTS", "assessment_id", proposal_id)


def latest_investment_score(db_path: Path, proposal_id: str) -> dict[str, Any] | None:
    return _latest(db_path, "INVESTMENT_SCORES", "score_id", proposal_id)


def latest_due_diligence_batch(db_path: Path, proposal_ids: list[str]) -> dict[str, dict[str, Any]]:
    return _latest_batch(db_path, "DUE_DILIGENCE_ASSESSMENTS", "assessment_id", proposal_ids)


def latest_investment_score_batch(db_path: Path, proposal_ids: list[str]) -> dict[str, dict[str, Any]]:
    return _latest_batch(db_path, "INVESTMENT_SCORES", "score_id", proposal_ids)


def _latest(db_path: Path, table: str, order_column: str, proposal_id: str) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {table} WHERE proposal_id = ? ORDER BY {order_column} DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
    if not row:
        return None
    return _decode_latest_payload(dict(row))


def _latest_batch(db_path: Path, table: str, order_column: str, proposal_ids: list[str]) -> dict[str, dict[str, Any]]:
    # 2026-08-15: batched form of _latest() -- recommendations() in api/__init__.py was
    # calling latest_due_diligence/latest_investment_score once per row, each opening its
    # own fresh Postgres connection (database.py's connect() does a real psycopg.connect()
    # every call, no pooling). For the mobile app's real limit=15 request that's 30 fresh
    # connections just for these two lookups. One IN-clause query replaces all of them.
    ids = [pid for pid in dict.fromkeys(proposal_ids) if pid]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE proposal_id IN ({placeholders}) ORDER BY proposal_id, {order_column} DESC",
            ids,
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = row["proposal_id"]
        if pid in result:
            continue
        result[pid] = _decode_latest_payload(dict(row))
    return result


def _decode_latest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ["reasoning_json", "policy_snapshot_json", "payload_json"]:
        if key in payload and payload[key]:
            try:
                payload[key.replace("_json", "")] = json.loads(payload[key])
            except json.JSONDecodeError:
                pass
    return payload


def _seed_policies(conn: sqlite3.Connection) -> None:
    now = utc_now_iso()
    for key, (value, value_type, description) in DEFAULT_INVESTMENT_POLICIES.items():
        _insert_policy(conn, "INVESTMENT_POLICIES", key, value, value_type, "investment", description, now)
    for key, (value, value_type, description) in DEFAULT_RISK_POLICIES.items():
        _insert_policy(conn, "RISK_POLICIES", key, value, value_type, "risk", description, now)
    for key, (value, value_type, description) in DEFAULT_LEARNING_POLICIES.items():
        _insert_policy(conn, "LEARNING_POLICIES", key, value, value_type, "learning", description, now)
    for broker, values in DEFAULT_BROKER_POLICIES.items():
        for key, (value, value_type, description) in values.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO BROKER_POLICIES (
                    broker, policy_key, policy_value, value_type, description,
                    founder_approved, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (broker, key, _stringify(value), value_type, description, now, now),
            )


def _insert_policy(
    conn: sqlite3.Connection,
    table: str,
    key: str,
    value: Any,
    value_type: str,
    category: str,
    description: str,
    now: str,
) -> None:
    conn.execute(
        f"""
        INSERT OR IGNORE INTO {table} (
            policy_key, policy_value, value_type, category, description,
            founder_approved, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        (key, _stringify(value), value_type, category, description, now, now),
    )


def _policy_map(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    return {
        row["policy_key"]: _parse_value(row["policy_value"], row["value_type"])
        for row in conn.execute(f"SELECT policy_key, policy_value, value_type FROM {table} WHERE active = 1")
    }


def _parse_value(value: str, value_type: str) -> Any:
    if value_type == "boolean":
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value_type == "integer":
        return int(value)
    if value_type == "float":
        return float(value)
    return value


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def list_capital_allocations(db_path: Path, *, symbol: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Recent per-trade sizing decisions, so trade size can be INSPECTED not reverse-engineered.

    2026-08-23: three Kraken trades landed at GBP 6.03, GBP 25.00 and GBP 3.86 within two
    hours. CAPITAL_ALLOCATION_HISTORY already recorded the account_equity, requested_notional
    and approved_notional behind each one -- but nothing exposed it, so explaining the
    differences meant reconstructing the arithmetic from qty x entry_price and guessing at
    which limb of the min() had bound. That is the same "cannot see the live value" problem
    that hid four inert settings the day before.

    policy_snapshot_json is decoded so the ceilings in force at the time are readable
    alongside the numbers they produced.
    """
    initialize_foundation_schema(db_path)
    sql = "SELECT * FROM CAPITAL_ALLOCATION_HISTORY"
    params: tuple[Any, ...] = ()
    if symbol:
        sql += " WHERE UPPER(symbol) = UPPER(?)"
        params = (symbol,)
    sql += " ORDER BY allocation_id DESC LIMIT ?"
    params = (*params, max(1, int(limit)))
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(sql, params)]
    for row in rows:
        raw = row.pop("policy_snapshot_json", None)
        try:
            row["policy_snapshot"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            row["policy_snapshot"] = None
        equity = row.get("account_equity") or 0.0
        approved = row.get("approved_notional") or 0.0
        # The single most useful derived figure: what share of the AI's capital this trade
        # actually took, which is what the percentage ceilings are expressed in.
        row["approved_pct_of_equity"] = round(approved / equity, 6) if equity else None
    return rows
