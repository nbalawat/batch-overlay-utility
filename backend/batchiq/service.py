"""Application service: wires connectors -> unified store -> correlation ->
business mapping -> intelligence, and answers the queries the API and the
assistant need. This is the only module that knows the whole pipeline.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

# Importing the adapter modules registers them.
import batchiq.adapters.adf.adapter  # noqa: F401
import batchiq.adapters.airflow.adapter  # noqa: F401
import batchiq.adapters.autosys.adapter  # noqa: F401
import batchiq.adapters.controlm.adapter  # noqa: F401
from batchiq.adapters import registry
from batchiq.adapters.adf.simulator import ADFSimulator
from batchiq.adapters.airflow.simulator import AirflowSimulator
from batchiq.adapters.autosys.simulator import AutoSysSimulator
from batchiq.adapters.base import SchedulerAdapter
from batchiq.adapters.controlm.simulator import ControlMSimulator
from batchiq.config import settings
from batchiq.core.business import BusinessMapper, load_catalogue
from batchiq.core.correlation import CorrelationEngine
from batchiq.core.graph import LineageGraph
from batchiq.core.stats import JobBaseline, compute_baselines
from batchiq.core.store import InMemoryEstate
from batchiq.domain.models import Incident, RunStatus, Service, Vendor
from batchiq.intelligence.forecast import Forecaster, JobForecast, ProcessForecast
from batchiq.intelligence.insights import Insight, InsightEngine
from batchiq.intelligence.knowledge import TfidfKnowledgeBase
from batchiq.intelligence.state import JobState, compute_states
from batchiq.simulation.estate import INCIDENT_HISTORY, SCHEDULERS, jobs_for
from batchiq.simulation.history import HistoryGenerator
from batchiq.simulation.scenarios import SCENARIOS

_SIMULATORS = {Vendor.CONTROL_M: ControlMSimulator, Vendor.AIRFLOW: AirflowSimulator,
               Vendor.AUTOSYS: AutoSysSimulator, Vendor.ADF: ADFSimulator}


@dataclass
class Analysis:
    estate: InMemoryEstate
    graph: LineageGraph
    mapper: BusinessMapper
    baselines: dict[str, JobBaseline]
    states: dict[str, JobState]
    job_fc: dict[str, JobForecast]
    proc_fc: dict[str, ProcessForecast]
    kb: TfidfKnowledgeBase
    services: dict[str, Service]
    insights: list[Insight]
    engine: InsightEngine


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="minutes") if dt else None


class EstateService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.adapters: dict[str, SchedulerAdapter] = {}
        self.a: Analysis | None = None
        self.scenario_id = settings.scenario
        self.load(self.scenario_id)

    # ------------------------------------------------------------------ lifecycle
    def _today(self) -> date:
        if settings.today:
            return date.fromisoformat(settings.today)
        return datetime.now(ZoneInfo(settings.estate_timezone)).date()

    def load(self, scenario_id: str) -> None:
        with self._lock:
            scenario = SCENARIOS[scenario_id]
            today = self._today()
            raw_runs, now = HistoryGenerator(settings.seed).generate(scenario, today)
            tz = ZoneInfo(settings.estate_timezone)
            self.adapters = {}
            for spec in SCHEDULERS:
                client = _SIMULATORS[spec.vendor](spec, jobs_for(spec.id), raw_runs, now, tz)
                self.adapters[spec.id] = registry.create(spec.vendor.value, client)
            estate = InMemoryEstate(now=now, business_date=(today.fromordinal(today.toordinal() - 1)).isoformat(),
                                    scenario_id=scenario_id)
            # 1) Ingest + normalise every connector.
            for sid, adapter in self.adapters.items():
                snap = adapter.sync(now)
                estate.schedulers[sid] = snap.scheduler
                estate.add_jobs(snap.jobs)
                estate.add_dependencies(snap.dependencies)
                estate.add_runs(snap.runs)
                estate.sync_stats[sid] = {**snap.stats, "last_sync": _iso(now), "status": "connected",
                                          "mode": "simulated"}
            # 2) Correlate across schedulers.
            estate.add_dependencies(CorrelationEngine(estate).run())
            # 3) Business context + knowledge base.
            processes, services = load_catalogue(settings.business_map)
            estate.processes, estate.services = processes, services
            estate.incidents = [Incident(id=i.id, date=i.date, title=i.title, scheduler=i.vendor, jobs=list(i.jobs),
                                         error_code=i.error_code, symptoms=i.symptoms, root_cause=i.root_cause,
                                         resolution=i.resolution, mttr_minutes=i.mttr_minutes)
                                for i in INCIDENT_HISTORY]
            self.scenario_id = scenario_id
            self._analyse(estate)

    def _analyse(self, estate: InMemoryEstate) -> None:
        graph = LineageGraph(list(estate.dependencies().values()))
        mapper = BusinessMapper(estate.processes, graph)
        baselines = compute_baselines(estate)
        states = compute_states(estate)
        kb = TfidfKnowledgeBase(estate.incidents)
        job_fc, proc_fc = Forecaster(estate, graph, baselines, states,
                                     [i.mttr_minutes for i in estate.incidents]).run(mapper)
        a = Analysis(estate, graph, mapper, baselines, states, job_fc, proc_fc, kb, estate.services, [], None)  # type: ignore[arg-type]
        a.engine = InsightEngine(a)
        a.insights = a.engine.run()
        self.a = a

    def reanalyse(self) -> None:
        with self._lock:
            assert self.a
            self._analyse(self.a.estate)

    # ------------------------------------------------------------------ serialisers
    def job_brief(self, jid: str) -> dict[str, Any]:
        a = self.a
        job, st, fc = a.estate.jobs()[jid], a.states[jid], a.job_fc.get(jid)
        return {"id": jid, "name": job.name, "container": job.container, "scheduler_id": job.scheduler_id,
                "vendor": job.vendor.value, "kind": job.kind.value, "status": st.status.value,
                "start": _iso(st.start), "end": _iso(st.end),
                "elapsed_min": round(st.elapsed_min, 1) if st.elapsed_min is not None else None,
                "failed_attempts": len(st.failed_attempts),
                "projected_end": _iso(fc.p50_end) if fc and not st.done else None,
                "projected_end_p90": _iso(fc.p90_end) if fc and not st.done else None,
                "p50_min": round(a.baselines[jid].p50, 1), "processes": a.mapper.processes_for(jid),
                "anomalous": jid in a.engine._anomaly_cache}

    def process_brief(self, pid: str) -> dict[str, Any]:
        a = self.a
        bp, fc = a.mapper.processes[pid], a.proc_fc[pid]
        members = a.mapper.members[pid]
        jobs = a.estate.jobs()
        by_sched: dict[str, int] = {}
        for m in members:
            by_sched[jobs[m].scheduler_id] = by_sched.get(jobs[m].scheduler_id, 0) + 1
        done = sum(1 for m in members if a.states[m].done)
        return {"id": pid, "name": bp.name, "description": bp.description, "owner": bp.owner,
                "criticality": bp.criticality, "regulatory": bp.regulatory,
                "sla": bp.sla_deadline.strftime("%H:%M"), "sla_description": bp.sla_description,
                "deadline": _iso(fc.deadline), "status": fc.status, "breach_probability": fc.breach_probability,
                "projected_p50": _iso(fc.p50_end), "projected_p90": _iso(fc.p90_end),
                "usual_end": _iso(fc.usual_end), "slack_min": fc.slack_min,
                "services": [a.services[s].model_dump() for s in bp.services],
                "job_count": len(members), "jobs_done": done, "jobs_by_scheduler": by_sched,
                "failed_jobs": [m for m in members if a.states[m].failed_attempts],
                "critical_path": fc.critical_path, "anchor_jobs": bp.anchor_jobs}

    def insight_dict(self, i: Insight) -> dict[str, Any]:
        d = dict(i.__dict__)
        d["detected_at"] = _iso(i.detected_at)
        return d

    # ------------------------------------------------------------------ queries
    def meta(self) -> dict[str, Any]:
        sc = SCENARIOS[self.scenario_id]
        return {"scenario": {"id": sc.id, "name": sc.name, "summary": sc.summary,
                             "talking_points": list(sc.talking_points)},
                "now": _iso(self.a.estate.now), "business_date": self.a.estate.business_date,
                "timezone": settings.estate_timezone,
                "scenarios": [{"id": s.id, "name": s.name} for s in SCENARIOS.values()],
                "adapters_registered": registry.registered()}

    def connectors(self) -> list[dict[str, Any]]:
        a = self.a
        out = []
        for sid, sch in a.estate.schedulers.items():
            jobs = [j for j in a.estate.jobs().values() if j.scheduler_id == sid]
            st = [a.states[j.id] for j in jobs]
            out.append({**sch.model_dump(), **a.estate.sync_stats[sid],
                        "tonight": {s.value: sum(1 for x in st if x.status == s) for s in RunStatus},
                        "failed_tonight": sum(1 for x in st if x.failed_attempts),
                        "anomalies": sum(1 for j in jobs if j.id in a.engine._anomaly_cache),
                        "cross_links": sum(1 for d in a.estate.dependencies().values()
                                           if d.cross_scheduler and sid in (a.estate.jobs()[d.source].scheduler_id,
                                                                            a.estate.jobs()[d.target].scheduler_id))})
        return out

    def native_sample(self, sid: str) -> dict[str, Any]:
        adapter = self.adapters[sid]
        native = adapter.native_sample()
        defs = native["definitions"]
        runs = native["runs"]
        # Trim run history for display: keep tonight's records.
        bd = self.a.estate.business_date
        if isinstance(runs, dict):
            for k, v in runs.items():
                if isinstance(v, list):
                    tonight = [r for r in v if bd.replace("-", "")[2:] in str(r) or bd in str(r)
                               or self.a.estate.now.strftime("%m/%d/%Y") in str(r)]
                    runs = {**runs, k: (tonight or v)[-12:]}
        return {"vendor": adapter.vendor, "definitions": defs, "runs": runs}

    def overview(self) -> dict[str, Any]:
        a = self.a
        states = a.states.values()
        cross = [d for d in a.estate.dependencies().values() if d.cross_scheduler]
        return {
            "meta": self.meta(),
            "kpis": {
                "schedulers": len(a.estate.schedulers), "jobs": len(a.estate.jobs()),
                "dependencies": len(a.estate.dependencies()), "cross_scheduler_links": len(cross),
                "inferred_links": sum(1 for d in cross if d.origin.value == "inferred"),
                "running": sum(1 for s in states if s.status == RunStatus.RUNNING),
                "succeeded": sum(1 for s in states if s.status == RunStatus.SUCCEEDED),
                "failed": sum(1 for s in states if s.failed_attempts),
                "waiting": sum(1 for s in states if s.status in (RunStatus.WAITING, RunStatus.SCHEDULED)),
                "processes_at_risk": sum(1 for f in a.proc_fc.values()
                                         if f.status in ("at-risk", "breach-likely", "breached")),
                "anomalies": len(a.engine._anomaly_cache),
                "history_runs": sum(len(v) for v in a.estate.runs_by_job.values()),
            },
            "connectors": self.connectors(),
            "processes": [self.process_brief(p) for p in a.mapper.processes],
            "insights": [self.insight_dict(i) for i in a.insights[:6]],
        }

    def jobs(self, scheduler: str | None = None, q: str | None = None, process: str | None = None) -> list[dict]:
        a = self.a
        ids = list(a.estate.jobs())
        if scheduler:
            ids = [j for j in ids if a.estate.jobs()[j].scheduler_id == scheduler]
        if process:
            ids = [j for j in ids if j in a.mapper.members.get(process, set())]
        if q:
            ql = q.lower()
            ids = [j for j in ids if ql in j.lower() or ql in (a.estate.jobs()[j].application or "").lower()]
        return [self.job_brief(j) for j in ids]

    def job_detail(self, jid: str) -> dict[str, Any]:
        a = self.a
        job = a.estate.jobs()[jid]
        b = a.baselines[jid]
        runs = a.estate.runs_for(jid)
        deps = a.estate.dependencies().values()
        return {**self.job_brief(jid), "definition": job.model_dump(mode="json"),
                "baseline": {"p50": round(b.p50, 1), "p90": round(b.p90, 1), "p95": round(b.p95, 1),
                             "failure_rate": round(b.failure_rate, 3), "nights": b.nights},
                "runs": [r.model_dump(mode="json") for r in runs[-45:]],
                "upstream": [{"dependency": d.model_dump(mode="json"), "job": self.job_brief(d.source)}
                             for d in deps if d.target == jid],
                "downstream": [{"dependency": d.model_dump(mode="json"), "job": self.job_brief(d.target)}
                               for d in deps if d.source == jid],
                "impact": a.engine.impact_of(jid), "root_cause": a.engine.root_cause_for(jid),
                "anomaly": a.engine._anomaly_cache.get(jid),
                "insights": [i.id for i in a.insights if jid in i.job_ids]}

    def graph(self, process: str | None = None, cross_only: bool = False) -> dict[str, Any]:
        a = self.a
        nodes = set(a.estate.jobs())
        if process:
            nodes = set(a.mapper.members[process])
        edges = [d for d in a.estate.dependencies().values() if d.source in nodes and d.target in nodes]
        if cross_only:
            keep = {d.source for d in edges if d.cross_scheduler} | {d.target for d in edges if d.cross_scheduler}
            nodes &= keep
            edges = [d for d in edges if d.cross_scheduler]
        crit = set()
        if process:
            crit = set(a.proc_fc[process].critical_path)
        return {"nodes": [{**self.job_brief(n), "critical": n in crit} for n in sorted(nodes)],
                "edges": [{**d.model_dump(mode="json"),
                           "active": d in a.graph.edges,
                           "critical": d.source in crit and d.target in crit} for d in edges],
                "schedulers": [s.model_dump() for s in a.estate.schedulers.values()]}

    def process_detail(self, pid: str) -> dict[str, Any]:
        a = self.a
        brief = self.process_brief(pid)
        members = a.mapper.members[pid]
        timeline = []
        for jid in a.graph.topo_order(set(members)):
            st = a.states[jid]
            usual_end = a.baselines[jid].typical_end_offset
            timeline.append({**self.job_brief(jid),
                             "usual_end_offset_min": usual_end, "critical": jid in a.proc_fc[pid].critical_path,
                             "failed_runs": [r.model_dump(mode="json") for r in st.failed_attempts]})
        insights = [self.insight_dict(i) for i in a.insights if pid in i.process_ids]
        return {**brief, "timeline": timeline, "graph": self.graph(process=pid), "insights": insights,
                "history": self._process_history(pid)}

    def _process_history(self, pid: str) -> list[dict[str, Any]]:
        a = self.a
        bp = a.mapper.processes[pid]
        out = []
        for d in sorted({r.business_date for r in a.estate.runs_for(bp.anchor_jobs[0])}):
            if d == a.estate.business_date:
                continue
            ends = [r.end for aj in bp.anchor_jobs for r in a.estate.runs_for(aj)
                    if r.business_date == d and r.end and r.status == RunStatus.SUCCEEDED]
            if ends:
                e = max(ends)
                deadline = datetime.combine(date.fromisoformat(d).fromordinal(date.fromisoformat(d).toordinal() + 1),
                                            bp.sla_deadline)
                out.append({"business_date": d, "end": _iso(e),
                            "slack_min": round((deadline - e).total_seconds() / 60, 1)})
        return out

    def insights(self, type_: str | None = None) -> list[dict[str, Any]]:
        return [self.insight_dict(i) for i in self.a.insights if not type_ or i.type == type_]

    def insight(self, iid: str) -> dict[str, Any] | None:
        i = next((x for x in self.a.insights if x.id == iid), None)
        return self.insight_dict(i) if i else None

    # ------------------------------------------------------------------ commands
    def execute_action(self, job_id: str, action: str, actor: str, note: str = "") -> dict[str, Any]:
        with self._lock:
            job = self.a.estate.jobs()[job_id]
            result = self.adapters[job.scheduler_id].execute(job, action)
            entry = {"at": _iso(self.a.estate.now), "actor": actor, "job_id": job_id, "action": action,
                     "vendor": job.vendor.value, "note": note, **result}
            self.a.estate.audit.append(entry)
            return entry

    def notify(self, process_id: str, actor: str) -> dict[str, Any]:
        bp = self.a.mapper.processes[process_id]
        fc = self.a.proc_fc[process_id]
        entry = {"at": _iso(self.a.estate.now), "actor": actor, "process_id": process_id, "action": "notify",
                 "command": f"notify → {bp.owner}",
                 "message": (f"Heads-up: '{bp.name}' is projected to finish {fc.p50_end:%H:%M} "
                             f"(P90 {fc.p90_end:%H:%M}) against the {bp.sla_deadline:%H:%M} SLA."),
                 "receipt": {"accepted": True, "simulated": True, "channel": "email/teams (simulated)"}}
        self.a.estate.audit.append(entry)
        return entry

    def review_dependency(self, dep_id: str, decision: str, actor: str) -> dict[str, Any]:
        with self._lock:
            d = self.a.estate.dependencies()[dep_id]
            d.review_state = "confirmed" if decision == "confirm" else "rejected"
            self.a.estate.audit.append({"at": _iso(self.a.estate.now), "actor": actor, "action": decision,
                                        "dependency_id": dep_id, "command": f"lineage {decision}",
                                        "receipt": {"accepted": True}})
            self.reanalyse()
            return d.model_dump(mode="json")

    def audit(self) -> list[dict[str, Any]]:
        return list(reversed(self.a.estate.audit))
