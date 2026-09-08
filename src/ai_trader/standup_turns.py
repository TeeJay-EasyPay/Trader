"""Running one standup turn in the background, so the app never waits on a single request.

2026-09-08, Founder-reported. He asked a question in the standup and got this back twice:

    "after 2 messages or less you provide a message saying 'the rest of that exchange did not
     get through.....' what does that mean and does it mean the conversation has ended?"

It meant the app gave up waiting. The server logs for that morning say why:

    09:16:24 -> 09:17:55   8 lookups   1m 31s   got through
    09:22:17 -> 09:24:14  13 lookups   1m 57s   app gave up at two minutes
    09:25:55 -> 09:30:01  ~19 calls    4m 06s   nobody was listening any more

Claude can search the code and query the database while it answers, and each lookup is another
round trip. That checking is the whole point of having it in the room -- it is what turned "the
price feed is stale" into "nothing reads that table" on 2026-09-06 -- so the answer is not to
make it look less. The answer is to stop holding a request open while it works.

So: the POST starts the turn and returns an id. The app asks how it is going every couple of
seconds and gets a real progress line back -- WHO is working and HOW FAR IN -- until the answer
is ready. No timeout can end a conversation any more, and a spinner is replaced by something
that says what is actually happening, which is what he asked for on 2026-09-07.

DELIBERATELY IN MEMORY, not in the database. A standup turn lives for a few minutes and is
worthless afterwards; the transcript itself is already written to the database as each reply
lands, so nothing is lost if this process restarts. Writing progress rows five times a minute
would add exactly the kind of chatter the egress work has been removing all week. The cost of
that choice is honest and small: after a restart, an id is simply unknown, and the app says so.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Any, Callable

# How long a finished turn stays readable. Long enough that a phone which lost signal mid-answer
# can still come back for it; short enough that a day of standups cannot grow without bound.
KEEP_FINISHED_SECONDS = 900

# A ceiling on stored turns, in case something starts them in a loop. Oldest go first.
MAX_TRACKED = 40

_LOCK = threading.Lock()
_TURNS: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.monotonic()


def _reap(now: float) -> None:
    """Called with _LOCK held."""
    stale = [
        turn_id for turn_id, turn in _TURNS.items()
        if turn["finished_at"] is not None and now - turn["finished_at"] > KEEP_FINISHED_SECONDS
    ]
    for turn_id in stale:
        _TURNS.pop(turn_id, None)
    if len(_TURNS) <= MAX_TRACKED:
        return
    # Oldest first, and never a turn that is still running -- dropping one of those would lose
    # an answer that is still being paid for.
    finished = sorted(
        (turn_id for turn_id, turn in _TURNS.items() if turn["finished_at"] is not None),
        key=lambda turn_id: _TURNS[turn_id]["started_at"],
    )
    for turn_id in finished[: len(_TURNS) - MAX_TRACKED]:
        _TURNS.pop(turn_id, None)


def start_turn(work: Callable[[Callable[[dict[str, Any]], None]], dict[str, Any]]) -> str:
    """Begin a turn in a background thread and hand back its id straight away.

    `work` is given a `report` callback to describe what it is doing as it goes. Anything it
    reports is merged into the progress the app polls for, so a slow turn can say "Claude is
    reading the code, lookup 6 of 12" rather than leaving a spinner to speak for it.
    """

    turn_id = uuid.uuid4().hex[:12]
    now = _now()
    with _LOCK:
        _reap(now)
        _TURNS[turn_id] = {
            "status": "running",
            "progress": {},
            "result": None,
            "started_at": now,
            "finished_at": None,
        }

    def _report(update: dict[str, Any]) -> None:
        # Progress is a convenience, never a correctness requirement: a bad update must not be
        # able to kill a turn the Founder is waiting on and paying for.
        try:
            with _LOCK:
                turn = _TURNS.get(turn_id)
                if turn is not None:
                    turn["progress"] = {**turn["progress"], **dict(update or {})}
        except Exception:  # noqa: BLE001
            pass

    def _worker() -> None:
        try:
            result = work(_report)
            status, payload = "done", result
        except Exception:  # noqa: BLE001 - a thread that dies silently is the worst outcome
            print(f"[standup] turn={turn_id} crashed\n{traceback.format_exc()}", flush=True)
            status, payload = "failed", {
                "status": "failed",
                "message": "That turn stopped unexpectedly. The conversation is still open.",
                "turns": [],
            }
        with _LOCK:
            turn = _TURNS.get(turn_id)
            if turn is None:
                return
            turn["status"] = status
            turn["result"] = payload
            turn["finished_at"] = _now()

    threading.Thread(target=_worker, name=f"standup-{turn_id}", daemon=True).start()
    return turn_id


def turn_state(turn_id: str) -> dict[str, Any]:
    """How a turn is going, for the app to poll.

    An id this process has never seen comes back as "unknown" rather than an error. That is the
    honest answer after a restart, and the app can say "that answer was lost, ask again" instead
    of waiting for something that is never coming.
    """

    wanted = str(turn_id or "").strip()
    now = _now()
    with _LOCK:
        _reap(now)
        turn = _TURNS.get(wanted)
        if turn is None:
            return {
                "status": "unknown",
                "turn_id": wanted,
                "message": "That turn is no longer being tracked. Ask again.",
            }
        state = {
            "status": turn["status"],
            "turn_id": wanted,
            "progress": dict(turn["progress"]),
            "elapsed_seconds": round(now - turn["started_at"], 1),
        }
        if turn["result"] is not None:
            state["result"] = turn["result"]
        return state


def reset_for_tests() -> None:
    with _LOCK:
        _TURNS.clear()
