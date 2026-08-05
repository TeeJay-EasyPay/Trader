"""External intelligence sources: equities/crypto news, macro data, and SEC filings.

Phase A of the external-intelligence work: wires the CRYPTO_NEWS, MACRO_EVENT_EVIDENCE,
FUNDAMENTAL_EVIDENCE, NEWS_CATALYST_EVIDENCE, MARKET_REGIME_EVIDENCE, and
MULTI_TIMEFRAME_INTELLIGENCE tables -- scaffolded with real schema (foundation.py,
market_intelligence_platform.py) and real consumer-side math (infer_regime_2_0,
multi_timeframe_conclusion) but never wired to a real data writer -- to free-tier
data sources. This module is the writer.

Every HTTP call is stdlib urllib only (no third-party dependency exists in this
codebase for it) and is isolated in its own try/except so one source failing
(missing API key, network error, rate limit, malformed response) never prevents
the others from running -- matching the codebase's existing per-broker/per-symbol
partial-failure isolation pattern (multi_broker.py, alpaca.py get_daily_bars).

The whole module is inert until a human explicitly sets EXTERNAL_INTELLIGENCE_ENABLED
(Settings.external_intelligence_enabled, default False) -- see
run_external_intelligence_refresh, the scheduled-job entrypoint.
"""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings
from .database import connect
from .foundation import initialize_foundation_schema
from .market_intelligence_platform import (
    infer_regime_2_0,
    initialize_market_intelligence_schema,
    multi_timeframe_conclusion,
)
from .models import utc_now_iso


ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
CRYPTOPANIC_POSTS_URL = "https://cryptopanic.com/api/v1/posts/"
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
SEC_EDGAR_FULLTEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# SEC's fair-access policy requires a descriptive User-Agent identifying the caller
# (company/application name plus a contact); requests without one are frequently
# rejected with 403. This is a placeholder identity for the account, not a secret.
SEC_EDGAR_USER_AGENT = "AI Trader Research Tool (contact: t_jehangir@hotmail.com)"

# Two series were chosen for Phase A, deliberately not more: this is a small
# crypto/equity account, not a macro desk, and two series fetched reliably beats
# five fetched flakily against FRED's free-tier rate limits.
#   - FEDFUNDS: the Fed's policy rate. The single biggest driver of risk-asset
#     discount rates and crypto liquidity conditions at this account's horizon.
#   - CPIAUCSL: headline CPI level (not yet YoY-transformed here). The input the
#     Fed itself watches most closely to set FEDFUNDS, so it is the leading
#     indicator for where policy (and therefore risk appetite) moves next.
FRED_SERIES_IDS: dict[str, str] = {
    "FEDFUNDS": "Effective Federal Funds Rate",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
}


def initialize_external_intelligence_schema(db_path: Path) -> None:
    """Ensure the foundation/market-intelligence tables exist, plus the dedup
    indexes this module's writers rely on for idempotent inserts.

    CRYPTO_NEWS, MACRO_EVENT_EVIDENCE, and FUNDAMENTAL_EVIDENCE were scaffolded
    (foundation.py, market_intelligence_platform.py) without a UNIQUE constraint --
    this module is their first real writer, and since nothing has ever written to
    them, it is safe to add a dedup index here rather than editing those files'
    CREATE TABLE statements. NEWS_CATALYST_EVIDENCE already ships with a real
    UNIQUE(normalized_symbol, cluster_key, source_timestamp) constraint and needs
    no change. MARKET_REGIME_EVIDENCE and MULTI_TIMEFRAME_INTELLIGENCE are
    append-only evidence logs -- matching MARKET_DATA_OBSERVATIONS's existing,
    unconstrained convention -- so they get no dedup index; the worker's own
    hourly job-bucket scheduling is what keeps external-intelligence-refresh from
    running more than once an hour.
    """
    initialize_foundation_schema(db_path)
    initialize_market_intelligence_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_crypto_news_dedup ON CRYPTO_NEWS(symbol, url)")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_macro_event_evidence_dedup "
                "ON MACRO_EVENT_EVIDENCE(event_type, affected_asset, event_time)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_fundamental_evidence_dedup "
                "ON FUNDAMENTAL_EVIDENCE(normalized_symbol, source, metric_name, source_timestamp)"
            )


