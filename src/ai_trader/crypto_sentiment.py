"""Real news sentiment for the crypto universe.

2026-08-27, Founder-directed. CRYPTO_RESEARCH_SCORES has always carried a `sentiment` column
and nothing has ever written to it, because no sentiment source was wired. It was therefore a
hard 0.0 in a five-way average, which told the scoring engine that every coin on earth had
terrible sentiment when the truth was that nobody had looked. Combined with liquidity being
stored on the wrong scale, that capped the achievable due-diligence score around 0.46 against
a 0.85 bar to trade -- so once the fabricated 0.85 scores were removed, crypto could not trade
at all.

The Founder's question was the right one: "why is sentiment not an important indicator?" It is.
The fix is to measure it, not to drop it.

The raw material was already being collected -- CRYPTO_NEWS holds real headlines and summaries
from the news pipeline. This reads that, asks the model to judge the tone of coverage per coin,
and stores the result. Deliberate constraints:

  * A coin with no recent coverage scores None, never 0.5 and never 0. "No news" is not
    "neutral news", and inventing either would repeat the exact fault this module exists to fix.
  * One batched call for the whole universe rather than one per coin, so a 20-coin cycle costs
    a single request instead of twenty.
  * Sentiment can only ever be one input among several. It never sets price, size, stop or
    target -- those stay deterministic risk arithmetic, the same rule CryptoTradeReviewer
    follows.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .database import connect
from .models import utc_now_iso

SENTIMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS CRYPTO_SENTIMENT_SCORES (
    sentiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    sentiment REAL,
    article_count INTEGER NOT NULL,
    headline_window_hours INTEGER NOT NULL,
    rationale TEXT,
    model TEXT,
    payload_json TEXT NOT NULL
);
"""

# How far back coverage still counts. Crypto news goes stale quickly; a week-old headline says
# little about whether a move can be sustained today.
DEFAULT_WINDOW_HOURS = 48

# Enough headlines to judge a mood, few enough to keep one request small.
MAX_HEADLINES_PER_SYMBOL = 6

# Below this, coverage is too thin to call a mood from, so the coin stays unscored rather than
# being judged on a single article that happens to exist.
MIN_ARTICLES_FOR_SENTIMENT = 2


def initialize_crypto_sentiment_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(SENTIMENT_SCHEMA)


