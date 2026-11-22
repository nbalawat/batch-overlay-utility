"""SLA forecasting by Monte Carlo simulation over the cross-scheduler graph.

Each simulation samples every unfinished job's duration from its own history
and propagates finish times through the unified lineage graph, so a delay in
Control-M flows into Airflow and ADF predictions exactly as it would for real.
"""
from __future__ import annotations

import random
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from batchiq.core.business import BusinessMapper
from batchiq.core.graph import LineageGraph
from batchiq.core.stats import JobBaseline
from batchiq.core.store import InMemoryEstate
from batchiq.domain.models import JobKind, RunStatus
from batchiq.intelligence.state import JobState, scheduled_dt


@dataclass
class JobForecast:
    p50_end: datetime
    p90_end: datetime


@dataclass
class ProcessForecast:
    process_id: str
    deadline: datetime
    p50_end: datetime
    p90_end: datetime
    breach_probability: float
    usual_end: datetime | None
    slack_min: float                    # deadline - p50 (negative = late)
    critical_path: list[str] = field(default_factory=list)
    status: str = "on-track"            # done | on-track | at-risk | breach-likely | breached


class Forecaster:
    def __init__(self, estate: InMemoryEstate, graph: LineageGraph, baselines: dict[str, JobBaseline],
                 states: dict[str, JobState], mttr_minutes: list[int], sims: int = 400, seed: int = 11) -> None:
        self.estate, self.graph, self.base, self.states = estate, graph, baselines, states
        self.mttr = [m for m in mttr_minutes if m > 0] or [45]
        self.sims = sims
        self.rng = random.Random(seed)
        self.order = graph.topo_order(set(estate.jobs()))
        self.contention = self._host_contention()

    def _host_contention(self) -> dict[str, float]:
        """Running jobs far over baseline suggest a slow shared host/warehouse."""
        factors: dict[str, float] = {}
        jobs = self.estate.jobs()
        for jid, st in self.states.items():
            b = self.base[jid]
            if st.status == RunStatus.RUNNING and jobs[jid].kind != JobKind.SENSOR and b.p50 and st.elapsed_min:
                ratio = st.elapsed_min / b.p50
                host = jobs[jid].host
                if ratio > 1.5 and host:
                    factors[host] = max(factors.get(host, 1.0), ratio ** 0.5)
        return factors

    def _sample(self, jid: str) -> float:
        b = self.base[jid]
        if not b.samples_min:
            return 5.0
        return self.rng.choice(b.samples_min) * self.rng.uniform(0.97, 1.03)

    def _simulate_once(self) -> tuple[dict[str, datetime], dict[str, str | None]]:
        now = self.estate.now
        jobs = self.estate.jobs()
        ends: dict[str, datetime] = {}
        binding: dict[str, str | None] = {}
        for jid in self.order:
            st, job = self.states[jid], jobs[jid]
            parents = self.graph.parents(jid)
            p_end = max((ends[p] for p in parents if p in ends), default=None)
            binding[jid] = max((p for p in parents if p in ends), key=lambda p: ends[p], default=None)
            if st.status == RunStatus.SUCCEEDED and st.end:
                ends[jid] = st.end
                continue
            if job.kind == JobKind.SENSOR:
                ends[jid] = max(p_end or now, now) + timedelta(minutes=1)
                continue
            dur = self._sample(jid)
            if st.status == RunStatus.RUNNING and st.start:
                elapsed = st.elapsed_min or 0
                longer = [s for s in self.base[jid].samples_min if s > elapsed]
                remaining = (self.rng.choice(longer) - elapsed) if longer else elapsed * self.rng.uniform(0.05, 0.3)
                ends[jid] = now + timedelta(minutes=max(remaining, 0.5))
                binding[jid] = None
                continue
            if st.status == RunStatus.FAILED:
                start = now + timedelta(minutes=self.rng.choice(self.mttr) * self.rng.uniform(0.6, 1.2))
            else:
                cands = [now]
                if p_end:
                    cands.append(p_end + timedelta(minutes=1))
                sd = scheduled_dt(job, self.estate.business_date)
                if sd:
                    cands.append(sd)
                start = max(cands)
            dur *= self.contention.get(job.host or "", 1.0)
            ends[jid] = start + timedelta(minutes=dur)
        return ends, binding

    def run(self, mapper: BusinessMapper) -> tuple[dict[str, JobForecast], dict[str, ProcessForecast]]:
        samples: dict[str, list[datetime]] = {j: [] for j in self.order}
        crit: dict[str, Counter] = {pid: Counter() for pid in mapper.processes}
        proc_ends: dict[str, list[datetime]] = {pid: [] for pid in mapper.processes}
        for _ in range(self.sims):
            ends, binding = self._simulate_once()
            for j, e in ends.items():
                samples[j].append(e)
            for pid, bp in mapper.processes.items():
                anchor = max(bp.anchor_jobs, key=lambda a: ends[a])
                proc_ends[pid].append(ends[anchor])
                node: str | None = anchor
                while node:
                    crit[pid][node] += 1
                    node = binding.get(node)

        def q(xs: list[datetime], p: float) -> datetime:
            xs = sorted(xs)
            return xs[min(int(p * len(xs)), len(xs) - 1)]

        job_fc = {j: JobForecast(q(v, 0.5), q(v, 0.9)) for j, v in samples.items() if v}
        proc_fc = {}
        bd = datetime.fromisoformat(self.estate.business_date)
        for pid, bp in mapper.processes.items():
            deadline = datetime.combine((bd + timedelta(days=1)).date(), bp.sla_deadline)
            ends = proc_ends[pid]
            breach = sum(e > deadline for e in ends) / len(ends)
            p50, p90 = q(ends, 0.5), q(ends, 0.9)
            anchor_bases = [self.base[a].typical_end_offset for a in bp.anchor_jobs]
            usual = (bd + timedelta(hours=20, minutes=max(anchor_bases))) if all(
                x is not None for x in anchor_bases) else None
            done = all(self.states[a].done for a in bp.anchor_jobs)
            if done:
                status = "breached" if max(self.states[a].end for a in bp.anchor_jobs) > deadline else "done"
            elif self.estate.now > deadline:
                status = "breached"
            elif breach >= 0.6:
                status = "breach-likely"
            elif breach >= 0.2:
                status = "at-risk"
            else:
                status = "on-track"
            path = [j for j, c in crit[pid].most_common() if c >= 0.5 * self.sims]
            path.sort(key=lambda j: statistics.median([s.timestamp() for s in samples[j]]))
            proc_fc[pid] = ProcessForecast(pid, deadline, p50, p90, round(breach, 3), usual,
                                           round((deadline - p50).total_seconds() / 60, 1), path, status)
        return job_fc, proc_fc
