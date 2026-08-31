"""The on-demand cycle: it must narrate honestly, and never lie about what failed.

2026-08-29, Founder-directed. The whole point of this feature is that the Founder can press
one button and read what actually happened, so the failure mode that matters most is not a
crash -- it is a run log that says something untrue.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from ai_trader.cycle_runner import (
    COMPLETED,
    brokers_for_scope,
    FAILED,
    cycle_status,
    run_cycle,
    start_cycle,
    start_cycle_in_background,
)
from ai_trader.audit import AuditDatabase
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

    def reconcile_open_positions(self, *, broker="kraken"):
        self._stage("reconcile")
        return {"status": "ok", "checked": 0, "closed": [], "kept": []}

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
    # CRYPTO_RESEARCH_SCORES lives in the multi-broker schema, not the operational one,
    # and EXECUTION_EVENTS (where the pre-proposal drop reasons are recorded) lives in the
    # audit schema. Three owners, which is itself why "nothing was recorded" was so easy to
    # conclude wrongly when looking in only one of them.
    initialize_multi_broker_schema(db_path)
    AuditDatabase(db_path, Path(str(db_path) + ".log")).initialize()
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
        assert len(steps) == 8, "the position check, five crypto stages, two equity stages"
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
        research = steps[4]["summary"] or ""
        assert "No coins were scored" not in research, (
            f"research reported nothing while step 2 wrote 3 scores: {research!r}"
        )
        assert "3 coins scored" in research, research
        # And it must name the best one, which is the number the Founder actually acts on.
        assert "LTC" in research and "0.81" in research, research


def test_a_cycle_killed_by_a_restart_does_not_disable_the_button_forever():
    """Found on the emulator: a deploy restarted the service mid-cycle.

    The background thread died with the process, but the database row still said "running".
    The app disables the Run button while a cycle is in flight, so the Founder was left with
    a cycle running forever and a button that would never work again. A feature whose entire
    point is a button that works cannot have a state where the button stops working.
    """
    from contextlib import closing as _closing
    from datetime import datetime, timedelta, timezone

    from ai_trader.cycle_runner import STALE_AFTER_MINUTES
    from ai_trader.database import connect as _connect

    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        orphan = start_cycle(db_path, scope="all")
        long_ago = (
            datetime.now(timezone.utc) - timedelta(minutes=STALE_AFTER_MINUTES + 5)
        ).isoformat()
        with _closing(_connect(db_path)) as conn:
            with conn:
                conn.execute("UPDATE CYCLE_RUNS SET started_at = ? WHERE cycle_id = ?",
                             (long_ago, orphan))
                conn.execute(
                    """INSERT INTO CYCLE_RUN_STEPS (cycle_id, seq, label, status, started_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (orphan, 1, "Refresh the list of coins we are allowed to trade",
                     "running", long_ago),
                )

        status = cycle_status(db_path, orphan)
        assert status["status"] == FAILED, "an abandoned cycle must not stay 'running'"
        assert "interrupted" in (status["conclusion"] or "").lower()
        assert all(s["status"] != "running" for s in status["steps"]), (
            "a step left mid-flight by a dead process must be closed out too"
        )

        # And crucially, a new cycle can now be started.
        service = _Service(db_path)
        result = start_cycle_in_background(service, scope="crypto")
        assert result["status"] == "started", result
        for _ in range(80):
            if cycle_status(db_path, result["cycle_id"])["status"] != "running":
                break
            time.sleep(0.1)


def test_a_recent_running_cycle_is_never_reaped():
    """The reaper must not kill a cycle that is simply still working."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        live = start_cycle(db_path, scope="all")
        assert cycle_status(db_path, live)["status"] == "running"


def test_the_whole_plan_exists_from_the_first_moment():
    """Seen on the emulator: the header read "step 1 of 1" while five steps were coming.

    Steps used to be created as each one started, so the total counted only what had already
    begun. That told the Founder the cycle was on its LAST step when it was on its first. A
    progress indicator that overstates progress is worse than no indicator at all.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)

        seen_totals: list[int] = []

        class _ChecksPlanMidRun(_Service):
            def refresh_crypto_candle_history(self):
                # Mid-cycle: by now the app must already be able to see every step.
                seen_totals.append(len(cycle_status(db_path, self.cycle_id)["steps"]))
                return self._stage("candles")

        service = _ChecksPlanMidRun(db_path)
        cycle_id = start_cycle(db_path, scope="crypto")
        service.cycle_id = cycle_id
        run_cycle(service, cycle_id, scope="crypto")

        assert seen_totals == [6], (
            f"the full six-step plan must be visible while the refresh runs, saw {seen_totals}"
        )
        steps = cycle_status(db_path, cycle_id)["steps"]
        assert [s["seq"] for s in steps] == [1, 2, 3, 4, 5, 6]
        assert all(s["status"] == COMPLETED for s in steps)