# ---------------------------------------------------------------------------
# HTTP fetchers. None of these raise -- each returns an empty/default result on
# any failure (missing credentials, network error, malformed response) so a
# single broken source can never crash the caller.
# ---------------------------------------------------------------------------


def _http_get_json(request: Request, *, timeout: int = 20) -> Any:
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def fetch_alpaca_equities_news(settings: Settings, *, symbols: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch recent equities news from Alpaca's news API.

    Uses the same already-configured Alpaca credentials (APCA-API-KEY-ID /
    APCA-API-SECRET-KEY headers) as AlpacaPaperClient._request in alpaca.py.
    """
    if not settings.has_alpaca_credentials:
        return []
    params: dict[str, str] = {"limit": str(max(1, min(int(limit), 50)))}
    if symbols:
        cleaned = [symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()]
        if cleaned:
            params["symbols"] = ",".join(cleaned)
    request = Request(
        f"{ALPACA_NEWS_URL}?{urlencode(params)}",
        headers={
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
            "Accept": "application/json",
        },
    )
    try:
        payload = _http_get_json(request, timeout=20)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return []
    articles = payload.get("news")
    return list(articles) if isinstance(articles, list) else []


def fetch_cryptopanic_news(settings: Settings, *, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch recent crypto news from CryptoPanic's free tier.

    Requires CRYPTOPANIC_API_KEY (Settings.cryptopanic_api_key). If it is unset
    this is a clean, silent skip (empty list), not an error -- CryptoPanic is an
    optional source, not a required one.
    """
    if not settings.cryptopanic_api_key:
        return []
    params = {"auth_token": settings.cryptopanic_api_key, "public": "true"}
    request = Request(f"{CRYPTOPANIC_POSTS_URL}?{urlencode(params)}", headers={"Accept": "application/json"})
    try:
        payload = _http_get_json(request, timeout=20)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return []
    results = payload.get("results")
    posts = list(results) if isinstance(results, list) else []
    return posts[: max(1, int(limit))]


def fetch_fred_series(
    settings: Settings,
    *,
    series_ids: dict[str, str] | None = None,
    limit: int = 12,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch recent observations for the hand-picked FRED_SERIES_IDS macro series.

    Requires FRED_API_KEY (Settings.fred_api_key). If it is unset this is a
    clean, silent skip (empty dict). Each series is fetched independently and
    wrapped in its own try/except so one bad/rate-limited series never blocks
    the others.
    """
    if not settings.fred_api_key:
        return {}
    series = series_ids or FRED_SERIES_IDS
    observations: dict[str, list[dict[str, Any]]] = {}
    for series_id in series:
        params = {
            "series_id": series_id,
            "api_key": settings.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": str(max(1, int(limit))),
        }
        request = Request(f"{FRED_OBSERVATIONS_URL}?{urlencode(params)}", headers={"Accept": "application/json"})
        try:
            payload = _http_get_json(request, timeout=20)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError):
            continue
        rows = payload.get("observations")
        if isinstance(rows, list):
            observations[series_id] = rows
    return observations


def fetch_sec_edgar_filings(query: str, *, forms: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Full-text search SEC EDGAR for recent filings mentioning `query` (typically
    a ticker or company name). Free, no API key required.
    """
    if not query or not query.strip():
        return []
    params: dict[str, str] = {"q": query.strip()}
    if forms:
        params["forms"] = forms
    request = Request(
        f"{SEC_EDGAR_FULLTEXT_SEARCH_URL}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": SEC_EDGAR_USER_AGENT},
    )
    try:
        payload = _http_get_json(request, timeout=20)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return []
    hits_block = payload.get("hits")
    hits = hits_block.get("hits") if isinstance(hits_block, dict) else None
    return list(hits)[: max(1, int(limit))] if isinstance(hits, list) else []


# ---------------------------------------------------------------------------
# Writers. Each takes db_path plus already-fetched payloads and performs an
# idempotent insert into its real table (schema read from foundation.py /
# market_intelligence_platform.py -- no guessed column names).
# ---------------------------------------------------------------------------


def record_crypto_news(db_path: Path, *, posts: list[dict[str, Any]], source: str = "CryptoPanic") -> dict[str, Any]:
    """Insert CryptoPanic posts into CRYPTO_NEWS, one row per (symbol, post).

    A CryptoPanic post can tag multiple currencies; each tagged currency gets
    its own CRYPTO_NEWS row. An untagged post (general market news) gets a
    single row with symbol="MARKET". Idempotent via the (symbol, url) dedup
    index from initialize_external_intelligence_schema -- INSERT OR IGNORE
    makes a re-fetch of the same article a genuine no-op.
    """
    initialize_external_intelligence_schema(db_path)
    now = utc_now_iso()
    inserted = 0
    skipped = 0
    with closing(connect(db_path)) as conn:
        with conn:
            for post in posts:
                title = post.get("title")
                url = post.get("url")
                published_at = post.get("published_at") or post.get("created_at")
                summary = post.get("body") or post.get("description")
                currencies = post.get("currencies")
                symbols = (
                    [str(item.get("code")).upper() for item in currencies if isinstance(item, dict) and item.get("code")]
                    if isinstance(currencies, list) and currencies
                    else []
                )
                if not symbols:
                    symbols = ["MARKET"]
                for symbol in symbols:
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO CRYPTO_NEWS (
                            crypto_id, symbol, published_at, title, summary, source, url, payload_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (None, symbol, published_at, title, summary, source, url, json.dumps(post, sort_keys=True, default=str), now),
                    )
                    if cursor.rowcount:
                        inserted += 1
                    else:
                        skipped += 1
    return {"inserted": inserted, "skipped_duplicates": skipped, "source": source}


def record_news_catalyst_evidence(db_path: Path, *, articles: list[dict[str, Any]], source: str = "Alpaca news API") -> dict[str, Any]:
    """Insert Alpaca equities news articles into NEWS_CATALYST_EVIDENCE.

    Each article maps to one row per tagged symbol. credibility_level is a
    coarse "wire_source" classification (Alpaca aggregates named news wires,
    not anonymous social posts); catalyst_type is left as the generic
    "news_article" -- this module records that a catalyst happened, it does not
    attempt sentiment or rumour/fact classification. cluster_key is the Alpaca
    article id, which the table's existing UNIQUE(normalized_symbol, cluster_key,
    source_timestamp) constraint uses to make a re-fetch a genuine no-op.
    """
    initialize_external_intelligence_schema(db_path)
    now = utc_now_iso()
    inserted = 0
    skipped = 0
    with closing(connect(db_path)) as conn:
        with conn:
            for article in articles:
                article_id = article.get("id")
                if article_id is None:
                    continue
                cluster_key = f"alpaca-news-{article_id}"
                headline = article.get("headline")
                summary = article.get("summary")
                created_at = article.get("created_at")
                raw_symbols = article.get("symbols") or []
                symbols = [str(symbol).upper() for symbol in raw_symbols if symbol] or ["MARKET"]
                for symbol in symbols:
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO NEWS_CATALYST_EVIDENCE (
                            created_at, normalized_symbol, source, source_timestamp, credibility_level,
                            catalyst_type, relevance, expected_duration, confirmed_fact, market_commentary,
                            analyst_opinion, rumour, opposing_interpretation, cluster_key, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            now,
                            symbol,
                            source,
                            created_at,
                            "wire_source",
                            "news_article",
                            "unclassified",
                            None,
                            headline,
                            summary,
                            None,
                            None,
                            None,
                            cluster_key,
                            json.dumps(article, sort_keys=True, default=str),
                        ),
                    )
                    if cursor.rowcount:
                        inserted += 1
                    else:
                        skipped += 1
    return {"inserted": inserted, "skipped_duplicates": skipped, "source": source}


