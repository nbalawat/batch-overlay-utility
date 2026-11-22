"""Source repository port: where a job's code lives (git, Endevor, ARM templates).

The overlay reads job source to learn what a job really does: files it opens,
tables it queries, hosts it pushes to, people it e-mails. Each scheduler
adapter knows how its vendor points at code (`SchedulerAdapter.source_refs`);
a repository only has to hand back text for a path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SourceRef:
    path: str
    section: str | None = None      # e.g. an Airflow task_id or an ADF activity name inside a larger file


class SourceRepository(Protocol):
    def describe(self) -> dict[str, str]: ...
    def list(self) -> list[str]: ...
    def get(self, path: str) -> tuple[str, str] | None: ...   # (language, text)


class EmptySourceRepository:
    """For schedulers whose code is not (yet) connected: mining is simply skipped."""

    def describe(self) -> dict[str, str]:
        return {"location": "not connected", "mode": "none"}

    def list(self) -> list[str]:
        return []

    def get(self, path: str) -> tuple[str, str] | None:
        return None
