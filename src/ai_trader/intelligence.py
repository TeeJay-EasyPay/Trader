from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from .intelligence_data import COMPANIES, THEMES
from .models import utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS COMPANY_MASTER (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    ticker TEXT NOT NULL,
    exchange TEXT NOT NULL,
    country TEXT,
    sector TEXT,
    industry TEXT,
    business_summary TEXT,
    investment_thesis TEXT,
    reasons_we_like_it TEXT,
    reasons_for_caution TEXT,
    potential_risks TEXT,
    primary_products TEXT,
    website TEXT,
    latest_news_summary TEXT,
    last_updated TEXT NOT NULL,
    source_urls TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(ticker, exchange)
);

CREATE TABLE IF NOT EXISTS COMPANY_FINANCIALS (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    financial_snapshot_date TEXT NOT NULL,
    currency TEXT,
    revenue REAL,
    revenue_period TEXT,
    net_income REAL,
    market_cap REAL,
    dividend_yield REAL,
    debt_to_equity REAL,
    notes TEXT,
    source_url TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(company_id) REFERENCES COMPANY_MASTER(id)
);

CREATE TABLE IF NOT EXISTS COMPANY_DAILY_UPDATES (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    update_date TEXT NOT NULL,
    update_type TEXT NOT NULL,
    summary TEXT,
    material_change INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(company_id) REFERENCES COMPANY_MASTER(id)
);

CREATE TABLE IF NOT EXISTS INVESTMENT_WATCHLIST (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    current_watchlist_priority TEXT,
    current_investment_philosophy_fit TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL,
    last_reviewed TEXT NOT NULL,
    notes TEXT,
    UNIQUE(company_id),
    FOREIGN KEY(company_id) REFERENCES COMPANY_MASTER(id)
);

