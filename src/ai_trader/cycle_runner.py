"""Run one complete trading cycle on demand, narrating every step as it happens.

2026-08-29, Founder-directed: "add a card to the app UI where I can click on a button for it
to start a research cycle and potentially trade. the card should show every step of the
process and it's results as a one line summary along the way and conclusion at the end."

Two design decisions worth stating.

FIRST, the step summaries are read back OUT OF THE DATABASE after each stage runs, rather
than echoing whatever status dict the stage returned. A stage that reports
{"status": "completed"} tells the Founder nothing -- the whole morning of 2026-08-29 was
spent discovering that "crypto research completed with 0 recommendations" was hiding a
permission gate rejecting companies that were plainly permitted. Counting the rows the stage
actually wrote is the difference between "it ran" and "here is what it decided".

SECOND, the cycle runs in a BACKGROUND THREAD and the caller polls. A full cycle takes two
to four minutes and Render's proxy cuts any single request at 60 seconds, so a synchronous
endpoint could not work even in principle -- the phone would always see a dropped connection
while the work carried on invisibly.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from .database import connect
from .models import utc_now_iso
from .operational import initialize_operational_schema

CYCLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS CYCLE_RUNS (
    cycle_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    trigger_source TEXT,
    conclusion TEXT
);

CREATE TABLE IF NOT EXISTS CYCLE_RUN_STEPS (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cycle_run_steps_cycle
ON CYCLE_RUN_STEPS(cycle_id, seq);
"""

RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"

_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = threading.Lock()
# One cycle at a time per process. Two concurrent cycles would interleave their writes and
# make every "what changed since this stage started" summary below wrong -- and the Founder
# tapping the button twice is the expected case, not an exotic one.
_RUN_LOCK = threading.Lock()


def initialize_cycle_schema(db_path: Path) -> None:
    key = str(Path(db_path).resolve())
    if key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if key in _SCHEMA_READY:
            return
        initialize_operational_schema(db_path)
        with closing(connect(db_path)) as conn:
            with conn:
                conn.executescript(CYCLE_SCHEMA)
        _SCHEMA_READY.add(key)


def _scalar(conn, sql: str, params: tuple = ()) -> Any:
    # Tolerates a table that does not exist yet. A count used only to describe what happened
    # must never be the reason a cycle reports failure -- see the summary/action split in
    # run_cycle for the same principle applied one level up.
    try:
        row = conn.execute(sql, params).fetchone()
    except Exception:  # noqa: BLE001 - a missing table means "nothing recorded", i.e. zero
        return None
    if row is None:
        return None
    # Postgres rows arrive as a dict subclass here (see the HybridRow note in database.py),
    # where iterating yields KEYS rather than values -- index explicitly.
    return row[0]


def _rows(conn, sql: str, params: tuple = ()) -> list:
    try:
        return list(conn.execute(sql, params).fetchall())
    except Exception:  # noqa: BLE001 - same reasoning as _scalar
        return []


# --------------------------------------------------------------------------------------
# Step summaries: each reads what the stage actually wrote, in the window it ran.
# --------------------------------------------------------------------------------------

def _summarise_universe(db_path: Path, since: str) -> str:
    with closing(connect(db_path)) as conn:
        total = _scalar(conn, "SELECT COUNT(*) FROM CRYPTO_ASSET_MASTER WHERE active = 1") or 0
    return f"{int(total)} coins are on the approved shopping list."


def _summarise_scores(db_path: Path, since: str) -> str:
    with closing(connect(db_path)) as conn:
        scored = _scalar(
            conn, "SELECT COUNT(*) FROM CRYPTO_RESEARCH_SCORES WHERE created_at >= ?", (since,)
        ) or 0
    if not int(scored):
        return "No new prices or liquidity readings were written."
    return f"Fresh prices, order-book liquidity and news read for {int(scored)} coins."


