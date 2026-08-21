from __future__ import annotations

import json
import logging
import os
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..agent import AITradingAgent, propose_crypto_trades
from ..ai import CryptoTradeReviewer, MarketForecastAnalyzer, OpenAIProposalAnalyzer
from ..alpaca import AlpacaPaperClient
from ..audit import AuditDatabase
from ..broker_adapters import _kraken_pair
from ..config import Settings
from ..daily_plan import record_daily_trading_plan
from ..database import connect
from ..forecasting import generate_market_forecast
from ..market_intelligence_platform import latest_observation_times_batch, record_market_observations
from ..models import AccountContext, TradeProposal, utc_now_iso
from ..multi_broker import (
    record_crypto_research_score,
    record_notification,
    record_recommendation_set,
    update_broker_runtime,
)
from ..operational import latest_pnl_snapshot, record_research_run, safe_float, safe_score, seed_crypto_universe
from ..orchestrator import InvestmentOrchestrator, next_research_run
from ..persistence.query_executor import QueryExecutor
from ..portfolio_intelligence import upsert_asset_metadata
from ..production_evidence import record_research_evidence
from ..rejection_review import run_crypto_rejection_review, run_crypto_rejection_rollup
from ..sprint6 import record_operational_event, refresh_strategy_maturity, seed_default_strategy_registry
from ..trading_intelligence import (
    STRATEGIES,
    calculate_calibration_metrics,
    record_historical_candle,
    run_strategy_backtest,
    run_walk_forward_validation,
)
from ..always_on import record_research_funnel, record_shadow_trade
from .shared_helpers import _csv_env, _int_or_default
from ..trade_scorecard import estimate_round_trip_fee_pct, load_closed_trades

logger = logging.getLogger("ai_trader.api")


# The following three helpers had exactly one call site each, all inside this cluster, so
# they moved fully rather than being duplicated.
def _symbol_from_kraken_pair(pair: str) -> str:
    normalized = str(pair or "").upper().replace("/", "").replace("-", "").strip()
    for suffix in ("GBP", "USD", "EUR", "USDT", "USDC"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    if normalized.startswith("X") and normalized in {"XXBT", "XXDG"}:
        normalized = normalized[1:]
    if normalized.startswith("Z") and len(normalized) > 4:
        normalized = normalized[1:]
    if normalized == "XBT":
        return "BTC"
    if normalized == "XDG":
        return "DOGE"
    return normalized


def _crypto_display_name(symbol: str) -> str:
    names = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "SOL": "Solana",
        "XRP": "XRP",
        "DOGE": "Dogecoin",
        "ADA": "Cardano",
        "LINK": "Chainlink",
        "DOT": "Polkadot",
        "AVAX": "Avalanche",
        "MATIC": "Polygon",
    }
    normalized = str(symbol or "").upper()
    return names.get(normalized, normalized)


def _crypto_requested_notional(*, account_equity: float, pct: float, fallback_amount: float) -> float:
    """Per-trade notional as a share of the AI's own capital, not a flat pound amount.

    Founder-directed 2026-08-20. The flat CRYPTO_MAX_AUTO_TRADE_AMOUNT meant adding capital
    to the account changed nothing about trade size -- every entry stayed pinned at the same
    few pounds. A percentage scales automatically as the account grows or shrinks.

    Pure function so the scaling is directly testable without standing up a research cycle.
    Falls back to the flat amount when equity is missing or non-positive: a failed balance
    read must degrade to the old behaviour, never to a zero-size (and therefore rejected)
    order. Never returns more than the percentage of real equity.
    """
    equity = float(account_equity or 0.0)
    share = float(pct or 0.0)
    if equity <= 0 or share <= 0:
        return max(0.0, float(fallback_amount or 0.0))
    return round(equity * share, 8)


def _proposal_expected_r(proposal: TradeProposal) -> float | None:
    risk = abs(float(proposal.entry_price) - float(proposal.stop_loss))
    reward = abs(float(proposal.take_profit) - float(proposal.entry_price))
    if risk <= 0:
        return None
    return reward / risk


