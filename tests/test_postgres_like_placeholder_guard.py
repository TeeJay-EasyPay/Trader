"""A literal % inside SQL breaks psycopg, and a bare `except` turns that into silence.

2026-09-04. Two live queries carried `LIKE '20%'` / `LIKE 'Top 20%'`. On Postgres psycopg
parses that % as the start of a bind placeholder and raises ProgrammingError before the
query runs -- with or without parameters bound. Both call sites wrapped the call in a bare
`except`, so the crash became "no rows found", which is indistinguishable from a genuinely
empty result. `symbol_track_record` therefore reported zero closed trades for every coin,
on every call, for as long as the app has run on Postgres.

Both were rewritten with SUBSTR, which is valid on SQLite and Postgres alike. This test
stops a third one appearing. SQLite-only maintenance paths are exempt: they never reach
psycopg, and `sqlite_%` is the documented way to filter internal tables.
"""

import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ai_trader"

# These modules only ever run against SQLite (schema migration / local DB inspection).
SQLITE_ONLY = {"database_migration.py", "db_browser.py"}

# A quoted LIKE/ILIKE pattern containing a literal % — the shape that breaks psycopg.
PATTERN = re.compile(r"(?i)\b(?:NOT\s+)?I?LIKE\s+'[^']*%[^']*'")


class PostgresLikePlaceholderGuard(unittest.TestCase):
    def test_no_literal_percent_in_like_patterns(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            if path.name in SQLITE_ONLY:
                continue
            text = path.read_text(encoding="utf-8")
            for match in PATTERN.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(SRC.parent.parent)}:{line}: {match.group(0)}")
        self.assertEqual(
            offenders, [],
            "A literal % inside a LIKE pattern raises psycopg ProgrammingError on Postgres.\n"
            "Use SUBSTR(col, 1, n) = '...' instead, which works on both backends.\n"
            "Offending sites:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
