"""A conversation participant must be able to CHECK a claim, and must not be able to change one.

2026-09-07, Founder-directed. He asked how Claude could contribute to a conversation about this
system without repo access -- "pulling one file here or there is ok but in conversations many
files may be checked. like you do when you check information to be able to provide info and
reasoning for solutions."

The evidence for why it matters is the day before. Asked what was wrong, the trading AI raised
four defects and THREE were artefacts of the census handed to it rather than real faults. It
hedged them correctly ("I cannot tell whether those inputs are absent from the system or simply
absent from the census") and was right to. A participant that cannot look things up produces
confident, specific, wrong findings.

These tests are mostly about the second half of the sentence: it must not be able to WRITE.
Editing and deploying stay with Claude Code, where a change passes tests, a production check
and a deploy confirmation before anyone believes it.
"""

import shutil
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.database import connect
from ai_trader.evidence_tools import (
    READABLE_DIRECTORIES,
    TOOL_SPECS,
    query_database,
    read_source_file,
    run_tool,
    search_source,
)


class ReadingIsConfinedTests(unittest.TestCase):
    """The allow-list is resolved BEFORE the check, so dot segments cannot walk out of it."""

    def test_paths_that_escape_the_allow_list_are_refused(self):
        for escape in (
            "../.env",
            "src/../../.env",
            "/etc/passwd",
            "../../Dockerfile",
            "src/ai_trader/../../../.env",
            "../.git/config",
        ):
            self.assertEqual(read_source_file(escape)["status"], "refused", escape)

    def test_a_real_source_file_reads(self):
        result = read_source_file("src/ai_trader/evidence_tools.py")
        self.assertEqual(result["status"], "ok")
        self.assertIn("READABLE_DIRECTORIES", result["content"])

    def test_a_missing_file_is_not_found_rather_than_refused(self):
        """The two are different answers: one says 'you may not', the other 'it isn't there'."""
        self.assertEqual(read_source_file("src/ai_trader/no_such_file.py")["status"], "not_found")

    def test_the_allow_list_holds_only_code_and_docs(self):
        self.assertEqual(set(READABLE_DIRECTORIES), {"src", "governance", "knowledge"})


class SearchTests(unittest.TestCase):
    def test_search_returns_the_line_not_just_the_filename(self):
        """The answer is usually visible in the line -- returning only filenames would cost a
        second round trip to find out what the match said."""
        result = search_source("READABLE_DIRECTORIES")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["hits"])
        first = result["hits"][0]
        self.assertIn("path", first)
        self.assertIn("line", first)
        self.assertIn("READABLE_DIRECTORIES", first["text"])

    def test_a_broken_expression_is_reported_not_raised(self):
        self.assertEqual(search_source("([unclosed")["status"], "bad_pattern")

    def test_an_empty_pattern_is_refused(self):
        self.assertEqual(search_source("   ")["status"], "refused")