def record_macro_event_evidence(
    db_path: Path,
    *,
    series_observations: dict[str, list[dict[str, Any]]],
    source: str = "FRED",
    affected_asset: str = "ALL",
) -> dict[str, Any]:
    """Insert FRED macro observations into MACRO_EVENT_EVIDENCE, one row per
    (series, observation date).

    potential_impact is a plain description of the published reading, not a
    directional trading call this module is not qualified to make.
    uncertainty_level is "low" because these are published, revised government
    statistics, not rumours or forecasts. Idempotent per
    (event_type, affected_asset, event_time) -- event_type is the FRED series
    id, event_time is the observation date, so re-fetching an already-recorded
    historical reading is a genuine no-op.
    """
    initialize_external_intelligence_schema(db_path)
    now = utc_now_iso()
    inserted = 0
    skipped = 0
    with closing(connect(db_path)) as conn:
        with conn:
            for series_id, observations in series_observations.items():
                label = FRED_SERIES_IDS.get(series_id, series_id)
                for observation in observations:
                    event_time = observation.get("date")
                    value = observation.get("value")
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO MACRO_EVENT_EVIDENCE (
                            created_at, event_type, affected_asset, event_time, time_until_event,
                            potential_impact, uncertainty_level, source, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            now,
                            series_id,
                            affected_asset,
                            event_time,
                            None,
                            f"{label} reading: {value}",
                            "low",
                            source,
                            json.dumps(observation, sort_keys=True, default=str),
                        ),
                    )
                    if cursor.rowcount:
                        inserted += 1
                    else:
                        skipped += 1
    return {"inserted": inserted, "skipped_duplicates": skipped, "source": source}


