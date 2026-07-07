from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any, Callable, Protocol

from .models import utc_now_iso
from .orchestrator import next_research_run


logger = logging.getLogger("ai_trader.scheduler")


class ResearchService(Protocol):
    def run_analysis(self, body: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ResearchCycleResult:
    started_at: str
    completed_at: str
    next_run_at: str
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "next_run_at": self.next_run_at,
            "result": self.result,
        }


class ResearchScheduler:
    def __init__(
        self,
        service: ResearchService,
        *,
        interval_minutes: int = 60,
        on_error: Callable[[Exception], None] | None = None,
    ):
        self.service = service
        self.interval_minutes = interval_minutes
        self.on_error = on_error

    def run_once(self, *, limit: int = 30) -> ResearchCycleResult:
        started = utc_now_iso()
        result = self.service.run_analysis({"limit": limit, "trigger_type": "scheduled"})
        completed = utc_now_iso()
        return ResearchCycleResult(
            started_at=started,
            completed_at=completed,
            next_run_at=next_research_run(datetime.now(timezone.utc), self.interval_minutes),
            result=result,
        )

    def start_background(self, *, limit: int = 30) -> Event:
        stop_event = Event()

        def loop() -> None:
            while not stop_event.is_set():
                try:
                    self.run_once(limit=limit)
                except Exception as exc:  # noqa: BLE001 - a research cycle must never kill the loop
                    logger.exception("Research cycle failed; will retry next interval.")
                    if self.on_error is not None:
                        try:
                            self.on_error(exc)
                        except Exception:
                            logger.exception("Research scheduler on_error handler itself failed.")
                stop_event.wait(max(60, self.interval_minutes * 60))

        Thread(target=loop, name="ai-trader-research-scheduler", daemon=True).start()
        return stop_event


class IntervalWorker:
    """Runs `fn` on a fixed cadence in a daemon thread. A raised exception is logged
    and reported via `on_error`, never allowed to kill the loop - used for continuous
    safety-critical monitoring (managed exits, order fills) that must survive a single
    bad cycle (network blip, broker timeout) rather than silently stopping forever."""

    def __init__(
        self,
        fn: Callable[[], Any],
        *,
        interval_seconds: int = 60,
        name: str = "ai-trader-worker",
        on_error: Callable[[Exception], None] | None = None,
    ):
        self.fn = fn
        self.interval_seconds = interval_seconds
        self.name = name
        self.on_error = on_error

    def start_background(self) -> Event:
        stop_event = Event()

        def loop() -> None:
            while not stop_event.is_set():
                try:
                    self.fn()
                except Exception as exc:  # noqa: BLE001 - one bad cycle must not stop monitoring
                    logger.exception("%s cycle failed; will retry next interval.", self.name)
                    if self.on_error is not None:
                        try:
                            self.on_error(exc)
                        except Exception:
                            logger.exception("%s on_error handler itself failed.", self.name)
                stop_event.wait(max(5, self.interval_seconds))

        Thread(target=loop, name=self.name, daemon=True).start()
        return stop_event
