"""Market themes the app maintains itself, for crypto and for shares.

2026-08-27, Founder-directed. MARKET_THEMES held 14 hand-written share sectors, every one last
updated 2 July, because refreshing them requires a person to hand the app a file and nobody
had. A two-month-old opinion stated with confidence is worse than no opinion: it is a
systematic bias applied across a whole sector rather than one bad trade.

The Founder asked two good questions. "Can coins also have themes?" -- yes, and the app was
already collecting them without using them: CRYPTO_MASTER carries "Top 20 AI coins" and "Top 20
security/privacy coins", which are exactly the crypto equivalent of Copper or Airlines. And
"how is this future proofed?" -- by never hardcoding the theme list. Themes are DERIVED from
what the app actually holds and tracks, so a new sector, a new narrative, or a new market
appears on its own without a code change.

Two deliberate differences between the asset classes, and neither is the number of assets:

  speed       Share sectors turn over quarters; crypto narratives rotate in weeks. Crypto is
              refreshed daily, shares weekly.
  membership  A mining company is still a mining company next year. A coin can move narrative
              when its team pivots, so crypto membership is re-derived every cycle rather
              than stored.

Themes scale BETTER with more assets, not worse. Ten narratives cover thousands of coins;
judging the sector covers everything in it. That is what makes "there are thousands of cryptos"
an argument FOR themes rather than against them.

A theme is a judgement applied across many positions, so it records why it holds the view and
what would change it, and a theme with no evidence behind it stays unwritten rather than being
guessed -- the same rule as sentiment and liquidity.
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

CRYPTO = "crypto"
EQUITY = "equity"

# How long a view stays usable before it is treated as stale. Set from how fast each market's
# narratives actually move, not from convenience.
MAX_AGE_HOURS = {CRYPTO: 36, EQUITY: 14 * 24}

# Enough headlines to form a view of a sector without making one request enormous.
MAX_HEADLINES_PER_THEME = 8

# Below this, there is not enough evidence to hold a view worth acting on.
MIN_HEADLINES_FOR_THEME = 2


def initialize_market_theme_schema(db_path: Path) -> None:
    """Create the table if absent, and add asset_class to an existing one.

    The original table predates crypto themes and has no asset_class, so equities are the
    implied default for any row already there -- which is exactly what those 14 rows are.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS MARKET_THEMES (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    theme TEXT NOT NULL,
                    current_outlook TEXT,
                    confidence TEXT,
                    summary TEXT,
                    key_drivers TEXT,
                    key_risks TEXT,
                    last_updated TEXT,
                    source_urls TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            try:
                existing = {row[1] for row in conn.execute("PRAGMA table_info(MARKET_THEMES)")}
            except sqlite3.OperationalError:
                existing = set()
            if existing and "asset_class" not in existing:
                conn.execute("ALTER TABLE MARKET_THEMES ADD COLUMN asset_class TEXT")
                conn.execute("UPDATE MARKET_THEMES SET asset_class = ? WHERE asset_class IS NULL", (EQUITY,))
            if existing and "evidence_json" not in existing:
                conn.execute("ALTER TABLE MARKET_THEMES ADD COLUMN evidence_json TEXT")


def discover_themes(db_path: Path, asset_class: str) -> dict[str, list[str]]:
    """The themes that matter right now, and which symbols sit in each.

    Derived from what the app actually holds and tracks rather than from a hardcoded list --
    this is the part that future-proofs it. Adding a market, a sector or a narrative to the
    universe makes its theme appear here with no code change.
    """
    query = (
        "SELECT category, symbol FROM CRYPTO_MASTER WHERE active = 1 AND category IS NOT NULL"
        if asset_class == CRYPTO
        else "SELECT sector, ticker FROM COMPANY_MASTER WHERE sector IS NOT NULL"
    )
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError:
        return {}
    grouped: dict[str, list[str]] = {}
    for row in rows:
        # Indexed, never unpacked. Under SQLite a row is a tuple so `for a, b in rows` works;
        # under this app's Postgres wrapper a row is a dict subclass, so unpacking yields the
        # COLUMN NAMES and every theme comes back called "category". Same trap already
        # documented in foundation.py's macro matcher, hit again here.
        name = str(row[0] or "").strip()
        ticker = str(row[1] or "").strip().upper()
        if not name or not ticker:
            continue
        # "Founder approved Kraken pairs" is a permissions list, not a market narrative --
        # it says where the app may trade, never what it thinks of the sector.
        if asset_class == CRYPTO and "approved" in name.lower():
            continue
        bucket = grouped.setdefault(name, [])
        if ticker not in bucket:
            bucket.append(ticker)
    return grouped


def _headlines(db_path: Path, asset_class: str, symbols: list[str], window_hours: int) -> list[dict[str, str]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(window_hours)))).isoformat()
    if not symbols:
        return []
    placeholders = ",".join(["?"] * len(symbols))
    if asset_class == CRYPTO:
        sql = (
            f"SELECT symbol, title, summary FROM CRYPTO_NEWS "
            f"WHERE UPPER(symbol) IN ({placeholders}) AND COALESCE(published_at, created_at) >= ? "
            f"ORDER BY COALESCE(published_at, created_at) DESC"
        )
    else:
        sql = (
            f"SELECT normalized_symbol, confirmed_fact, market_commentary FROM NEWS_CATALYST_EVIDENCE "
            f"WHERE UPPER(normalized_symbol) IN ({placeholders}) AND created_at >= ? "
            f"ORDER BY created_at DESC"
        )
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(sql, (*symbols, cutoff)).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        headline = str(row[1] or "").strip()
        if not headline:
            continue
        out.append({"symbol": str(row[0] or ""), "headline": headline[:200], "detail": str(row[2] or "")[:200]})
        if len(out) >= MAX_HEADLINES_PER_THEME:
            break
    return out


