"""What analysis rules can look at. Built once per sync by the service."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from batchiq.discovery.miner import MinedFact
from batchiq.domain.models import Dependency, Job

if TYPE_CHECKING:
    from batchiq.core.business import BusinessMapper
    from batchiq.core.graph import LineageGraph
    from batchiq.core.stats import JobBaseline
    from batchiq.core.store import InMemoryEstate
    from batchiq.intelligence.forecast import ProcessForecast
    from batchiq.knowledge.graph import KnowledgeGraph


@dataclass
class AnalysisInputs:
    estate: InMemoryEstate
    graph: LineageGraph                              # declared + approved links
    kg: KnowledgeGraph
    mapper: BusinessMapper
    baselines: dict[str, JobBaseline]
    proc_fc: dict[str, ProcessForecast]
    mined: dict[str, list[MinedFact]]
    link_states: dict[str, str]                      # dependency id -> review state
    windows: dict[str, dict[str, tuple[datetime, datetime]]] = field(default_factory=dict)
    change_for_job: dict[str, str] = field(default_factory=dict)   # job id -> change id that last touched it

    @property
    def jobs(self) -> dict[str, Job]:
        return self.estate.jobs()

    def deps(self) -> list[Dependency]:
        return list(self.estate.dependencies().values())

    def tier1_processes(self, jid: str) -> list[str]:
        return [p for p in self.mapper.processes_for(jid) if self.mapper.processes[p].criticality == "tier-1"]
