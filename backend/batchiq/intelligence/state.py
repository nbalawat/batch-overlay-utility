"""Tonight's live state per job, derived from normalised runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from batchiq.core.store import InMemoryEstate
from batchiq.domain.models import Job, JobRun, RunStatus


@dataclass
class JobState:
    job_id: str
    status: RunStatus
    latest: JobRun | None
    failed_attempts: list[JobRun]
    start: datetime | None
    end: datetime | None
    elapsed_min: float | None

    @property
    def done(self) -> bool:
        return self.status == RunStatus.SUCCEEDED


def scheduled_dt(job: Job, business_date: str) -> datetime | None:
    if job.scheduled_time is None:
        return None
    base = datetime.fromisoformat(business_date)
    d = datetime.combine(base.date(), job.scheduled_time)
    return d if d.hour >= 20 else d + timedelta(days=1)


def compute_states(estate: InMemoryEstate) -> dict[str, JobState]:
    out = {}
    for jid, job in estate.jobs().items():
        runs = estate.tonight_runs(jid)
        failed = [r for r in runs if r.status == RunStatus.FAILED]
        latest = max(runs, key=lambda r: (r.attempt, r.start or datetime.min)) if runs else None
        if latest is None:
            sd = scheduled_dt(job, estate.business_date)
            status = RunStatus.SCHEDULED if sd and sd > estate.now else RunStatus.WAITING
            out[jid] = JobState(jid, status, None, failed, None, None, None)
            continue
        elapsed = None
        if latest.start:
            elapsed = ((latest.end or estate.now) - latest.start).total_seconds() / 60
        out[jid] = JobState(jid, latest.status, latest, failed, latest.start, latest.end, elapsed)
    return out
