from __future__ import annotations

import html
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .config import load_settings


PAGE_SIZE = 100


class ReadOnlyDatabaseBrowser:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def tables(self) -> list[str]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name ASC
                """
            )
            return [str(row["name"]) for row in rows]

    def columns(self, table: str) -> list[str]:
        self._require_table(table)
        with closing(self.connect()) as conn:
            rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")
            return [str(row["name"]) for row in rows]

    def rows(self, table: str, *, search: str = "", sort: str = "", direction: str = "ASC") -> tuple[list[str], list[dict[str, Any]]]:
        columns = self.columns(table)
        params: list[Any] = []
        where = ""
        if search:
            where = " WHERE " + " OR ".join(f"CAST({_quote_identifier(column)} AS TEXT) LIKE ?" for column in columns)
            params.extend([f"%{search}%"] * len(columns))
        order = ""
        if sort in columns:
            order = f" ORDER BY {_quote_identifier(sort)} {'DESC' if direction.upper() == 'DESC' else 'ASC'}"
        sql = f"SELECT * FROM {_quote_identifier(table)}{where}{order} LIMIT {PAGE_SIZE}"
        with closing(self.connect()) as conn:
            records = [dict(row) for row in conn.execute(sql, params)]
        return columns, records

    def _require_table(self, table: str) -> None:
        if table not in self.tables():
            raise ValueError(f"Unknown table: {table}")


class BrowserHandler(BaseHTTPRequestHandler):
    browser: ReadOnlyDatabaseBrowser

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/data":
                self._json(self._data(query))
                return
            self._html(APP_HTML)
        except Exception as exc:
            self._json({"error": str(exc)}, status=400)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _data(self, query: dict[str, list[str]]) -> dict[str, Any]:
        tables = self.browser.tables()
        table = _first(query, "table") or (tables[0] if tables else "")
        search = _first(query, "search") or ""
        sort = _first(query, "sort") or ""
        direction = _first(query, "direction") or "ASC"
        columns: list[str] = []
        rows: list[dict[str, Any]] = []
        if table:
            columns, rows = self.browser.rows(table, search=search, sort=sort, direction=direction)
        return {
            "db_path": str(self.browser.db_path),
            "read_only": True,
            "tables": tables,
            "table": table,
            "columns": columns,
            "rows": rows,
            "search": search,
            "sort": sort,
            "direction": direction,
            "page_size": PAGE_SIZE,
        }

    def _html(self, body: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def run_browser(host: str = "127.0.0.1", port: int = 8770, db_path: Path | None = None) -> None:
    settings = load_settings()
    BrowserHandler.browser = ReadOnlyDatabaseBrowser(db_path or settings.db_path)
    server = ThreadingHTTPServer((host, port), BrowserHandler)
    print(f"Read-only SQLite browser listening on http://{host}:{port}")
    server.serve_forever()


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Trader SQLite Browser</title>
  <style>
    body { margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f6f7f9; color: #17202a; }
    header { background: #fff; border-bottom: 1px solid #dde1e7; padding: 18px 24px; }
    main { padding: 18px; }
    .layout { display: grid; grid-template-columns: 240px 1fr; gap: 16px; }
    aside, section { background: #fff; border: 1px solid #dde1e7; border-radius: 8px; padding: 12px; }
    button, input { min-height: 36px; border-radius: 8px; border: 1px solid #cfd6df; padding: 0 10px; }
    button { background: #1f6feb; border: 0; color: #fff; font-weight: 800; cursor: pointer; }
    .table-button { display: block; width: 100%; margin-bottom: 6px; background: #eef2f7; color: #17202a; border: 1px solid #cfd6df; text-align: left; }
    .table-button.active { background: #1f6feb; color: #fff; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
    th, td { border-bottom: 1px solid #e6e9ee; padding: 8px; text-align: left; vertical-align: top; max-width: 360px; overflow-wrap: anywhere; }
    th { background: #f8fafc; position: sticky; top: 0; cursor: pointer; }
    .controls { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .muted { color: #667085; font-size: 13px; }
    @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>AI Trader SQLite Browser</h1>
    <div class="muted">Read only. No editing commands are exposed.</div>
  </header>
  <main class="layout">
    <aside>
      <h2>Tables</h2>
      <div id="tables"></div>
    </aside>
    <section>
      <div class="controls">
        <input id="search" placeholder="Search records">
        <button onclick="applySearch()">Search</button>
        <button onclick="clearSearch()">Clear</button>
      </div>
      <div class="muted" id="meta"></div>
      <div style="overflow:auto">
        <table id="records"></table>
      </div>
    </section>
  </main>
  <script>
    let state = { table: '', search: '', sort: '', direction: 'ASC' };
    function esc(value) {
      if (value === null || value === undefined || value === '') return 'Not available';
      return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    async function loadData(next = {}) {
      state = { ...state, ...next };
      const params = new URLSearchParams(state);
      const response = await fetch(`/data?${params.toString()}`);
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      state.table = data.table;
      document.getElementById('search').value = data.search || '';
      document.getElementById('meta').textContent = `${data.rows.length} records shown from ${data.table || 'no table'} (${data.db_path})`;
      document.getElementById('tables').innerHTML = data.tables.map(table => `
        <button class="table-button ${table === data.table ? 'active' : ''}" onclick="loadData({table: '${table}', sort: '', search: ''})">${table}</button>
      `).join('');
      const head = `<tr>${data.columns.map(column => `<th onclick="sortBy('${column}')">${esc(column)}</th>`).join('')}</tr>`;
      const body = data.rows.map(row => `<tr>${data.columns.map(column => `<td>${esc(row[column])}</td>`).join('')}</tr>`).join('');
      document.getElementById('records').innerHTML = head + body;
    }
    function applySearch() { loadData({ search: document.getElementById('search').value }); }
    function clearSearch() { loadData({ search: '' }); }
    function sortBy(column) {
      const direction = state.sort === column && state.direction === 'ASC' ? 'DESC' : 'ASC';
      loadData({ sort: column, direction });
    }
    loadData().catch(error => {
      document.getElementById('meta').textContent = `Problem: ${error}`;
    });
  </script>
</body>
</html>"""


if __name__ == "__main__":
    run_browser()
