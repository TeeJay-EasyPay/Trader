from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any, Protocol

from .models import utc_now_iso
from .orchestrator import next_research_run


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
    def __init__(self, service: ResearchService, *, interval_minutes: int = 60):
        self.service = service
        self.interval_minutes = interval_minutes

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
                self.run_once(limit=limit)
                stop_event.wait(max(60, self.interval_minutes * 60))

        Thread(target=loop, name="ai-trader-research-scheduler", daemon=True).start()
        return stop_event
