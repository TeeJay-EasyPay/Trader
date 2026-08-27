from __future__ import annotations

import json
import math
import sqlite3
import threading
from .database import connect, selected_backend
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .models import utc_now_iso


OPERATIONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS PORTFOLIO_SNAPSHOTS (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    exchange TEXT NOT NULL,
    account_currency TEXT,
    cash REAL,
    portfolio_value REAL,
    buying_power REAL,
    open_positions_count INTEGER,
    day_pnl REAL,
    week_pnl REAL,
    month_pnl REAL,
    month_start_value REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS RESEARCH_RUNS (
    research_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    markets_reviewed TEXT,
    companies_reviewed INTEGER,
    crypto_assets_reviewed INTEGER,
    benchmark_traders_reviewed INTEGER,
    recommendations_created INTEGER,
    trades_executed INTEGER,
    trades_rejected INTEGER,
    errors TEXT,
    next_scheduled_run TEXT,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS CRYPTO_ASSET_MASTER (
    asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    market_cap_rank INTEGER,
    source TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    last_updated TEXT NOT NULL
);
"""


QUALITATIVE_SCORES = {
    "excellent": 0.95,
    # 2026-08-22: "strong" was missing entirely, so safe_score() returned None for it and
    # the caller fell through to 0.0 -- meaning the 19 companies rated "Strong", the BEST
    # rating in INVESTMENT_WATCHLIST, scored ZERO for investment philosophy fit while the 28
    # merely "Good" ones scored 0.75. Confirmed live: SCCO/FCX/MLM (Strong) came back 0.0
    # and MSFT/LULU/ISRG (Good) came back 0.75, against a 0.85 auto-trade threshold that
    # neither could ever reach. Every Alpaca recommendation was blocked on
    # "Investment philosophy fit is below 85%" as a direct result. Placed above "high" since
    # Strong is the top label this dataset actually uses (Strong > Good > Moderate).
    "strong": 0.9,
    "very high": 0.9,
    "high": 0.85,
    "good": 0.75,
    "positive": 0.75,
    "medium": 0.5,
    "moderate": 0.5,
    "neutral": 0.5,
    "cautious": 0.35,
    "low": 0.25,
    "poor": 0.15,
    "negative": 0.15,
    "unknown": None,
    "not available": None,
}


_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_SCHEMA_KEYS: set[str] = set()


def _schema_key(db_path: Path) -> str:
    if selected_backend() == "postgres":
        return "postgres"
    return f"sqlite:{Path(db_path).resolve()}"


def initialize_operational_schema(db_path: Path) -> None:
    """Create schema once per process.

    Called unconditionally from 6 different functions in this module
    (record_notification, record_recommendation_set, record_research_run, etc.),
    each of which record_crypto_analysis's end-of-cycle bookkeeping calls in
    sequence. Hosted evidence (2026-08-01): after the propose_crypto_trades loop
    itself started finishing well inside budget (all 9 symbols evaluated), this
    end-of-cycle bookkeeping tail alone still consumed ~71s and pushed the job
    over its 300s timeout. Same fix pattern as kraken_reconciliation,
    trading_intelligence, and multi_broker.
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
                conn.executescript(OPERATIONAL_SCHEMA)
        _INITIALIZED_SCHEMA_KEYS.add(key)


def safe_score(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 100 if number > 1 else number
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in QUALITATIVE_SCORES:
        return QUALITATIVE_SCORES[lowered]
    try:
        cleaned = lowered.replace("%", "")
        number = float(cleaned)
    except ValueError:
        return None
    return number / 100 if number > 1 else number


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def display_value(value: Any, reason: str) -> Any:
    return value if value not in (None, "") else f"Not available - {reason}"


def record_portfolio_snapshot(
    db_path: Path,
    *,
    broker: str,
    exchange: str,
    account: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    notes: str,
) -> dict[str, Any]:
    initialize_operational_schema(db_path)
    account = account or {}
    now = utc_now_iso()
    cash = safe_float(account.get("cash"))
    portfolio_value = safe_float(account.get("portfolio_value") or account.get("equity"))
    buying_power = safe_float(account.get("buying_power"))
    currency = account.get("currency")
    month_start_value = _month_start_value(db_path, broker, exchange, now) or portfolio_value
    day_pnl = _pnl_since(db_path, broker, exchange, portfolio_value, days=1)
    week_pnl = _pnl_since(db_path, broker, exchange, portfolio_value, days=7)
    month_pnl = None if month_start_value is None or portfolio_value is None else portfolio_value - month_start_value
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PORTFOLIO_SNAPSHOTS (
                    created_at, broker, exchange, account_currency, cash, portfolio_value,
                    buying_power, open_positions_count, day_pnl, week_pnl, month_pnl,
                    month_start_value, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    broker,
                    exchange,
                    currency,
                    cash,
                    portfolio_value,
                    buying_power,
                    len(positions),
                    day_pnl,
                    week_pnl,
                    month_pnl,
                    month_start_value,
                    notes,
                ),
            )
    return {
        "created_at": now,
        "broker": broker,
        "exchange": exchange,
        "account_currency": currency,
        "cash": cash,
        "portfolio_value": portfolio_value,
        "buying_power": buying_power,
        "open_positions_count": len(positions),
        "day_pnl": day_pnl,
        "week_pnl": week_pnl,
        "month_pnl": month_pnl,
        "month_start_value": month_start_value,
        "notes": notes,
    }


def record_research_run(
    db_path: Path,
    *,
    started_at: str,
    completed_at: str | None,
    status: str,
    trigger_type: str,
    markets_reviewed: list[str],
    companies_reviewed: int,
    crypto_assets_reviewed: int,
    benchmark_traders_reviewed: int,
    recommendations_created: int,
    trades_executed: int,
    trades_rejected: int,
    errors: list[str],
    next_scheduled_run: str | None,
    summary: str,
) -> None:
    initialize_operational_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO RESEARCH_RUNS (
                    started_at, completed_at, status, trigger_type, markets_reviewed,
                    companies_reviewed, crypto_assets_reviewed, benchmark_traders_reviewed,
                    recommendations_created, trades_executed, trades_rejected, errors,
                    next_scheduled_run, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    completed_at,
                    status,
                    trigger_type,
                    json.dumps(markets_reviewed),
                    companies_reviewed,
                    crypto_assets_reviewed,
                    benchmark_traders_reviewed,
                    recommendations_created,
                    trades_executed,
                    trades_rejected,
                    json.dumps(errors),
                    next_scheduled_run,
                    summary,
                ),
            )


def latest_pnl_snapshot(db_path: Path, broker: str) -> dict[str, Any]:
    initialize_operational_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT day_pnl, week_pnl, month_pnl, portfolio_value
            FROM PORTFOLIO_SNAPSHOTS WHERE broker = ?
            ORDER BY snapshot_id DESC LIMIT 1
            """,
            (broker.lower(),),
        ).fetchone()
        peak = conn.execute(
            "SELECT MAX(portfolio_value) FROM PORTFOLIO_SNAPSHOTS WHERE broker = ?",
            (broker.lower(),),
        ).fetchone()
    return {
        "day_pnl": row["day_pnl"] if row else None,
        "week_pnl": row["week_pnl"] if row else None,
        "month_pnl": row["month_pnl"] if row else None,
        "portfolio_value": row["portfolio_value"] if row else None,
        "peak_equity": peak[0] if peak and peak[0] is not None else None,
    }


def latest_research_run(db_path: Path) -> dict[str, Any] | None:
    initialize_operational_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM RESEARCH_RUNS ORDER BY research_run_id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


CRYPTO_CATEGORY_ENDPOINTS: dict[str, str] = {
    "Top 20 by market cap": (
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc"
        "&per_page=20&page=1&price_change_percentage=24h,7d,30d"
    ),
    "Top 20 AI coins": (
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=artificial-intelligence"
        "&order=market_cap_desc&per_page=20&page=1&price_change_percentage=24h,7d,30d"
    ),
    "Top 20 security/privacy coins": (
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=privacy-coins"
        "&order=market_cap_desc&per_page=20&page=1&price_change_percentage=24h,7d,30d"
    ),
}


def _float_env_hours(name: str, default: float) -> float:
    import os

    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _hours_since_last_universe_refresh(db_path: Path) -> float | None:
    """Age in hours of the newest CRYPTO_ASSET_MASTER row, or None if there are none."""
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute("SELECT MAX(last_updated) FROM CRYPTO_ASSET_MASTER").fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not row or not row[0]:
        return None
    try:
        stamp = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def seed_crypto_universe(db_path: Path, *, fetch_live: bool = False) -> dict[str, Any]:
    initialize_operational_schema(db_path)
    assets: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    source = "Unavailable"
    notes = "Live public ranking fetch was not requested."
    # 2026-08-23: this ran hourly and made three CoinGecko calls per run, which the free
    # public API answered with "HTTP Error 429: Too Many Requests" on every attempt, and the
    # retrying then burned the worker's whole 180s job budget -- confirmed live as a
    # "Worker job timed out: crypto-universe-refresh" every hour. A starved worker loop is
    # the documented cause of earlier production incidents, so the cost was not confined to
    # this job. Market-cap rankings barely move within a day, so refreshing at most every
    # CRYPTO_UNIVERSE_MIN_REFRESH_HOURS (default 12) keeps the data just as useful while
    # taking the rate-limiting and the timeouts away.
    if fetch_live:
        min_interval = _float_env_hours("CRYPTO_UNIVERSE_MIN_REFRESH_HOURS", 12.0)
        age_hours = _hours_since_last_universe_refresh(db_path)
        if age_hours is not None and age_hours < min_interval:
            return {
                "inserted": 0,
                "source": "Cached",
                "skipped": True,
                "notes": (
                    f"Universe last refreshed {age_hours:.1f}h ago; minimum interval is "
                    f"{min_interval:.0f}h. Skipped to avoid CoinGecko rate limiting."
                ),
            }
    if fetch_live:
        try:
            for category_label, url in CRYPTO_CATEGORY_ENDPOINTS.items():
                with urlopen(url, timeout=20) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                for row in raw:
                    assets.append(_crypto_row(row, category_label, "CoinGecko public markets API"))
                    market_rows.append(row)
            source = "CoinGecko public markets API"
            notes = "Fetched live public market data across market-cap, AI, and privacy/security categories."
        except Exception as exc:
            notes = f"Rankings unavailable: {exc}"
    with closing(connect(db_path)) as conn:
        with conn:
            if assets:
                for asset in assets:
                    conn.execute(
                        """
                        INSERT INTO CRYPTO_ASSET_MASTER (
                            symbol, name, category, market_cap_rank, source, active, notes, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset["symbol"],
                            asset["name"],
                            asset["category"],
                            asset["market_cap_rank"],
                            asset["source"],
                            1,
                            asset["notes"],
                            utc_now_iso(),
                        ),
                    )
    if assets:
        _populate_crypto_master_and_scores(db_path, assets, market_rows)
        return {"inserted": len(assets), "source": source, "notes": notes}
    if fetch_live:
        # CoinGecko was asked and did not answer (outage, or the HTTP 429 rate-limiting this
        # free API already returns in production). Before this fallback existed that ended the
        # function with zero scores written and no signal that crypto research had stopped --
        # the universe just kept trading on whatever scores it last had, however stale. Kraken's
        # own stored candles cover the price behaviour, so score from those instead.
        # Deferred import: sprint6 imports this module, so a module-level import is circular.
        from .sprint6 import record_operational_event

        fallback = record_crypto_scores_from_kraken_candles(db_path)
        record_operational_event(
            db_path,
            component="crypto_universe",
            event_type="crypto_universe_scored_from_kraken_fallback",
            broker="kraken",
            severity="warning",
            summary=(
                f"CoinGecko was unavailable, so {fallback['scored']} crypto symbols were scored "
                f"from stored Kraken candles instead. Market-cap ranking is not refreshed and "
                f"liquidity is carried forward from the last CoinGecko reading."
            ),
            details={"coingecko_error": notes, **fallback},
            success=fallback["scored"] > 0,
        )
        return {
            "inserted": 0,
            "source": KRAKEN_CANDLE_SOURCE if fallback["scored"] else source,
            "notes": f"{notes} Fell back to Kraken candles: {fallback['notes']}",
            "fallback": fallback,
        }
    return {"inserted": len(assets), "source": source, "notes": notes}


