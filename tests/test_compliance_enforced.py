"""The Shariah screen is checked at permission time, not assumed from the watchlist.

2026-08-29, Founder-directed. compliance_screen.py existed and was tested, but nothing
called it -- the screen was enforced only by the accident that a human had hand-picked all
50 companies on the watchlist. That is safe exactly as long as the list stays hand-picked,
and the Founder's stated goal is the opposite: "keeping fifty as a list that's static and
never changes is not really a good long term strategy... there could be thousands."

So these tests do the thing the old arrangement could not survive: they put a tobacco
company, a casino and a defence contractor ON the watchlist, and require that the app still
refuses to trade them.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from ai_trader.agent import AITradingAgent
from ai_trader.audit import AuditDatabase
from ai_trader.config import load_settings
from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.models import utc_now_iso
from ai_trader.operational import PERMITTED_UNIVERSE_FIT


def _agent_with(tmp: str):
    settings = load_settings()
    settings = settings.__class__(**{
        **{f: getattr(settings, f) for f in settings.__dataclass_fields__},
        "db_path": Path(tmp) / "t.db",
        "trading_log_path": Path(tmp) / "t.log",
    })
    InvestmentIntelligenceDatabase(settings.db_path).seed_initial_data()
    audit = AuditDatabase(settings.db_path, settings.trading_log_path)
    agent = AITradingAgent(
        market_data=None, audit=audit, guardrails=settings.guardrails, db_path=settings.db_path,
    )
    return agent, settings.db_path


def _add_to_watchlist(db_path: Path, *, ticker: str, name: str, sector: str, industry: str,
                      summary: str = "") -> None:
    """Put a company on the watchlist exactly as a future dynamic importer would."""
    now = utc_now_iso()
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cur = conn.execute(
                """INSERT INTO COMPANY_MASTER
                       (company_name, ticker, exchange, sector, industry, business_summary,
                        last_updated, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, ticker, "NASDAQ", sector, industry, summary, now, now, now),
            )
            conn.execute(
                """INSERT INTO INVESTMENT_WATCHLIST
                       (company_id, current_investment_philosophy_fit, active, added_at, last_reviewed)
                   VALUES (?, ?, 1, ?, ?)""",
                (cur.lastrowid, "Strong", now, now),
            )


def test_an_excluded_company_cannot_trade_even_when_on_the_watchlist():
    """The regression that matters: being on the list is no longer enough.

    Each of these is rated "Strong" -- the BEST rating -- and is active on the watchlist.
    Under the old membership-only rule every one of them would have been permitted.
    """
    cases = [
        ("MO2", "Altria Group", "Consumer Staples", "Tobacco", "tobacco"),
        ("LVS2", "Las Vegas Sands", "Consumer Discretionary", "Casinos and Gaming", "gambling"),
        ("LMT2", "Lockheed Martin", "Industrials", "Aerospace and Defense", "defence"),
        ("BUD2", "Anheuser-Busch", "Consumer Staples", "Brewers", "alcohol"),
        ("JPM2", "JPMorgan Chase", "Financials", "Diversified Banks", "conventional_finance"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        agent, db_path = _agent_with(tmp)
        for ticker, name, sector, industry, _category in cases:
            _add_to_watchlist(db_path, ticker=ticker, name=name, sector=sector, industry=industry)
        for ticker, name, _sector, _industry, category in cases:
            assert agent._watchlist_philosophy_fit(ticker) is None, (
                f"{name} ({category}) was permitted to trade despite being an excluded business"
            )


def test_a_pork_producer_is_caught_by_its_description_not_its_sector():
    """Smithfield's real classification is only 'Packaged Foods' -- bland and clean.

    This is the case the classification test alone cannot catch, and the reason the screen
    also reads the business description for words that carry no innocent reading.
    """
    with tempfile.TemporaryDirectory() as tmp:
        agent, db_path = _agent_with(tmp)
        _add_to_watchlist(
            db_path, ticker="SFD2", name="Smithfield Foods", sector="Consumer Staples",
            industry="Packaged Foods", summary="The world's largest pork processor.",
        )
        assert agent._watchlist_philosophy_fit("SFD2") is None


def test_an_ambiguous_company_is_referred_not_admitted():
    """Uncertainty must never resolve to a pass -- a human decides, not the app."""
    with tempfile.TemporaryDirectory() as tmp:
        agent, db_path = _agent_with(tmp)
        _add_to_watchlist(
            db_path, ticker="XYZ2", name="Generic Industrials", sector="Industrials",
            industry="Industrial Machinery",
            summary="Supplies components used in military vehicles among other markets.",
        )
        assert agent._watchlist_philosophy_fit("XYZ2") is None


def test_a_clean_company_on_the_watchlist_still_trades():
    """The screen must not block the ordinary case -- verified live: all 50 pass."""
    with tempfile.TemporaryDirectory() as tmp:
        agent, db_path = _agent_with(tmp)
        _add_to_watchlist(
            db_path, ticker="ZZY2", name="Clean Software Co", sector="Technology",
            industry="Application Software", summary="Builds accounting software.",
        )
        assert agent._watchlist_philosophy_fit("ZZY2") == PERMITTED_UNIVERSE_FIT


def test_the_existing_seeded_universe_is_entirely_permitted():
    """A guard on the Founder's own 50: if wiring the screen would have barred any of the
    companies he chose by hand, that is something he must be told about, not discover as
    silent inactivity."""
    with tempfile.TemporaryDirectory() as tmp:
        agent, db_path = _agent_with(tmp)
        with closing(sqlite3.connect(db_path)) as conn:
            tickers = [
                r[0] for r in conn.execute(
                    """SELECT cm.ticker FROM INVESTMENT_WATCHLIST iw
                       JOIN COMPANY_MASTER cm ON cm.id = iw.company_id"""
                ).fetchall()
            ]
        assert tickers, "seed data should populate the watchlist"
        blocked = [t for t in tickers if agent._watchlist_philosophy_fit(t) is None]
        assert blocked == [], f"the screen would bar Founder-approved companies: {blocked}"