def _summarise_research(db_path: Path, since: str, bar: float) -> str:
    """`since` must be the CYCLE start, not this step's start.

    2026-08-29, found on the first live run: the scores are written by the PREVIOUS step
    (the price and liquidity refresh) and merely read by this one, so measuring this step's
    own window found nothing and reported "No coins were scored this cycle" directly beneath
    a step that had just said 20 coins were scored. Two adjacent lines contradicting each
    other is precisely the dishonest narration this whole feature exists to replace.
    """
    with closing(connect(db_path)) as conn:
        scored = int(_scalar(
            conn, "SELECT COUNT(*) FROM CRYPTO_RESEARCH_SCORES WHERE created_at >= ?", (since,)
        ) or 0)
        if not scored:
            return "No coins were scored this cycle."
        found = _rows(
            conn,
            """SELECT symbol, overall_due_diligence_score FROM CRYPTO_RESEARCH_SCORES
               WHERE created_at >= ? ORDER BY overall_due_diligence_score DESC LIMIT 1""",
            (since,),
        )
        row = found[0] if found else None
        passed = int(_scalar(
            conn,
            """SELECT COUNT(*) FROM CRYPTO_RESEARCH_SCORES
               WHERE created_at >= ? AND overall_due_diligence_score >= ?""",
            (since, bar),
        ) or 0)
        # A coin must ALSO have a rising price trend to be bought -- a second gate in
        # propose_crypto_trades that nothing in the app used to mention. Reporting only the
        # score bar is why the log could say "2 cleared the bar" and then buy nothing, with
        # no line accounting for the difference (Founder, 2026-08-30).
        tradeable = int(_scalar(
            conn,
            """SELECT COUNT(*) FROM CRYPTO_RESEARCH_SCORES
               WHERE created_at >= ? AND overall_due_diligence_score >= ?
                 AND technical_trend_score > 0.5""",
            (since, bar),
        ) or 0)
    best_symbol, best_score = (row[0], float(row[1] or 0.0)) if row else ("-", 0.0)
    if not passed:
        return (f"{scored} coins scored, none cleared the {bar:.2f} bar. "
                f"Best was {best_symbol} at {best_score:.2f} - nothing worth buying today.")
    if tradeable:
        return (f"{scored} coins scored. {tradeable} cleared the {bar:.2f} bar with a rising "
                f"trend. Best was {best_symbol} at {best_score:.2f}.")
    return (f"{scored} coins scored. {passed} cleared the {bar:.2f} bar but none had a rising "
            f"price trend, which is also required. Best was {best_symbol} at {best_score:.2f}.")


# Plain English for every reason propose_crypto_trades records before a proposal exists.
# These drops happen BEFORE the two rules are applied, so without this the run log jumps
# straight from "2 coins cleared the bar" to "nothing reached the checks" and never accounts
# for the difference -- which is exactly what the Founder caught on 2026-08-30.
_DROP_REASONS = {
    "crypto_due_diligence_below_threshold_or_negative_trend": "score or price trend too weak",
    "entry_too_extended_in_24h_range": "already run too far up today to buy safely",
    "fee_hurdle_not_cleared": "profit would not cover Kraken's fees",
    "own_track_record_negative": "our own past trades in it have lost money",
    "liquidity_structure_unfavourable": "order book too thin to trade cleanly",
    "btc_weak_regime": "Bitcoin is weak, so the whole market is risky",
    "recently_stopped_out": "stopped out of it recently, still cooling off",
    "kraken_pair_unavailable": "not tradeable on Kraken right now",
    "current_price_not_available": "no live price available",
}


def _drops_before_the_checks(db_path: Path, since: str) -> list[tuple[str, str]]:
    """(symbol, plain-English reason) for ideas discarded before the two rules ran."""
    with closing(connect(db_path)) as conn:
        rows = _rows(
            conn,
            """SELECT proposal_id, payload_json FROM EXECUTION_EVENTS
               WHERE event_type = 'agent_no_trade' AND created_at >= ?
               ORDER BY created_at""",
            (since,),
        )
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        # Index explicitly. Under Postgres these rows are a dict subclass, so tuple
        # unpacking (`for proposal_id, raw in rows`) yields the COLUMN NAMES, not the values
        # -- which is precisely what shipped: the app displayed
        # "PROPOSAL_ID (no reason recorded)". The tests pass under SQLite, where rows really
        # are tuples, so only running it against production caught it.
        proposal_id, raw = row[0], row[1]
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            payload = {}
        symbol = str(payload.get("symbol") or proposal_id or "").upper()
        symbol = symbol.replace("NO-TRADE-CRYPTO-", "").replace("NO-TRADE-", "")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        reason = str(payload.get("reason") or "")
        out.append((symbol, _DROP_REASONS.get(reason, reason.replace("_", " ") or "no reason recorded")))
    return out


