"""Business process mapping.

Loads the client's process catalogue and derives each process's full,
cross-scheduler supply chain from the lineage graph: anchors plus everything
upstream of them, whichever scheduler owns it.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import yaml

from batchiq.core.graph import LineageGraph
from batchiq.domain.models import BusinessProcess, Service


def load_catalogue(path: Path) -> tuple[dict[str, BusinessProcess], dict[str, Service]]:
    data = yaml.safe_load(path.read_text())
    services = {s["id"]: Service(**s) for s in data["services"]}
    processes = {}
    for p in data["processes"]:
        hh, mm = p["sla_deadline"].split(":")
        processes[p["id"]] = BusinessProcess(**{**p, "sla_deadline": time(int(hh), int(mm))})
    return processes, services


class BusinessMapper:
    def __init__(self, processes: dict[str, BusinessProcess], graph: LineageGraph) -> None:
        self.processes = processes
        self.graph = graph
        self.members: dict[str, set[str]] = {}
        self.by_job: dict[str, list[str]] = {}
        for pid, bp in processes.items():
            m = set(bp.anchor_jobs)
            for a in bp.anchor_jobs:
                m |= set(graph.ancestors(a))
            self.members[pid] = m
            for j in m:
                self.by_job.setdefault(j, []).append(pid)

    def processes_for(self, job_id: str) -> list[str]:
        return self.by_job.get(job_id, [])