CREATE TABLE IF NOT EXISTS MARKET_THEMES (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    theme TEXT NOT NULL UNIQUE,
    current_outlook TEXT,
    confidence TEXT,
    summary TEXT,
    key_drivers TEXT,
    key_risks TEXT,
    last_updated TEXT NOT NULL,
    source_urls TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


COMPANY_FIELDS = [
    "company_name",
    "ticker",
    "exchange",
    "country",
    "sector",
    "industry",
    "business_summary",
    "investment_thesis",
    "reasons_we_like_it",
    "reasons_for_caution",
    "potential_risks",
    "primary_products",
    "website",
    "latest_news_summary",
    "last_updated",
    "source_urls",
]


class InvestmentIntelligenceDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            with conn:
                conn.executescript(SCHEMA)

    def seed_initial_data(self) -> dict[str, int]:
        company_count = 0
        theme_count = 0
        with closing(self.connect()) as conn:
            with conn:
                for company in COMPANIES:
                    company_id = self._upsert_company(conn, company)
                    self._upsert_watchlist(conn, company_id, company)
                    self._insert_financial_placeholder(conn, company_id, company["last_updated"])
                    self._append_company_update(
                        conn,
                        company_id=company_id,
                        update_date=company["last_updated"],
                        update_type="initial_profile",
                        summary=company.get("latest_news_summary") or "Initial profile seeded from public company information.",
                        material_change=False,
                        source_url=company.get("source_urls"),
                        payload=company,
                    )
                    company_count += 1

                for theme in THEMES:
                    self._upsert_theme(conn, theme)
                    theme_count += 1
        return {"companies": company_count, "themes": theme_count}

    def daily_refresh(self, refresh_date: date, update_file: Path | None = None) -> dict[str, int]:
        updates = _load_updates(update_file) if update_file else {}
        company_updates = updates.get("companies", {})
        theme_updates = updates.get("themes", {})
        date_text = refresh_date.isoformat()
        reviewed_companies = 0
        reviewed_themes = 0
        material_company_updates = 0

        with closing(self.connect()) as conn:
            with conn:
                companies = list(
                    conn.execute(
                        """
                        SELECT cm.* FROM COMPANY_MASTER cm
                        JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
                        WHERE iw.active = 1
                        ORDER BY iw.current_watchlist_priority ASC, cm.company_name ASC
                        """
                    )
                )
                for row in companies:
                    key = f"{row['ticker']}:{row['exchange']}"
                    update = company_updates.get(key) or company_updates.get(row["ticker"]) or {}
                    summary = update.get("summary") or "Daily review completed; no material change supplied."
                    material = bool(update.get("material_change", False))
                    source_url = update.get("source_url")
                    payload = {"ticker": row["ticker"], "exchange": row["exchange"], "supplied_update": update}
                    self._append_company_update(
                        conn,
                        company_id=int(row["id"]),
                        update_date=date_text,
                        update_type="daily_review",
                        summary=summary,
                        material_change=material,
                        source_url=source_url,
                        payload=payload,
                    )
                    conn.execute(
                        """
                        UPDATE COMPANY_MASTER
                        SET latest_news_summary = COALESCE(?, latest_news_summary),
                            last_updated = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (summary if material else None, date_text, utc_now_iso(), int(row["id"])),
                    )
                    conn.execute(
                        "UPDATE INVESTMENT_WATCHLIST SET last_reviewed = ? WHERE company_id = ?",
                        (date_text, int(row["id"])),
                    )
                    reviewed_companies += 1
                    if material:
                        material_company_updates += 1

                themes = list(conn.execute("SELECT * FROM MARKET_THEMES ORDER BY theme ASC"))
                for row in themes:
                    update = theme_updates.get(row["theme"]) or {}
                    conn.execute(
                        """
                        UPDATE MARKET_THEMES
                        SET current_outlook = COALESCE(?, current_outlook),
                            confidence = COALESCE(?, confidence),
                            summary = COALESCE(?, summary),
                            key_drivers = COALESCE(?, key_drivers),
                            key_risks = COALESCE(?, key_risks),
                            last_updated = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            update.get("current_outlook"),
                            update.get("confidence"),
                            update.get("summary"),
                            update.get("key_drivers"),
                            update.get("key_risks"),
                            date_text,
                            utc_now_iso(),
                            int(row["id"]),
                        ),
                    )
                    reviewed_themes += 1

        return {
            "companies_reviewed": reviewed_companies,
            "themes_reviewed": reviewed_themes,
            "material_company_updates": material_company_updates,
        }

    def write_report(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "INVESTMENT_INTELLIGENCE_ENGINE_REPORT.md"
        with closing(self.connect()) as conn:
            companies = list(
                conn.execute(
                    """
                    SELECT cm.*, iw.current_watchlist_priority, iw.current_investment_philosophy_fit
                    FROM COMPANY_MASTER cm
                    JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
                    ORDER BY
                        CASE iw.current_watchlist_priority
                            WHEN 'High' THEN 1
                            WHEN 'Medium' THEN 2
                            ELSE 3
                        END,
                        cm.company_name
                    """
                )
            )
            themes = list(conn.execute("SELECT * FROM MARKET_THEMES ORDER BY theme ASC"))

        lines = [
            "# Investment Intelligence Engine Report",
            "",
            f"Generated: {utc_now_iso()}",
            "",
            "## Summary",
            "",
            f"- Watchlist companies: {len(companies)}",
            f"- Market themes: {len(themes)}",
            "- Storage: local SQLite master database",
            "- Trading pipeline: unchanged",
            "",
            "## Watchlist",
            "",
        ]
        for row in companies:
            lines.extend(
                [
                    f"### {row['company_name']} ({row['ticker']} / {row['exchange']})",
                    "",
                    f"- Country: {row['country']}",
                    f"- Sector: {row['sector']}",
                    f"- Priority: {row['current_watchlist_priority']}",
                    f"- Philosophy fit: {row['current_investment_philosophy_fit']}",
                    f"- Thesis: {row['investment_thesis']}",
                    f"- Caution: {row['reasons_for_caution']}",
                    "",
                ]
            )
        lines.extend(["## Market Themes", ""])
        for row in themes:
            lines.extend(
                [
                    f"### {row['theme']}",
                    "",
                    f"- Outlook: {row['current_outlook']}",
                    f"- Confidence: {row['confidence']}",
                    f"- Summary: {row['summary']}",
                    f"- Key risks: {row['key_risks']}",
                    "",
                ]
            )
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _upsert_company(self, conn: sqlite3.Connection, company: dict[str, Any]) -> int:
        now = utc_now_iso()
        values = [company.get(field) for field in COMPANY_FIELDS]
        conn.execute(
            f"""
            INSERT INTO COMPANY_MASTER ({", ".join(COMPANY_FIELDS)}, created_at, updated_at)
            VALUES ({", ".join(["?"] * len(COMPANY_FIELDS))}, ?, ?)
            ON CONFLICT(ticker, exchange) DO UPDATE SET
                company_name = excluded.company_name,
                country = excluded.country,
                sector = excluded.sector,
                industry = excluded.industry,
                business_summary = excluded.business_summary,
                investment_thesis = excluded.investment_thesis,
                reasons_we_like_it = excluded.reasons_we_like_it,
                reasons_for_caution = excluded.reasons_for_caution,
                potential_risks = excluded.potential_risks,
                primary_products = excluded.primary_products,
                website = excluded.website,
                latest_news_summary = excluded.latest_news_summary,
                last_updated = excluded.last_updated,
                source_urls = excluded.source_urls,
                updated_at = excluded.updated_at
            """,
            (*values, now, now),
        )
        row = conn.execute(
            "SELECT id FROM COMPANY_MASTER WHERE ticker = ? AND exchange = ?",
            (company["ticker"], company["exchange"]),
        ).fetchone()
        return int(row["id"])

    def _upsert_watchlist(self, conn: sqlite3.Connection, company_id: int, company: dict[str, Any]) -> None:
        now_date = company["last_updated"]
        conn.execute(
            """
            INSERT INTO INVESTMENT_WATCHLIST (
                company_id, current_watchlist_priority, current_investment_philosophy_fit,
                active, added_at, last_reviewed, notes
            ) VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                current_watchlist_priority = excluded.current_watchlist_priority,
                current_investment_philosophy_fit = excluded.current_investment_philosophy_fit,
                active = 1,
                last_reviewed = excluded.last_reviewed,
                notes = excluded.notes
            """,
            (
                company_id,
                company.get("watchlist_priority"),
                company.get("investment_philosophy_fit"),
                now_date,
                now_date,
                "Initial Sprint 2 curated watchlist.",
            ),
        )

    def _insert_financial_placeholder(self, conn: sqlite3.Connection, company_id: int, snapshot_date: str) -> None:
        existing = conn.execute(
            """
            SELECT id FROM COMPANY_FINANCIALS
            WHERE company_id = ? AND financial_snapshot_date = ? AND notes = ?
            """,
            (company_id, snapshot_date, "Initial placeholder; financial metrics not collected in Sprint 2 seed."),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO COMPANY_FINANCIALS (
                company_id, financial_snapshot_date, currency, revenue, revenue_period,
                net_income, market_cap, dividend_yield, debt_to_equity, notes, source_url, created_at
            ) VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, NULL, ?)
            """,
            (company_id, snapshot_date, "Initial placeholder; financial metrics not collected in Sprint 2 seed.", utc_now_iso()),
        )

    def _append_company_update(
        self,
        conn: sqlite3.Connection,
        *,
        company_id: int,
        update_date: str,
        update_type: str,
        summary: str,
        material_change: bool,
        source_url: str | None,
        payload: dict[str, Any],
    ) -> None:
        payload_json = json.dumps(payload, sort_keys=True)
        existing = conn.execute(
            """
            SELECT id FROM COMPANY_DAILY_UPDATES
            WHERE company_id = ? AND update_date = ? AND update_type = ? AND payload_json = ?
            """,
            (company_id, update_date, update_type, payload_json),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO COMPANY_DAILY_UPDATES (
                company_id, update_date, update_type, summary, material_change,
                source_url, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (company_id, update_date, update_type, summary, int(material_change), source_url, payload_json, utc_now_iso()),
        )

    def _upsert_theme(self, conn: sqlite3.Connection, theme: dict[str, Any]) -> None:
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO MARKET_THEMES (
                theme, current_outlook, confidence, summary, key_drivers,
                key_risks, last_updated, source_urls, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(theme) DO UPDATE SET
                current_outlook = excluded.current_outlook,
                confidence = excluded.confidence,
                summary = excluded.summary,
                key_drivers = excluded.key_drivers,
                key_risks = excluded.key_risks,
                last_updated = excluded.last_updated,
                source_urls = excluded.source_urls,
                updated_at = excluded.updated_at
            """,
            (
                theme["theme"],
                theme.get("current_outlook"),
                theme.get("confidence"),
                theme.get("summary"),
                theme.get("key_drivers"),
                theme.get("key_risks"),
                theme["last_updated"],
                theme.get("source_urls"),
                now,
                now,
            ),
        )


def _load_updates(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Update file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Update file must contain a JSON object")
    return data