def _summarise_proposals(db_path: Path, since: str) -> str:
    with closing(connect(db_path)) as conn:
        made = int(_scalar(
            conn,
            "SELECT COUNT(*) FROM TRADE_AUDIT WHERE event_type = 'agent_proposal' AND created_at >= ?",
            (since,),
        ) or 0)
        rows = _rows(
            conn,
            """SELECT symbol, result, reason FROM BROKER_DECISIONS
               WHERE created_at >= ? ORDER BY created_at DESC""",
            (since,),
        )
    approved = [r for r in rows if str(r[1] or "").lower() in {"approved", "accepted", "executed"}]
    if not made and not rows:
        # 2026-08-30, Founder-caught: this used to stop at "nothing reached the checks",
        # directly under a line saying two coins had cleared the bar. It never accounted for
        # the difference, so the log read as a contradiction. Every idea discarded earlier is
        # now named, with the reason in plain English.
        dropped = _drops_before_the_checks(db_path, since)
        if dropped:
            head = f"Nothing reached the two rules. {len(dropped)} idea(s) were dropped earlier: "
            shown = "; ".join(f"{symbol} ({reason})" for symbol, reason in dropped[:3])
            more = f" and {len(dropped) - 3} more" if len(dropped) > 3 else ""
            return head + shown + more + "."
        return "No trade ideas reached the checks, so there was nothing to approve or reject."
    parts = [f"{made} trade idea(s) put forward"]
    if rows:
        parts.append(f"{len(approved)} passed the checks, {len(rows) - len(approved)} rejected")
        if len(rows) > len(approved):
            reason = str(rows[0][2] or "").split(",")[0].strip().replace("_", " ")
            if reason:
                parts.append(f"most common reason: {reason}")
    return ". ".join(parts) + "."


def _summarise_orders(db_path: Path, since: str, broker: str) -> str:
    with closing(connect(db_path)) as conn:
        placed = int(_scalar(
            conn,
            """SELECT COUNT(*) FROM TRADE_AUDIT
               WHERE event_type IN ('order_submitted', 'execution_submitted')
                 AND created_at >= ?""",
            (since,),
        ) or 0)
    if placed:
        return f"{placed} order(s) submitted to {broker}. Check Trade History for the fills."
    return f"No orders were placed on {broker} this cycle."


def _summarise_equity_research(db_path: Path, since: str) -> str:
    with closing(connect(db_path)) as conn:
        made = int(_scalar(
            conn,
            """SELECT COUNT(*) FROM TRADE_AUDIT WHERE event_type = 'agent_proposal'
               AND created_at >= ?""",
            (since,),
        ) or 0)
        # The LIKE pattern is BOUND, not inlined. Inlining it works on SQLite and is a hard
        # 500 on Postgres, whose driver reads '%m' as a format placeholder -- which is
        # production. tests/test_always_on_operations.py has a static check for this and
        # caught this exact line.
        closed = _scalar(
            conn,
            """SELECT COUNT(*) FROM BROKER_DECISIONS
               WHERE created_at >= ? AND reason LIKE ?""",
            (since, "%market_closed%"),
        )
    if int(closed or 0):
        return ("The US market is closed, so no shares could be bought or sold. "
                "Ideas were still researched and recorded.")
    return f"{made} share idea(s) researched."


# --------------------------------------------------------------------------------------
# Cycle bookkeeping
# --------------------------------------------------------------------------------------

def start_cycle(db_path: Path, *, scope: str = "all", trigger_source: str = "app") -> str:
    initialize_cycle_schema(db_path)
    cycle_id = uuid.uuid4().hex[:12]
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """INSERT INTO CYCLE_RUNS (cycle_id, started_at, status, scope, trigger_source)
                   VALUES (?, ?, ?, ?, ?)""",
                (cycle_id, utc_now_iso(), RUNNING, scope, trigger_source),
            )
    return cycle_id


