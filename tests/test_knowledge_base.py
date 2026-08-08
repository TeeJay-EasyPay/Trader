import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.database import connect
from ai_trader.knowledge_base import (
    KNOWLEDGE_DIR,
    load_knowledge_index,
    record_knowledge_gap,
    relevant_excerpts,
)
from ai_trader.sprint6 import initialize_sprint6_schema


def _write(tmp: Path, name: str, *, title: str, topics: list[str], applies_to: list[str], sectors: list[str], body: str) -> None:
    frontmatter = (
        "---\n"
        f'title: "{title}"\n'
        f"topics: [{', '.join(topics)}]\n"
        f"applies_to: [{', '.join(applies_to)}]\n"
        f"sectors: [{', '.join(sectors)}]\n"
        "---\n\n"
        f"{body}\n"
    )
    (tmp / name).write_text(frontmatter, encoding="utf-8")


class KnowledgeBaseIndexTests(unittest.TestCase):
    def test_parses_frontmatter_and_body_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _write(
                tmp,
                "sizing.md",
                title="Position Sizing Discipline",
                topics=["position_sizing", "risk_management"],
                applies_to=["stock", "crypto"],
                sectors=[],
                body="Position size is the single lever that matters most.",
            )
            index = load_knowledge_index(tmp)
        self.assertEqual(len(index), 1)
        entry = index[0]
        self.assertEqual(entry["title"], "Position Sizing Discipline")
        self.assertEqual(entry["topics"], ["position_sizing", "risk_management"])
        self.assertEqual(entry["applies_to"], ["stock", "crypto"])
        self.assertEqual(entry["sectors"], [])
        self.assertIn("Position size is the single lever", entry["excerpt"])

    def test_skips_malformed_file_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            (tmp / "broken.md").write_text("no frontmatter here at all", encoding="utf-8")
            _write(
                tmp,
                "good.md",
                title="Good File",
                topics=["risk_management"],
                applies_to=["stock"],
                sectors=[],
                body="Fine.",
            )
            index = load_knowledge_index(tmp)
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["title"], "Good File")

    def test_missing_directory_returns_empty_list(self):
        index = load_knowledge_index(Path("this/does/not/exist"))
        self.assertEqual(index, [])


class RelevantExcerptsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        _write(
            tmp,
            "sizing.md",
            title="Position Sizing",
            topics=["position_sizing", "risk_management"],
            applies_to=["stock", "crypto"],
            sectors=[],
            body="Broadly applicable sizing content.",
        )
        _write(
            tmp,
            "airlines.md",
            title="Sector Notes: Airlines",
            topics=["sector_analysis"],
            applies_to=["stock"],
            sectors=["airlines"],
            body="Fuel costs and load factor drive airline economics.",
        )
        _write(
            tmp,
            "crypto_l1.md",
            title="Sector Notes: Crypto L1",
            topics=["sector_analysis", "crypto"],
            applies_to=["crypto"],
            sectors=["crypto_l1"],
            body="Tokenomics and unlock schedules matter for L1 tokens.",
        )
        self.index = load_knowledge_index(tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_filters_by_asset_type(self):
        results = relevant_excerpts(asset_type="crypto", index=self.index)
        titles = {entry["title"] for entry in results}
        self.assertIn("Position Sizing", titles)
        self.assertIn("Sector Notes: Crypto L1", titles)
        self.assertNotIn("Sector Notes: Airlines", titles)

    def test_sector_match_is_ranked_above_non_matching_sector_file(self):
        results = relevant_excerpts(asset_type="stock", sector="airlines", index=self.index)
        # Both "Position Sizing" (broad, no sector) and "Sector Notes: Airlines"
        # (matches the queried sector) are eligible for asset_type=stock; the
        # sector-matching file must be ranked first.
        self.assertEqual(results[0]["title"], "Sector Notes: Airlines")

    def test_respects_limit(self):
        results = relevant_excerpts(asset_type="crypto", limit=1, index=self.index)
        self.assertEqual(len(results), 1)

    def test_asset_type_with_no_matches_returns_empty_list(self):
        results = relevant_excerpts(asset_type="forex", index=self.index)
        self.assertEqual(results, [])

    def test_topic_overlap_boosts_ranking(self):
        results = relevant_excerpts(asset_type="crypto", topics=["crypto"], index=self.index)
        self.assertEqual(results[0]["title"], "Sector Notes: Crypto L1")


class KnowledgeGapLoggingTests(unittest.TestCase):
    def test_record_knowledge_gap_writes_an_operational_event(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            db_path = Path(tmp_str) / "audit.sqlite3"
            initialize_sprint6_schema(db_path)
            record_knowledge_gap(db_path, asset_type="forex", sector=None, topics_searched=["carry_trade"])
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT component, event_type, summary FROM OPERATIONAL_EVENTS ORDER BY event_id DESC LIMIT 1"
                ).fetchone()
        self.assertEqual(row[0], "knowledge_base")
        self.assertEqual(row[1], "knowledge_gap")
        self.assertIn("forex", row[2])

    def test_no_gap_logged_when_relevant_excerpts_finds_a_match(self):
        # relevant_excerpts itself never calls record_knowledge_gap -- that is
        # the caller's responsibility once it observes an empty result. This
        # test documents that contract: a match means the caller has nothing
        # to log.
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _write(
                tmp,
                "sizing.md",
                title="Position Sizing",
                topics=["position_sizing"],
                applies_to=["stock"],
                sectors=[],
                body="Content.",
            )
            index = load_knowledge_index(tmp)
        results = relevant_excerpts(asset_type="stock", index=index)
        self.assertTrue(len(results) > 0)


class RealKnowledgeDirectorySanityCheckTests(unittest.TestCase):
    def test_real_committed_knowledge_folder_parses_and_has_at_least_seven_entries(self):
        index = load_knowledge_index(KNOWLEDGE_DIR)
        self.assertGreaterEqual(len(index), 7)
        for entry in index:
            self.assertTrue(entry["title"])
            self.assertTrue(entry["applies_to"], msg=f"{entry['title']} has no applies_to tags")
            self.assertTrue(entry["excerpt"], msg=f"{entry['title']} has an empty body")


if __name__ == "__main__":
    unittest.main()
