"""Read-only tools that let a conversation participant CHECK a claim instead of guessing.

2026-09-07, Founder-directed. He asked how Claude could contribute usefully to a conversation
about this system without access to the repository:

    "how would Claude be able to positively contribute to the conversation if it doesn't have
     access to the repo... pulling one file here or there is ok but in conversations many files
     may be checked. like you do when you check information to be able to provide info and
     reasoning for solutions."

He is right, and the evidence is the day before. On 2026-09-06 the trading AI was asked what
was wrong and raised four defects. THREE were artefacts of the census it had been handed rather
than faults in the system -- it reported no Alpaca feeds (22,199 rows existed), no broker
attribution on P&L (the column existed and was populated), and possible use of stale crypto
prices (nothing reads that table). It hedged all three correctly -- "I cannot tell whether
those inputs are absent from the system or simply absent from the census" -- and was right to.

A participant that cannot look things up produces confident, specific, wrong findings. These
three tools are the difference between an opinion and a check, and they are deliberately the
same three Claude Code used all that day: search the code, read a file, query the database.

READ ONLY, BY CONSTRUCTION AND NOT BY INSTRUCTION. Every function here refuses to write:

  * the code tools serve a fixed allow-list of directories under the app root and reject any
    path that escapes it after resolution, so a crafted "../../etc/passwd" cannot work
  * the query tool opens a read-only connection AND rejects anything that is not a single
    SELECT, so neither layer alone is load-bearing

The dangerous half -- editing code, deploying -- deliberately does not live here. That stays
with Claude Code, where a change passes tests, a production check and a deploy confirmation
before it is believed.
"""

from __future__ import annotations

import os
import re
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect, row_values

# Directories a participant may read. Everything else on the container -- the environment, the
# data volume, pip's site-packages, anything holding a credential -- is outside this list and
# stays that way. It is an allow-list rather than a deny-list on purpose: a deny-list is a
# guess about what is dangerous, and the guess only has to be wrong once.
READABLE_DIRECTORIES: tuple[str, ...] = ("src", "governance", "knowledge")

# One file cannot flood a conversation's context. api/__init__.py alone is thousands of lines,
# and reading it whole would crowd out everything else being discussed.
MAX_FILE_BYTES = 60_000
MAX_SEARCH_HITS = 60
MAX_QUERY_ROWS = 200


def app_root() -> Path:
    """Where the code actually is.

    /app in the deployed container (see the Dockerfile's WORKDIR), the repository root when
    running locally, and overridable so a test can point it somewhere harmless.
    """

    configured = os.getenv("AI_TRADER_APP_ROOT")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    # src/ai_trader/evidence_tools.py -> the directory holding src/
    return here.parents[2]


def _resolved_within_allowed(relative_path: str) -> Path | None:
    """The absolute path, or None if it escapes the allow-list.

    Resolved BEFORE the check, not after: "src/../../../etc/passwd" only reveals itself as an
    escape once symlinks and dot segments are collapsed. Comparing the raw string would pass it.
    """

    root = app_root()
    try:
        candidate = (root / str(relative_path or "").strip()).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for allowed in READABLE_DIRECTORIES:
        base = (root / allowed).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        return candidate
    return None


def read_source_file(relative_path: str) -> dict[str, Any]:
    """One file, as deployed.

    Truncates rather than refusing: half of a long file usually answers the question, and
    "too big, ask differently" wastes a conversational turn. The reply says it was truncated
    so nothing is quietly presented as complete.
    """

    path = _resolved_within_allowed(relative_path)
    if path is None:
        return {
            "status": "refused",
            "path": relative_path,
            "message": (
                "Only " + ", ".join(READABLE_DIRECTORIES) + " may be read. This tool cannot "
                "reach the rest of the filesystem, and cannot write anywhere."
            ),
        }
    if not path.is_file():
        return {"status": "not_found", "path": relative_path}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "unreadable", "path": relative_path, "message": str(exc)}
    truncated = len(text.encode("utf-8")) > MAX_FILE_BYTES
    if truncated:
        text = text.encode("utf-8")[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")
    return {
        "status": "ok",
        "path": relative_path,
        "truncated": truncated,
        "lines": text.count("\n") + 1,
        "content": text,
    }


def search_source(pattern: str, *, max_hits: int = MAX_SEARCH_HITS) -> dict[str, Any]:
    """Every line matching a regular expression, with its file and line number.

    This is the tool that answers "does anything actually read this table?" -- the question
    that on 2026-09-06 separated a real defect from three imagined ones. Returning the line
    itself rather than only the filename matters: the answer is usually visible in the line.
    """

    expression = str(pattern or "").strip()
    if not expression:
        return {"status": "refused", "message": "A search needs a pattern."}
    try:
        matcher = re.compile(expression, re.IGNORECASE)
    except re.error as exc:
        return {"status": "bad_pattern", "pattern": expression, "message": str(exc)}

    root = app_root()
    hits: list[dict[str, Any]] = []
    searched = 0
    for directory in READABLE_DIRECTORIES:
        base = (root / directory)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".json", ".yaml", ".yml", ".txt"}:
                continue
            searched += 1
            try:
                for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if matcher.search(line):
                        hits.append({
                            "path": str(path.relative_to(root)).replace("\\", "/"),
                            "line": number,
                            "text": line.strip()[:300],
                        })
                        if len(hits) >= max(1, int(max_hits)):
                            return {"status": "ok", "pattern": expression, "files_searched": searched,
                                    "hits": hits, "truncated": True}
            except OSError:
                continue
    return {"status": "ok", "pattern": expression, "files_searched": searched,
            "hits": hits, "truncated": False}