PENDING = "pending"


def _plan_steps(db_path: Path, cycle_id: str, labels: list[str]) -> None:
    """Write the whole plan up front, every step pending.

    2026-08-29, seen on the emulator: steps used to be created as they started, so while the
    first one ran the app read "step 1 of 1" -- telling the Founder the cycle was on its last
    step when it was on its first, out of five. A progress indicator that overstates progress
    is worse than none.

    Writing the plan first also means the screen shows the whole sequence immediately, so he
    can see what is coming rather than watching lines appear one at a time with no idea how
    many are left.
    """
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            for seq, label in enumerate(labels, start=1):
                conn.execute(
                    """INSERT INTO CYCLE_RUN_STEPS (cycle_id, seq, label, status, started_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (cycle_id, seq, label, PENDING, now),
                )


def _open_step(db_path: Path, cycle_id: str, seq: int, label: str) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """UPDATE CYCLE_RUN_STEPS SET status = ?, started_at = ?
                   WHERE cycle_id = ? AND seq = ?""",
                (RUNNING, utc_now_iso(), cycle_id, seq),
            )


def _close_step(db_path: Path, cycle_id: str, seq: int, *, status: str, summary: str) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """UPDATE CYCLE_RUN_STEPS SET status = ?, summary = ?, completed_at = ?
                   WHERE cycle_id = ? AND seq = ?""",
                (status, summary, utc_now_iso(), cycle_id, seq),
            )


def _finish_cycle(db_path: Path, cycle_id: str, *, status: str, conclusion: str) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """UPDATE CYCLE_RUNS SET status = ?, conclusion = ?, completed_at = ?
                   WHERE cycle_id = ?""",
                (status, conclusion, utc_now_iso(), cycle_id),
            )


# A cycle normally finishes in two to four minutes; the slowest stage observed in production
# is equity research at around ten. Twenty is generous enough never to reap a live run and
# short enough that an orphan does not sit there all afternoon.
STALE_AFTER_MINUTES = 20


def _reap_interrupted(db_path: Path) -> None:
    """Close out cycles whose process died mid-run.

    2026-08-29, found on the emulator: a deploy restarted the web service while a cycle was
    on its last step. The thread died with it, but the database row still said "running" --
    so the app showed a cycle running forever and, because the button is disabled while one
    is in flight, the Founder could never start another. A feature whose entire purpose is a
    button that works cannot have a state where the button stops working.

    Every restart-driven orphan looks like this, so it is reaped on read rather than needing
    anyone to notice and clear it by hand.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_AFTER_MINUTES)).isoformat()
    with closing(connect(db_path)) as conn:
        stale = _rows(
            conn,
            """SELECT r.cycle_id FROM CYCLE_RUNS r
               WHERE r.status = ?
                 AND COALESCE(
                       (SELECT MAX(COALESCE(s.completed_at, s.started_at))
                          FROM CYCLE_RUN_STEPS s WHERE s.cycle_id = r.cycle_id),
                       r.started_at) < ?""",
            (RUNNING, cutoff),
        )
        if not stale:
            return
        with conn:
            for row in stale:
                conn.execute(
                    """UPDATE CYCLE_RUNS SET status = ?, completed_at = ?, conclusion = ?
                       WHERE cycle_id = ?""",
                    (FAILED, utc_now_iso(),
                     "This cycle was interrupted before it finished - usually because the "
                     "service restarted. Nothing was left half-traded; press Run again.",
                     row[0]),
                )
                conn.execute(
                    """UPDATE CYCLE_RUN_STEPS SET status = ?, completed_at = ?, summary = ?
                       WHERE cycle_id = ? AND status = ?""",
                    (FAILED, utc_now_iso(), "Interrupted when the service restarted.",
                     row[0], RUNNING),
                )


