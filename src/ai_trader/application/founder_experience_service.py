from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date
from typing import Any, Callable

from ..config import Settings
from ..operational import safe_float
from ..persistence.query_executor import QueryExecutor
from ..portfolio_intelligence import calculate_portfolio_exposure
from ..trading_intelligence import calculate_performance_metrics


# Phase 4 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md): these two
# small pure formatting helpers are also used by parts of api/__init__.py that are out of
# this phase's scope (broker panels, broker permissions summaries -- Phase 6 territory), so
# they cannot be imported without a circular import (api/__init__.py imports
# FounderExperienceService at module load time, before its own later-defined functions
# exist yet). Already duplicated once in application/reporting_service.py for the same
# reason (Phase 3) -- each application/* module stays self-contained rather than importing
# from a peer service, per the plan's dependency rules. Behaviourally identical to
# api/__init__.py's copy.
def _broker_label(broker: str) -> str:
    labels = {
        "alpaca": "Alpaca",
        "kraken": "Kraken",
        "coinbase": "Coinbase",
        "binance": "Binance",
        "interactive_brokers": "Interactive Brokers",
    }
    return labels.get(broker.lower(), broker.replace("_", " ").title())


def _money_text(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "Not available"
    return f"{number:,.2f}"


def _average_numeric(values: list[Any]) -> float | None:
    numeric = [safe_float(value) for value in values]
    clean = [value for value in numeric if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _committee_numeric_confidence(committee: dict[str, Any] | None) -> float | None:
    if not committee:
        return None
    votes = committee.get("member_votes") or []
    scores = [safe_float(vote.get("score")) for vote in votes if isinstance(vote, dict)]
    return _average_numeric(scores)


def _plain_confidence(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "Unknown - not enough evidence yet"
    if number >= 0.8:
        return "High confidence"
    if number >= 0.6:
        return "Moderate confidence"
    if number >= 0.4:
        return "Low to moderate confidence"
    return "Low confidence"


def _plain_regime(regime: str) -> str:
    text = str(regime or "unknown").replace("_", " ").lower()
    labels = {
        "bull": "Trending up",
        "bear": "Trending down",
        "range": "Moving sideways",
        "recovery": "Recovering",
        "contraction": "Weakening",
        "transition": "Changing direction",
        "crisis": "Highly stressed",
        "unknown": "Unknown - not enough market evidence yet",
    }
    return labels.get(text, text.title())


def _plain_market_health(regime: str, confidence: Any) -> str:
    conf = safe_float(confidence)
    regime_text = str(regime or "").lower()
    if regime_text in {"bull", "recovery"} and conf is not None and conf >= 0.6:
        return "Constructive"
    if regime_text in {"bear", "crisis", "contraction"}:
        return "Cautious"
    if regime_text == "range":
        return "Mixed"
    return "Unclear"


def _portfolio_rebalancing_suggestions(risk_level: str, diversification: str) -> list[str]:
    suggestions = []
    if risk_level == "HIGH":
        suggestions.append("Review whether too much capital is deployed before approving new trades.")
    if "Concentrated" in diversification:
        suggestions.append("Review whether too few positions are driving too much portfolio risk.")
    if not suggestions:
        suggestions.append("No urgent rebalance suggestion from current data.")
    return suggestions


class FounderExperienceService:
    """Read-only founder-facing aggregation (architecture/AI_TRADER_MODULARISATION_
    ARCHITECTURE_2026-08-02.md Phase 4): founder experience payload, world-class evidence,
    executive summaries, connection readiness, portfolio extremes, positions requiring
    attention, strategy/signal summaries, moved out of LocalApiService.

    This service must not execute trades, change broker settings, or mutate operational
    controls -- confirmed true of every method moved here (all are read-only aggregation
    over already-recorded data).

    Depends on several LocalApiService methods/attributes that have not been extracted yet
    (broker panels and portfolio are Phase 6 territory; daily learning and recommendations
    are Phase 5 territory; themes/companies and operational-truth status each have their own
    separate route contracts and are out of this phase's scope to move). Per the plan's
    Section 5 dependency rule 6, these are narrow, explicit injected Callables rather than a
    reference to the whole LocalApiService object. `hosted_read_only_lookup` and
    `api_token_configured_lookup` specifically must read LIVE state, not a value captured at
    construction time: LocalApiService.hosted_read_only/api_token_configured are reassigned
    by run_server() AFTER LocalApiService.__init__ runs (and by tests, after construction --
    see test_connection_readiness_shows_hosted_control_lock), so both are wired as bound
    lambdas reading the live attribute off the LocalApiService instance, not a snapshot bool.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        query_executor: QueryExecutor,
        broker_panels_lookup: Callable[[], list[dict[str, Any]]],
        recommendations_lookup: Callable[[int], list[dict[str, Any]]],
        daily_learning_lookup: Callable[[str | None], dict[str, Any]],
        operational_truth_status_lookup: Callable[[], dict[str, Any]],
        themes_lookup: Callable[[], list[dict[str, Any]]],
        companies_lookup: Callable[[], list[dict[str, Any]]],
        hosted_read_only_lookup: Callable[[], bool],
        api_token_configured_lookup: Callable[[], bool],
    ) -> None:
        self.settings = settings
        self._query_executor = query_executor
        self._broker_panels_lookup = broker_panels_lookup
        self._recommendations_lookup = recommendations_lookup
        self._daily_learning_lookup = daily_learning_lookup
        self._operational_truth_status_lookup = operational_truth_status_lookup
        self._themes_lookup = themes_lookup
        self._companies_lookup = companies_lookup
        self._hosted_read_only_lookup = hosted_read_only_lookup
        self._api_token_configured_lookup = api_token_configured_lookup

    def founder_experience_payload(
        self,
        brokers: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        policy: Any,
        research_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        active = [row for row in recommendations if row.get("freshness_status") != "Expired"]
        probabilities = [safe_float(row.get("probability_of_success") or row.get("confidence")) for row in active]
        probabilities = [value for value in probabilities if value is not None]
        avg_confidence = sum(probabilities) / len(probabilities) if probabilities else None
        regimes = Counter(
            str(((row.get("market_regime") or {}).get("primary_regime") or "unknown")).lower()
            for row in active
        )
        current_regime = regimes.most_common(1)[0][0] if regimes else "unknown"
        broker_total = sum(safe_float(row.get("portfolio_balance")) or 0.0 for row in brokers if safe_float(row.get("portfolio_balance")) is not None)
        broker_cash = sum(safe_float(row.get("cash_balance")) or 0.0 for row in brokers if safe_float(row.get("cash_balance")) is not None)
        broker_positions = sum(int(safe_float(row.get("open_positions")) or 0) for row in brokers)
        deployed = max(0.0, broker_total - broker_cash) if broker_total else None
        deployment_pct = deployed / broker_total if broker_total and deployed is not None else None
        strategy_rows = self._latest_strategy_performance_rows()
        best_strategy = strategy_rows[0] if strategy_rows else None
        weakest_strategy = strategy_rows[-1] if len(strategy_rows) > 1 else None
        try:
            lab_rows = [dict(row) for row in self._query_executor.rows("SELECT * FROM STRATEGY_LAB_RUNS ORDER BY lab_run_id DESC LIMIT 8")]
        except sqlite3.OperationalError:
            lab_rows = []
        try:
            calibration_rows = [dict(row) for row in self._query_executor.rows("SELECT * FROM CONFIDENCE_CALIBRATION ORDER BY calibration_id DESC LIMIT 10")]
        except sqlite3.OperationalError:
            calibration_rows = []
        accuracy = _average_numeric([row.get("observed_win_rate") for row in calibration_rows])
        daily_learning = self._daily_learning_lookup(date.today().isoformat())
        committee_confidence = _average_numeric([
            _committee_numeric_confidence(row.get("committee"))
            for row in active
        ])
        risk_level = "LOW" if deployment_pct is not None and deployment_pct < 0.35 else "MEDIUM" if deployment_pct is not None and deployment_pct < 0.70 else "HIGH" if deployment_pct is not None else "UNKNOWN"
        diversification = "Concentrated" if broker_positions <= 2 else "Moderate" if broker_positions <= 7 else "Broad by position count"
        return {
            "architectural_principle": [
                "Does it help AI Trader make a better investment decision?",
                "Does it help the Founder make a better decision?",
                "Does it help AI Trader learn to make better decisions in the future?",
            ],
            "executive_dashboard": {
                "headline": "AI Trader is monitoring brokers, recommendations, risk, and learning evidence.",
                "good_morning": [
                    "Good morning. Here is what changed overnight.",
                    f"{len(active)} active recommendation(s) are currently visible.",
                    f"The dominant market regime in current recommendations is {current_regime}.",
                    f"Portfolio risk is {risk_level}.",
                    "I will continue watching broker health, fresh recommendations, open positions, and guardrail breaches.",
                ],
                "portfolio_health": "Needs attention" if risk_level == "HIGH" else "Stable",
                "overall_ai_confidence": _plain_confidence(avg_confidence),
                "current_market_regime": _plain_regime(current_regime),
                "todays_recommendation_count": len(active),
                "portfolio_risk": risk_level,
                "portfolio_diversification": diversification,
                "open_positions": broker_positions,
                "capital_deployed": deployed,
                "cash_available": broker_cash if brokers else None,
                "learning_progress": f"{len(strategy_rows)} strategy performance snapshot(s), {len(lab_rows)} strategy lab run(s).",
                "prediction_accuracy": accuracy,
                "current_best_strategy": (best_strategy or {}).get("strategy_id"),
                "current_weakest_strategy": (weakest_strategy or {}).get("strategy_id"),
                "committee_confidence": _plain_confidence(committee_confidence),
                "what_to_do": "Review green/amber dossiers only; do not override red guardrails.",
                "what_to_worry_about": "Missing data, weak calibration, concentrated exposure, and any recommendation without fresh evidence.",
            },
            "portfolio_command": {
                "portfolio_allocation": {
                    "total": broker_total or None,
                    "cash": broker_cash if brokers else None,
                    "deployed": deployed,
                    "deployed_pct": deployment_pct,
                },
                "diversification": diversification,
                "sector_exposure": "Shown when company sector data is attached to positions.",
                "country_exposure": "Shown when country data is attached to positions.",
                "currency_exposure": "Broker/account currency evidence only in current implementation.",
                "correlation": "Not enough provider data yet for statistical correlation.",
                "portfolio_risk": risk_level,
                "expected_portfolio_return": "Requires more closed trades before AI Trader can estimate this responsibly.",
                "largest_winners": self._portfolio_extremes(winners=True),
                "largest_losers": self._portfolio_extremes(winners=False),
                "positions_requiring_attention": self._positions_requiring_attention(brokers),
                "rebalancing_suggestions": _portfolio_rebalancing_suggestions(risk_level, diversification),
            },
            "market_intelligence_centre": {
                "current_market_regime": _plain_regime(current_regime),
                "market_health": _plain_market_health(current_regime, avg_confidence),
                "volatility": "High volatility means prices may move quickly and stops may be hit more easily.",
                "momentum": "Momentum means whether recent price movement is helping or fighting the trade idea.",
                "breadth": "Market breadth needs a market-data provider before it can be measured responsibly.",
                "fear_greed": _plain_confidence(avg_confidence),
                "crypto_health": self._crypto_health_summary(brokers, active),
                "sector_rotation": "Uses theme and company evidence where available; no sector-rotation provider is configured yet.",
                "major_themes": [row.get("theme") for row in self._themes_lookup()[:5]],
                "watch_list": [row.get("ticker") for row in self._companies_lookup()[:10]],
                "important_news": "Summarised inside each recommendation dossier when news is available.",
                "upcoming_risks": ["stale recommendations", "uncalibrated strategy evidence", "broker disconnection", "open-position drawdown"],
            },
            "learning_lab": {
                "learning_progress": f"{len(strategy_rows)} performance snapshot(s) and {len(lab_rows)} lab validation run(s) recorded.",
                "prediction_accuracy": accuracy,
                "calibration": calibration_rows[:5],
                "strategy_rankings": strategy_rows,
                "best_performing_strategy": best_strategy,
                "worst_performing_strategy": weakest_strategy,
                "strategy_validation_status": self._strategy_validation_summary(lab_rows),
                "backtest_results": [row for row in lab_rows if row.get("run_type") == "backtest"],
                "walk_forward_results": [row for row in lab_rows if row.get("run_type") == "walk_forward"],
                "committee_performance": "Tracked through committee reviews and closed-trade attribution; larger samples are needed before claiming skill.",
                "signal_rankings": self._signal_rankings(),
                "lessons_learned": (daily_learning or {}).get("trade_lessons", []),
                "founder_suggestions": (daily_learning or {}).get("recommendations_for_founder", []),
            },
        }

    def _latest_strategy_performance_rows(self) -> list[dict[str, Any]]:
        try:
            rows = [
                dict(row)
                for row in self._query_executor.rows(
                    """
                    SELECT pi.*
                    FROM PERFORMANCE_INTELLIGENCE pi
                    JOIN (
                        SELECT strategy_id, MAX(performance_id) AS performance_id
                        FROM PERFORMANCE_INTELLIGENCE
                        GROUP BY strategy_id
                    ) latest ON latest.performance_id = pi.performance_id
                    ORDER BY COALESCE(pi.expectancy_r, pi.average_r, -999) DESC
                    LIMIT 12
                    """
                )
            ]
        except sqlite3.OperationalError:
            rows = []
        if rows:
            return rows
        strategy_ids = ["equity_conservative_ai_assisted", "crypto_trend_following_2r", "trend_following", "momentum"]
        generated = []
        for strategy_id in strategy_ids:
            perf = calculate_performance_metrics(self.settings.db_path, strategy_id)
            if perf.get("sample_size"):
                generated.append({"strategy_id": strategy_id, **perf})
        return sorted(generated, key=lambda item: safe_float(item.get("expectancy_r") or item.get("average_r") or -999), reverse=True)

    def _portfolio_extremes(self, *, winners: bool) -> list[dict[str, Any]]:
        try:
            rows = [
                dict(row)
                for row in self._query_executor.rows(
                    """
                    SELECT broker, symbol, profit_loss, entry_price, exit_price, closed_at
                    FROM PERFORMANCE_ATTRIBUTION
                    WHERE profit_loss IS NOT NULL
                    ORDER BY profit_loss {direction}
                    LIMIT 5
                    """.format(direction="DESC" if winners else "ASC")
                )
            ]
        except sqlite3.OperationalError:
            rows = []
        return rows

    def _positions_requiring_attention(self, brokers: list[dict[str, Any]]) -> list[str]:
        attention = []
        for broker in brokers:
            label = broker.get("label") or broker.get("broker") or "Broker"
            if str(broker.get("connection_status") or "").lower() not in {"connected", "ok - connected"}:
                attention.append(f"{label}: connection is not confirmed.")
            if safe_float(broker.get("todays_pnl")) is not None and (safe_float(broker.get("todays_pnl")) or 0) < 0:
                attention.append(f"{label}: today's P&L is negative.")
            if str(broker.get("due_diligence_status") or "").lower() == "blocked":
                attention.append(f"{label}: due diligence is blocked.")
        return attention[:8] or ["No urgent broker attention item is visible from current data."]

    def _crypto_health_summary(self, brokers: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
        kraken = next((row for row in brokers if str(row.get("broker") or "").lower() == "kraken"), None)
        crypto_recs = [row for row in recommendations if str(row.get("asset_type") or "").lower() == "crypto"]
        if not kraken:
            return "Kraken is not visible in the current broker panel data."
        if str(kraken.get("connection_status") or "").lower() == "connected":
            return f"Crypto connection is visible; {len(crypto_recs)} active crypto recommendation(s) are available."
        return f"Crypto broker needs attention: {kraken.get('connection_status') or 'not connected'}."

    def _strategy_validation_summary(self, lab_rows: list[dict[str, Any]]) -> list[str]:
        if not lab_rows:
            return ["No Strategy Lab validation run has been recorded yet."]
        return [
            f"{row.get('strategy_id')}: {row.get('run_type')} is {row.get('status')}."
            for row in lab_rows[:8]
        ]

    def _signal_rankings(self) -> list[dict[str, Any]]:
        try:
            rows = [
                dict(row)
                for row in self._query_executor.rows(
                    """
                    SELECT signal_name, COUNT(*) AS sample_size, AVG(score) AS average_score,
                           AVG(confidence) AS average_confidence
                    FROM TRADE_SIGNALS
                    GROUP BY signal_name
                    ORDER BY average_score DESC
                    LIMIT 10
                    """
                )
            ]
        except sqlite3.OperationalError:
            rows = []
        return rows

    def world_class_evidence(
        self,
        *,
        brokers: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        brokers = brokers if brokers is not None else self._broker_panels_lookup()
        recommendations = recommendations if recommendations is not None else self._recommendations_lookup(50)
        connected_brokers = [
            item for item in brokers
            if str(item.get("broker") or "").lower() in {"alpaca", "kraken"}
            and str(item.get("connection_status") or "").lower() == "connected"
        ]
        future_brokers = [
            {
                "broker": item.get("broker"),
                "label": item.get("label"),
                "status": self._future_broker_status(item),
            }
            for item in brokers
            if str(item.get("broker") or "").lower() not in {"alpaca", "kraken"}
        ]
        operational = self._operational_truth_status_lookup()
        portfolio_evidence = self._portfolio_intelligence_summary(connected_brokers)
        dossier_ready = [
            item for item in recommendations
            if item.get("strongest_argument_for")
            and item.get("strongest_argument_against")
            and item.get("freshness_status") != "Expired"
        ]
        unknowns = self._data_availability_unknowns(connected_brokers, recommendations)
        daily_learning = self._daily_learning_lookup(date.today().isoformat())
        first_conclusion = self._executive_first_conclusion(connected_brokers, dossier_ready, unknowns)
        return {
            "first_conclusion": first_conclusion,
            "measured": [
                "Broker connection state for Alpaca and Kraken.",
                "Recorded broker trade/order rows.",
                "Canonical lifecycle events generated from broker history.",
                "Portfolio/cash values when broker APIs return them.",
            ],
            "calculated_from_assumptions": [
                "Estimated capital in positions equals measured portfolio value minus measured cash when both are present.",
                "Portfolio exposure uses available broker positions and metadata; missing metadata is labelled.",
                "R, slippage, and MAE/MFE are calculated only when required entry, stop, fill, and observation data exist.",
            ],
            "unavailable": unknowns,
            "operational_truth": operational,
            "portfolio_intelligence": portfolio_evidence,
            "experience_learning": {
                "closed_trade_reviews": self._query_executor.scalar("SELECT COUNT(*) FROM POST_TRADE_REVIEWS") or 0,
                "experience_records": self._query_executor.scalar("SELECT COUNT(*) FROM EXPERIENCE_RECORDS") or 0,
                "learning_proposals": self._query_executor.scalar("SELECT COUNT(*) FROM LEARNING_PROPOSALS") or 0,
                "today": daily_learning,
                "boundary": "Learning may suggest improvements, but cannot change broker permissions, guardrails, or production strategy status without approval.",
            },
            "recommendation_standard": {
                "active_dossiers_with_for_and_against": len(dossier_ready),
                "do_nothing_is_valid": True,
                "minimum_required_fields": [
                    "strongest argument for",
                    "strongest argument against",
                    "invalidation",
                    "why taking no action may be preferable",
                ],
            },
            "future_connections": future_brokers,
        }

    def _portfolio_intelligence_summary(self, brokers: list[dict[str, Any]]) -> dict[str, Any]:
        positions: list[dict[str, Any]] = []
        for broker in brokers:
            for row in broker.get("trade_history") or []:
                symbol = row.get("symbol")
                if symbol and str(row.get("status") or "").lower() in {"filled", "open"}:
                    positions.append({
                        "symbol": symbol,
                        "asset_type": row.get("asset_type") or ("crypto" if broker.get("broker") == "kraken" else "stock"),
                        "notional": row.get("notional") or row.get("price"),
                        "currency": "GBP" if broker.get("broker") == "kraken" else "USD",
                    })
        exposure = calculate_portfolio_exposure(self.settings.db_path, positions, broker="all") if positions else {
            "total_value": 0,
            "exposure": {},
            "largest_positions": [],
            "warnings": ["Not available - no broker position rows with measurable notional were available."],
            "plain_english": "Portfolio exposure cannot be calculated yet because measurable broker position rows are unavailable.",
        }
        return exposure

    def _future_broker_status(self, panel: dict[str, Any]) -> str:
        connection = str(panel.get("connection_status") or "").lower()
        if "not configured" in connection or "not configured" in str(panel.get("source") or "").lower():
            return "Not configured"
        if "authentication failed" in connection:
            return "Authentication failed"
        if connection == "connected":
            return "Connected"
        return "Not connected"

    def _data_availability_unknowns(self, brokers: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> list[dict[str, str]]:
        unknowns: list[dict[str, str]] = []
        for broker in brokers:
            key = str(broker.get("broker") or "broker")
            for field, requirement in [
                ("todays_pnl", "at least two same-day portfolio snapshots or broker-reported day P&L"),
                ("week_pnl", "a prior weekly snapshot or broker-reported week P&L"),
                ("month_pnl", "a month-start snapshot or broker-reported month P&L"),
            ]:
                value = broker.get(field)
                if value in {None, "", "Not available"} or str(value).lower().startswith("not available"):
                    unknowns.append({
                        "field": f"{key}.{field}",
                        "why": str(value or "No value returned by broker or snapshot layer."),
                        "required": requirement,
                        "expected_or_error": "Expected early in a deployment or after a database reset; review if snapshots exist but values remain missing.",
                    })
        incomplete_recommendations = [
            row.get("symbol") or "unknown"
            for row in recommendations
            if not row.get("strongest_argument_for") or not row.get("strongest_argument_against")
        ]
        if incomplete_recommendations:
            unknowns.append({
                "field": "recommendation_dossier.arguments",
                "why": f"{len(incomplete_recommendations)} recommendation(s) lack complete bull/bear evidence.",
                "required": "Trading committee evidence with strongest argument for and strongest argument against.",
                "expected_or_error": "Execution should not treat these as actionable recommendations.",
            })
        return unknowns

    def _executive_first_conclusion(
        self,
        connected_brokers: list[dict[str, Any]],
        dossier_ready: list[dict[str, Any]],
        unknowns: list[dict[str, str]],
    ) -> str:
        if not connected_brokers:
            return "Broker issue requires attention"
        if any("recommendation_dossier" in item["field"] for item in unknowns):
            return "Data issue requires attention"
        if dossier_ready:
            return "Review one recommendation"
        return "No action required"

    def executive_summary(self, panels: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if panels is None:
            panels = self._broker_panels_lookup()
        summaries: list[dict[str, Any]] = []
        for panel in panels:
            broker_key = str(panel.get("broker") or "").lower()
            summaries.append({
                "broker": panel.get("label") or _broker_label(broker_key),
                "broker_key": broker_key,
                "portfolio_balance": panel.get("portfolio_value"),
                "cash_balance": panel.get("cash_available"),
                "estimated_in_positions": panel.get("estimated_in_positions"),
                "last_day_pnl": panel.get("todays_pnl"),
                "last_week_pnl": panel.get("week_pnl"),
                "last_month_pnl": panel.get("month_pnl"),
                "amount_traded_today": panel.get("trades_today"),
                "month_start_portfolio_balance": panel.get("month_start_value"),
                "open_positions": panel.get("open_positions"),
                "status": panel.get("connection_status") or panel.get("source"),
            })
        return summaries

    def founder_executive_summary(self, panels: list[dict[str, Any]], executive_summary: list[dict[str, Any]]) -> dict[str, Any]:
        broker_lines = []
        for item in executive_summary:
            portfolio_value = safe_float(item.get("portfolio_balance"))
            cash = safe_float(item.get("cash_balance"))
            invested = safe_float(item.get("estimated_in_positions"))
            positions = item.get("open_positions")
            line = f"{item.get('broker')}: "
            if portfolio_value is None and cash is None:
                line += f"{item.get('status') or 'no account values available'}."
            else:
                line += f"account about {_money_text(portfolio_value)}, cash {_money_text(cash)}"
                if invested is not None:
                    line += f", about {_money_text(invested)} currently tied up in open positions"
                line += f", open positions {positions if positions not in (None, '') else 'not available'}."
            broker_lines.append(line)
        latest_trade = self._latest_broker_trade_any()
        trade_line = "No broker fill has been recorded yet."
        if latest_trade:
            trade_line = (
                f"Latest recorded broker fill/order is {str(latest_trade.get('side') or '').upper()} "
                f"{latest_trade.get('symbol') or 'unknown'} for {latest_trade.get('quantity') or 'unknown'} "
                f"at {_money_text(latest_trade.get('price'))}, status {latest_trade.get('status') or 'unknown'}."
            )
        learning_line = self._plain_learning_status()
        headline = "AI Trader is connected and monitoring broker data." if panels else "AI Trader has not received broker data yet."
        return {
            "headline": headline,
            "plain_english": broker_lines + [trade_line, learning_line],
            "latest_trade": latest_trade,
        }

    def connection_readiness(self, panels: list[dict[str, Any]]) -> dict[str, Any]:
        control_ready = not self._hosted_read_only_lookup()
        control_status = "unlocked" if control_ready else "locked"
        if control_ready and not self._api_token_configured_lookup():
            control_status = "local token not required"
        checks = [
            {
                "component": "Render API",
                "status": "connected",
                "ready": True,
                "detail": "The mobile app reached the hosted API and received this status response.",
            },
            {
                "component": "Control Actions",
                "status": control_status,
                "ready": control_ready,
                "detail": (
                    "POST trading/control commands are enabled for this API."
                    if control_ready
                    else "Hosted POST trading/control commands are locked until AI_TRADER_API_TOKEN is configured in Render."
                ),
            },
            {
                "component": "OpenAI",
                "status": "configured" if self.settings.openai_api_key else "missing",
                "ready": bool(self.settings.openai_api_key),
                "detail": "Ask AI Trader and AI proposal analysis can use OpenAI." if self.settings.openai_api_key else "OPENAI_API_KEY is not configured for this deployment.",
            },
        ]
        for broker in panels:
            key = str(broker.get("broker") or "").lower()
            if key not in {"alpaca", "kraken", "coinbase", "binance", "interactive_brokers"}:
                continue
            connected = str(broker.get("connection_status") or "").lower() == "connected"
            auto_enabled = bool(broker.get("auto_trading_enabled"))
            detail = broker.get("source") or broker.get("connection_status") or "No broker detail returned."
            if key == "kraken" and broker.get("balance_summary"):
                summary = broker["balance_summary"]
                detail = (
                    f"Total estimated GBP {summary.get('total_estimated_gbp')}; "
                    f"GBP cash {summary.get('gbp_cash')}; "
                    f"AI trading allocation {summary.get('trading_allocation_gbp')}. "
                    f"{summary.get('valuation_note')}"
                )
            checks.append({
                "component": broker.get("label") or _broker_label(key),
                "status": "connected" if connected else str(broker.get("connection_status") or "not connected"),
                "ready": connected,
                "auto_trading_enabled": auto_enabled,
                "detail": detail,
            })
        trade_ready = all(
            item["ready"]
            for item in checks
            if item["component"] in {"Render API", "Control Actions", "OpenAI", "Alpaca", "Kraken"}
        )
        return {
            "overall_status": "ready" if trade_ready else "attention_needed",
            "trade_ready": trade_ready,
            "checks": checks,
            "note": "Readiness confirms connections and configuration visibility only. Every trade still requires orchestrator and guardrail validation.",
        }

    def _latest_broker_trade_any(self) -> dict[str, Any] | None:
        row = self._query_executor.row("SELECT * FROM BROKER_TRADE_HISTORY ORDER BY COALESCE(closed_at, opened_at, updated_at) DESC, trade_history_id DESC LIMIT 1")
        return dict(row) if row else None

    def _plain_learning_status(self) -> str:
        today = date.today().isoformat()
        closed_count = self._query_executor.scalar(
            "SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION WHERE COALESCE(closed_at, created_at) LIKE ?",
            (f"{today}%",),
        ) or 0
        if closed_count:
            return f"Learning today is based on {closed_count} closed trade outcome(s), plus benchmark and guardrail observations."
        return "Learning today is limited: no fully closed trade outcome has been recorded yet, so the app should not claim the strategy improved or failed until open positions are reconciled."
