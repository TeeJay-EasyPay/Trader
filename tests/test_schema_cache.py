"""Ask the database what a table looks like once, not six million times.

2026-09-03, Founder-reported: Supabase egress running at 1-1.9 GB per DAY on a free plan.

pg_stat_statements named the cause, and it was not trading data:

      611,816 calls   SELECT ... FROM information_schema.columns ...   700 seconds
    5,731,823 calls   SELECT pg_get_serial_sequence(...) ...           596 seconds

6.3 million round trips asking the database to describe its own structure. The
SQLite/Postgres compatibility layer re-derived a table's columns on every query and its
primary-key sequence on every INSERT. A schema does not change between two inserts a
millisecond apart, so nearly all of it was repeated work for an answer already known.

THE TWO WAYS THIS CACHE COULD BE WORSE THAN THE PROBLEM, both tested below:

  1. CACHING A MISS. Schema creation and use are interleaved throughout this codebase --
     initialize_*_schema is called lazily from dozens of places. If "this table does not
     exist" were cached, a table created seconds later would be permanently invisible, and
     every write to it would fail in a way no test would reproduce. Only successful lookups
     are stored.

  2. SHARING BETWEEN DATABASES. The cache is keyed by (database, table). The test suite runs
     many temporary databases in a single process, so a cache keyed on table name alone
     would hand one database's structure to another -- and would almost certainly pass CI,
     because every test database has the same schema.
"""

from __future__ import annotations

from ai_trader import database as db


def setup_function():
    db.clear_schema_cache()


def teardown_function():
    db.clear_schema_cache()


def test_the_caches_start_empty_and_can_be_cleared():
    db._TABLE_INFO_CACHE[("x", "y")] = [{"name": "col"}]
    db._SEQUENCE_NAME_CACHE[("x", "y")] = "seq"
    db.clear_schema_cache()
    assert db._TABLE_INFO_CACHE == {}
    assert db._SEQUENCE_NAME_CACHE == {}


def test_the_key_includes_the_database_not_just_the_table():
    """Two databases in one process must not read each other's structure. Keying on table
    name alone would pass every test -- they all share a schema -- and corrupt production."""
    db._TABLE_INFO_CACHE[("db-one", "trades")] = [{"name": "a"}]
    db._TABLE_INFO_CACHE[("db-two", "trades")] = [{"name": "b"}]
    assert db._TABLE_INFO_CACHE[("db-one", "trades")] != db._TABLE_INFO_CACHE[("db-two", "trades")]
    assert len(db._TABLE_INFO_CACHE) == 2


def test_a_missing_table_is_never_cached():
    """The dangerous case. Reading the source because reproducing it needs a live Postgres,
    and getting this wrong is invisible until a write fails in production."""
    source = (
        __import__("pathlib").Path(db.__file__).read_text(encoding="utf-8")
    )
    block = source[source.index("def _table_info"):]
    block = block[:block.index("\n    def ")]
    assert "if described:" in block, (
        "table structure must only be cached when the lookup actually found columns -- "
        "caching an empty result makes a later-created table permanently invisible"
    )


def test_the_sequence_lookup_is_cached_but_currval_is_not():
    """currval is SESSION state -- it answers 'what id did I just insert'. Caching that would
    return a stale id and silently mis-link records. Only the sequence NAME is stable."""
    source = (
        __import__("pathlib").Path(db.__file__).read_text(encoding="utf-8")
    )
    block = source[source.index("def _last_insert_id"):]
    block = block[:block.index("\n\ndef ")]
    assert "_SEQUENCE_NAME_CACHE.get(cache_key)" in block
    assert "_SEQUENCE_NAME_CACHE[cache_key] = sequence_name" in block
    # currval must still be executed every time, inside and outside the cached path.
    assert block.count("SELECT currval(") == 2, (
        "currval must run on every insert; only the sequence name may be remembered"
    )


def test_schema_creation_clears_the_cache():
    """After a migration the cached description is stale. ensure_schema_once must drop it."""
    from ai_trader.persistence import schema_once

    source = (
        __import__("pathlib").Path(schema_once.__file__).read_text(encoding="utf-8")
    )
    assert "_clear_schema_cache()" in source
    block = source[source.index("def ensure_schema_once"):]
    assert "_INITIALIZED.add(key)" in block
    after_init = block[block.index("_INITIALIZED.add(key)"):]
    assert "_clear_schema_cache()" in after_init, (
        "the cache must be cleared AFTER init_fn creates tables, not before"
    )


def test_clearing_the_cache_never_breaks_schema_creation():
    """A stale cache is a performance problem; a crashed migration is an outage. The helper
    swallows failures deliberately, so assert that it does."""
    from ai_trader.persistence import schema_once

    source = (
        __import__("pathlib").Path(schema_once.__file__).read_text(encoding="utf-8")
    )
    block = source[source.index("def _clear_schema_cache"):]
    block = block[:block.index("\n\ndef ")]
    assert "except Exception" in block and "pass" in block


def test_sqlite_is_untouched_by_any_of_this():
    """SQLite answers PRAGMA table_info locally with no round trip, so it has nothing to
    cache and must not be made to depend on one."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plain.db"
        conn = db.connect(path)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS THING (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO THING (name) VALUES ('a')")
            rows = conn.execute("SELECT name FROM THING").fetchall()
        finally:
            conn.close()
    assert len(rows) == 1
    assert db._TABLE_INFO_CACHE == {}, "the SQLite path must not populate the Postgres cache"
