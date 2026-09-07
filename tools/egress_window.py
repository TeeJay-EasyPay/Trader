"""Measure what the database actually SENDS over a window, rather than since the epoch.

pg_stat_statements counts from its last reset -- here, 18 July -- so reading it directly
answers "what has this database ever done", not "what is it doing now". Every fix made since
then is invisible in that total, which is exactly the trap that produced a wrong "egress is
under control" answer on 2026-09-05.

So: snapshot, wait, snapshot, diff. No reset, so no history is destroyed.

The byte model charges the MEASURED WIDTH OF THE COLUMNS ACTUALLY SELECTED. An earlier version
charged the whole row whenever a column list merely mentioned a wide column, and was wrong by
47x. Width comes from pg_stats where the planner has it, and falls back to a modest default
only for columns it has never analysed.

    python tools/egress_window.py snapshot  out.json
    python tools/egress_window.py diff      before.json after.json
"""

from __future__ import annotations

import json
import os
import re
import sys

DEFAULT_WIDTH = 32          # only for columns the planner has never analysed
OVERHEAD_PER_ROW = 5        # wire protocol: row header plus per-column length prefixes


def _connect():
    import psycopg

    url = os.environ.get("AUDIT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set AUDIT_DATABASE_URL (or DATABASE_URL) first.")
    return psycopg.connect(url)


def snapshot(path: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT NOW()::text")
        taken_at = cur.fetchone()[0]
        cur.execute(
            r"""SELECT queryid, calls, rows, total_exec_time,
                      regexp_replace(query, '\s+', ' ', 'g') AS query
               FROM pg_stat_statements WHERE query ILIKE 'SELECT%'"""
        )
        rows = [
            {"queryid": str(q), "calls": c, "rows": r, "ms": float(t or 0), "query": s}
            for q, c, r, t, s in cur.fetchall()
        ]
        # Measured average width per column, so the byte estimate is grounded rather than guessed.
        cur.execute(
            """SELECT tablename, attname, avg_width FROM pg_stats
               WHERE schemaname = 'public'"""
        )
        widths = {f"{t}.{a}".lower(): int(w or DEFAULT_WIDTH) for t, a, w in cur.fetchall()}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"taken_at": taken_at, "widths": widths, "statements": rows}, handle)
    print(f"snapshot at {taken_at}: {len(rows)} SELECT statements -> {path}")


_COLUMNS = re.compile(r"^\s*SELECT\s+(?:DISTINCT\s+)?(.*?)\s+FROM\s", re.IGNORECASE | re.DOTALL)


def _row_bytes(query: str, widths: dict[str, int]) -> int:
    """Bytes per row: the widths of the columns this query actually selects."""
    match = _COLUMNS.search(query)
    if not match:
        return DEFAULT_WIDTH + OVERHEAD_PER_ROW
    selected = match.group(1)
    if "*" in selected:
        # A star selects everything, so the widest table mentioned is the fair charge.
        by_table: dict[str, int] = {}
        for key, width in widths.items():
            table = key.split(".", 1)[0]
            if re.search(r"\b" + re.escape(table) + r"\b", query, re.IGNORECASE):
                by_table[table] = by_table.get(table, 0) + width
        return (max(by_table.values()) if by_table else DEFAULT_WIDTH * 8) + OVERHEAD_PER_ROW
    total = 0
    for part in selected.split(","):
        name = re.sub(r"\s+AS\s+\w+\s*$", "", part.strip(), flags=re.IGNORECASE)
        name = name.split(".")[-1].strip().strip('"').lower()
        candidates = [w for key, w in widths.items() if key.endswith("." + name)]
        total += max(candidates) if candidates else DEFAULT_WIDTH
    return total + OVERHEAD_PER_ROW


def diff(before_path: str, after_path: str) -> None:
    before = json.load(open(before_path, encoding="utf-8"))
    after = json.load(open(after_path, encoding="utf-8"))
    was = {s["queryid"]: s for s in before["statements"]}
    widths = after.get("widths") or {}

    grown = []
    for statement in after["statements"]:
        old = was.get(statement["queryid"])
        calls = statement["calls"] - (old["calls"] if old else 0)
        rows = statement["rows"] - (old["rows"] if old else 0)
        if calls <= 0 and rows <= 0:
            continue
        grown.append({**statement, "calls": calls, "rows": rows,
                      "bytes": rows * _row_bytes(statement["query"], widths)})

    grown.sort(key=lambda s: s["bytes"], reverse=True)
    total = sum(s["bytes"] for s in grown)

    span_note = f"{before['taken_at'][:19]} -> {after['taken_at'][:19]}"
    print(f"=== window {span_note} ===")
    print(f"estimated bytes sent: {total / 1e6:,.1f} MB across {sum(s['calls'] for s in grown):,} calls\n")
    print(f"  {'MB':>8}  {'share':>6}  {'calls':>9}  {'rows':>11}  query")
    for statement in grown[:20]:
        if statement["bytes"] < 1e5:
            break
        print("  %8.1f  %5.1f%%  %9s  %11s  %s" % (
            statement["bytes"] / 1e6,
            100 * statement["bytes"] / total if total else 0,
            f"{statement['calls']:,}",
            f"{statement['rows']:,}",
            statement["query"][:88],
        ))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    if sys.argv[1] == "snapshot":
        snapshot(sys.argv[2])
    elif sys.argv[1] == "diff" and len(sys.argv) >= 4:
        diff(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