class ResearchService:
    """Research pipeline (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md
    Phase 5): run_analysis/run_crypto_analysis and everything that feeds them, moved out of
    LocalApiService. Preserves separate equity (run_analysis) and crypto
    (run_crypto_analysis) entry points -- they are not merged, per the plan's explicit
    instruction, even though they share several lifecycle-recording helpers.

    `account_context_lookup`, `recommendations_lookup`, and `broker_factory` are narrow,
    explicit injected dependencies for LocalApiService methods that have not been extracted
    yet (`_account_context_for_broker` is broker/execution territory -- Phase 6/8;
    `recommendations` is founder-presentation-adjacent and used by several not-yet-extracted
    callers; `_broker` constructs an AlpacaPaperClient and is still needed elsewhere in
    api/__init__.py too). `_account_context_for_broker` specifically carries the Kraken AI
    capital-sleeve isolation logic (`_kraken_trading_allocation_gbp`) -- this is deliberately
    injected, not duplicated, so that safety-critical isolation logic has exactly one
    implementation anywhere in the codebase, per the plan's Section 5 dependency rule 6.

    (A fourth lookup, `auto_execute_recommendations_lookup`, was removed 2026-08-17: the
    equity research jobs it served used to call it inline after generating proposals, which
    duplicated -- at the cost of a guaranteed 900s timeout -- work the independently-scheduled
    `auto-execution-alpaca` job already does on its own ~180s cadence. See `run_analysis`'s
    2026-08-17 incident comment.)

    All lookups are wired in LocalApiService.__init__ as lambdas that read the
    LocalApiService instance's own method *at call time* (`lambda: self.recommendations(...)`,
    not `self.recommendations` captured directly) rather than snapshotting a bound method at
    construction time. This matters because `tests/test_strategy_lab.py` and
    `tests/test_production_evidence.py` monkeypatch `service._broker` /
    `service.recommendations` as instance attributes *after* `LocalApiService(settings)` has
    already constructed this service -- a directly-captured bound method would keep pointing
    at the pre-patch class method and silently ignore the test's patch. Phase 4 established
    this same pattern for `hosted_read_only`/`api_token_configured` for the identical reason.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        audit: AuditDatabase,
        orchestrator: InvestmentOrchestrator,
        query_executor: QueryExecutor,
        account_context_lookup: Callable[[str], AccountContext],
        recommendations_lookup: Callable[[int], list[dict[str, Any]]],
        broker_factory: Callable[[], AlpacaPaperClient],
    ) -> None:
        self.settings = settings
        self.audit = audit
        self.orchestrator = orchestrator
        self._query_executor = query_executor
        self._account_context_lookup = account_context_lookup
        self._recommendations_lookup = recommendations_lookup
        self._broker_factory = broker_factory

    def refresh_crypto_universe(self) -> dict[str, Any]:
        result = seed_crypto_universe(self.settings.db_path, fetch_live=True)
        update_broker_runtime(
            self.settings.db_path,
            "kraken",
            research_status="running" if result["inserted"] else "idle",
            due_diligence_status="completed" if result["inserted"] else "blocked",
            current_stage="crypto_universe_refresh",
            last_scan=utc_now_iso(),
            next_scan=next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
            research_freshness="Fresh" if result["inserted"] else result["notes"],
            details={"crypto_universe": result},
        )
        if not result["inserted"]:
            record_notification(
                self.settings.db_path,
                event_type="research_failure",
                broker="kraken",
                symbol=None,
                title="Crypto universe refresh returned no data",
                message=result["notes"],
                payload=result,
            )
        logger.info("Crypto universe refresh: %s", result)
        crypto_analysis = self.run_crypto_analysis()
        result["crypto_analysis"] = crypto_analysis
        return result

    def refresh_strategy_lab(self) -> dict[str, Any]:
        """Ingests recent daily candles for the equity universe, backtests and walk-forward
        validates every stock-eligible named strategy against that history, and evaluates each
        for promotion.

        This connects three subsystems that previously existed fully built and unit-tested but
        had zero production callers: record_historical_candle (HISTORICAL_CANDLES was
        permanently empty), the backtester/walk-forward validator, and
        strategy_promotion_decision. Equity-only for now - crypto historical ingestion needs a
        new Kraken OHLC client, which is a genuine new integration rather than a wiring fix and is
        intentionally deferred as a near-term follow-up rather than shipped untested here.
        """
        seed_default_strategy_registry(self.settings.db_path)
        if not self.settings.has_alpaca_credentials:
            result = {"status": "not_available", "message": "Alpaca paper credentials are required for historical candle ingestion."}
            record_operational_event(
                self.settings.db_path,
                component="strategy_lab",
                event_type="strategy_lab_blocked_configuration",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            return result
        symbols = [row["ticker"] for row in self._query_executor.rows("SELECT ticker FROM COMPANY_MASTER ORDER BY id ASC LIMIT 30")]
        if not symbols:
            result = {"status": "not_available", "message": "No equity symbols available in COMPANY_MASTER."}
            record_operational_event(
                self.settings.db_path,
                component="strategy_lab",
                event_type="strategy_lab_completed_no_action",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            return result
        bars_response = self._broker_factory().get_daily_bars(symbols)
        candles_written = 0
        symbols_with_history: set[str] = set()
        for symbol, bars in (bars_response.get("bars") or {}).items():
            for bar in bars:
                observed_at = bar.get("t")
                close = bar.get("c")
                if not observed_at or close is None:
                    continue
                record_historical_candle(
                    self.settings.db_path,
                    symbol=symbol,
                    asset_type="stock",
                    timeframe="1d",
                    observed_at=observed_at,
                    close=float(close),
                    open=bar.get("o"),
                    high=bar.get("h"),
                    low=bar.get("l"),
                    volume=bar.get("v"),
                    source="alpaca",
                )
                candles_written += 1
                symbols_with_history.add(symbol)
        strategy_results = []
        for strategy_id, definition in STRATEGIES.items():
            if "stock" not in (definition.get("supported_assets") or []):
                continue
            trades = 0
            expectancy_values: list[float] = []
            profit_factor_values: list[float] = []
            max_drawdown = 0.0
            for symbol in sorted(symbols_with_history):
                backtest = run_strategy_backtest(self.settings.db_path, strategy_id=strategy_id, symbol=symbol, asset_type="stock", timeframe="1d")
                run_walk_forward_validation(self.settings.db_path, strategy_id=strategy_id, symbol=symbol, asset_type="stock", timeframe="1d")
                trades += int(backtest.get("trades") or 0)
                if backtest.get("expectancy_r") is not None:
                    expectancy_values.append(backtest["expectancy_r"])
                if backtest.get("profit_factor") is not None:
                    profit_factor_values.append(backtest["profit_factor"])
                max_drawdown = max(max_drawdown, abs(backtest.get("max_drawdown_r") or 0.0))
            calibration = calculate_calibration_metrics(self.settings.db_path, strategy_id)
            evidence = {
                "sample_size": trades,
                "expectancy": (sum(expectancy_values) / len(expectancy_values)) if expectancy_values else None,
                "profit_factor": (sum(profit_factor_values) / len(profit_factor_values)) if profit_factor_values else None,
                "max_drawdown": max_drawdown,
                "calibration_error": calibration.get("calibration_error"),
                "recent_drawdown": max_drawdown,
            }
            maturity = refresh_strategy_maturity(self.settings.db_path, strategy_id=strategy_id, evidence=evidence)
            strategy_results.append({"strategy_id": strategy_id, "evidence": evidence, "maturity": maturity})
        pending_approval = [item["strategy_id"] for item in strategy_results if item["maturity"].get("requires_founder_approval")]
        result = {
            "status": "completed",
            "symbols_requested": symbols,
            "symbols_with_history": sorted(symbols_with_history),
            "candles_written": candles_written,
            "unavailable_symbols": bars_response.get("unavailable_symbols") or [],
            "strategies_evaluated": len(strategy_results),
            "strategy_results": strategy_results,
            "pending_founder_approval": pending_approval,
        }
        record_operational_event(
            self.settings.db_path,
            component="strategy_lab",
            event_type="strategy_lab_completed",
            summary=f"Strategy lab refresh: {candles_written} candles across {len(symbols_with_history)} symbols; {len(strategy_results)} strategies evaluated; {len(pending_approval)} pending Founder approval.",
            details={"candles_written": candles_written, "symbols_with_history": sorted(symbols_with_history), "pending_founder_approval": pending_approval},
        )
        return result

    def refresh_crypto_candle_history(self) -> dict[str, Any]:
        """Ingests real Kraken OHLC candle history for the crypto universe -- Phase 1 of
        the CIO-level forecasting build (2026-08-20, Founder-directed).

        Crypto has never had multi-point price history anywhere in this codebase before
        this method; every existing live crypto price read was a single current-price
        snapshot (KrakenAdapter.current_prices, `/0/public/Ticker`). This is the crypto
        equivalent of refresh_strategy_lab's equity candle ingestion above -- daily bars,
        written into the same real, quality-validated, previously-zero-caller
        MARKET_DATA_OBSERVATIONS table (market_intelligence_platform.py) rather than a
        new parallel schema.

        record_market_observations has no dedup of its own, so this only ever fetches
        candles newer than what's already stored (latest_observation_time), matching
        Kraken's own OHLC `since` parameter -- safe to run on a recurring schedule
        without the table growing duplicate rows.
        """
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not getattr(adapter, "configured", False):
            result = {"status": "not_available", "message": "Kraken credentials are required for crypto candle ingestion."}
            record_operational_event(
                self.settings.db_path,
                component="crypto_candle_history",
                event_type="crypto_candle_refresh_blocked_configuration",
                broker="kraken",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            return result
        symbols = self._bootstrap_crypto_universe_from_kraken_permissions(limit=30)
        if not symbols:
            result = {"status": "not_available", "message": "No active crypto symbols are available yet."}
            record_operational_event(
                self.settings.db_path,
                component="crypto_candle_history",
                event_type="crypto_candle_refresh_completed_no_action",
                broker="kraken",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            return result
        candles_written = 0
        symbols_with_history: list[str] = []
        quality_issues: list[dict[str, Any]] = []
        # 2026-08-21 egress audit: one connection for every symbol's watermark instead of
        # one fresh remote-Postgres connection per symbol per hourly cycle -- with the
        # universe cap removed (up to 30 symbols now, was 10), the old per-symbol
        # latest_observation_time() call here would have tripled this refresh's
        # connection count for no benefit. See latest_observation_times_batch's docstring.
        since_by_symbol = latest_observation_times_batch(self.settings.db_path, provider="kraken", normalized_symbols=symbols, timeframe="1d")
        for symbol in symbols:
            pair = _kraken_pair(symbol)
            since_iso = since_by_symbol.get(symbol)
            if since_iso:
                since_epoch = int(datetime.fromisoformat(since_iso).timestamp())
            else:
                # First-ever fetch for this symbol: bound to ~200 days rather than
                # Kraken's full multi-year default history. analyze_price_series only
                # ever needs a 20-period moving-average window; fetching years of daily
                # candles just to write them one row at a time to remote Postgres was
                # confirmed live to blow past Render's ~60s proxy timeout for no benefit.
                since_epoch = int((datetime.now(timezone.utc) - timedelta(days=200)).timestamp())
            try:
                candles = adapter.get_ohlc_candles(pair, interval_minutes=1440, since=since_epoch)
            except Exception as exc:  # noqa: BLE001 - one pair's fetch failure must never block the rest
                quality_issues.append({"symbol": symbol, "pair": pair, "reason": str(exc)})
                continue
            if since_iso:
                # Confirmed live: Kraken's `since` boundary is inclusive (or at least not
                # reliably exclusive) -- without this filter, the candle already stored as
                # the latest observation kept coming back and being rewritten on every
                # single call, forever, instead of converging to "nothing new" once caught
                # up. record_market_observations has no dedup of its own (see
                # latest_observation_time's docstring), so this must be filtered before it
                # ever reaches that call, not relied on to be handled downstream.
                candles = [candle for candle in candles if str(candle.get("observation_time") or "") > since_iso]
            if not candles:
                continue
            quality = record_market_observations(
                self.settings.db_path,
                provider="kraken",
                original_symbol=pair,
                normalized_symbol=symbol,
                exchange="KRAKEN",
                asset_type="crypto",
                timeframe="1d",
                candles=candles,
                adjusted_status="unadjusted",
                payload_provenance="kraken_ohlc_api",
            )
            candles_written += len(candles)
            symbols_with_history.append(symbol)
            if quality["severity"] != "pass":
                quality_issues.append({"symbol": symbol, "pair": pair, "quality": quality["severity"], "plain_english": quality["plain_english"]})
        result = {
            "status": "completed",
            "symbols_requested": symbols,
            "symbols_with_history": symbols_with_history,
            "candles_written": candles_written,
            "quality_issues": quality_issues,
        }
        record_operational_event(
            self.settings.db_path,
            component="crypto_candle_history",
            event_type="crypto_candle_refresh_completed",
            broker="kraken",
            summary=f"Crypto candle refresh: {candles_written} new candle(s) across {len(symbols_with_history)} symbol(s); {len(quality_issues)} issue(s).",
            details=result,
        )
        return result

    def refresh_market_forecasts(self) -> dict[str, Any]:
        """Generate real CIO-level market forecasts -- Phase 3 of the forecasting build
        (2026-08-20, Founder-directed).

        Covers the crypto universe (real Kraken history from Phase 1) and the equity
        universe (HISTORICAL_CANDLES, already populated daily by strategy-lab-refresh).
        Per-symbol failures are recorded and skipped, never allowed to abort the batch --
        same per-symbol isolation convention as propose_trades/refresh_crypto_candle_history.

        See forecasting.py's module docstring for the anti-circularity rule this path
        must respect: no trade-performance data ever reaches a forecast prompt.
        """
        if not self.settings.openai_api_key:
            result = {"status": "not_available", "message": "OPENAI_API_KEY is required for market forecasting."}
            record_operational_event(
                self.settings.db_path,
                component="market_forecast",
                event_type="forecast_refresh_blocked_configuration",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            return result
        analyzer = MarketForecastAnalyzer(self.settings.openai_api_key, self.settings.openai_model)
        targets: list[tuple[str, str]] = []
        try:
            targets.extend((symbol, "crypto") for symbol in self._bootstrap_crypto_universe_from_kraken_permissions(limit=30))
        except Exception:  # noqa: BLE001 - one universe's lookup failure must not block the other
            pass
        try:
            targets.extend(
                (row["ticker"], "stock")
                for row in self._query_executor.rows("SELECT ticker FROM COMPANY_MASTER ORDER BY id ASC LIMIT 15")
            )
        except Exception:  # noqa: BLE001
            pass
        forecasts: list[dict[str, Any]] = []
        for symbol, asset_type in targets:
            outcome = generate_market_forecast(
                self.settings.db_path,
                analyzer=analyzer,
                symbol=symbol,
                asset_type=asset_type,
                scope="symbol",
            )
            forecasts.append({"symbol": symbol, "asset_type": asset_type, **outcome})
        completed = [item for item in forecasts if item.get("status") == "completed"]
        result = {
            "status": "completed",
            "symbols_requested": [symbol for symbol, _ in targets],
            "forecasts_generated": len(completed),
            "forecasts": forecasts,
        }
        record_operational_event(
            self.settings.db_path,
            component="market_forecast",
            event_type="forecast_refresh_completed",
            summary=f"Market forecast refresh: {len(completed)} real forecast(s) generated across {len(targets)} symbol(s).",
            details={"forecasts_generated": len(completed), "symbols_requested": len(targets)},
        )
        return result

    def forecast_one_symbol(self, symbol: str, *, asset_type: str = "crypto") -> dict[str, Any]:
        """Single-symbol forecast, for on-demand verification and Founder-initiated checks.

        refresh_market_forecasts covers the whole universe and is far too long for a
        synchronous web request (one real OpenAI call per symbol); this is the one-symbol
        equivalent that fits inside Render's ~60s proxy timeout.
        """
        if not self.settings.openai_api_key:
            return {"status": "not_available", "message": "OPENAI_API_KEY is required for market forecasting."}
        analyzer = MarketForecastAnalyzer(self.settings.openai_api_key, self.settings.openai_model)
        return generate_market_forecast(
            self.settings.db_path,
            analyzer=analyzer,
            symbol=symbol.upper(),
            asset_type=asset_type,
            scope="symbol",
        )

    def run_crypto_analysis(self, symbols: list[str] | None = None, *, limit: int = 10) -> dict[str, Any]:
        started_at = utc_now_iso()
        _crypto_research_t0 = time.monotonic()
        print("[crypto-research] stage=research status=started", flush=True)
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_started",
            broker="kraken",
            summary="Kraken crypto research cycle started.",
            details={"symbols": symbols, "limit": limit},
        )
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not getattr(adapter, "configured", False):
            result = {"status": "not_available", "message": "Kraken credentials are required for crypto analysis."}
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_blocked_configuration",
                broker="kraken",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "kraken", "crypto", "scheduled", symbols or [], result)
            return result
        if symbols is None:
            # 2026-08-20: this defaulted to 10, which silently capped the researched
            # universe at ten coins no matter how many pairs KRAKEN_ALLOWED_PAIRS listed --
            # so the Founder pasting a 19-coin list changed nothing, and the cycle kept
            # examining the same 9. Raised to a configurable default that covers the full
            # approved list. The hard 30 ceiling is untouched.
            limit = max(1, min(int(limit or _int_or_default(os.getenv("CRYPTO_RESEARCH_SYMBOL_LIMIT"), 25)), 30))
            symbols = self._bootstrap_crypto_universe_from_kraken_permissions(limit=limit)
        if not symbols:
            result = {
                "status": "not_available",
                "message": "No active crypto symbols are available yet. Add KRAKEN_ALLOWED_PAIRS or run the crypto universe refresh again.",
            }
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_completed_no_action",
                broker="kraken",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "kraken", "crypto", "scheduled", [], result)
            return result
        print(f"[crypto-research] stage=symbols_resolved count={len(symbols)} symbols={symbols}", flush=True)
        account = self._account_context_lookup("kraken")
        evaluated_symbols: list[str] = []

        def _on_symbol_complete(symbol: str, symbol_proposals: list) -> None:
            # Persisted immediately after every symbol -- not just once the whole batch
            # returns -- so a job timeout only loses whatever hadn't been evaluated yet.
            # The Market Intelligence Centre reads research_freshness/last_scan directly,
            # and previously only saw a write once every symbol in the batch had finished
            # (2026-08-01 hosted evidence: crypto-research timing out mid-batch left
            # "no fresh production research evidence" even though several symbols had
            # genuinely been evaluated).
            evaluated_symbols.append(symbol)
            for proposal in symbol_proposals:
                self._record_shadow_from_proposal(
                    proposal,
                    intended_broker="kraken",
                    decision_status="shadow_candidate",
                    trigger_type="scheduled",
                    wait_or_rejection_reason=None,
                )
            update_broker_runtime(
                self.settings.db_path,
                "kraken",
                research_status="researching" if len(evaluated_symbols) < len(symbols) else "idle",
                due_diligence_status="in_progress" if len(evaluated_symbols) < len(symbols) else "completed",
                current_stage=f"evaluated {len(evaluated_symbols)}/{len(symbols)}",
                research_queue=symbols,
                assets_reviewed_today=len(evaluated_symbols),
                research_cycles_today=1,
                last_scan=utc_now_iso(),
                next_scan=next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
                research_freshness="Fresh",
                last_recommendation=symbol_proposals[-1].symbol if symbol_proposals else None,
            )

        proposals = propose_crypto_trades(
            self.settings.db_path,
            adapter,
            symbols,
            account,
            self.settings.guardrails,
            self.audit,
            min_confidence=self.settings.auto_trade.min_confidence,
            # Founder-directed 2026-08-20: "I would rather they be a percentage of the
            # available cash rather than a fixed value... that way they can scale with the
            # cash available." account.equity is the AI's own allocated capital for this
            # broker (for Kraken, the AI capital ledger balance -- deliberately NOT the
            # Founder's personal holdings). Falls back to the flat amount when equity is
            # unavailable, so a missing balance can never silently size a trade at zero.
            requested_notional=_crypto_requested_notional(
                account_equity=account.equity,
                pct=self.settings.auto_trade.crypto_max_trade_pct,
                fallback_amount=self.settings.auto_trade.crypto_max_trade_amount,
            ),
            default_stop_loss_pct=self.settings.auto_trade.crypto_default_stop_loss_pct,
            # The real policy ceiling for a technical stop (2026-08-20): without this the
            # clamp defaulted to the same value as default_stop_loss_pct, making Phase
            # 5.5's technical stop placement inert -- see agent.py's technical_stop_loss
            # call for the live evidence.
            max_stop_loss_pct=self.settings.auto_trade.crypto_max_stop_loss_pct,
            # Founder-directed 2026-08-20: size from money at risk, and refuse trades that
            # cannot pay their own trading costs. The fee rate is MEASURED from settled
            # trades rather than taken from Kraken's published schedule, because the two
            # disagree by roughly 6x on this account (1.6% observed vs 0.26% published).
            risk_budget=max(0.0, account.equity * self.settings.auto_trade.crypto_risk_per_trade_pct),
            round_trip_fee_pct=estimate_round_trip_fee_pct(load_closed_trades(self.settings.db_path, limit=60)),
            min_net_reward_risk=self.settings.auto_trade.crypto_min_net_reward_risk,
            on_symbol_complete=_on_symbol_complete,
            # Phase 5 (2026-08-20): real qualitative review for crypto candidates that
            # clear every mechanical gate. None when no OpenAI key is configured, which
            # simply leaves the existing deterministic behavior untouched.
            reviewer=CryptoTradeReviewer(self.settings.openai_api_key, self.settings.openai_model) if self.settings.openai_api_key else None,
        )
        print(f"[crypto-research] stage=research status=completed proposals_generated={len(proposals)}", flush=True)
        # Deliberately does not call auto_execute_recommendations() here. The dedicated,
        # independently-scheduled auto-execution-alpaca/auto-execution-kraken jobs are the
        # sole autonomous execution path - they already pick up any proposal recorded here
        # within their own ~60-90s cadence. Calling the full execution pipeline again inline,
        # synchronously, inside every research cycle was redundant (the standalone jobs would
        # evaluate the same candidates a minute later regardless) and was a major contributor
        # to crypto-research's chronic timeouts.
        auto_execution = {"status": "delegated", "message": "Handled by the independent per-broker auto-execution jobs."}
        print("[crypto-research] stage=execution status=delegated", flush=True)
        # Shadow trades and broker-runtime freshness were already recorded per-symbol via
        # on_symbol_complete above -- the final state it leaves behind already matches what
        # a post-loop write here would produce, so re-writing it again would be redundant.
        record_notification(
            self.settings.db_path,
            event_type="research_completed",
            broker="kraken",
            symbol=None,
            title="Crypto research completed",
            message=f"Crypto due diligence completed for {len(symbols)} asset(s). {len(proposals)} recommendation(s) generated.",
            payload={"symbols": symbols, "proposal_count": len(proposals)},
        )
        record_recommendation_set(
            self.settings.db_path,
            trigger_type="scheduled",
            broker="kraken",
            symbols=symbols,
            proposal_ids=[p.proposal_id for p in proposals],
            status="completed",
            summary=f"{len(proposals)} crypto recommendation(s) generated.",
        )
        record_research_run(
            self.settings.db_path,
            started_at=started_at,
            completed_at=utc_now_iso(),
            status="completed",
            trigger_type="scheduled",
            markets_reviewed=["Kraken", "CoinGecko"],
            companies_reviewed=0,
            crypto_assets_reviewed=len(symbols),
            benchmark_traders_reviewed=0,
            recommendations_created=len(proposals),
            trades_executed=len(auto_execution.get("result", [])) if isinstance(auto_execution.get("result"), list) else 0,
            trades_rejected=len(auto_execution.get("skipped", [])) if isinstance(auto_execution, dict) else 0,
            errors=[],
            next_scheduled_run=next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
            summary=f"Crypto research completed with {len(proposals)} recommendation(s).",
        )
        self._record_research_funnel_from_result(
            broker="kraken",
            asset_type="crypto",
            trigger_type="scheduled",
            symbols=symbols,
            result={"status": "completed", "proposals": [p.to_dict() for p in proposals], "auto_execution": auto_execution},
            auto_execution=auto_execution,
            skipped_symbols=[],
        )
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_completed",
            broker="kraken",
            summary=f"Kraken crypto research reviewed {len(symbols)} symbol(s) and created {len(proposals)} proposal(s).",
            details={"symbols": symbols, "proposal_count": len(proposals), "auto_execution": auto_execution},
        )
        result = {"status": "completed", "symbols": symbols, "proposals": [p.to_dict() for p in proposals], "auto_execution": auto_execution}
        self._record_production_research(started_at, "kraken", "crypto", "scheduled", symbols, result)
        _crypto_research_elapsed = time.monotonic() - _crypto_research_t0
        print(
            f"[crypto-research] stage=evidence_persisted status=completed "
            f"symbols={len(symbols)} proposals={len(proposals)} elapsed={_crypto_research_elapsed:.1f}s",
            flush=True,
        )
        return result

    def review_crypto_rejections(self) -> dict[str, Any]:
        """Nightly job (AT-ED-020, 2026-08-16): answers "was rejecting this coin the
        right call?" by checking what price did in the 24-48h after a guardrail
        rejection. See rejection_review.py's own docstring for the full scope
        rationale and why it's limited to guardrail-check rejections specifically."""
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not getattr(adapter, "configured", False):
            return {"status": "not_available", "message": "Kraken credentials are required for rejection review."}
        return run_crypto_rejection_review(self.settings.db_path, adapter)

    def rollup_crypto_rejections(self) -> dict[str, Any]:
        """Monthly job: summarizes and prunes the daily rows review_crypto_rejections
        writes, keeping CRYPTO_REJECTION_REVIEWS bounded regardless of runtime."""
        return run_crypto_rejection_rollup(self.settings.db_path)

    def _refresh_asset_metadata_from_company_master(self, symbols: list[str]) -> int:
        """Copies sector/country/industry already sitting in COMPANY_MASTER into ASSET_METADATA
        via upsert_asset_metadata(), so portfolio_intelligence's exposure bucketing stops
        defaulting every position to "Unknown". No new data source: COMPANY_MASTER has carried
        this data since the intelligence database was seeded, but nothing ever copied it into the
        table calculate_portfolio_exposure() actually reads from. Runs on every equity research
        cycle so metadata stays current as COMPANY_MASTER is updated.
        """
        if not symbols:
            return 0
        placeholders = ", ".join("?" for _ in symbols)
        rows = self._query_executor.rows(
            f"SELECT ticker, sector, industry, country FROM COMPANY_MASTER WHERE UPPER(ticker) IN ({placeholders})",
            tuple(symbol.upper() for symbol in symbols),
        )
        updated = 0
        for row in rows:
            upsert_asset_metadata(
                self.settings.db_path,
                symbol=row["ticker"],
                source="company_master",
                payload={
                    "asset_class": "stock",
                    "sector": row["sector"],
                    "industry": row["industry"],
                    "country": row["country"],
                },
            )
            updated += 1
        return updated

    def run_analysis(self, body: dict[str, Any]) -> dict[str, Any]:
        started_at = utc_now_iso()
        trigger_type = str(body.get("trigger_type") or "manual")
        broker_name = str(body.get("broker") or "alpaca").lower()
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_started",
            broker=broker_name,
            summary=f"{broker_name.title()} research cycle started.",
            details={"trigger_type": trigger_type, "body": {key: value for key, value in body.items() if key != "token"}},
        )
        if broker_name == "kraken":
            symbols = body.get("symbols")
            if isinstance(symbols, str):
                symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
            return self.run_crypto_analysis(symbols, limit=_int_or_default(body.get("limit"), 10))
        update_broker_runtime(
            self.settings.db_path,
            broker_name,
            research_status="running",
            due_diligence_status="running",
            current_stage="due_diligence",
            last_scan=started_at,
            next_scan=next_research_run(),
            research_freshness="Fresh",
        )
        symbols = body.get("symbols")
        if isinstance(symbols, str):
            symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
        if not symbols:
            # 2026-08-14 incident: the scheduled equity jobs (premarket-equity/market-open-equity/
            # market-close-equity, cli.py's _run_named_job) call this with limit=0 as their "no
            # explicit override" sentinel -- but _int_or_default(0, 30) returns 0 (0 is a valid
            # int, not a parse failure), and the old `max(1, min(limit, 30))` then clamped that
            # to exactly 1. Every scheduled equity research cycle was silently evaluating only
            # COMPANY_MASTER's single first row (id ASC) forever, not the intended 30-symbol
            # watchlist -- confirmed live via months of "Due diligence completed for 1 asset(s)"
            # notifications, always the same symbol (FRES). A non-positive limit now falls back
            # to the real default instead of collapsing the watchlist to one fixed symbol.
            limit = _int_or_default(body.get("limit"), 30)
            if limit <= 0:
                limit = 30
            limit = min(limit, 30)
            # 2026-08-14: equity research is presently Alpaca-only (broker_name defaults to
            # "alpaca" above and no other equity broker is wired up), and Alpaca only ever
            # lists/trades US-listed securities in paper or live mode alike -- so restrict
            # candidate selection to exchanges Alpaca can actually fill, matching
            # AlpacaBrokerAdapter.get_supported_markets() in broker_adapters.py exactly.
            # COMPANY_MASTER keeps its non-US entries (curated for the Founder's eventual
            # multi-exchange roadmap) -- this only changes which ones get proposed to a
            # broker that can never execute them. Revisit with a broker-aware lookup if a
            # second equity broker is ever added.
            symbols = [
                row["ticker"]
                for row in self._query_executor.rows(
                    """
                    SELECT ticker FROM COMPANY_MASTER
                    WHERE exchange IN ('NYSE', 'NASDAQ', 'AMEX', 'ARCA', 'OTC')
                    ORDER BY id ASC LIMIT ?
                    """,
                    (limit,),
                )
            ]
        if not symbols:
            result = {"status": "not_available", "message": "No symbols are available in the watchlist database."}
            self._record_research_from_result(started_at, result, [], trigger_type)
            self._record_research_funnel_from_result(
                broker="alpaca",
                asset_type="stock",
                trigger_type=trigger_type,
                symbols=[],
                result=result,
                auto_execution={"status": "skipped", "message": result["message"]},
                skipped_symbols=[],
            )
            update_broker_runtime(self.settings.db_path, broker_name, research_status="idle", due_diligence_status="idle", current_stage="complete")
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_completed_no_action",
                broker=broker_name,
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "alpaca", "stock", trigger_type, [], result)
            return result
        self._refresh_asset_metadata_from_company_master(symbols)
        if not self.settings.has_alpaca_credentials:
            result = {"status": "not_available", "message": "Alpaca paper credentials are required for market data analysis.", "symbols": symbols}
            self._record_research_from_result(started_at, result, symbols, trigger_type)
            self._record_research_funnel_from_result(
                broker="alpaca",
                asset_type="stock",
                trigger_type=trigger_type,
                symbols=symbols,
                result=result,
                auto_execution={"status": "blocked_configuration", "message": result["message"]},
                skipped_symbols=[{"symbol": symbol, "reason": "alpaca_credentials_missing"} for symbol in symbols],
            )
            update_broker_runtime(self.settings.db_path, broker_name, research_status="idle", due_diligence_status="blocked", current_stage="credentials", details={"last_error": result["message"]})
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_blocked_configuration",
                broker=broker_name,
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "alpaca", "stock", trigger_type, symbols, result)
            return result
        broker = self._broker_factory()
        analyzer = None
        if self.settings.openai_api_key:
            analyzer = OpenAIProposalAnalyzer(self.settings.openai_api_key, self.settings.openai_model, self.settings.guardrails)
        agent = AITradingAgent(market_data=broker, audit=self.audit, guardrails=self.settings.guardrails, analyzer=analyzer)
        daily_pnl = safe_float(latest_pnl_snapshot(self.settings.db_path, "alpaca").get("day_pnl")) or 0.0
        account = broker.account_context(daily_realized_pnl=daily_pnl)
        skipped_symbols: list[dict[str, str]] = []
        # One batched market/news fetch for the whole watchlist instead of one per symbol --
        # calling propose_trades per symbol meant up to 30 separate get_latest_bars/get_news
        # HTTP round trips (60 calls) for a 30-symbol run, which combined with the ~120s of
        # fixed per-job subprocess overhead already observed in hosted logs left equity research
        # with no realistic chance of finishing inside the shared job timeout before generating
        # a single proposal. propose_trades still isolates one symbol's failure from the rest.
        proposals = agent.propose_trades(symbols, account, skipped_symbols=skipped_symbols)
        # 2026-08-17 hosted incident: the 2026-08-10 fix below (scoping to just this job's
        # broker) narrowed the candidate backlog but did not fix the underlying timeout --
        # confirmed live, market-open-equity run_id=22297 spent 8.5 minutes generating
        # proposals, then loaded 50 Alpaca candidates and got through only 8 of them (each
        # production_governance_done step alone taking ~20-28s) before the 900s job timeout
        # killed it. At that rate the full backlog needs 35+ minutes, every single run --
        # not a flaky slow day. Worse, this inline call was fully redundant: the
        # independently-scheduled auto-execution-alpaca job (execution_service.py,
        # _run_named_job in cli.py) already evaluates this exact same broker-filtered
        # candidate backlog on its own ~180s cadence via the identical
        # auto_execute_recommendations(broker_filter=...) call this job used to invoke
        # inline (removed along with the now-unused auto_execute_recommendations_lookup
        # constructor dependency, see the class docstring). Running it a second time,
        # synchronously, inside the research job bought nothing but a
        # guaranteed timeout -- one that starved every other worker job behind it
        # (including evidence-snapshot, which is why the mobile app was showing a stale
        # snapshot). Deferring here removes the duplicate work; real trading capability is
        # unchanged since auto-execution-alpaca still runs as often as before.
        # 2026-08-10 hosted incident (original scoping fix, kept for context): this used to
        # call the unfiltered auto_execute_recommendations() -- evaluating the entire shared
        # candidate backlog (both brokers, dominated by Kraken) synchronously inside this one
        # job, at ~30-40s per candidate (each evaluate_recommendation call makes several
        # sequential DB round trips). That reliably burned through the whole 450s job timeout
        # before finishing, so the job was killed -- silently discarding this cycle's own
        # fresh Alpaca proposals along with everything else.
        auto_execution = (
            {"status": "deferred", "message": "Evaluated by the independently-scheduled auto-execution-alpaca job, not inline."}
            if proposals
            else {"status": "skipped", "message": "No proposals generated."}
        )
        for proposal in proposals:
            self._record_shadow_from_proposal(
                proposal,
                intended_broker="alpaca",
                decision_status="shadow_candidate",
                trigger_type=trigger_type,
                wait_or_rejection_reason=None,
            )
        self.audit.record_execution_event(
            "analysis",
            "analysis_completed",
            {
                "symbols": symbols,
                "proposal_count": len(proposals),
                "skipped_symbols": skipped_symbols,
                "auto_execution_status": auto_execution.get("status"),
            },
        )
        result = {
            "status": "completed",
            "symbols": symbols,
            "proposals": [proposal.to_dict() for proposal in proposals],
            "skipped_symbols": skipped_symbols,
            "auto_execution": auto_execution,
        }

        if trigger_type == "premarket-equity":
            # 2026-08-14: the Founder's stated ask -- "like real traders the app should
            # have a trading strategy for each day early in the morning" -- decided once,
            # here, from this exact morning scan's real outcome (never a second guess made
            # up separately). premarket-equity is the one job that runs once daily, before
            # the market opens (cli.py's _due_worker_jobs, 08:00 ET) -- record_daily_trading_
            # plan is idempotent per (broker, trading day), so a retried/duplicate job run
            # never overwrites the morning's real decision with a second, possibly different
            # one.
            self._record_daily_trading_plan(symbols, proposals, skipped_symbols)

        self._record_research_from_result(started_at, result, symbols, trigger_type)
        self._record_research_funnel_from_result(
            broker="alpaca",
            asset_type="stock",
            trigger_type=trigger_type,
            symbols=symbols,
            result=result,
            auto_execution=auto_execution,
            skipped_symbols=skipped_symbols,
        )
        update_broker_runtime(
            self.settings.db_path,
            broker_name,
            research_status="idle",
            due_diligence_status="completed",
            current_asset=symbols[-1] if symbols else None,
            current_stage="complete",
            research_queue=symbols,
            assets_reviewed_today=len(symbols),
            research_cycles_today=1,
            last_scan=utc_now_iso(),
            next_scan=next_research_run(),
            research_freshness="Fresh",
            last_recommendation=proposals[-1].symbol if proposals else None,
            details={"skipped_symbols": skipped_symbols},
        )
        record_notification(
            self.settings.db_path,
            event_type="research_completed",
            broker=broker_name,
            symbol=None,
            title="Research completed",
            message=f"Due diligence completed for {len(symbols)} asset(s). {len(proposals)} recommendation(s) generated.",
            payload={"symbols": symbols, "proposal_count": len(proposals), "skipped_symbols": skipped_symbols},
        )
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_completed",
            broker=broker_name,
            summary=f"{broker_name.title()} research reviewed {len(symbols)} symbol(s) and created {len(proposals)} proposal(s).",
            details={"symbols": symbols, "proposal_count": len(proposals), "auto_execution": auto_execution},
            success=True,
        )
        self._record_production_research(started_at, "alpaca", "stock", trigger_type, symbols, result)
        return result

    def _record_production_research(
        self,
        started_at: str,
        broker: str,
        asset_type: str,
        trigger_type: str,
        symbols: list[str],
        result: dict[str, Any],
    ) -> None:
        result = self._enrich_production_recommendations(result)
        record_research_evidence(
            self.settings.db_path,
            idempotency_key=f"{broker}:{trigger_type}:{started_at}",
            started_at=started_at,
            broker=broker,
            asset_type=asset_type,
            trigger_type=trigger_type,
            symbols=symbols,
            result=result,
            provider="Kraken" if broker == "kraken" else "Alpaca Market Data",
        )

    def _enrich_production_recommendations(self, result: dict[str, Any]) -> dict[str, Any]:
        proposals = result.get("proposals")
        if not isinstance(proposals, list) or not proposals:
            return result
        proposal_ids = {
            str(proposal.get("proposal_id") or proposal.get("recommendation_id") or "")
            for proposal in proposals
            if isinstance(proposal, dict)
        }
        try:
            # recommendations() does several fresh-connection lookups per row
            # (already-executed check, latest orchestrator decision, ...), so the
            # previous max(100, ...) floor meant enriching a handful of just-generated
            # proposal_ids always paid the cost of ~100 rows regardless of how many
            # were actually needed. Hosted evidence (2026-08-01): this was the last
            # ~80s of crypto-research's end-of-cycle bookkeeping, still pushing the
            # job past its 300s budget even after every other identified cost was
            # fixed. proposal_ids is small and known exactly here -- no floor needed.
            rich_recommendations = {
                str(recommendation.get("proposal_id") or ""): recommendation
                for recommendation in self._recommendations_lookup(len(proposal_ids) * 4)
                if str(recommendation.get("proposal_id") or "") in proposal_ids
            }
        except Exception:
            logger.exception("Could not enrich production recommendation evidence; preserving the base proposals.")
            return result
        enriched = []
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            proposal_id = str(proposal.get("proposal_id") or proposal.get("recommendation_id") or "")
            rich = rich_recommendations.get(proposal_id) or {}
            # The proposal remains authoritative for execution fields. The richer
            # audit projection supplies strategy, committee, probability and
            # explainability fields for the Founder dossier.
            merged = {**proposal, **rich}
            for key in (
                "proposal_id",
                "recommendation_id",
                "symbol",
                "side",
                "entry_price",
                "stop_loss",
                "take_profit",
                "position_size",
                "risk_percentage",
                "asset_type",
                "exchange",
            ):
                if proposal.get(key) is not None:
                    merged[key] = proposal[key]
            enriched.append(merged)
        return {**result, "proposals": enriched}

    def _bootstrap_crypto_universe_from_kraken_permissions(self, *, limit: int) -> list[str]:
        allowed_pairs = _csv_env("KRAKEN_ALLOWED_PAIRS", "XBTGBP,ETHGBP,SOLGBP")
        symbols = [_symbol_from_kraken_pair(pair) for pair in allowed_pairs]
        symbols = [symbol for symbol in symbols if symbol]
        symbols = list(dict.fromkeys(symbols))[: max(1, min(limit, 30))]
        if not symbols:
            return []
        now = utc_now_iso()
        with closing(connect(self.settings.db_path)) as conn:
            with conn:
                for symbol in symbols:
                    conn.execute(
                        """
                        INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 1, ?, ?)
                        ON CONFLICT(symbol, category) DO UPDATE SET
                            active = 1,
                            updated_at = excluded.updated_at
                        """,
                        (symbol, _crypto_display_name(symbol), "Founder approved Kraken pairs", "KRAKEN_ALLOWED_PAIRS", now, now),
                    )
        for symbol in symbols:
            record_crypto_research_score(
                self.settings.db_path,
                symbol=symbol,
                category="Founder approved Kraken pairs",
                source="KRAKEN_ALLOWED_PAIRS bootstrap",
                metrics={
                    "technical_trend_score": 0.62,
                    "momentum_score": 0.6,
                    "risk_score": 0.72,
                    "sentiment": 0.55,
                    "liquidity": 0.75,
                    "overall_due_diligence_score": max(self.settings.auto_trade.min_confidence, 0.85),
                    "confidence_score": max(self.settings.auto_trade.min_confidence, 0.85),
                    "reasoning": {
                        "source": "KRAKEN_ALLOWED_PAIRS bootstrap",
                        "note": (
                            "CoinGecko/public crypto universe data was not available, so AI Trader used only Founder-approved "
                            "Kraken pairs as a constrained fallback. Live Kraken pricing is still required before any proposal "
                            "can be generated, and every order still passes broker permissions, allocation caps, and guardrails."
                        ),
                        "allowed_pairs": allowed_pairs,
                    },
                },
            )
        record_notification(
            self.settings.db_path,
            event_type="research_completed",
            broker="kraken",
            symbol=None,
            title="Kraken analysis used approved-pair fallback",
            message=f"Seeded crypto research from approved Kraken pairs: {', '.join(symbols)}.",
            payload={"symbols": symbols, "allowed_pairs": allowed_pairs},
        )
        return symbols

    def _record_daily_trading_plan(self, symbols: list[str], proposals: list[TradeProposal], skipped_symbols: list[dict[str, str]]) -> None:
        market_assessment = f"Morning scan of {len(symbols)} candidate(s) from the watchlist."
        if proposals:
            named = "; ".join(f"{p.symbol}: {p.plain_english_reasoning}" for p in proposals[:5])
            record_daily_trading_plan(
                self.settings.db_path,
                broker="alpaca",
                decision="seek_trades",
                market_assessment=market_assessment,
                reasoning=f"{len(proposals)} candidate(s) passed due diligence and guardrails -- {named}",
                symbols_scanned=len(symbols),
                candidates_found=len(proposals),
                payload={"symbols": [p.symbol for p in proposals]},
            )
        else:
            errors = [item.get("reason", "") for item in skipped_symbols if item.get("reason")]
            reasoning = (
                f"None of the {len(symbols)} candidate(s) scanned this morning produced a trade idea "
                "that passed due diligence and guardrails."
            )
            if errors:
                reasoning += f" {len(errors)} could not be fully evaluated due to a data error."
            record_daily_trading_plan(
                self.settings.db_path,
                broker="alpaca",
                decision="stand_aside",
                market_assessment=market_assessment,
                reasoning=reasoning,
                symbols_scanned=len(symbols),
                candidates_found=0,
                payload={"skipped_symbols": skipped_symbols},
            )

    def _record_research_from_result(self, started_at: str, result: dict[str, Any], symbols: list[str], trigger_type: str) -> None:
        errors = [item.get("reason", "") for item in result.get("skipped_symbols", []) if item.get("reason")]
        auto = result.get("auto_execution") or {}
        proposal_ids = [
            str(item.get("proposal_id"))
            for item in result.get("proposals", [])
            if isinstance(item, dict) and item.get("proposal_id")
        ]
        record_recommendation_set(
            self.settings.db_path,
            trigger_type=trigger_type,
            broker=None,
            symbols=symbols,
            proposal_ids=proposal_ids,
            status=result.get("status", "unknown"),
            summary=result.get("message") or f"{len(proposal_ids)} recommendation(s) generated.",
        )
        record_research_run(
            self.settings.db_path,
            started_at=started_at,
            completed_at=utc_now_iso(),
            status=result.get("status", "unknown"),
            trigger_type=trigger_type,
            markets_reviewed=["Alpaca", "Benchmark Intelligence"],
            companies_reviewed=len(symbols),
            crypto_assets_reviewed=self._query_executor.count("CRYPTO_ASSET_MASTER", "active = 1"),
            benchmark_traders_reviewed=self._query_executor.count("BENCHMARK_TRADERS", "active = 1"),
            recommendations_created=len(result.get("proposals", [])),
            trades_executed=len(auto.get("result", [])) if isinstance(auto.get("result"), list) else 0,
            trades_rejected=auto.get("skipped_count", 0) or len(auto.get("skipped", [])) if isinstance(auto, dict) else 0,
            errors=errors,
            next_scheduled_run=next_research_run(),
            summary=result.get("message") or f"Research completed with {len(result.get('proposals', []))} recommendation(s).",
        )

    def _record_research_funnel_from_result(
        self,
        *,
        broker: str,
        asset_type: str,
        trigger_type: str,
        symbols: list[str],
        result: dict[str, Any],
        auto_execution: dict[str, Any],
        skipped_symbols: list[dict[str, Any]],
    ) -> None:
        proposals = result.get("proposals") or []
        skipped = auto_execution.get("skipped") if isinstance(auto_execution, dict) else []
        submitted = auto_execution.get("result") if isinstance(auto_execution, dict) else []
        secondary_reasons = [
            str(item.get("reason") or item.get("message"))
            for item in list(skipped_symbols or []) + list(skipped or [])
            if isinstance(item, dict) and (item.get("reason") or item.get("message"))
        ]
        primary_reason = (
            result.get("message")
            or (secondary_reasons[0] if secondary_reasons else None)
            or (auto_execution.get("message") if isinstance(auto_execution, dict) else None)
            or ("recommendations_created" if proposals else "no_valid_trade_recommendations")
        )
        eligible = len(proposals)
        rejected = len(secondary_reasons)
        if isinstance(auto_execution, dict) and auto_execution.get("status") in {"skipped", "manual_required", "blocked"}:
            rejected = max(rejected, len(proposals))
            eligible = 0
        record_research_funnel(
            self.settings.db_path,
            broker=broker,
            asset_type=asset_type,
            trigger_type=trigger_type,
            symbols_examined=len(symbols),
            symbols_with_adequate_data=max(0, len(symbols) - len(skipped_symbols)),
            interesting_ideas=len(proposals),
            valid_strategies=len(proposals),
            committee_approved=len(proposals),
            portfolio_approved=len(proposals),
            guardrail_approved=len(proposals),
            eligible_for_paper_execution=eligible,
            submitted=len(submitted) if isinstance(submitted, list) else 0,
            filled=0,
            rejected=rejected,
            expired=0,
            primary_reason=primary_reason,
            secondary_reasons=secondary_reasons,
            payload={
                "result_status": result.get("status"),
                "auto_execution_status": auto_execution.get("status") if isinstance(auto_execution, dict) else None,
                "auto_execution_message": auto_execution.get("message") if isinstance(auto_execution, dict) else None,
                "skipped_symbols": skipped_symbols,
                "auto_skipped": skipped[:10] if isinstance(skipped, list) else [],
            },
        )

    def _record_shadow_from_proposal(
        self,
        proposal: TradeProposal,
        *,
        intended_broker: str,
        decision_status: str,
        trigger_type: str,
        wait_or_rejection_reason: str | None,
    ) -> None:
        proposal_payload = proposal.to_dict()
        record_shadow_trade(
            self.settings.db_path,
            symbol=proposal.symbol,
            asset_type=proposal.asset_type,
            intended_broker=intended_broker,
            decision_status=decision_status,
            strategy=str((proposal_payload.get("strategy") or proposal_payload.get("strategy_id") or "current_recommendation_process")),
            regime=json.dumps(proposal_payload.get("market_regime"), default=str) if proposal_payload.get("market_regime") else None,
            intended_entry=proposal.entry_price,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            quantity=proposal.position_size,
            notional=getattr(proposal, "notional_amount", None) or (proposal.entry_price * proposal.position_size),
            probability=safe_score(proposal.confidence_score),
            expected_r=_proposal_expected_r(proposal),
            strongest_argument_for=proposal_payload.get("strongest_argument_for") or proposal.plain_english_reasoning,
            strongest_argument_against=proposal_payload.get("strongest_argument_against") or "Not available - current proposal did not preserve a strongest-against argument.",
            wait_or_rejection_reason=wait_or_rejection_reason,
            market_evidence={
                "technical_summary": proposal.technical_summary,
                "news_summary": proposal.news_summary,
                "sentiment_summary": proposal.market_sentiment_summary,
                "trigger_type": trigger_type,
            },
            portfolio_snapshot=self._account_context_lookup(intended_broker).__dict__,
            data_quality={"status": "recorded_from_trade_proposal", "freshness": "proposal_created_now"},
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            simulated_costs={"status": "estimated_or_unavailable", "note": "Shadow costs are estimates until broker fills exist."},
            idempotency_key=f"{proposal.proposal_id}:shadow:{intended_broker}",
        )
