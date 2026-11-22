"""Unified, vendor-neutral batch domain model.

Every scheduler adapter normalises its native payloads into these types. Nothing
downstream of the adapters (correlation, business mapping, intelligence, API)
knows or cares which vendor a job came from, beyond the `vendor` label.
"""
from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Vendor(StrEnum):
    CONTROL_M = "control-m"
    AIRFLOW = "airflow"
    AUTOSYS = "autosys"
    ADF = "azure-data-factory"


class JobKind(StrEnum):
    COMMAND = "command"
    SENSOR = "sensor"          # waits on a file / dataset / event
    TRANSFER = "transfer"
    TRANSFORM = "transform"
    NOTIFY = "notify"


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RUNNING = "running"
    WAITING = "waiting"        # eligible window open, waiting on upstream
    SCHEDULED = "scheduled"    # not yet reached
    CANCELLED = "cancelled"


class ArtifactType(StrEnum):
    FILE = "file"
    DATASET = "dataset"
    TABLE = "table"
    EVENT = "event"
    QUEUE = "queue"


class Artifact(BaseModel):
    """Something a job produces or consumes (file, dataset, table, event).

    `canonical` is a normalised key (date tokens collapsed, prefixes stripped)
    used by the correlation engine to match producers and consumers across
    schedulers that describe the same thing differently.
    """
    type: ArtifactType
    raw: str
    canonical: str
    match: str = "exact"  # exact | prefix


class Scheduler(BaseModel):
    id: str
    vendor: Vendor
    name: str
    environment: str
    endpoint: str
    description: str = ""


class Job(BaseModel):
    id: str                         # "<scheduler_id>::<native key>"
    scheduler_id: str
    vendor: Vendor
    native_id: str
    name: str
    container: str                  # folder / DAG / box / pipeline
    kind: JobKind = JobKind.COMMAND
    application: str | None = None  # app / tag the scheduler exposes
    owner: str | None = None
    host: str | None = None
    command: str | None = None
    schedule: str | None = None     # human readable schedule
    scheduled_time: time | None = None
    tags: list[str] = Field(default_factory=list)
    produces: list[Artifact] = Field(default_factory=list)
    consumes: list[Artifact] = Field(default_factory=list)
    description: str | None = None
    alerting: bool | None = None                # raises an alert on failure (None = unknown)
    unresolved_conditions: list[str] = Field(default_factory=list)  # waits on things nobody provides
    attributes: dict[str, Any] = Field(default_factory=dict)        # vendor-specific extras

    @property
    def team(self) -> str | None:
        """Owning team, normalised across dialects (AutoSys owners look like 'team@AE1')."""
        return (self.owner or "").split("@")[0] or None


class DependencyOrigin(StrEnum):
    DECLARED = "declared"           # native intra-scheduler dependency
    ARTIFACT = "artifact"           # producer/consumer of the same artifact
    INFERRED = "inferred"           # heuristic / temporal evidence, needs review


class Evidence(BaseModel):
    kind: str          # e.g. "file-path-match", "dataset-name-match", "temporal"
    detail: str
    weight: float


class Dependency(BaseModel):
    id: str
    source: str       # upstream job id
    target: str       # downstream job id
    origin: DependencyOrigin
    cross_scheduler: bool
    confidence: float = 1.0
    artifact: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    review_state: str = "auto"   # auto (declared) | suggested (in review) | confirmed | rejected


class JobRun(BaseModel):
    id: str
    job_id: str
    business_date: str
    attempt: int = 1
    status: RunStatus
    start: datetime | None = None
    end: datetime | None = None
    duration_s: float | None = None
    error_code: str | None = None
    message: str | None = None
    host: str | None = None          # where it actually ran, when the scheduler reports it


class Service(BaseModel):
    id: str
    name: str
    owner: str
    tier: int = 2


class BusinessProcess(BaseModel):
    id: str
    name: str
    description: str
    owner: str
    criticality: str                 # tier-1 / tier-2 / tier-3
    sla_deadline: time
    sla_description: str
    services: list[str]
    anchor_jobs: list[str]           # jobs whose completion = process done
    regulatory: bool = False


class Incident(BaseModel):
    """A past incident in the knowledge base (the RAG layer in the design)."""
    id: str
    date: str
    title: str
    scheduler: Vendor
    jobs: list[str]
    error_code: str | None
    symptoms: str
    root_cause: str
    resolution: str
    mttr_minutes: int
