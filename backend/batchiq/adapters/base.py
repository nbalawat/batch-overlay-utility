"""The pluggable scheduler adapter contract.

An adapter has two halves:

* a **client** (transport) that talks to the scheduler's native API. In this
  prototype every client is a simulator; at a client site the same interface
  is implemented over HTTP/CLI with read-only credentials.
* a **translator** that normalises native payloads into the unified model and
  turns overlay actions back into native commands.

Adding a scheduler means implementing `SchedulerAdapter` and registering it.
Nothing else in the system changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from batchiq.domain.models import Dependency, Job, JobRun, Scheduler


class NativeClient(Protocol):
    """Read-only transport to one scheduler instance (plus a guarded submit)."""

    def describe(self) -> dict[str, Any]: ...
    def fetch_definitions(self) -> Any: ...
    def fetch_runs(self) -> Any: ...
    def submit(self, command: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class NormalisedSnapshot:
    scheduler: Scheduler
    jobs: list[Job]
    dependencies: list[Dependency]
    runs: list[JobRun]
    fetched_at: datetime
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionCommand:
    """An overlay action translated into the scheduler's own vocabulary."""
    action: str
    job_id: str
    vendor: str
    native_command: str
    api_call: dict[str, Any]


SUPPORTED_ACTIONS = ("rerun", "hold", "release", "kill", "boost_priority")


class SchedulerAdapter(ABC):
    vendor: str

    def __init__(self, client: NativeClient) -> None:
        self.client = client

    @abstractmethod
    def scheduler(self) -> Scheduler: ...

    @abstractmethod
    def normalise_definitions(self, native: Any) -> tuple[list[Job], list[Dependency]]: ...

    @abstractmethod
    def normalise_runs(self, native: Any, jobs: dict[str, Job]) -> list[JobRun]: ...

    @abstractmethod
    def build_action(self, job: Job, action: str) -> ActionCommand: ...

    # ----------------------------------------------------------- template method
    def sync(self, now: datetime) -> NormalisedSnapshot:
        jobs, deps = self.normalise_definitions(self.client.fetch_definitions())
        runs = self.normalise_runs(self.client.fetch_runs(), {j.id: j for j in jobs})
        return NormalisedSnapshot(self.scheduler(), jobs, deps, runs, now,
                                  {"jobs": len(jobs), "dependencies": len(deps), "runs": len(runs)})

    def execute(self, job: Job, action: str) -> dict[str, Any]:
        if action not in SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported action '{action}'")
        cmd = self.build_action(job, action)
        receipt = self.client.submit(cmd.api_call)
        return {"command": cmd.native_command, "api_call": cmd.api_call, "receipt": receipt}

    def native_sample(self) -> dict[str, Any]:
        """Raw payloads, for showing how normalisation works in the demo."""
        return {"definitions": self.client.fetch_definitions(), "runs": self.client.fetch_runs()}