# A single SELECT (or a CTE that ends in one) and nothing else. Semicolons are rejected outright
# rather than split on, because "SELECT 1; DROP TABLE x" is the entire reason this check exists
# and permitting the separator invites an argument about how well it is parsed.
_SELECT_ONLY = re.compile(r"^\s*(?:WITH\b.+?)?\bSELECT\b", re.IGNORECASE | re.DOTALL)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|CALL|DO)\b",
    re.IGNORECASE,
)


def query_database(sql: str, *, db_path: Path | None = None, max_rows: int = MAX_QUERY_ROWS) -> dict[str, Any]:
    """One read-only SELECT against the live database.

    TWO INDEPENDENT GUARDS, deliberately. The statement must look like a lone SELECT, and the
    connection is set read-only so the database itself refuses a write. Either would probably
    do; neither is trusted to be the only thing standing between a conversation and the
    production trading record.
    """

    statement = str(sql or "").strip().rstrip(";").strip()
    if not statement:
        return {"status": "refused", "message": "A query needs SQL."}
    if ";" in statement:
        return {"status": "refused", "message": "One statement at a time; semicolons are not accepted."}
    if not _SELECT_ONLY.match(statement):
        return {"status": "refused", "message": "Only SELECT (or WITH ... SELECT) queries are allowed."}
    forbidden = _FORBIDDEN.search(statement)
    if forbidden:
        return {"status": "refused", "message": f"'{forbidden.group(0)}' is not allowed -- this tool only reads."}

    from .config import load_settings

    target = db_path or load_settings().db_path
    try:
        with closing(connect(target)) as conn:
            # Belt to the parser's braces: even a statement that slipped past the checks above
            # cannot write through a read-only connection.
            try:
                conn.read_only = True
            except Exception:  # noqa: BLE001 - SQLite has no such attribute; the parser stands alone there
                pass
            # Ask SQLite for named rows. Without this a bare sqlite3 connection yields plain
            # tuples, the loop below falls through to positional naming, and the tool reports
            # "column_1, column_2, column_3" for a query the caller wrote as broker, trades,
            # net. Production is Postgres and returns dicts, so this only ever showed up
            # locally -- which is precisely the kind of gap that ships.
            try:
                import sqlite3 as _sqlite3

                conn.row_factory = _sqlite3.Row
            except Exception:  # noqa: BLE001 - Postgres rows already carry their names
                pass
            cursor = conn.execute(statement + " LIMIT " + str(max(1, int(max_rows))))
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001 - a failed query is an ANSWER, not a crash
        return {"status": "failed", "message": f"{type(exc).__name__}: {exc}"}

    # Column names come from the ROW, not from cursor.description. The compatibility layer's
    # PostgresCursor does not expose description, so the first version silently produced
    # `columns: []` and collapsed every row to its first value -- a three-column GROUP BY came
    # back as {"value": "kraken"}, with the counts and the P&L simply gone. Not an error, just
    # a quietly wrong answer, which is the worst thing a fact-checking tool can return.
    out: list[dict[str, Any]] = []
    columns: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            if not columns:
                columns = list(row.keys())
            out.append(dict(row))
            continue
        keys = getattr(row, "keys", None)
        if callable(keys):  # sqlite3.Row
            names = list(keys())
            if not columns:
                columns = names
            out.append({name: row[name] for name in names})
            continue
        values = row_values(row)
        if not columns:
            columns = [f"column_{index + 1}" for index in range(len(values))]
        out.append(dict(zip(columns, values)))
    return {"status": "ok", "row_count": len(out), "columns": columns, "rows": out}


# The tool definitions, in the shape both the Claude Messages API and OpenAI tool calling
# expect. Held here beside the implementations so a description can never drift from what the
# function actually does.
TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "search_source",
        "description": (
            "Search the deployed source code for a regular expression and return matching lines "
            "with their file and line number. Use this to CHECK a claim about how the system "
            "behaves -- for example whether anything actually reads a given table -- rather than "
            "reasoning about what the code probably does."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string", "description": "Regular expression to search for."}},
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_source_file",
        "description": (
            "Read one source file as deployed. Paths are relative to the app root and only "
            "src/, governance/ and knowledge/ are readable. Long files are truncated and say so."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"relative_path": {"type": "string", "description": "e.g. src/ai_trader/agent.py"}},
            "required": ["relative_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_database",
        "description": (
            "Run ONE read-only SELECT against the live trading database and return up to 200 "
            "rows. Use it to check real numbers -- how many trades closed, how fresh a feed is, "
            "why candidates were rejected -- instead of estimating them. Writes are refused."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT statement."}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
)


def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch by name, refusing anything not on the list.

    An unknown name returns a refusal rather than raising: a model that invents a tool should
    be told plainly that it does not exist and be able to carry on, not end the conversation.
    """

    args = arguments or {}
    if name == "search_source":
        return search_source(str(args.get("pattern") or ""))
    if name == "read_source_file":
        return read_source_file(str(args.get("relative_path") or ""))
    if name == "query_database":
        return query_database(str(args.get("sql") or ""))
    return {"status": "refused", "message": f"There is no tool called '{name}'."}
