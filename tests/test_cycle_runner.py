"""The on-demand cycle: it must narrate honestly, and never lie about what failed.

2026-08-29, Founder-directed. The whole point of this feature is that the Founder can press
one button and read what actually happened, so the failure mode that matters most is not a
crash -- it is a run log that says something untrue.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from ai_trader.cycle_runner import (
    COMPLETED,
    FAILED,
    cycle_status,
    run_cycle,
    start_cycle,
    start_cycle_in_background,
)
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.operational import initialize_operational_schema


class _Settings:
    def __init__(self, db_path: Path):
        self.db_path = db_path


class _Service:
    """Stands in for LocalApiService, recording which stages were asked to run."""

    def __init__(self, db_path: Path, *, fail: set[str] | None = None):
        self.settings = _Settings(db_path)
        self.called: list[str] = []
        self._fail = fail or set()

    def _stage(self, name: str):
        self.called.append(name)
        if name in self._fail:
            raise RuntimeError(f"{name} is unreachable")
        return {"status": "ok"}

    def refresh_crypto_universe(self):
        return self._stage("universe")

    def refresh_crypto_candle_history(self):
        return self._stage("candles")

    def run_crypto_analysis(self, limit=0):
        return self._stage("research")

    def auto_execute_recommendations_kraken(self):
        return self._stage("kraken-orders")

    def run_analysis(self, body):
        return self._stage("equity-research")

    def auto_execute_recommendations_alpaca(self):
        return self._stage("alpaca-orders")


def _fresh_db(tmp: str) -> Path:
    db_path = Path(tmp) / "cycle.db"
    initialize_operational_schema(db_path)
    # CRYPTO_RESEARCH_SCORES lives in the multi-broker schema, not the operational one.
    initialize_multi_broker_schema(db_path)
    return db_path


def test_every_step_is_recorded_in_order_with_a_summary_and_a_conclusion():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        service = _Service(db_path)
        cycle_id = start_cycle(db_path, scope="all", trigger_source="test")
        run_cycle(service, cycle_id, scope="all")

        status = cycle_status(db_path, cycle_id)
        assert status["status"] == COMPLETED
        steps = status["steps"]
        assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1)), "steps must be ordered"
        assert len(steps) == 7, "five crypto stages plus two equity stages"
        for step in steps:
            assert step["label"], "every step needs a Founder-readable label"
            assert step["summary"], f"step {step['seq']} produced no one-line summary"
            assert step["completed_at"], "a finished step must record when it finished"
        assert status["conclusion"], "the Founder asked for a conclusion at the end"


def test_crypto_only_skips_the_equity_stages():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        service = _Service(db_path)
        cycle_id = start_cycle(db_path, scope="crypto")
        run_cycle(service, cycle_id, scope="crypto")
        assert "equity-research" not in service.called
        assert "alpaca-orders" not in service.called
        assert cycle_status(db_path, cycle_id)["status"] == COMPLETED


def test_one_broken_stage_does_not_stop_the_others():
    """A dead Alpaca must not prevent crypto from trading, or vice versa."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        service = _Service(db_path, fail={"equity-research"})
        cycle_id = start_cycle(db_path)
        run_cycle(service, cycle_id, scope="all")

        status = cycle_status(db_path, cycle_id)
        assert status["status"] == FAILED
        failed = [s for s in status["steps"] if s["status"] == FAILED]
        assert len(failed) == 1, "only the genuinely broken stage should be marked failed"
        assert "Research shares" in failed[0]["label"]
        # The stages after the failure still ran.
        assert "alpaca-orders" in service.called
        assert "failed" in (status["conclusion"] or "").lower()


def test_a_broken_summary_never_reports_a_working_stage_as_failed():
    """The exact bug found while building this, against a database missing a table.

    Four stages that had genuinely completed all displayed as failed, because the summary
    query and the stage itself were caught by one try block. Telling the Founder his cycle
    broke when it did not is worse than showing no summary at all.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "bare.db"
        # Deliberately NOT initialising the operational schema: every summary query below
        # will fail against the missing tables, exactly as it did when this was found.
        from ai_trader.cycle_runner import initialize_cycle_schema

        initialize_cycle_schema(db_path)
        service = _Service(db_path)
        cycle_id = start_cycle(db_path, scope="crypto")
        run_cycle(service, cycle_id, scope="crypto")

        status = cycle_status(db_path, cycle_id)
        failed = [s for s in status["steps"] if s["status"] == FAILED]
        assert failed == [], (
            "stages whose work succeeded must not be reported as failed just because their "
            f"summary could not be written: {[s['label'] for s in failed]}"
        )
        assert status["status"] == COMPLETED


def test_a_second_cycle_is_refused_while_one_is_running():
    """Two overlapping runs would corrupt every 'what changed during this stage' summary."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)

        class _Slow(_Service):
            def run_crypto_analysis(self, limit=0):
                time.sleep(1.5)
                return self._stage("research")

        service = _Slow(db_path)
        first = start_cycle_in_background(service, scope="crypto")
        assert first["status"] == "started"
        time.sleep(0.3)
        second = start_cycle_in_background(service, scope="crypto")
        assert second["status"] == "already_running"
        assert second["cycle_id"] == first["cycle_id"], "must point at the run already going"
        for _ in range(80):
            if cycle_status(db_path, first["cycle_id"])["status"] != "running":
                break
            time.sleep(0.1)


def test_a_step_reporting_on_an_earlier_steps_work_uses_the_whole_cycle_window():
    """Found on the very first live production run, and it made the log self-contradictory.

    The scores are written by step 2 (the price and liquidity refresh) and only READ by step
    3 (research). Measuring step 3's own window found nothing, so the run log printed:

        [OK] 2. Get fresh prices...  Fresh prices... read for 20 coins.
        [OK] 3. Research and score every coin   No coins were scored this cycle.

    Two adjacent lines flatly contradicting each other, in the one feature whose entire
    purpose is to say truthfully what happened.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)

        written: dict[str, bool] = {}

        class _WritesScoresInStepTwo(_Service):
            def refresh_crypto_candle_history(self):
                result = self._stage("candles")
                # Write score rows the way the real refresh does: during step 2.
                from contextlib import closing as _closing

                from ai_trader.database import connect as _connect
                from ai_trader.models import utc_now_iso as _now

                with _closing(_connect(db_path)) as conn:
                    with conn:
                        for symbol, score in (("LTC", 0.81), ("SOL", 0.64), ("ETH", 0.55)):
                            conn.execute(
                                """INSERT INTO CRYPTO_RESEARCH_SCORES
                                       (created_at, symbol, overall_due_diligence_score,
                                        reasoning_json, source)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (_now(), symbol, score, "{}", "test"),
                            )
                written["yes"] = True
                return result

        service = _WritesScoresInStepTwo(db_path)
        cycle_id = start_cycle(db_path, scope="crypto")
        run_cycle(service, cycle_id, scope="crypto")

        assert written.get("yes"), "the fake refresh should have written score rows"
        steps = {s["seq"]: s for s in cycle_status(db_path, cycle_id)["steps"]}
        research = steps[3]["summary"] or ""
        assert "No coins were scored" not in research, (
            f"research reported nothing while step 2 wrote 3 scores: {research!r}"
        )
        assert "3 coins scored" in research, research
        # And it must name the best one, which is the number the Founder actually acts on.
        assert "LTC" in research and "0.81" in research, research


def test_status_before_any_run_is_reported_plainly():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        status = cycle_status(db_path)
        assert status["status"] == "none"
        assert status["steps"] == []
        assert status["message"]
