"""Shared plumbing for the vendor simulators."""
from __future__ import annotations

import hashlib
import itertools
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from batchiq.simulation.estate import JobSpec, SchedulerSpec
from batchiq.simulation.history import RawRun

_counter = itertools.count(1)


class SimulatedClient:
    """Base for simulators. Subclasses render native payloads."""

    def __init__(self, scheduler: SchedulerSpec, specs: list[JobSpec], runs: list[RawRun],
                 now: datetime, tz: ZoneInfo) -> None:
        self.scheduler = scheduler
        self.specs = specs
        keys = {s.key for s in specs}
        self.runs = [r for r in runs if r.key in keys]
        self.now = now
        self.tz = tz
        self.submitted: list[dict[str, Any]] = []

    def describe(self) -> dict[str, Any]:
        return {"id": self.scheduler.id, "vendor": self.scheduler.vendor.value, "name": self.scheduler.name,
                "environment": self.scheduler.environment, "endpoint": self.scheduler.endpoint,
                "description": self.scheduler.description, "mode": "simulated"}

    def submit(self, command: dict[str, Any]) -> dict[str, Any]:
        """Accepts an action. Nothing runs: the receipt says it was simulated."""
        self.submitted.append(command)
        return {"accepted": True, "simulated": True, "request_id": f"SIM-{next(_counter):05d}",
                "submitted_at": self.now.isoformat()}

    # helpers ----------------------------------------------------------------
    @staticmethod
    def short_id(*parts: str) -> str:
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:8]

    def to_utc(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.replace(tzinfo=self.tz).astimezone(ZoneInfo("UTC")).isoformat()

    @staticmethod
    def odate(bd: date) -> str:
        return bd.strftime("%Y%m%d")