class WritingIsImpossibleTests(unittest.TestCase):
    """Two independent guards, and this exercises the parser half. The connection is also set
    read-only, so neither is the only thing standing between a conversation and the trading
    record."""

    def test_every_write_verb_is_refused(self):
        for statement in (
            "DROP TABLE logical_trades",
            "DELETE FROM logical_trades WHERE 1=1",
            "UPDATE logical_trades SET state = 'x'",
            "INSERT INTO logical_trades (a) VALUES (1)",
            "TRUNCATE performance_attribution",
            "ALTER TABLE logical_trades ADD COLUMN x TEXT",
            "GRANT ALL ON logical_trades TO PUBLIC",
        ):
            self.assertEqual(query_database(statement)["status"], "refused", statement)

    def test_a_write_smuggled_after_a_semicolon_is_refused(self):
        """The whole reason semicolons are rejected outright rather than split on."""
        self.assertEqual(
            query_database("SELECT 1; DELETE FROM logical_trades")["status"], "refused"
        )

    def test_a_select_reads_and_names_its_columns(self):
        """Column names come from the ROW, not cursor.description -- the compatibility layer's
        cursor does not expose description, and the first version silently collapsed every row
        to its first value. A three-column GROUP BY came back as one string with the numbers
        gone: not an error, just a quietly wrong answer, which is the worst thing a
        fact-checking tool can return."""
        tmp = tempfile.mkdtemp()
        try:
            db_path = Path(tmp) / "audit.sqlite3"
            with closing(connect(db_path)) as conn:
                with conn:
                    conn.execute("CREATE TABLE t (broker TEXT, trades INTEGER, net REAL)")
                    conn.execute("INSERT INTO t VALUES ('kraken', 27, -5.41)")
            result = query_database("SELECT broker, trades, net FROM t", db_path=db_path)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["columns"], ["broker", "trades", "net"])
            self.assertEqual(result["rows"][0]["broker"], "kraken")
            self.assertEqual(result["rows"][0]["trades"], 27)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DispatchTests(unittest.TestCase):
    def test_an_invented_tool_is_refused_rather_than_raising(self):
        """A model that invents a tool should be told plainly and be able to carry on, not end
        the conversation with a stack trace."""
        self.assertEqual(run_tool("delete_everything", {})["status"], "refused")

    def test_every_advertised_tool_can_actually_be_called(self):
        """A description that names a tool the dispatcher does not have is a promise the
        conversation cannot keep."""
        for spec in TOOL_SPECS:
            self.assertNotEqual(
                run_tool(spec["name"], {}).get("message", ""),
                f"There is no tool called '{spec['name']}'.",
            )

    def test_no_advertised_tool_offers_to_change_anything(self):
        """Matched on ACTIONS the model might attempt, not on bare words -- the first version
        of this test failed on the phrase "deployed source code", which contains "deploy" and
        promises nothing."""
        blob = " ".join(spec["description"].lower() for spec in TOOL_SPECS)
        for offer in ("edit a file", "write a file", "modify the code", "deploy the",
                      "change the code", "update the database"):
            self.assertNotIn(offer, blob, f"a read-only tool must not offer to '{offer}'")
        # And it must say plainly that it will not write.
        self.assertIn("writes are refused", blob)


class SourceRootTests(unittest.TestCase):
    """The root must be a directory that actually holds the source.

    2026-09-07, found in production and only because Claude said so plainly: "no hits, and it
    reported 0 files searched." Every code lookup had been failing on the deployed container
    since the day the tools shipped, while passing on my machine.

    The Dockerfile runs `pip install .`, so at runtime the package lives in site-packages and
    walking up from __file__ lands on /usr/local/lib/python3.12 -- no src/, no governance/, no
    knowledge/. The same walk on a source checkout lands on the repository root and works
    perfectly, which is precisely why verifying it locally proved nothing.
    """

    def test_the_root_contains_the_directories_it_promises_to_read(self):
        from ai_trader.evidence_tools import READABLE_DIRECTORIES, app_root

        root = app_root()
        present = [name for name in READABLE_DIRECTORIES if (root / name).is_dir()]
        self.assertTrue(present, f"app_root() returned {root}, which holds no readable source")

    def test_an_explicit_override_still_wins(self):
        import os
        import tempfile

        from ai_trader.evidence_tools import app_root

        with tempfile.TemporaryDirectory() as tmp:
            saved = os.environ.get("AI_TRADER_APP_ROOT")
            os.environ["AI_TRADER_APP_ROOT"] = tmp
            try:
                self.assertEqual(app_root(), Path(tmp).resolve())
            finally:
                if saved is None:
                    os.environ.pop("AI_TRADER_APP_ROOT", None)
                else:
                    os.environ["AI_TRADER_APP_ROOT"] = saved

    def test_the_container_is_told_where_the_source_is(self):
        """Belt and braces: app_root() detects this itself now, but a deployment that states
        it outright cannot be broken by a future change to the path arithmetic."""
        dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("AI_TRADER_APP_ROOT=/app", dockerfile)
        self.assertIn("COPY src ./src", dockerfile)

    def test_searching_the_source_finds_this_projects_own_code(self):
        """The end-to-end check the production failure would have tripped: a pattern that must
        exist in this repository has to come back with hits."""
        from ai_trader.evidence_tools import run_tool

        outcome = run_tool("search_source", {"pattern": "MAX_SCORING_SYMBOLS"})
        self.assertEqual(outcome.get("status"), "ok")
        # files_searched is the tell. In production it came back 0 with an "ok" status, so a
        # test that only checked the status would have passed against the broken deployment.
        self.assertGreater(outcome.get("files_searched", 0), 10,
                           f"searched almost nothing: {str(outcome)[:160]}")
        self.assertTrue(outcome.get("hits"), f"no hits at all: {str(outcome)[:200]}")


if __name__ == "__main__":
    unittest.main()
