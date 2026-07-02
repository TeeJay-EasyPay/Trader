from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from .benchmark_data import BENCHMARK_RESEARCH, BENCHMARK_TRADERS
from .models import utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS BENCHMARK_TRADERS (
    trader_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trader_name TEXT NOT NULL,
    platform TEXT,
    region TEXT,
    strategy_style TEXT,
    markets_traded TEXT,
    risk_rating TEXT,
    performance_notes TEXT,
    drawdown_notes TEXT,
    consistency_score REAL,
    why_monitored TEXT,
    source_urls TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_date TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    UNIQUE(trader_name, platform)
);

CREATE TABLE IF NOT EXISTS BENCHMARK_DAILY_RESEARCH (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    research_date TEXT NOT NULL,
    trader_id INTEGER NOT NULL,
    source TEXT,
    observed_trade_or_portfolio_change TEXT,
    ai_interpretation TEXT,
    risk_lesson TEXT,
    market_lesson TEXT,
    related_company TEXT,
    related_sector TEXT,
    related_theme TEXT,
    confidence TEXT,
    impact_on_our_view TEXT,
    created_date TEXT NOT NULL,
    FOREIGN KEY(trader_id) REFERENCES BENCHMARK_TRADERS(trader_id)
);
"""


TRADER_FIELDS = [
    "trader_name",
    "platform",
    "region",
    "strategy_style",
    "markets_traded",
    "risk_rating",
    "performance_notes",
    "drawdown_notes",
    "consistency_score",
    "why_monitored",
    "source_urls",
]


class BenchmarkIntelligenceDatabase:
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
        trader_count = 0
        research_count = 0
        with closing(self.connect()) as conn:
            with conn:
                trader_ids: dict[str, int] = {}
                for trader in BENCHMARK_TRADERS:
                    trader_id = self._upsert_trader(conn, trader)
                    trader_ids[trader["trader_name"]] = trader_id
                    trader_count += 1

                for research in BENCHMARK_RESEARCH:
                    trader_id = trader_ids[research["trader_name"]]
                    if self._append_research(conn, trader_id, research):
                        research_count += 1
        return {"benchmark_traders": trader_count, "benchmark_research_rows": research_count}

    def monitored_today(self, research_date: date) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return list(
                conn.execute(
                    """
                    SELECT bt.*, bdr.*
                    FROM BENCHMARK_DAILY_RESEARCH bdr
                    JOIN BENCHMARK_TRADERS bt ON bt.trader_id = bdr.trader_id
                    WHERE bdr.research_date = ?
                    ORDER BY bt.trader_name ASC, bdr.id ASC
                    """,
                    (research_date.isoformat(),),
                )
            )

    def write_schema_doc(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_schema_doc(), encoding="utf-8")
        return path

    def write_initial_brief(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT bt.trader_name, bt.platform, bt.strategy_style, bt.risk_rating,
                           bt.performance_notes, bt.drawdown_notes, bt.why_monitored, bt.source_urls,
                           bdr.research_date, bdr.source, bdr.observed_trade_or_portfolio_change,
                           bdr.ai_interpretation, bdr.risk_lesson, bdr.market_lesson,
                           bdr.related_sector, bdr.related_theme, bdr.confidence, bdr.impact_on_our_view
                    FROM BENCHMARK_DAILY_RESEARCH bdr
                    JOIN BENCHMARK_TRADERS bt ON bt.trader_id = bdr.trader_id
                    ORDER BY bdr.research_date DESC, bt.trader_name ASC
                    """
                )
            )
        lines = [
            "# Benchmark Trader Intelligence Brief",
            "",
            f"Generated: {utc_now_iso()}",
            "",
            "Public information only. Private trades, undisclosed performance, and unavailable facts are left blank in SQLite.",
            "",
        ]
        for row in rows:
            lines.extend(
                [
                    f"## {row['trader_name']}",
                    "",
                    f"- Platform: {_na(row['platform'])}",
                    f"- Strategy style: {_na(row['strategy_style'])}",
                    f"- Risk rating: {_na(row['risk_rating'])}",
                    f"- Observed public information: {_na(row['observed_trade_or_portfolio_change'])}",
                    f"- AI interpretation: {_na(row['ai_interpretation'])}",
                    f"- Risk lesson: {_na(row['risk_lesson'])}",
                    f"- Market lesson: {_na(row['market_lesson'])}",
                    f"- Related sector/theme: {_na(row['related_sector'])} / {_na(row['related_theme'])}",
                    f"- Impact on our view: {_na(row['impact_on_our_view'])}",
                    f"- Sources: {_na(row['source_urls'])}",
                    "",
                ]
            )
        path = output_dir / "BENCHMARK_TRADER_INTELLIGENCE_BRIEF.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _upsert_trader(self, conn: sqlite3.Connection, trader: dict[str, Any]) -> int:
        now = utc_now_iso()
        values = [trader.get(field) for field in TRADER_FIELDS]
        conn.execute(
            f"""
            INSERT INTO BENCHMARK_TRADERS ({", ".join(TRADER_FIELDS)}, active, created_date, last_updated)
            VALUES ({", ".join(["?"] * len(TRADER_FIELDS))}, 1, ?, ?)
            ON CONFLICT(trader_name, platform) DO UPDATE SET
                region = excluded.region,
                strategy_style = excluded.strategy_style,
                markets_traded = excluded.markets_traded,
                risk_rating = excluded.risk_rating,
                performance_notes = excluded.performance_notes,
                drawdown_notes = excluded.drawdown_notes,
                consistency_score = excluded.consistency_score,
                why_monitored = excluded.why_monitored,
                source_urls = excluded.source_urls,
                active = 1,
                last_updated = excluded.last_updated
            """,
            (*values, now, now),
        )
        row = conn.execute(
            "SELECT trader_id FROM BENCHMARK_TRADERS WHERE trader_name = ? AND platform = ?",
            (trader["trader_name"], trader.get("platform")),
        ).fetchone()
        return int(row["trader_id"])

    def _append_research(self, conn: sqlite3.Connection, trader_id: int, research: dict[str, Any]) -> bool:
        existing = conn.execute(
            """
            SELECT id FROM BENCHMARK_DAILY_RESEARCH
            WHERE research_date = ? AND trader_id = ? AND source = ? AND observed_trade_or_portfolio_change = ?
            """,
            (
                research["research_date"],
                trader_id,
                research.get("source"),
                research.get("observed_trade_or_portfolio_change"),
            ),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """
            INSERT INTO BENCHMARK_DAILY_RESEARCH (
                research_date, trader_id, source, observed_trade_or_portfolio_change,
                ai_interpretation, risk_lesson, market_lesson, related_company,
                related_sector, related_theme, confidence, impact_on_our_view, created_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                research["research_date"],
                trader_id,
                research.get("source"),
                research.get("observed_trade_or_portfolio_change"),
                research.get("ai_interpretation"),
                research.get("risk_lesson"),
                research.get("market_lesson"),
                research.get("related_company"),
                research.get("related_sector"),
                research.get("related_theme"),
                research.get("confidence"),
                research.get("impact_on_our_view"),
                utc_now_iso(),
            ),
        )
        return True


def _na(value: Any) -> str:
    return "Not available" if value in (None, "") else str(value)


def _schema_doc() -> str:
    return """# Benchmark Trader Intelligence Schema

Date: 2026-07-02

Storage: `data/audit.sqlite3`

Benchmark intelligence is local-only and uses public information only. It does not redesign the trading engine, execution engine, guardrails, or SQLite storage.

## BENCHMARK_TRADERS

- `trader_id` INTEGER PRIMARY KEY
- `trader_name` TEXT NOT NULL
- `platform` TEXT
- `region` TEXT
- `strategy_style` TEXT
- `markets_traded` TEXT
- `risk_rating` TEXT
- `performance_notes` TEXT
- `drawdown_notes` TEXT
- `consistency_score` REAL
- `why_monitored` TEXT
- `source_urls` TEXT
- `active` INTEGER NOT NULL DEFAULT 1
- `created_date` TEXT NOT NULL
- `last_updated` TEXT NOT NULL

Unique key: `trader_name, platform`

## BENCHMARK_DAILY_RESEARCH

Append-only benchmark research log.

- `id` INTEGER PRIMARY KEY
- `research_date` TEXT NOT NULL
- `trader_id` INTEGER NOT NULL
- `source` TEXT
- `observed_trade_or_portfolio_change` TEXT
- `ai_interpretation` TEXT
- `risk_lesson` TEXT
- `market_lesson` TEXT
- `related_company` TEXT
- `related_sector` TEXT
- `related_theme` TEXT
- `confidence` TEXT
- `impact_on_our_view` TEXT
- `created_date` TEXT NOT NULL

## Data Rules

- Use only publicly available information.
- Do not fabricate private trades, performance, drawdowns, or consistency scores.
- Leave unavailable information as `NULL` in SQLite.
- Use this screen for learning only; do not copy benchmark trades automatically.
"""