def cycle_status(db_path: Path, cycle_id: str | None = None) -> dict[str, Any]:
    """One cycle's progress, for the app to poll. Defaults to the most recent cycle."""
    initialize_cycle_schema(db_path)
    _reap_interrupted(db_path)
    with closing(connect(db_path)) as conn:
        if cycle_id:
            run = conn.execute(
                """SELECT cycle_id, started_at, completed_at, status, scope, trigger_source,
                          conclusion FROM CYCLE_RUNS WHERE cycle_id = ?""",
                (cycle_id,),
            ).fetchone()
        else:
            run = conn.execute(
                """SELECT cycle_id, started_at, completed_at, status, scope, trigger_source,
                          conclusion FROM CYCLE_RUNS ORDER BY started_at DESC LIMIT 1"""
            ).fetchone()
        if run is None:
            return {"status": "none", "steps": [], "message": "No cycle has been run yet."}
        steps = conn.execute(
            """SELECT seq, label, status, summary, started_at, completed_at
               FROM CYCLE_RUN_STEPS WHERE cycle_id = ? ORDER BY seq""",
            (run[0],),
        ).fetchall()
    return {
        "cycle_id": run[0],
        "started_at": run[1],
        "completed_at": run[2],
        "status": run[3],
        "scope": run[4],
        "trigger_source": run[5],
        "conclusion": run[6],
        "steps": [
            {
                "seq": s[0],
                "label": s[1],
                "status": s[2],
                "summary": s[3],
                "started_at": s[4],
                "completed_at": s[5],
            }
            for s in steps
        ],
    }


# --------------------------------------------------------------------------------------
# The cycle itself
# --------------------------------------------------------------------------------------

def _confidence_bar(service) -> float:
    try:
        from .foundation import load_trading_policy

        return float(load_trading_policy(service.settings.db_path).min_ai_confidence)
    except Exception:  # noqa: BLE001 - a display bar must never break the run
        return 0.70


def run_cycle(service, cycle_id: str, *, scope: str = "all") -> None:
    """Execute the cycle, writing one row per step as it goes.

    Never raises: a failure is recorded as a failed step and a plain-English conclusion,
    because the caller is a background thread whose exception nobody would ever see.
    """
    db_path = service.settings.db_path
    bar = _confidence_bar(service)
    # Some steps REPORT on rows an EARLIER step wrote (research reads the scores the price
    # refresh produced), so those summaries measure from the start of the whole cycle rather
    # than from their own step. See _summarise_research.
    cycle_started = cycle_status(db_path, cycle_id).get("started_at") or utc_now_iso()
    do_crypto = scope in {"all", "crypto"}
    do_equities = scope in {"all", "equities"}

    stages: list[tuple[str, Callable[[], Any], Callable[[str], str]]] = []
    if do_crypto:
        stages += [
            ("Refresh the list of coins we are allowed to trade",
             lambda: service.refresh_crypto_universe(),
             lambda since: _summarise_universe(db_path, since)),
            ("Get fresh prices, liquidity and news for each coin",
             lambda: service.refresh_crypto_candle_history(),
             lambda since: _summarise_scores(db_path, since)),
            ("Research and score every coin",
             lambda: service.run_crypto_analysis(limit=0),
             lambda since: _summarise_research(db_path, cycle_started, bar)),
            # Same window problem as research above: the proposals and their pass/fail
            # decisions are written DURING the research step, so this reports on the cycle
            # rather than on its own (instantaneous) step.
            ("Check each idea against the two rules",
             lambda: {"status": "reviewed"},
             lambda since: _summarise_proposals(db_path, cycle_started)),
            ("Place any crypto orders",
             lambda: service.auto_execute_recommendations_kraken(),
             lambda since: _summarise_orders(db_path, since, "Kraken")),
        ]
    if do_equities:
        stages += [
            ("Research shares",
             lambda: service.run_analysis({"limit": 0, "trigger_type": "founder-cycle", "broker": "alpaca"}),
             lambda since: _summarise_equity_research(db_path, since)),
            ("Place any share orders",
             lambda: service.auto_execute_recommendations_alpaca(),
             lambda since: _summarise_orders(db_path, since, "Alpaca")),
        ]

    # Lay out the whole plan before running anything, so "step 2 of 5" is true from the
    # first moment rather than counting only the steps created so far.
    _plan_steps(db_path, cycle_id, [label for label, _action, _summarise in stages])

    failed = False
    for seq, (label, action, summarise) in enumerate(stages, start=1):
        started = utc_now_iso()
        _open_step(db_path, cycle_id, seq, label)
        # The WORK and the DESCRIPTION of the work are caught separately and deliberately.
        # Collapsing them means a broken count in a summary query reports the trading stage
        # itself as failed -- telling the Founder his cycle broke when it in fact completed
        # normally. Found by running this exact code against a database missing a table:
        # four stages that had genuinely succeeded all showed as failed.
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - report the failing step, keep going
            failed = True
            detail = str(exc).strip() or exc.__class__.__name__
            _close_step(
                db_path, cycle_id, seq, status=FAILED,
                summary=f"This step could not finish: {detail[:200]}",
            )
            print(f"[cycle] step={seq} label={label!r} FAILED: {detail}\n{traceback.format_exc()}",
                  flush=True)
            continue
        try:
            summary = summarise(started)
        except Exception as exc:  # noqa: BLE001 - the step DID work; only the wording failed
            summary = "Finished, but the result could not be summarised."
            print(f"[cycle] step={seq} summary failed: {exc}\n{traceback.format_exc()}", flush=True)
        _close_step(db_path, cycle_id, seq, status=COMPLETED, summary=summary)

    try:
        conclusion = _conclusion(db_path, cycle_id, failed=failed)
    except Exception:  # noqa: BLE001 - a cycle that ran must never be recorded as crashed
        # because the closing sentence could not be composed.
        conclusion = "The cycle finished. See the steps above for what happened."
        print(f"[cycle] conclusion failed\n{traceback.format_exc()}", flush=True)
    _finish_cycle(
        db_path, cycle_id,
        status=FAILED if failed else COMPLETED,
        conclusion=conclusion,
    )