def record_fundamental_evidence(
    db_path: Path,
    *,
    normalized_symbol: str,
    filings: list[dict[str, Any]],
    source: str = "SEC EDGAR full-text search",
) -> dict[str, Any]:
    """Insert SEC EDGAR filing hits into FUNDAMENTAL_EVIDENCE, one "sec_filing"
    metric row per filing: metric_value is the form type (e.g. "10-Q"),
    source_timestamp is the filing date. This module does not parse filing
    contents -- recording that a filing happened is itself real evidence a
    human or a future analysis step can act on. Idempotent per
    (normalized_symbol, source, metric_name, source_timestamp).
    """
    initialize_external_intelligence_schema(db_path)
    now = utc_now_iso()
    inserted = 0
    skipped = 0
    with closing(connect(db_path)) as conn:
        with conn:
            for filing in filings:
                body = filing.get("_source") if isinstance(filing.get("_source"), dict) else filing
                form_type = body.get("form") or body.get("root_form")
                filed_at = body.get("file_date")
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO FUNDAMENTAL_EVIDENCE (
                        created_at, normalized_symbol, source, metric_name, metric_value,
                        source_timestamp, confidence, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        normalized_symbol.upper(),
                        source,
                        "sec_filing",
                        form_type,
                        filed_at,
                        "high",
                        json.dumps(filing, sort_keys=True, default=str),
                    ),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    skipped += 1
    return {"inserted": inserted, "skipped_duplicates": skipped, "source": source}