def _prompt(asset_class: str, evidence: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    horizon = "the next few weeks" if asset_class == CRYPTO else "the next few months"
    return {
        "role": "market_theme_analyst",
        "instruction": (
            f"You are forming a view on each {asset_class} theme listed, over {horizon}, using only "
            "the news supplied. Return only JSON: an object keyed by the exact theme names given, "
            "each mapping to an object with fields `outlook`, `confidence`, `summary`, "
            "`key_drivers` and `key_risks`. "
            "`outlook` is a short phrase such as 'Constructive', 'Cautious', 'Deteriorating' or "
            "'Structurally positive'. `confidence` must be exactly one of High, Medium or Low. "
            "`summary` is one or two plain-English sentences a non-technical founder can follow, "
            "citing what the supplied news actually says. `key_drivers` and `key_risks` are each "
            "an array of at most three short strings. "
            "This is a view on a SECTOR, not a recommendation to buy anything, and you are not "
            "setting any price, size or risk level -- those are decided elsewhere by arithmetic. "
            "If the evidence for a theme is too thin or too generic to hold a real view, omit "
            "that theme entirely rather than writing a bland neutral one."
        ),
        "evidence": evidence,
    }


def _extract_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output") or []:
        for chunk in item.get("content") or []:
            if chunk.get("text"):
                return str(chunk["text"])
    return str(payload.get("output_text") or "")


def _as_list(value: Any, limit: int = 3) -> str:
    if isinstance(value, list):
        return "; ".join(str(item)[:120] for item in value[:limit])
    return str(value or "")[:360]


def refresh_market_themes(
    db_path: Path,
    *,
    api_key: str | None,
    model: str,
    asset_class: str,
    window_hours: int = 72,
    timeout_seconds: int = 45,
) -> dict[str, Any]:
    """Form and store a current view per theme for one asset class."""
    initialize_market_theme_schema(db_path)
    themes = discover_themes(db_path, asset_class)
    if not themes:
        return {"status": "no_themes", "asset_class": asset_class, "written": 0,
                "message": f"No {asset_class} themes are derivable from the tracked universe yet."}
    evidence = {}
    for theme, symbols in themes.items():
        headlines = _headlines(db_path, asset_class, symbols, window_hours)
        if len(headlines) >= MIN_HEADLINES_FOR_THEME:
            evidence[theme] = headlines
    if not evidence:
        return {"status": "no_evidence", "asset_class": asset_class, "written": 0,
                "themes_considered": sorted(themes),
                "message": (
                    f"No {asset_class} news inside the last {window_hours}h, so no theme view was "
                    "written. Existing views are left as they are and will age out rather than "
                    "being refreshed with nothing."
                )}
    if not api_key:
        return {"status": "not_available", "asset_class": asset_class, "written": 0,
                "message": "OPENAI_API_KEY is required to form theme views."}

    payload = {
        "model": model,
        "input": json.dumps(_prompt(asset_class, evidence), default=str),
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
    except Exception as exc:  # noqa: BLE001 - a failed refresh must never stop research
        return {"status": "failed", "asset_class": asset_class, "written": 0, "message": str(exc)[:200]}
    if not isinstance(judged, dict):
        return {"status": "failed", "asset_class": asset_class, "written": 0,
                "message": "Model did not return an object."}

    now = utc_now_iso()
    written: list[str] = []
    with closing(connect(db_path)) as conn:
        with conn:
            for theme, headlines in evidence.items():
                view = judged.get(theme)
                if not isinstance(view, dict) or not view.get("outlook"):
                    continue  # declined to hold a view; leave whatever is there to age out
                written.append(theme)
                row = (
                    str(view.get("outlook"))[:120],
                    str(view.get("confidence") or "Medium")[:20],
                    str(view.get("summary") or "")[:800],
                    _as_list(view.get("key_drivers")),
                    _as_list(view.get("key_risks")),
                    now, now,
                    json.dumps({"headlines": headlines, "symbols": themes.get(theme, [])}, default=str),
                )
                updated = conn.execute(
                    """
                    UPDATE MARKET_THEMES
                    SET current_outlook = ?, confidence = ?, summary = ?, key_drivers = ?,
                        key_risks = ?, last_updated = ?, updated_at = ?, evidence_json = ?
                    WHERE theme = ? AND (asset_class = ? OR asset_class IS NULL)
                    """,
                    (*row, theme, asset_class),
                ).rowcount
                if not updated:
                    conn.execute(
                        """
                        INSERT INTO MARKET_THEMES (
                            theme, asset_class, current_outlook, confidence, summary,
                            key_drivers, key_risks, last_updated, updated_at, evidence_json,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (theme, asset_class, *row, now),
                    )
    return {
        "status": "completed",
        "asset_class": asset_class,
        "written": len(written),
        "themes": sorted(written),
        "message": f"Refreshed {len(written)} of {len(evidence)} {asset_class} theme(s) with evidence.",
    }


def theme_for_symbol(db_path: Path, symbol: str, asset_class: str) -> str | None:
    """Which theme this symbol belongs to, re-derived rather than stored."""
    target = str(symbol or "").upper().strip()
    if not target:
        return None
    for theme, symbols in discover_themes(db_path, asset_class).items():
        if target in symbols:
            return theme
    return None


def current_theme_view(db_path: Path, symbol: str, asset_class: str) -> dict[str, Any] | None:
    """The live view covering this symbol, or None when there is none or it has gone stale.

    Stale is treated as absent on purpose. A two-month-old outlook asserted as current is what
    this module exists to stop.
    """
    initialize_market_theme_schema(db_path)
    theme = theme_for_symbol(db_path, symbol, asset_class)
    if not theme:
        return None
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS.get(asset_class, 14 * 24))
    ).isoformat()
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                """
                SELECT theme, current_outlook, confidence, summary, last_updated
                FROM MARKET_THEMES
                WHERE theme = ? AND last_updated >= ? AND current_outlook IS NOT NULL
                ORDER BY last_updated DESC LIMIT 1
                """,
                (theme, cutoff),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return {
        "theme": row[0], "outlook": row[1], "confidence": row[2],
        "summary": row[3], "last_updated": row[4],
    }