def test_the_log_accounts_for_coins_that_clear_the_bar_but_are_dropped_anyway():
    """The Founder's exact report, 2026-08-30: "2 coins cleared the checks but no trades
    reached the checks."

    His run log read:

        3. Research and score every coin
           20 coins scored. 2 cleared the 0.70 bar. Best was SOL at 0.71.
        4. Check each idea against the two rules
           No trade ideas reached the checks, so there was nothing to approve or reject.

    Two coins clear the bar and then simply vanish, with no line explaining where they went.
    The score bar is not the only gate -- a coin also needs a rising price trend, and can
    still be dropped for fees, liquidity or its own losing history. Every one of those is
    recorded; none of it was being shown.
    """
    from contextlib import closing as _closing

    from ai_trader.database import connect as _connect
    from ai_trader.models import utc_now_iso as _now

    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)

        class _RealShape(_Service):
            def refresh_crypto_candle_history(self):
                result = self._stage("candles")
                with _closing(_connect(db_path)) as conn:
                    with conn:
                        # SOL clears both gates; ALGO clears the score bar but its trend is
                        # weak; XRP misses the bar. These are yesterday's real numbers.
                        for symbol, score, trend in (
                            ("SOL", 0.7137, 0.7701),
                            ("ALGO", 0.7097, 0.4178),
                            ("XRP", 0.6978, 0.4240),
                        ):
                            conn.execute(
                                """INSERT INTO CRYPTO_RESEARCH_SCORES
                                       (created_at, symbol, overall_due_diligence_score,
                                        technical_trend_score, reasoning_json, source)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (_now(), symbol, score, trend, "{}", "test"),
                            )
                return result

            def run_crypto_analysis(self, limit=0):
                result = self._stage("research")
                # ALGO is discarded before any proposal exists, exactly as the real path does.
                with _closing(_connect(db_path)) as conn:
                    with conn:
                        conn.execute(
                            """INSERT INTO EXECUTION_EVENTS
                                   (created_at, proposal_id, event_type, payload_json)
                               VALUES (?, ?, ?, ?)""",
                            (_now(), "no-trade-crypto-ALGO", "agent_no_trade",
                             json.dumps({
                                 "symbol": "ALGO",
                                 "reason": "crypto_due_diligence_below_threshold_or_negative_trend",
                             })),
                        )
                return result

        service = _RealShape(db_path)
        cycle_id = start_cycle(db_path, scope="crypto")
        run_cycle(service, cycle_id, scope="crypto")

        steps = {s["seq"]: s["summary"] or "" for s in cycle_status(db_path, cycle_id)["steps"]}

        # Step 3 must not imply two buyable ideas when only one clears both gates.
        assert "1 cleared the 0.70 bar with a rising trend" in steps[4], steps[4]

        # Step 4 must name what happened to the one that fell out, in plain English.
        assert "ALGO" in steps[5], steps[5]
        assert "trend" in steps[5].lower(), steps[5]
        assert steps[5] != "No trade ideas reached the checks, so there was nothing to approve or reject.", (
            "step 4 must account for ideas dropped before the checks, not stop at silence"
        )


def test_status_before_any_run_is_reported_plainly():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        status = cycle_status(db_path)
        assert status["status"] == "none"
        assert status["steps"] == []
        assert status["message"]

def test_each_broker_can_be_run_on_its_own():
    """2026-09-01, Founder-directed: "alpaca should have its own cycle like kraken...
    especially if we are doing test runs after upgrades or updates."

    A change to one venue must be testable without running -- or waiting on -- the other.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        service = _Service(db_path)
        cycle_id = start_cycle(db_path, scope="alpaca")
        run_cycle(service, cycle_id, scope="alpaca")
        assert "equity-research" in service.called
        assert "alpaca-orders" in service.called
        assert not any(c.startswith("cycle") or c in {"universe", "candles", "research"}
                       for c in service.called), service.called


def test_scope_names_resolve_to_brokers():
    """Scope is the BROKER now, not the asset class.

    The asset-class names still resolve because they are stored on every cycle run already
    recorded -- a scope that silently stopped working would break the history rather than
    migrate it.
    """
    assert brokers_for_scope("all") == ("kraken", "alpaca")
    assert brokers_for_scope("kraken") == ("kraken",)
    assert brokers_for_scope("alpaca") == ("alpaca",)
    assert brokers_for_scope("crypto") == ("kraken",)
    assert brokers_for_scope("equities") == ("alpaca",)


def test_an_unknown_scope_runs_nothing_rather_than_everything():
    """Failing closed matters: a typo that quietly ran every broker would place real orders
    on an account the caller never named."""
    assert brokers_for_scope("krakan") == ()
    assert brokers_for_scope("bogus") == ()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _fresh_db(tmp)
        service = _Service(db_path)
        cycle_id = start_cycle(db_path, scope="krakan")
        run_cycle(service, cycle_id, scope="krakan")
        assert service.called == [], service.called