def derive_macro_signal(series_observations: dict[str, list[dict[str, Any]]]) -> str:
    """Classify fetched FRED readings into infer_regime_2_0's coarse macro
    vocabulary ("supportive" / "hostile" / "unknown").

    Deliberately simple for Phase A: compares the latest two Fed funds rate
    readings only -- a rate cut reads as supportive for risk assets, a hike
    reads as hostile, a hold is "unknown" (neutral). CPI is fetched and stored
    as MACRO_EVENT_EVIDENCE but not yet used here -- a real inflation-trend
    read needs YoY math this phase does not attempt; recording the raw reading
    without inventing a directional call is the honest option. Falls back to
    "unknown" whenever fewer than two Fed funds observations are available.
    """
    rate_observations = series_observations.get("FEDFUNDS") or []
    values: list[float] = []
    for observation in rate_observations:
        try:
            values.append(float(observation.get("value")))
        except (TypeError, ValueError):
            continue
        if len(values) >= 2:
            break
    if len(values) < 2:
        return "unknown"
    latest, previous = values[0], values[1]
    if latest < previous:
        return "supportive"
    if latest > previous:
        return "hostile"
    return "unknown"


def record_market_regime_evidence(
    db_path: Path,
    *,
    scope: str,
    multi_timeframe: dict[str, Any],
    macro: str = "unknown",
    volatility: str = "unknown",
    breadth: str = "unknown",
    liquidity: str = "unknown",
    crypto_risk: str = "unknown",
) -> dict[str, Any]:
    """Run the existing regime-detection math (infer_regime_2_0,
    market_intelligence_platform.py) with real data and persist the result to
    MARKET_REGIME_EVIDENCE.

    Append-only evidence log, matching MARKET_DATA_OBSERVATIONS's existing
    convention -- no dedup index. Idempotency at this granularity comes from
    the worker's own hourly job-bucket scheduling (external-intelligence-refresh
    only claims one run per hour), not a per-row database constraint.
    """
    initialize_external_intelligence_schema(db_path)
    regime = infer_regime_2_0(
        multi_timeframe=multi_timeframe,
        volatility=volatility,
        breadth=breadth,
        liquidity=liquidity,
        macro=macro,
        crypto_risk=crypto_risk,
    )
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO MARKET_REGIME_EVIDENCE (
                    created_at, scope, primary_regime, confidence, supporting_evidence_json,
                    contradictory_evidence_json, data_quality_json, plain_english
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    scope,
                    regime["primary_regime"],
                    regime["confidence"],
                    json.dumps(regime["supporting_evidence"], sort_keys=True, default=str),
                    json.dumps(regime["contradictory_evidence"], sort_keys=True, default=str),
                    json.dumps(regime["data_quality"], sort_keys=True, default=str),
                    regime["plain_english"],
                ),
            )
    return regime