def _conclusion(db_path: Path, cycle_id: str, *, failed: bool) -> str:
    """The one-line answer to "so what happened?", written for the Founder, not for a log."""
    status = cycle_status(db_path, cycle_id)
    steps = status.get("steps") or []
    started = status.get("started_at") or ""
    with closing(connect(db_path)) as conn:
        orders = int(_scalar(
            conn,
            """SELECT COUNT(*) FROM TRADE_AUDIT
               WHERE event_type IN ('order_submitted', 'execution_submitted') AND created_at >= ?""",
            (started,),
        ) or 0)
    broken = [s for s in steps if s.get("status") == FAILED]
    if orders:
        head = f"{orders} order(s) placed - they will appear in Trade History."
    else:
        head = "No trades placed. Nothing today met both rules."
    if failed or broken:
        return f"{head} {len(broken)} step(s) failed - see the red step(s) above."
    return head


def start_cycle_in_background(service, *, scope: str = "all", trigger_source: str = "app") -> dict[str, Any]:
    """Begin a cycle and return immediately with its id, for the app to poll.

    Refuses to start a second cycle while one is already running rather than queueing it:
    two overlapping runs would corrupt every "what changed during this stage" summary, and
    the honest answer to a double tap is "one is already going", not a silent second run.
    """
    db_path = service.settings.db_path
    initialize_cycle_schema(db_path)
    # Clear any orphan from a previous process before deciding whether one is "already
    # running" -- otherwise a restart-killed cycle blocks the button for good.
    _reap_interrupted(db_path)
    if _RUN_LOCK.locked():
        current = cycle_status(db_path)
        return {
            "status": "already_running",
            "cycle_id": current.get("cycle_id"),
            "message": "A cycle is already running. Watch that one rather than starting another.",
        }
    cycle_id = start_cycle(db_path, scope=scope, trigger_source=trigger_source)

    def _worker() -> None:
        with _RUN_LOCK:
            try:
                run_cycle(service, cycle_id, scope=scope)
            except Exception:  # noqa: BLE001 - a thread that dies silently is the worst outcome
                print(f"[cycle] cycle={cycle_id} crashed\n{traceback.format_exc()}", flush=True)
                _finish_cycle(
                    db_path, cycle_id, status=FAILED,
                    conclusion="The cycle stopped unexpectedly. Nothing was traded.",
                )

    threading.Thread(target=_worker, name=f"cycle-{cycle_id}", daemon=True).start()
    return {"status": "started", "cycle_id": cycle_id, "scope": scope}