def _populate_crypto_master_and_scores(db_path: Path, assets: list[dict[str, Any]], market_rows: list[dict[str, Any]]) -> None:
    # Deferred imports: foundation.py and multi_broker.py both import this module, so importing
    # them at module load time here would be circular. By call time (runtime, not import time)
    # both modules are already fully loaded, so this is safe.
    from .foundation import initialize_foundation_schema
    from .multi_broker import record_crypto_research_score

    initialize_foundation_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            for asset, raw_row in zip(assets, market_rows):
                conn.execute(
                    """
                    INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(symbol, category) DO UPDATE SET
                        active = 1, name = excluded.name, updated_at = excluded.updated_at
                    """,
                    (asset["symbol"], asset["name"], asset["category"], asset["source"], now, now),
                )
                conn.execute(
                    """
                    INSERT INTO CRYPTO_MARKET_DATA (
                        symbol, observed_at, price_usd, market_cap_usd, volume_24h_usd, source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset["symbol"],
                        now,
                        safe_float(raw_row.get("current_price")),
                        safe_float(raw_row.get("market_cap")),
                        safe_float(raw_row.get("total_volume")),
                        asset["source"],
                        json.dumps(raw_row, default=str),
                    ),
                )
    # Indicators come from candles regardless of which provider supplied the price changes,
    # so the CoinGecko path gets them too -- otherwise rsi/macd/volume_trend would only ever
    # be populated on the fallback path, and the primary path would keep writing the empty
    # columns this audit found. Loaded in ONE batched query rather than per symbol inside the
    # loop, the remote-Postgres cost class already fixed repeatedly in this codebase.
    from .market_intelligence_platform import load_recent_observations_batch

    symbols = [asset["symbol"] for asset in assets]
    try:
        candles_by_symbol = load_recent_observations_batch(db_path, symbols, timeframe="1d", limit=120)
    except Exception:  # noqa: BLE001 - missing candles must not stop the scores being written
        candles_by_symbol = {}
    for asset, raw_row in zip(assets, market_rows):
        metrics = _crypto_metrics_from_market_row(raw_row, db_path=db_path, symbol=asset["symbol"])
        candles = candles_by_symbol.get(asset["symbol"]) or []
        if candles:
            metrics = {**metrics, **_technical_indicators(candles)}
        record_crypto_research_score(
            db_path,
            symbol=asset["symbol"],
            category=asset["category"],
            metrics=metrics,
            source=asset["source"],
        )


def _recent_crypto_news_coverage_score(db_path: Path, symbol: str, *, window_hours: int = 48, cap: int = 5) -> float | None:
    """Phase D: a real, honestly-labeled coverage-volume proxy computed from
    Phase A's CRYPTO_NEWS table -- how many real articles this symbol has had
    in the last `window_hours`, normalized to 0..1 and capped at `cap`
    articles. Deliberately NOT a sentiment score: this codebase's existing
    convention (see _crypto_metrics_from_market_row's docstring/comment
    below) is to leave a metric unset rather than fabricate it, and no real
    sentiment analysis exists anywhere in this codebase -- article *volume*
    is real and honestly computable from data this system actually has;
    article *sentiment* is not, and populating this field must never be
    read as a substitute for that. Returns None (not 0.0) when the table
    does not exist yet or the query fails, so a fresh/pre-Phase-A database
    behaves exactly as it did before this function existed.
    """
    try:
        with closing(connect(db_path)) as conn:
            cutoff = (datetime.now(timezone.utc).timestamp()) - (window_hours * 3600)
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
            count = conn.execute(
                "SELECT COUNT(*) FROM CRYPTO_NEWS WHERE symbol = ? AND published_at >= ?",
                (symbol.upper(), cutoff_iso),
            ).fetchone()[0]
    except sqlite3.OperationalError:
        return None
    return round(min(1.0, count / cap), 4)


def _recent_crypto_sentiment(db_path: Path | None, symbol: str | None) -> float | None:
    """Recent news sentiment for one coin, or None when it has not been judged.

    Deferred import: crypto_sentiment reads this module's connect/schema helpers indirectly,
    and this is a runtime-only dependency. Any failure returns None rather than raising --
    unscored sentiment is a known, honest state; a crashed research cycle is not.
    """
    if db_path is None or not symbol:
        return None
    try:
        from .crypto_sentiment import latest_sentiment

        return latest_sentiment(db_path).get(str(symbol).upper())
    except Exception:  # noqa: BLE001 - sentiment is one input, never a reason to stop research
        return None


def _crypto_metrics_from_market_row(row: dict[str, Any], *, db_path: Path | None = None, symbol: str | None = None) -> dict[str, Any]:
    change_24h = safe_float(row.get("price_change_percentage_24h_in_currency") or row.get("price_change_percentage_24h"))
    change_7d = safe_float(row.get("price_change_percentage_7d_in_currency"))
    change_30d = safe_float(row.get("price_change_percentage_30d_in_currency"))
    market_cap = safe_float(row.get("market_cap"))
    volume = safe_float(row.get("total_volume"))
    liquidity = liquidity_score(volume, market_cap)
    volatility = min(1.0, abs(change_30d) / 100) if change_30d is not None else None
    risk_score = round(1.0 - volatility, 4) if volatility is not None else None
    news_score = _recent_crypto_news_coverage_score(db_path, symbol) if db_path is not None and symbol else None
    return {
        "technical_trend_score": _pct_to_unit_score(change_7d, _TREND_FULL_SCALE_PCT),
        "momentum_score": _pct_to_unit_score(change_24h, _MOMENTUM_FULL_SCALE_PCT),
        "volatility": volatility,
        "liquidity": liquidity,
        "risk_score": risk_score,
        # news_score, when db_path/symbol are supplied, is a real coverage-volume proxy
        # from Phase A's CRYPTO_NEWS table (see _recent_crypto_news_coverage_score) -- not
        # sentiment. No real sentiment analysis exists anywhere in this codebase, and
        # on-chain activity has no wired data source yet either; both stay unset (None)
        # rather than fabricated, so due diligence correctly treats them as
        # insufficient_data instead of silently passing. news_score is also NOT included
        # in overall_due_diligence_score's average (multi_broker.py's
        # record_crypto_research_score only averages technical/momentum/risk/sentiment/
        # liquidity) -- it is informational, not a factor in the accept/reject threshold.
        # 2026-08-27, Founder-directed: this was a hard None, which record_crypto_research_score
        # turned into 0.0 inside a five-way average -- asserting that every coin had terrible
        # sentiment when nothing had ever measured it. Now a real judgement of recent news
        # coverage when there is coverage to judge, and still None when there is not.
        "sentiment": _recent_crypto_sentiment(db_path, symbol),
        "news_score": news_score,
        "onchain_activity": None,
        "reasoning": {
            "source": "CoinGecko public markets API",
            "note": "technical/momentum/volatility/liquidity are computed from live price, volume, and market-cap data. "
            "news_score (when available) is real article-volume coverage from CryptoPanic, not sentiment. "
            "sentiment, when present, is a judgement of recent news coverage (crypto_sentiment.py); "
            "on-chain activity has no wired data source and is left blank.",
            "price_change_pct_24h": change_24h,
            "price_change_pct_7d": change_7d,
            "price_change_pct_30d": change_30d,
            # 2026-08-27: the raw turnover behind the liquidity SCORE. Recorded because the
            # Kraken path carries this coin's liquidity forward, and without the raw figure it
            # cannot tell an old ratio (0.041) from a new score (0.041) -- the two mean
            # opposite things, and guessing between them is exactly the class of error this
            # calibration pass exists to remove.
            "liquidity_turnover": (volume / market_cap) if market_cap and volume and market_cap > 0 else None,
        },
    }


# How big a move has to be to count as a full-strength signal over each window. Chosen from
# the real distribution rather than from round numbers: today's 24h moves across the traded
# universe spanned -2.56% to +4.09%, and a 3-4% day is a genuinely strong one in crypto.
#
# 2026-08-27, same defect as liquidity and found while fixing it. Both scores previously used a
# fixed +/-100% scale, so a 4% daily move -- a big day -- scored 0.54, barely off neutral, and
# every coin was squeezed into a band around 0.5 no matter what it did. The signal was real and
# the scale erased it, which is exactly what the Founder was pointing at when he asked whether
# liquidity should inform "momentum going to push and sustain a rally".
_MOMENTUM_FULL_SCALE_PCT = 8.0   # 24-hour move
_TREND_FULL_SCALE_PCT = 25.0     # 7-day move


def _pct_to_unit_score(pct: float | None, full_scale_pct: float = 100.0) -> float | None:
    """A percentage move mapped onto 0-1, where `full_scale_pct` is the end of the scale.

    0.5 is unchanged, 1.0 is a full-strength rise, 0.0 a full-strength fall. Clamped, so an
    exceptional move saturates rather than distorting the average.
    """
    if pct is None:
        return None
    scale = float(full_scale_pct) if full_scale_pct else 100.0
    return round(max(0.0, min(1.0, 0.5 + (float(pct) / (2.0 * scale)))), 4)


# Turnover (24h volume / market cap) that marks the ends of the useful range. Below the floor
# a position is genuinely hard to enter and leave; above the ceiling extra turnover tells you
# nothing more about whether a move can be sustained.
_LIQUIDITY_FLOOR_TURNOVER = 0.002
_LIQUIDITY_CEILING_TURNOVER = 0.10


def liquidity_score(volume: float | None, market_cap: float | None) -> float | None:
    """Turnover expressed as a 0-1 quality score.

    2026-08-27, Founder-challenged: "shouldn't liquidity be a part of gauging whether momentum
    is going to push and sustain a rally?" It should, and it was already in the score -- but on
    the wrong scale, which quietly destroyed it.

    Liquidity was stored as the raw ratio volume/market_cap. Real values: ETH 0.041, XRP 0.044,
    SOL 0.064. Those are HEALTHY -- a coin turning over 4% of its entire market cap in a day is
    deeply liquid. Averaged into a due-diligence score whose other components run 0-1, though,
    0.041 reads as "4 out of 100", so every genuinely liquid coin was scored as nearly
    untradeable and the composite could never approach the 0.85 bar required to trade.

    Log-scaled between the two ends of the range because it spans two orders of magnitude and
    the interesting differences are multiplicative: 0.002 -> 0.004 is the difference between
    untradeable and thin, while 0.06 -> 0.12 barely matters. On a linear scale the thin end,
    which is the end that can actually hurt, would be indistinguishable.

    Returns None when either input is missing, so an unmeasured coin stays unmeasured rather
    than scoring zero -- the exact failure this whole audit has been unpicking.
    """
    volume_value = safe_float(volume)
    cap_value = safe_float(market_cap)
    if not cap_value or cap_value <= 0 or volume_value is None or volume_value < 0:
        return None
    turnover = volume_value / cap_value
    if turnover <= _LIQUIDITY_FLOOR_TURNOVER:
        return 0.0
    if turnover >= _LIQUIDITY_CEILING_TURNOVER:
        return 1.0
    span = math.log(_LIQUIDITY_CEILING_TURNOVER / _LIQUIDITY_FLOOR_TURNOVER)
    return round(math.log(turnover / _LIQUIDITY_FLOOR_TURNOVER) / span, 4)


# --- Second price source: Kraken's own candles -------------------------------------------
#
# 2026-08-27 audit finding. Every crypto research score in this codebase was derived from
# one place -- CoinGecko's free public markets API -- and seed_crypto_universe only reaches
# _populate_crypto_master_and_scores when that fetch succeeds. So a CoinGecko outage, or the
# HTTP 429 rate-limiting this API already returns in production, does not degrade crypto
# research: it stops it, and the universe silently keeps whatever scores it last had.
#
# The fix is not a third-party CoinGecko clone. refresh_crypto_candle_history already
# ingests real daily OHLC candles straight from Kraken -- the venue we actually trade on --
# into MARKET_DATA_OBSERVATIONS, and as of this audit that table holds 4,415 candles across
# 19 symbols going back two years. Price behaviour was already being collected from a second
# independent source; nothing read it for scoring. This does.
#
# The formulas below are deliberately IDENTICAL to _crypto_metrics_from_market_row's, just
# fed from candles instead of CoinGecko fields. That matters more than sophistication: if
# the two sources produced differently-scaled scores, failing over would quietly change
# trading behaviour at the worst possible moment. Same scale in, same decisions out.
#
# The one metric candles genuinely cannot produce is liquidity, which CoinGecko computes as
# 24h volume / market cap -- there is no market cap in an OHLC bar, and inventing a
# substitute would put a fabricated number into a live sizing decision. record_crypto_
# research_score averages over five metrics and treats a missing one as 0.0, so simply
# leaving it None would drag every Kraken-sourced score ~20% below its CoinGecko equivalent
# and make failover look like a market-wide downgrade. Instead it carries forward the last
# real CoinGecko liquidity for that symbol -- turnover ratios move slowly, the value is
# genuinely measured rather than guessed, and the reasoning payload says plainly that it is
# carried forward and how old it is.
#
# A coin CoinGecko has never covered (its fetch is top-20 by market cap plus two categories;
# BCH, KSM and MINA all trade on Kraken and are absent from it) therefore has no liquidity to
# carry forward and scores ~20% lower than an equivalent covered coin. That bias is left in
# deliberately: it errs towards not trading the least-covered assets, which is the safe
# direction, and removing it would mean scoring Kraken-sourced coins on a more generous scale
# than CoinGecko-sourced ones.

KRAKEN_CANDLE_SOURCE = "Kraken OHLC candles"

# Below this many daily candles a 30-day change cannot be computed honestly.
_MIN_CANDLES_FOR_SCORING = 31


def _close_change_pct(candles: list[dict[str, Any]], days_back: int) -> float | None:
    """Percent change between the newest close and the one `days_back` bars earlier.

    Candles arrive oldest-first (see _recent_observations_query's ORDER BY), so the newest
    bar is the last element and the comparison bar is indexed from the end.
    """
    if len(candles) <= days_back:
        return None
    latest = safe_float(candles[-1].get("close"))
    earlier = safe_float(candles[-1 - days_back].get("close"))
    if latest is None or earlier is None or earlier <= 0:
        return None
    return ((latest - earlier) / earlier) * 100.0


def _last_coingecko_liquidity(db_path: Path, symbol: str) -> tuple[float | None, str | None]:
    """The most recent liquidity CoinGecko actually measured for this symbol, and when.

    Returns (None, None) when CoinGecko has never scored it, so the caller leaves liquidity
    unset rather than substituting a number nobody measured.
    """
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                """
                SELECT liquidity, created_at, reasoning_json FROM CRYPTO_RESEARCH_SCORES
                WHERE symbol = ? AND source = ? AND liquidity IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (symbol.upper(), "CoinGecko public markets API"),
            ).fetchone()
    except sqlite3.OperationalError:
        return None, None
    if not row:
        return None, None
    stamp = str(row[1]) if row[1] is not None else None
    # Prefer the raw turnover and rescale it here. Rows written before the 2026-08-27 rescale
    # hold a raw ratio in the liquidity column, and a stored 0.04 is either "deeply liquid"
    # (old ratio) or "almost untradeable" (new score) with nothing in the column to separate
    # them. Turnover is unambiguous, so it wins whenever it is present.
    reasoning = _json_dict(row[2])
    turnover = safe_float(reasoning.get("liquidity_turnover"))
    if turnover is not None:
        return liquidity_score(turnover, 1.0), stamp
    return safe_float(row[0]), stamp


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# CRYPTO_RESEARCH_SCORES has always carried rsi, macd, moving_average_position, volume_trend
# and market_structure columns. As of the 2026-08-27 audit, 0 of 12,474 rows had a value in
# any of them -- five empty columns that every reader treated as "insufficient data".
#
# Nothing new had to be invented to fill them. trading_intelligence.analyze_price_series
# already computes moving-average position, volume trend and price structure from candles and
# is used on the equity path; it was simply never pointed at the crypto candles. RSI and MACD
# were the only genuinely missing pieces and are now computed there too, so the equity callers
# gain them as well.
#
# The two classifications it returns are strings, and these columns are numeric, so they are
# mapped onto a 0-1 scale here rather than stored as text. The mapping reuses the function's
# own classification instead of re-deriving one, so there is exactly one definition of what
# "above the moving averages" means.
_MOVING_AVERAGE_POSITION_SCORES = {"above_short_and_long": 1.0, "mixed_or_below": 0.0}
_MARKET_STRUCTURE_SCORES = {"higher_bias": 1.0, "balanced": 0.5, "lower_bias": 0.0}


def _technical_indicators(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """RSI, MACD, moving-average position, volume trend and market structure from candles."""
    from .trading_intelligence import analyze_price_series

    metrics = analyze_price_series(candles)
    return {
        "rsi": safe_float(metrics.get("rsi")),
        "macd": safe_float(metrics.get("macd")),
        "volume_trend": safe_float(metrics.get("volume_trend")),
        "moving_average_position": _MOVING_AVERAGE_POSITION_SCORES.get(
            str(metrics.get("moving_average_position") or "")
        ),
        "market_structure": _MARKET_STRUCTURE_SCORES.get(str(metrics.get("price_structure") or "")),
    }


def _crypto_metrics_from_kraken_candles(
    candles: list[dict[str, Any]], *, db_path: Path, symbol: str
) -> dict[str, Any] | None:
    """The same five research metrics as the CoinGecko path, computed from Kraken candles.

    Returns None when there is not enough real history to compute them, so a thin symbol is
    left unscored instead of scored on guesses.
    """
    if len(candles) < _MIN_CANDLES_FOR_SCORING:
        return None
    change_24h = _close_change_pct(candles, 1)
    change_7d = _close_change_pct(candles, 7)
    change_30d = _close_change_pct(candles, 30)
    if change_24h is None and change_7d is None:
        return None
    volatility = min(1.0, abs(change_30d) / 100) if change_30d is not None else None
    risk_score = round(1.0 - volatility, 4) if volatility is not None else None
    liquidity, liquidity_as_of = _last_coingecko_liquidity(db_path, symbol)
    newest = str(candles[-1].get("observation_time") or "")
    indicators = _technical_indicators(candles)
    return {
        **indicators,
        "technical_trend_score": _pct_to_unit_score(change_7d, _TREND_FULL_SCALE_PCT),
        "momentum_score": _pct_to_unit_score(change_24h, _MOMENTUM_FULL_SCALE_PCT),
        "volatility": volatility,
        "liquidity": liquidity,
        "risk_score": risk_score,
        "sentiment": _recent_crypto_sentiment(db_path, symbol),
        "news_score": _recent_crypto_news_coverage_score(db_path, symbol),
        "onchain_activity": None,
        "reasoning": {
            "source": KRAKEN_CANDLE_SOURCE,
            "note": (
                "technical/momentum/volatility are computed from real daily OHLC candles fetched "
                "from Kraken, the venue these trades actually execute on, using the same formulas "
                "as the CoinGecko path so the scores stay directly comparable. Liquidity cannot be "
                "derived from an OHLC bar (it needs market cap) and is carried forward from the "
                "last CoinGecko measurement rather than invented. Sentiment and on-chain activity "
                "have no wired data source and stay blank."
            ),
            "candles_used": len(candles),
            "newest_candle": newest,
            "liquidity_carried_forward_from": liquidity_as_of,
            "price_change_pct_24h": change_24h,
            "price_change_pct_7d": change_7d,
            "price_change_pct_30d": change_30d,
        },
    }


def record_crypto_scores_from_kraken_candles(
    db_path: Path, *, symbols: list[str] | None = None, limit: int = 40
) -> dict[str, Any]:
    """Score the crypto universe from stored Kraken candles instead of CoinGecko.

    Used as the fallback when the CoinGecko fetch fails or is rate-limited, so losing that
    provider degrades crypto research (no market-cap ranking, carried-forward liquidity)
    instead of stopping it.
    """
    from .market_intelligence_platform import load_recent_observations_batch
    from .multi_broker import record_crypto_research_score

    targets = [str(symbol).upper() for symbol in (symbols or _active_crypto_symbols(db_path, limit=limit))]
    if not targets:
        return {"scored": 0, "skipped": 0, "source": KRAKEN_CANDLE_SOURCE, "notes": "No active crypto symbols to score."}

    candles_by_symbol = load_recent_observations_batch(db_path, targets, timeframe="1d", limit=120)
    scored: list[str] = []
    skipped: list[str] = []
    for symbol in targets:
        metrics = _crypto_metrics_from_kraken_candles(
            candles_by_symbol.get(symbol) or [], db_path=db_path, symbol=symbol
        )
        if metrics is None:
            skipped.append(symbol)
            continue
        record_crypto_research_score(
            db_path, symbol=symbol, category=None, metrics=metrics, source=KRAKEN_CANDLE_SOURCE
        )
        scored.append(symbol)
    return {
        "scored": len(scored),
        "skipped": len(skipped),
        "source": KRAKEN_CANDLE_SOURCE,
        "symbols_scored": scored,
        "symbols_skipped_insufficient_history": skipped,
        "notes": (
            f"Scored {len(scored)} symbols from stored Kraken daily candles; {len(skipped)} had "
            f"fewer than {_MIN_CANDLES_FOR_SCORING} candles and were left unscored."
        ),
    }


def _active_crypto_symbols(db_path: Path, *, limit: int = 40) -> list[str]:
    """Symbols that actually have stored Kraken candles, newest history first."""
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT normalized_symbol FROM MARKET_DATA_OBSERVATIONS
                WHERE provider = ? AND timeframe = ? AND asset_type = ?
                GROUP BY normalized_symbol
                ORDER BY count(*) DESC LIMIT ?
                """,
                ("kraken", "1d", "crypto", max(1, int(limit))),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [str(row[0]).upper() for row in rows if row and row[0]]


def _crypto_row(row: dict[str, Any], category: str, source: str) -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol", "")).upper(),
        "name": str(row.get("name", "")),
        "category": category,
        "market_cap_rank": row.get("market_cap_rank"),
        "source": source,
        "notes": "Public market ranking.",
    }


def _pnl_since(db_path: Path, broker: str, exchange: str, current_value: float | None, *, days: int) -> float | None:
    if current_value is None:
        return None
    cutoff = (datetime.now(timezone.utc).timestamp() - days * 86400)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT created_at, portfolio_value FROM PORTFOLIO_SNAPSHOTS
            WHERE broker = ? AND exchange = ? AND portfolio_value IS NOT NULL
            ORDER BY snapshot_id ASC
            """,
            (broker, exchange),
        ).fetchall()
    candidate = None
    for row in rows:
        parsed = _parse_dt(row["created_at"])
        if parsed and parsed.timestamp() <= cutoff:
            candidate = row
    if not candidate:
        return None
    return current_value - float(candidate["portfolio_value"])


def _month_start_value(db_path: Path, broker: str, exchange: str, now_iso: str) -> float | None:
    parsed = _parse_dt(now_iso)
    if parsed is None:
        return None
    month_start = parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT portfolio_value FROM PORTFOLIO_SNAPSHOTS
            WHERE broker = ? AND exchange = ? AND created_at >= ? AND portfolio_value IS NOT NULL
            ORDER BY snapshot_id ASC LIMIT 1
            """,
            (broker, exchange, month_start),
        ).fetchone()
    return None if row is None else float(row[0])


def _parse_dt(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