def recent_headlines(
    db_path: Path, *, window_hours: int = DEFAULT_WINDOW_HOURS, limit_per_symbol: int = MAX_HEADLINES_PER_SYMBOL
) -> dict[str, list[dict[str, str]]]:
    """Recent coverage grouped by coin, newest first, from the news already collected."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(window_hours)))).isoformat()
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT symbol, title, summary, source, published_at FROM CRYPTO_NEWS
                WHERE COALESCE(published_at, created_at) >= ?
                ORDER BY COALESCE(published_at, created_at) DESC
                """,
                (cutoff,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        symbol = str(row[0] or "").upper().strip()
        title = str(row[1] or "").strip()
        if not symbol or not title:
            continue
        bucket = grouped.setdefault(symbol, [])
        if len(bucket) >= limit_per_symbol:
            continue
        bucket.append({
            "title": title[:200],
            "summary": str(row[2] or "")[:300],
            "source": str(row[3] or "")[:60],
        })
    return grouped


def _prompt(coverage: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    return {
        "role": "crypto_news_sentiment",
        "instruction": (
            "You are judging the TONE of recent news coverage for each crypto asset listed. "
            "Return only JSON: an object whose keys are the exact symbols supplied, each mapping "
            "to an object with fields `sentiment` and `reason`. "
            "`sentiment` is a decimal between 0 and 1: 0.0 is strongly negative coverage "
            "(hacks, enforcement action, collapse, delistings), 0.5 is genuinely mixed or "
            "routine, 1.0 is strongly positive (major adoption, listings, favourable rulings). "
            "`reason` is one short plain-English sentence citing the actual headlines. "
            "Judge only the coverage supplied. Do not use prior knowledge of prices, do not "
            "predict price direction, and do not recommend any trade -- position sizing and "
            "risk are decided elsewhere by arithmetic, not by you. "
            "If the coverage for a symbol is too thin or too generic to judge a mood, omit that "
            "symbol from your response entirely rather than guessing a neutral score."
        ),
        "coverage": coverage,
    }


def _extract_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output") or []:
        for chunk in item.get("content") or []:
            text = chunk.get("text")
            if text:
                return str(text)
    return str(payload.get("output_text") or "")


def _clamp(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return round(max(0.0, min(1.0, number)), 4)


def score_crypto_sentiment(
    db_path: Path,
    *,
    api_key: str | None,
    model: str,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Score recent coverage per coin and persist the result.

    Returns without calling the model when there is no API key or no coverage, so a missing
    key degrades to "no sentiment recorded" rather than to a fabricated one.
    """
    initialize_crypto_sentiment_schema(db_path)
    coverage = {
        symbol: articles
        for symbol, articles in recent_headlines(db_path, window_hours=window_hours).items()
        if len(articles) >= MIN_ARTICLES_FOR_SENTIMENT
    }
    if not coverage:
        return {"status": "no_coverage", "scored": 0, "symbols": [],
                "message": "No crypto news inside the window, so no sentiment was recorded."}
    if not api_key:
        return {"status": "not_available", "scored": 0, "symbols": [],
                "message": "OPENAI_API_KEY is required to judge news sentiment."}

    payload = {
        "model": model,
        "input": json.dumps(_prompt(coverage), default=str),
        "text": {"format": {"type": "json_object"}},
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        judged = json.loads(_extract_text(raw) or "{}")
    except Exception as exc:  # noqa: BLE001 - a failed sentiment read must not stop research
        return {"status": "failed", "scored": 0, "symbols": [], "message": str(exc)[:200]}
    if not isinstance(judged, dict):
        return {"status": "failed", "scored": 0, "symbols": [], "message": "Model did not return an object."}

    now = utc_now_iso()
    written: list[str] = []
    rows: list[tuple[Any, ...]] = []
    for symbol, articles in coverage.items():
        verdict = judged.get(symbol)
        if not isinstance(verdict, dict):
            continue  # the model declined to judge this one; leave it unscored
        sentiment = _clamp(verdict.get("sentiment"))
        if sentiment is None:
            continue
        written.append(symbol)
        rows.append((
            now, symbol, sentiment, len(articles), int(window_hours),
            str(verdict.get("reason") or "")[:400], model,
            json.dumps({"articles": articles, "verdict": verdict}, default=str),
        ))
    if rows:
        with closing(connect(db_path)) as conn:
            with conn:
                conn.executemany(
                    """
                    INSERT INTO CRYPTO_SENTIMENT_SCORES (
                        created_at, symbol, sentiment, article_count, headline_window_hours,
                        rationale, model, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
    return {
        "status": "completed",
        "scored": len(written),
        "symbols": sorted(written),
        "covered": sorted(coverage.keys()),
        "message": (
            f"Judged news sentiment for {len(written)} of {len(coverage)} covered coin(s) "
            f"from the last {window_hours}h."
        ),
    }


def latest_sentiment(db_path: Path, *, max_age_hours: int = 12) -> dict[str, float]:
    """The most recent sentiment per coin, ignoring anything stale.

    Stale sentiment is worse than none: it would keep asserting last week's mood as today's.
    Symbols absent from the result are genuinely unscored and must stay that way.
    """
    initialize_crypto_sentiment_schema(db_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(max_age_hours)))).isoformat()
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT symbol, sentiment, created_at FROM CRYPTO_SENTIMENT_SCORES
                WHERE sentiment IS NOT NULL AND created_at >= ?
                ORDER BY created_at ASC
                """,
                (cutoff,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    # Ascending order means the newest row for each symbol wins.
    return {str(row[0]).upper(): float(row[1]) for row in rows if row[1] is not None}
