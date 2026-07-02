from __future__ import annotations

import json
import socket
import sqlite3
import sys
from contextlib import closing
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .agent import AITradingAgent
from .ai import OpenAIProposalAnalyzer
from .alpaca import AlpacaCredentials, AlpacaPaperClient
from .audit import AuditDatabase
from .benchmark import BenchmarkIntelligenceDatabase
from .briefing import generate_daily_briefing
from .config import Settings, load_settings
from .execution import ExecutionEngine
from .intelligence import InvestmentIntelligenceDatabase
from .models import TradeProposal, utc_now_iso


CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS engine_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    trading_state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_command TEXT
);
"""


class LocalApiService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.audit = AuditDatabase(settings.db_path, settings.trading_log_path)
        self.intelligence = InvestmentIntelligenceDatabase(settings.db_path)
        self.benchmark = BenchmarkIntelligenceDatabase(settings.db_path)
        self._initialize_control()

    def get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        if path == "/status":
            return 200, self.status()
        if path == "/portfolio":
            return 200, self.portfolio()
        if path == "/founder-brief":
            return 200, self.founder_brief()
        if path == "/recommendations":
            return 200, {"recommendations": self.recommendations()}
        if path == "/intelligence/companies":
            return 200, {"companies": self.companies()}
        if path == "/intelligence/themes":
            return 200, {"themes": self.themes()}
        if path == "/benchmark-traders":
            return 200, {"benchmark_traders": self.benchmark_traders()}
        if path == "/benchmark-daily-brief":
            brief_date = _first(query, "date") or date.today().isoformat()
            return 200, self.benchmark_daily_brief(brief_date)
        if path == "/developer-status":
            return 200, self.developer_status()
        if path == "/developer-dashboard":
            return 200, {"html": DEVELOPER_DASHBOARD_HTML}
        return 404, {"error": "not_found", "path": path}

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/run-analysis":
            return 200, self.run_analysis(body)
        if path == "/pause-trading":
            return 200, self.set_trading_state("paused", "pause-trading")
        if path == "/resume-trading":
            return 200, self.set_trading_state("running", "resume-trading")
        if path == "/stop-trading":
            return 200, self.set_trading_state("stopped", "stop-trading")
        if path == "/approve-and-execute":
            return 200, self.approve_and_execute(body)
        return 404, {"error": "not_found", "path": path}

    def status(self) -> dict[str, Any]:
        control = self._control_state()
        last_analysis = self._scalar("SELECT MAX(created_at) FROM trade_audit WHERE event_type IN ('agent_proposal', 'agent_no_trade')")
        last_activity = self._rows(
            """
            SELECT created_at, event_type, proposal_id, symbol, execution_result
            FROM trade_audit
            ORDER BY id DESC
            LIMIT 8
            """
        )
        return {
            "system_status": control["trading_state"],
            "paper_live_mode": "Paper" if self.settings.guardrails.paper_trading_only else "Live disabled by local API",
            "engine_health": "Available" if self.settings.db_path.exists() else "Database not initialized",
            "last_analysis_time": last_analysis,
            "latest_activity": [dict(row) for row in last_activity],
            "updated_at": control["updated_at"],
        }

    def portfolio(self) -> dict[str, Any]:
        if not self.settings.has_alpaca_credentials:
            return {
                "portfolio_value": None,
                "cash_available": None,
                "todays_pnl": None,
                "open_positions": [],
                "source": "Not available: Alpaca paper credentials are not configured.",
            }
        try:
            broker = self._broker()
            account = broker.get_account()
            positions = broker.get_positions()
            return {
                "portfolio_value": _float_or_none(account.get("portfolio_value") or account.get("equity")),
                "cash_available": _float_or_none(account.get("cash")),
                "todays_pnl": None,
                "open_positions": [
                    {
                        "symbol": row.get("symbol"),
                        "qty": _float_or_none(row.get("qty")),
                        "market_value": _float_or_none(row.get("market_value")),
                        "unrealized_pl": _float_or_none(row.get("unrealized_pl")),
                    }
                    for row in positions
                ],
                "source": "Alpaca Paper Trading",
            }
        except Exception as exc:
            return {
                "portfolio_value": None,
                "cash_available": None,
                "todays_pnl": None,
                "open_positions": [],
                "source": f"Not available: {exc}",
            }

    def founder_brief(self) -> dict[str, Any]:
        row = self._row("SELECT * FROM daily_briefings ORDER BY id DESC LIMIT 1")
        if row:
            return {"briefing_date": row["briefing_date"], "report_markdown": row["report_markdown"], "created_at": row["created_at"]}
        markdown = generate_daily_briefing(self.audit, date.today(), self.settings.output_dir)
        return {"briefing_date": date.today().isoformat(), "report_markdown": markdown, "created_at": utc_now_iso()}

    def recommendations(self) -> list[dict[str, Any]]:
        rows = self._rows(
            """
            SELECT ta.*, cm.company_name, cm.country, cm.sector, cm.investment_thesis,
                   cm.reasons_for_caution, iw.current_investment_philosophy_fit
            FROM trade_audit ta
            LEFT JOIN COMPANY_MASTER cm ON UPPER(cm.ticker) = UPPER(ta.symbol)
            LEFT JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
            WHERE ta.event_type = 'agent_proposal'
            ORDER BY ta.id DESC
            LIMIT 20
            """
        )
        recommendations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if row["proposal_id"] in seen:
                continue
            seen.add(row["proposal_id"])
            recommendations.append(
                {
                    "proposal_id": row["proposal_id"],
                    "company": row["company_name"],
                    "ticker": row["symbol"],
                    "sector": row["sector"],
                    "country": row["country"],
                    "confidence": row["ai_confidence"],
                    "investment_philosophy_fit": row["current_investment_philosophy_fit"],
                    "investment_thesis": row["investment_thesis"],
                    "reason_for_recommendation": row["ai_reasoning"],
                    "key_risks": row["reasons_for_caution"] or row["validation_result"],
                    "suggested_stop_loss": row["stop_loss"],
                    "suggested_take_profit": row["take_profit"],
                    "suggested_position_size": row["position_size"],
                    "created_at": row["created_at"],
                    "guardrails_passed": bool(row["execution_guardrails_passed"]),
                }
            )
        return recommendations

    def companies(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._rows(
                """
                SELECT cm.*, iw.current_watchlist_priority, iw.current_investment_philosophy_fit, iw.active
                FROM COMPANY_MASTER cm
                LEFT JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
                ORDER BY cm.company_name ASC
                """
            )
        ]

    def themes(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows("SELECT * FROM MARKET_THEMES ORDER BY theme ASC")]

    def benchmark_traders(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows("SELECT * FROM BENCHMARK_TRADERS WHERE active = 1 ORDER BY trader_name ASC")]

    def benchmark_daily_brief(self, brief_date: str) -> dict[str, Any]:
        rows = [
            dict(row)
            for row in self._rows(
                """
                SELECT bt.trader_name, bt.platform, bt.strategy_style, bt.risk_rating,
                       bdr.research_date, bdr.source, bdr.observed_trade_or_portfolio_change,
                       bdr.ai_interpretation, bdr.risk_lesson, bdr.market_lesson,
                       bdr.related_company, bdr.related_sector, bdr.related_theme,
                       bdr.confidence, bdr.impact_on_our_view
                FROM BENCHMARK_DAILY_RESEARCH bdr
                JOIN BENCHMARK_TRADERS bt ON bt.trader_id = bdr.trader_id
                WHERE bdr.research_date = ?
                ORDER BY bt.trader_name ASC
                """,
                (brief_date,),
            )
        ]
        summary = "Not available" if not rows else "Benchmark intelligence is for learning only. Do not copy trades automatically."
        return {"date": brief_date, "summary": summary, "items": rows}

    def developer_status(self) -> dict[str, Any]:
        watchlist_count = self._count("INVESTMENT_WATCHLIST", "active = 1")
        theme_count = self._count("MARKET_THEMES")
        benchmark_count = self._count("BENCHMARK_TRADERS", "active = 1")
        journal_count = self._count("trade_audit")
        founder = self._row("SELECT briefing_date, created_at FROM daily_briefings ORDER BY id DESC LIMIT 1")
        control = self._control_state()
        db_ok = self.settings.db_path.exists()
        knowledge_ok = watchlist_count > 0 and theme_count > 0
        benchmark_ok = benchmark_count > 0
        return {
            "generated_at": utc_now_iso(),
            "python_version": sys.version.split()[0],
            "components": {
                "python": _component(True, sys.version.split()[0]),
                "sqlite": _component(db_ok, str(self.settings.db_path)),
                "openai": _component(bool(self.settings.openai_api_key), "Configured" if self.settings.openai_api_key else "OPENAI_API_KEY missing"),
                "alpaca": _component(self.settings.has_alpaca_credentials, "Configured" if self.settings.has_alpaca_credentials else "Alpaca credentials missing"),
                "knowledge_engine": _component(knowledge_ok, f"{watchlist_count} watchlist / {theme_count} themes"),
                "benchmark_engine": _component(benchmark_ok, f"{benchmark_count} traders"),
                "trading_engine": _component(control["trading_state"] in {"running", "paused", "stopped"}, control["trading_state"]),
                "api": _component(True, "Listening"),
                "mobile_app": _component(_port_open("127.0.0.1", 8082), "Expo port 8082"),
            },
            "counts": {
                "watchlist": watchlist_count,
                "market_themes": theme_count,
                "benchmark_traders": benchmark_count,
                "trading_journal": journal_count,
            },
            "last_founder_brief": dict(founder) if founder else None,
        }

    def run_analysis(self, body: dict[str, Any]) -> dict[str, Any]:
        symbols = body.get("symbols")
        if isinstance(symbols, str):
            symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
        if not symbols:
            symbols = [row["ticker"] for row in self._rows("SELECT ticker FROM COMPANY_MASTER ORDER BY id ASC LIMIT 3")]
        if not symbols:
            return {"status": "not_available", "message": "No symbols available in SQLite."}
        if not self.settings.has_alpaca_credentials:
            return {"status": "not_available", "message": "Alpaca paper credentials are required for market data analysis.", "symbols": symbols}
        broker = self._broker()
        analyzer = None
        if self.settings.openai_api_key:
            analyzer = OpenAIProposalAnalyzer(self.settings.openai_api_key, self.settings.openai_model, self.settings.guardrails)
        agent = AITradingAgent(market_data=broker, audit=self.audit, guardrails=self.settings.guardrails, analyzer=analyzer)
        proposals = agent.propose_trades(symbols, broker.account_context())
        return {"status": "completed", "symbols": symbols, "proposals": [proposal.to_dict() for proposal in proposals]}

    def set_trading_state(self, state: str, command: str) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO engine_control (id, trading_state, updated_at, last_command)
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        trading_state = excluded.trading_state,
                        updated_at = excluded.updated_at,
                        last_command = excluded.last_command
                    """,
                    (state, utc_now_iso(), command),
                )
        self.audit.record_execution_event(f"control-{command}", "engine_control", {"state": state, "command": command})
        return {"status": state, "command": command}

    def approve_and_execute(self, body: dict[str, Any]) -> dict[str, Any]:
        control = self._control_state()
        if control["trading_state"] != "running":
            return {"status": "blocked", "message": f"Trading state is {control['trading_state']}."}
        proposal_id = body.get("proposal_id")
        if not proposal_id:
            return {"status": "rejected", "message": "proposal_id is required."}
        if not self.settings.has_alpaca_credentials:
            return {"status": "not_available", "message": "Alpaca paper credentials are required for execution."}
        row = self._row(
            "SELECT payload_json FROM trade_audit WHERE proposal_id = ? AND event_type = 'agent_proposal' ORDER BY id DESC LIMIT 1",
            (str(proposal_id),),
        )
        if not row:
            return {"status": "rejected", "message": "Proposal not found in SQLite."}
        payload = json.loads(row["payload_json"])
        proposal = TradeProposal.from_dict(payload["proposal"])
        engine = ExecutionEngine(broker=self._broker(), audit=self.audit, guardrails=self.settings.guardrails)
        result = engine.execute_proposals([proposal])
        return {"status": "submitted", "result": result, "amount_requested": body.get("amount")}

    def _broker(self) -> AlpacaPaperClient:
        return AlpacaPaperClient(
            AlpacaCredentials(
                api_key=self.settings.alpaca_api_key or "",
                secret_key=self.settings.alpaca_secret_key or "",
                base_url=self.settings.alpaca_paper_base_url,
                data_base_url=self.settings.alpaca_data_base_url,
            )
        )

    def _initialize_control(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.executescript(CONTROL_SCHEMA)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO engine_control (id, trading_state, updated_at, last_command)
                    VALUES (1, 'running', ?, 'api-start')
                    """,
                    (utc_now_iso(),),
                )

    def _control_state(self) -> dict[str, Any]:
        row = self._row("SELECT * FROM engine_control WHERE id = 1")
        return dict(row) if row else {"trading_state": "unknown", "updated_at": None, "last_command": None}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(sql, params).fetchone()

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn:
            return list(conn.execute(sql, params))

    def _scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = self._row(sql, params)
        return None if row is None else row[0]

    def _count(self, table: str, where: str | None = None) -> int:
        if table not in {
            "INVESTMENT_WATCHLIST",
            "MARKET_THEMES",
            "BENCHMARK_TRADERS",
            "trade_audit",
        }:
            raise ValueError(f"Unsupported count table: {table}")
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self._scalar(sql) or 0)


class ApiHandler(BaseHTTPRequestHandler):
    service: LocalApiService

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        status, payload = self.service.get(parsed.path, parse_qs(parsed.query))
        self._json(status, payload)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self._read_body()
        status, payload = self.service.post(parsed.path, body)
        self._json(status, payload)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("POST body must be a JSON object")
        return data

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        if "html" in payload and len(payload) == 1:
            body = str(payload["html"]).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    service = LocalApiService(load_settings())
    service.intelligence.seed_initial_data()
    service.benchmark.seed_initial_data()
    service.benchmark.write_schema_doc(Path("governance/BENCHMARK_INTELLIGENCE_SCHEMA.md"))
    service.benchmark.write_initial_brief(service.settings.output_dir)
    ApiHandler.service = service
    server = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"AI Trader local API listening on http://{host}:{port}")
    server.serve_forever()


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _component(healthy: bool, detail: str) -> dict[str, Any]:
    return {"healthy": healthy, "state": "Healthy" if healthy else "Problem", "detail": detail}


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


DEVELOPER_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Trader Developer Dashboard</title>
  <style>
    body { margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f6f7f9; color: #17202a; }
    header { background: #ffffff; border-bottom: 1px solid #dde1e7; padding: 20px 28px; }
    main { padding: 24px; max-width: 1100px; margin: 0 auto; }
    h1 { margin: 0; font-size: 26px; }
    .sub { margin-top: 6px; color: #667085; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
    .card { background: #ffffff; border: 1px solid #dde1e7; border-radius: 8px; padding: 14px; }
    .label { font-weight: 800; margin-bottom: 8px; }
    .healthy { color: #137333; font-weight: 800; }
    .problem { color: #b42318; font-weight: 800; }
    .detail { margin-top: 8px; color: #475467; font-size: 13px; overflow-wrap: anywhere; }
    .counts { margin-top: 18px; }
    button { border: 0; border-radius: 8px; background: #1f6feb; color: #fff; font-weight: 800; padding: 10px 14px; cursor: pointer; }
  </style>
</head>
<body>
  <header>
    <h1>AI Trader Developer Dashboard</h1>
    <div class="sub" id="generated">Loading local status...</div>
  </header>
  <main>
    <p><button onclick="loadStatus()">Refresh</button></p>
    <section class="grid" id="components"></section>
    <section class="card counts">
      <div class="label">Counts</div>
      <div id="counts">Not available</div>
    </section>
    <section class="card counts">
      <div class="label">Last Founder Brief</div>
      <div id="brief">Not available</div>
    </section>
  </main>
  <script>
    const names = {
      python: 'Python Version',
      sqlite: 'SQLite Status',
      openai: 'OpenAI Status',
      alpaca: 'Alpaca Status',
      knowledge_engine: 'Knowledge Engine Status',
      benchmark_engine: 'Benchmark Engine Status',
      trading_engine: 'Trading Engine Status',
      api: 'API Status',
      mobile_app: 'Mobile App Status'
    };
    function icon(ok) { return ok ? '🟢 Healthy' : '🔴 Problem'; }
    async function loadStatus() {
      const response = await fetch('/developer-status');
      const data = await response.json();
      document.getElementById('generated').textContent = `Generated ${data.generated_at}`;
      document.getElementById('components').innerHTML = Object.entries(data.components).map(([key, item]) => `
        <div class="card">
          <div class="label">${names[key] || key}</div>
          <div class="${item.healthy ? 'healthy' : 'problem'}">${icon(item.healthy)}</div>
          <div class="detail">${item.detail || 'Not available'}</div>
        </div>
      `).join('');
      document.getElementById('counts').innerHTML = `
        Watchlist Count: ${data.counts.watchlist}<br>
        Market Theme Count: ${data.counts.market_themes}<br>
        Benchmark Trader Count: ${data.counts.benchmark_traders}<br>
        Trading Journal Count: ${data.counts.trading_journal}
      `;
      document.getElementById('brief').textContent = data.last_founder_brief
        ? `${data.last_founder_brief.briefing_date} (${data.last_founder_brief.created_at})`
        : 'Not available';
    }
    loadStatus().catch(error => {
      document.getElementById('generated').textContent = `Problem loading status: ${error}`;
    });
  </script>
</body>
</html>"""
