"""Estate repository.

`EstateRepository` is the persistence port. The prototype ships an in-memory
implementation; a production build would back the same port with Postgres
(plus Apache AGE for the graph and pgvector for the knowledge base) without
changing any caller.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from batchiq.domain.models import (BusinessProcess, Dependency, Incident, Job, JobRun, Scheduler,
                                   Service)


class EstateRepository(Protocol):
    def jobs(self) -> dict[str, Job]: ...
    def dependencies(self) -> dict[str, Dependency]: ...
    def runs_for(self, job_id: str) -> list[JobRun]: ...


@dataclass
class InMemoryEstate:
    now: datetime
    business_date: str
    scenario_id: str
    schedulers: dict[str, Scheduler] = field(default_factory=dict)
    sync_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs_by_id: dict[str, Job] = field(default_factory=dict)
    deps_by_id: dict[str, Dependency] = field(default_factory=dict)
    runs_by_job: dict[str, list[JobRun]] = field(default_factory=lambda: defaultdict(list))
    processes: dict[str, BusinessProcess] = field(default_factory=dict)
    services: dict[str, Service] = field(default_factory=dict)
    incidents: list[Incident] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)

    # EstateRepository -------------------------------------------------------
    def jobs(self) -> dict[str, Job]:
        return self.jobs_by_id

    def dependencies(self) -> dict[str, Dependency]:
        return self.deps_by_id

    def runs_for(self, job_id: str) -> list[JobRun]:
        return self.runs_by_job.get(job_id, [])

    # writes -----------------------------------------------------------------
    def add_jobs(self, jobs: list[Job]) -> None:
        self.jobs_by_id.update({j.id: j for j in jobs})

    def add_dependencies(self, deps: list[Dependency]) -> None:
        for d in deps:
            if d.source in self.jobs_by_id and d.target in self.jobs_by_id:
                self.deps_by_id[d.id] = d

    def add_runs(self, runs: list[JobRun]) -> None:
        for r in runs:
            self.runs_by_job[r.job_id].append(r)
        for lst in self.runs_by_job.values():
            lst.sort(key=lambda r: (r.business_date, r.attempt))

    def tonight_runs(self, job_id: str) -> list[JobRun]:
        return [r for r in self.runs_for(job_id) if r.business_date == self.business_date]

    def history_runs(self, job_id: str) -> list[JobRun]:
        return [r for r in self.runs_for(job_id) if r.business_date < self.business_date]
