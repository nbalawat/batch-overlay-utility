"""Findings: what static and runtime analysis say about the estate, with evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class Finding:
    id: str
    kind: str                     # static | runtime
    category: str                 # e.g. "dead-condition", "sensor-waste"
    severity: str                 # high | medium | low | info
    title: str
    detail: str
    recommendation: str
    scope: str                    # a scheduler id, or "cross" for cross-ecosystem
    job_ids: list[str] = field(default_factory=list)
    process_ids: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    link_id: str | None = None


CATEGORY_TITLES = {
    # static
    "dead-condition": "Waits on something that no longer exists",
    "missing-dependency": "Reads another job's output without waiting for it",
    "redundant-dependency": "Redundant condition",
    "unmonitored": "Fails silently",
    "plaintext-secret": "Credential in source code",
    "orphan-output": "Output nobody reads",
    "external-input": "Input from outside the estate",
    "single-point-of-failure": "Single point of failure",
    "host-concentration": "Critical work concentrated on one host",
    "external-egress": "Data leaving the bank",
    "cross-coupling": "Coupling between ecosystems",
    # runtime
    "sensor-waste": "Sensor poking for hours",
    "duration-trend": "Duration growing night over night",
    "queueing-delay": "Starts late after its inputs are ready",
    "failure-hotspot": "Repeated failures",
    "critical-path-leverage": "Where minutes saved move the SLA",
    "stale-read": "Ran before the data it reads was ready",
    "host-load": "Host concurrency peak",
}
