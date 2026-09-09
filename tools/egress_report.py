"""What the day's database egress is actually made of, by the thing that causes it.

2026-09-07, Founder-directed:

    "One thing I think we need to understand, which we don't really, is a table showing what
     the five hundred megaday of egress is actually composed of, like a comprehensive table.
     And once we have that comprehensive table, we'll be able to see what's causing the spikes
     in data or the increase in egress how many times a day."

He is right that this was missing. Everything so far has been a ranked list of SQL, which tells
you which statement is expensive but not which PART OF THE SYSTEM is spending the money, nor how
often it does it. Three separate fixes were made off that list; one of them was proposed off a
number inflated threefold by my own deploys, and a table like this would have shown that
immediately.

So this attributes every read to the module that issues it, by finding the query in the source
rather than by guessing, and reports calls per day beside megabytes per day.

TWO HONEST LIMITS, both of which matter when reading the output:

  * This counts ROW DATA leaving Postgres. Supabase bills real network bytes across Database,
    Auth, Realtime, Storage, Pooler and Log Drains. An earlier comparison was about twice
    this estimate, but that is not a conversion factor or proof of where the difference
    went. Use this to rank comparable workloads, never as the bill. Supabase's own
    project-filtered chart is the usage authority.
  * A window containing deploys measures the deploys. Each restart replays history and
    re-derives schemas, so a "busy" component may just be a busy afternoon at the keyboard.
    The report says how many worker restarts fell inside the window for exactly this reason.

    python tools/egress_report.py <before.json> <after.json>
    python tools/egress_report.py <before.json> --now      # snapshot now and compare
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from egress_window import _row_bytes, snapshot  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO / "src" / "ai_trader"

# What each module is FOR, in the Founder's terms rather than the code's. Anything not named
# here is reported under its own module name, which is a prompt to add it, not a failure.
PURPOSE = {
    "always_on.py": "Worker health and job history",
    "kraken_reconciliation.py": "Kraken: matching our records to the exchange",
    "canonical_trades.py": "Building each trade from its fills",
    "production_evidence.py": "Trade evidence for the app and the briefing",
    "multi_broker.py": "Broker polling (orders, positions, history)",
    "market_intelligence_platform.py": "Price candles and market data",
    "operational.py": "Coin universe and classifications",
    "database.py": "Table-shape lookups (compatibility layer)",
    "sprint6.py": "Learning loop",
    "api/__init__.py": "Serving the mobile app",
    "trade_reasons.py": "Why each trade opened and closed",
    "scoring_universe.py": "Choosing which coins to score",
    "self_assessment.py": "Daily self-assessment",
    "conversations.py": "Ask and Standup transcripts",
    "performance_attribution.py": "Profit and loss attribution",
}

_PLACEHOLDER = re.compile(r"\$\d+|%s|\?")
_WS = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """One line, one space between words, placeholders flattened.

    pg_stat_statements rewrites constants to $1 while the source carries ? or %s, and the
    source wraps SQL across lines. Both sides get the same treatment so they can be compared.
    """

    return _PLACEHOLDER.sub("@", _WS.sub(" ", str(text or ""))).strip().lower()


def _source_index() -> dict[str, str]:
    """Every source file, whitespace-normalised, ready to be searched."""

    index: dict[str, str] = {}
    for path in SOURCE_ROOT.rglob("*.py"):
        try:
            index[str(path.relative_to(SOURCE_ROOT)).replace("\\", "/")] = _normalise(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue
    return index


def _fingerprint(query: str) -> str:
    """A distinctive chunk of the query to look for in the source.

    The column list plus its table is what makes one read different from another; the WHERE
    clause is where the dialects diverge most, so it is deliberately left out.
    """

    normalised = _normalise(query)
    match = re.match(r"(select .*? from [a-z_0-9.\"]+)", normalised)
    fragment = match.group(1) if match else normalised[:90]
    return fragment[:160]


def _attribute(query: str, index: dict[str, str]) -> str:
    """Which module issues this read. Falls back honestly rather than guessing."""

    fingerprint = _fingerprint(query)
    hits = [name for name, body in index.items() if fingerprint and fingerprint in body]
    if not hits:
        # Try the table alone: enough to name the area even when the column list has drifted.
        table = re.search(r" from ([a-z_0-9]+)", _normalise(query))
        if table:
            needle = f" from {table.group(1)}"
            hits = [name for name, body in index.items() if needle in body]
    if not hits:
        return "unattributed"
    # A query written once and imported everywhere should be credited to where it is written,
    # so prefer the shortest path, which is the module that owns the table.
    return sorted(hits, key=lambda name: (len(name), name))[0]


def _postgres_only(query: str) -> bool:
    """Reads the database makes about itself, not about trading."""

    lowered = query.lower()
    return "information_schema" in lowered or "pg_" in lowered.split("from")[-1][:40]


def report(before_path: str, after_path: str) -> None:
    before = json.load(open(before_path, encoding="utf-8"))
    after = json.load(open(after_path, encoding="utf-8"))
    was = {statement["queryid"]: statement for statement in before["statements"]}
    widths = after.get("widths") or {}

    from datetime import datetime

    start = datetime.fromisoformat(before["taken_at"])
    end = datetime.fromisoformat(after["taken_at"])
    hours = max((end - start).total_seconds() / 3600, 0.01)
    per_day = 24 / hours

    index = _source_index()
    by_component: dict[str, dict] = defaultdict(lambda: {"bytes": 0, "calls": 0, "rows": 0, "queries": 0})

    for statement in after["statements"]:
        old = was.get(statement["queryid"])
        calls = statement["calls"] - (old["calls"] if old else 0)
        rows = statement["rows"] - (old["rows"] if old else 0)
        if calls <= 0 and rows <= 0:
            continue
        component = "database.py" if _postgres_only(statement["query"]) else _attribute(statement["query"], index)
        entry = by_component[component]
        entry["bytes"] += rows * _row_bytes(statement["query"], widths)
        entry["calls"] += calls
        entry["rows"] += rows
        entry["queries"] += 1

    total_bytes = sum(entry["bytes"] for entry in by_component.values()) or 1
    ordered = sorted(by_component.items(), key=lambda item: item[1]["bytes"], reverse=True)

    print(f"WINDOW   {before['taken_at'][:19]} -> {after['taken_at'][:19]}  ({hours:.1f} hours)")
    print(f"MEASURED {total_bytes / 1e6:,.1f} MB of row data  ->  {total_bytes / 1e6 * per_day:,.0f} MB/day at this rate")
    print("         Estimated SQL row bytes, not billed network traffic; no fixed multiplier.")
    print("         Compare the same project's Supabase service breakdown and time window.\n")

    header = f"  {'WHAT IS READING':<44}{'MB/day':>9}{'share':>8}{'reads/day':>11}{'rows/read':>11}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for component, entry in ordered:
        if entry["bytes"] / total_bytes < 0.004:
            continue
        purpose = PURPOSE.get(component, component)
        print("  %-44s%9.1f%7.1f%%%11s%11s" % (
            purpose[:44],
            entry["bytes"] / 1e6 * per_day,
            100 * entry["bytes"] / total_bytes,
            f"{entry['calls'] * per_day:,.0f}",
            f"{entry['rows'] / max(entry['calls'], 1):,.0f}",
        ))

    tail = sum(e["bytes"] for c, e in ordered if e["bytes"] / total_bytes < 0.004)
    if tail:
        print("  %-44s%9.1f%7.1f%%" % ("everything else, individually under 0.4%",
                                       tail / 1e6 * per_day, 100 * tail / total_bytes))


def _restart_count(before: str, after: str) -> None:
    """Worker restarts inside the window, because each one replays history and re-derives
    schemas -- so a window full of deploys measures the deploys."""

    url = os.environ.get("AUDIT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        return
    try:
        import psycopg

        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM SCHEDULED_JOB_RUNS
                   WHERE job_name = 'kraken-startup-reconciliation'
                     AND started_at >= %s AND started_at < %s""",
                # Postgres hands back "2026-09-07 08:47:19+00" with a space; started_at is
                # stored ISO with a T. Compared as text, 'T' sorts after ' ', so every row on
                # the day passed the lower bound and failed the upper one -- the count came
                # back 0 for a window that contained six restarts. Same class of bug as the
                # timestamp-format one this codebase already fixed in production_evidence.
                (before[:19].replace(" ", "T"), after[:19].replace(" ", "T")),
            )
            restarts = cur.fetchone()[0]
    except Exception:
        return
    note = " -- a clean measurement" if restarts <= 1 else " -- DEPLOY-HEAVY, read with caution"
    print(f"\n  Worker restarts inside this window: {restarts}{note}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    before_file = sys.argv[1]
    if sys.argv[2] == "--now":
        after_file = str(Path(before_file).with_name("egress_report_now.json"))
        snapshot(after_file)
        print()
    else:
        after_file = sys.argv[2]
    report(before_file, after_file)
    _restart_count(
        json.load(open(before_file, encoding="utf-8"))["taken_at"],
        json.load(open(after_file, encoding="utf-8"))["taken_at"],
    )