def record_multi_timeframe_intelligence(
    db_path: Path,
    *,
    normalized_symbol: str,
    asset_type: str,
    timeframes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Run the existing multi_timeframe_conclusion math
    (market_intelligence_platform.py) with real per-timeframe evidence and
    persist the result to MULTI_TIMEFRAME_INTELLIGENCE.

    Append-only evidence log; same idempotency rationale as
    record_market_regime_evidence above. Not called by
    run_external_intelligence_refresh's default cycle -- none of this phase's
    fetched sources (news, macro, filings) are themselves per-timeframe price
    evidence, so calling this with no real timeframe data would only produce a
    hollow "insufficient evidence" row every hour. It is available for a future
    caller that has real per-symbol timeframe/trend data to feed in.
    """
    initialize_external_intelligence_schema(db_path)
    conclusion = multi_timeframe_conclusion(timeframes)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO MULTI_TIMEFRAME_INTELLIGENCE (
                    created_at, normalized_symbol, asset_type, conclusion,
                    supporting_evidence_json, contradictory_evidence_json, data_quality_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    normalized_symbol.upper(),
                    asset_type,
                    conclusion["conclusion"],
                    json.dumps(conclusion["supporting_evidence"], sort_keys=True, default=str),
                    json.dumps(conclusion["contradictory_evidence"], sort_keys=True, default=str),
                    json.dumps(conclusion["data_quality"], sort_keys=True, default=str),
                ),
            )
    return conclusion


# ---------------------------------------------------------------------------
# Scheduled-job orchestration.
# ---------------------------------------------------------------------------


def _watchlist_equity_symbols(db_path: Path, *, limit: int = 20) -> list[str]:
    # COMPANY_MASTER's schema lives in intelligence.py, not this module; a fresh
    # database (or a test fixture that never ran equity research) may not have
    # created the table yet. That is not a reason to fail the whole refresh --
    # equities news/filings are simply skipped for this cycle.
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute("SELECT ticker FROM COMPANY_MASTER ORDER BY id ASC LIMIT ?", (limit,)).fetchall()
    except Exception:  # noqa: BLE001 - defensive, table may not exist yet (e.g. sqlite3.OperationalError)
        return []
    return [row[0] for row in rows]


def run_external_intelligence_refresh(db_path: Path, settings: Settings) -> dict[str, Any]:
    """Scheduled-job entrypoint for the `external-intelligence-refresh` worker job.

    A true no-op when settings.external_intelligence_enabled is False: makes no
    HTTP calls, writes no rows, and returns immediately. Once enabled, each
    source is fetched and written independently inside its own try/except, so
    one source's failure (missing key, network error, bad response, a bug in
    that source's writer) is isolated to that source and never prevents the
    others from running -- matching this codebase's existing per-broker
    partial-failure isolation pattern (see _run_broker_job_group in cli.py).
    """
    if not settings.external_intelligence_enabled:
        return {"status": "disabled", "message": "external_intelligence_enabled is False; no sources were queried."}

    initialize_external_intelligence_schema(db_path)
    result: dict[str, Any] = {"status": "completed", "sources": {}}
    equity_symbols = _watchlist_equity_symbols(db_path, limit=20)

    try:
        posts = fetch_cryptopanic_news(settings, limit=30)
        result["sources"]["cryptopanic"] = record_crypto_news(db_path, posts=posts)
    except Exception as exc:  # noqa: BLE001 - one source's failure must not sink the refresh
        result["sources"]["cryptopanic"] = {"status": "failed", "error": str(exc)}

    try:
        articles = fetch_alpaca_equities_news(settings, symbols=equity_symbols, limit=30)
        result["sources"]["alpaca_news"] = record_news_catalyst_evidence(db_path, articles=articles)
    except Exception as exc:  # noqa: BLE001
        result["sources"]["alpaca_news"] = {"status": "failed", "error": str(exc)}

    fred_observations: dict[str, list[dict[str, Any]]] = {}
    try:
        fred_observations = fetch_fred_series(settings)
        result["sources"]["fred"] = record_macro_event_evidence(db_path, series_observations=fred_observations)
    except Exception as exc:  # noqa: BLE001
        result["sources"]["fred"] = {"status": "failed", "error": str(exc)}

    try:
        filing_totals = {"inserted": 0, "skipped_duplicates": 0}
        for symbol in equity_symbols[:5]:
            filings = fetch_sec_edgar_filings(symbol)
            written = record_fundamental_evidence(db_path, normalized_symbol=symbol, filings=filings)
            filing_totals["inserted"] += written["inserted"]
            filing_totals["skipped_duplicates"] += written["skipped_duplicates"]
        result["sources"]["sec_edgar"] = filing_totals
    except Exception as exc:  # noqa: BLE001
        result["sources"]["sec_edgar"] = {"status": "failed", "error": str(exc)}

    try:
        macro_signal = derive_macro_signal(fred_observations)
        empty_multi_timeframe = multi_timeframe_conclusion({})
        result["sources"]["market_regime"] = record_market_regime_evidence(
            db_path,
            scope="global",
            multi_timeframe=empty_multi_timeframe,
            macro=macro_signal,
        )
    except Exception as exc:  # noqa: BLE001
        result["sources"]["market_regime"] = {"status": "failed", "error": str(exc)}

    return result
