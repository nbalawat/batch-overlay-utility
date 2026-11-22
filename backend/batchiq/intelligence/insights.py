"""Insight engine: anomalies, failures, SLA risk, impact, root-cause hints and
recommended actions. Deterministic and explainable: every insight carries the
evidence it was built from. The LLM layer narrates and answers questions on
top of these facts; it does not invent them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from batchiq.domain.models import JobKind, RunStatus

if TYPE_CHECKING:
    from batchiq.service import Analysis

VENDOR_LABEL = {"control-m": "Control-M", "autosys": "AutoSys", "airflow": "Airflow",
                "azure-data-factory": "Azure Data Factory"}
_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class Insight:
    id: str
    type: str                    # failure | sla_risk | anomaly | correlation
    severity: str
    title: str
    summary: str
    detected_at: datetime
    job_ids: list[str] = field(default_factory=list)
    process_ids: list[str] = field(default_factory=list)
    scheduler_ids: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    impact: dict[str, Any] = field(default_factory=dict)
    root_cause: list[dict[str, Any]] = field(default_factory=list)
    similar_incidents: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else "n/a"


class InsightEngine:
    def __init__(self, a: "Analysis") -> None:
        self.a = a

    # ------------------------------------------------------------------ public
    def run(self) -> list[Insight]:
        out: list[Insight] = []
        out += self._failures()
        out += self._sla_risks()
        out += self._anomalies()
        out += self._correlations()
        return sorted(out, key=lambda i: (_SEV_ORDER[i.severity], i.type != "sla_risk"))

    def anomalies(self) -> dict[str, dict[str, Any]]:
        """Duration anomalies tonight: job_id -> details."""
        found = {}
        for jid, st in self.a.states.items():
            job = self.a.estate.jobs()[jid]
            b = self.a.baselines[jid]
            if job.kind == JobKind.SENSOR or len(b.samples_min) < 10 or st.elapsed_min is None:
                continue
            if st.status not in (RunStatus.SUCCEEDED, RunStatus.RUNNING):
                continue
            x = st.elapsed_min
            mad = max(b.mad, 0.05 * b.p50, 0.5)
            z = 0.6745 * (x - b.p50) / mad
            running_flag = st.status == RunStatus.RUNNING and x > b.p95 * 1.1
            done_flag = st.status == RunStatus.SUCCEEDED
            if z > 3.5 and x - b.p50 > 5 and (running_flag or done_flag):
                found[jid] = {"observed_min": round(x, 1), "p50_min": round(b.p50, 1),
                              "p95_min": round(b.p95, 1), "robust_z": round(z, 1),
                              "ratio": round(x / b.p50, 2) if b.p50 else None, "running": st.status == RunStatus.RUNNING}
        return found

    def impact_of(self, job_id: str) -> dict[str, Any]:
        desc = self.a.graph.descendants(job_id)
        jobs = self.a.estate.jobs()
        by_sched: dict[str, int] = {}
        for d in desc:
            by_sched[jobs[d].scheduler_id] = by_sched.get(jobs[d].scheduler_id, 0) + 1
        procs = []
        for pid in self.a.mapper.processes_for(job_id):
            bp, fc = self.a.mapper.processes[pid], self.a.proc_fc[pid]
            procs.append({"id": pid, "name": bp.name, "criticality": bp.criticality, "status": fc.status,
                          "breach_probability": fc.breach_probability, "sla": bp.sla_deadline.strftime("%H:%M"),
                          "projected_p50": _fmt(fc.p50_end), "regulatory": bp.regulatory})
        services = sorted({s for p in self.a.mapper.processes_for(job_id)
                           for s in self.a.mapper.processes[p].services})
        return {"downstream_jobs": len(desc), "downstream_by_scheduler": by_sched,
                "cross_scheduler_hops": sum(1 for s in by_sched if s != jobs[job_id].scheduler_id),
                "processes": procs, "services": [self.a.services[s].name for s in services]}

    def root_cause_for(self, job_id: str, critical: set[str] | None = None) -> list[dict[str, Any]]:
        """Ranked hypotheses for why `job_id` is failing, late or at risk.

        `critical` (a process's critical path) demotes problems that sit on a
        branch which is not actually holding the process back.
        """
        jobs, states = self.a.estate.jobs(), self.a.states
        anomalies = self._anomaly_cache
        hyps: list[dict[str, Any]] = []
        candidates = [job_id] + sorted(self.a.graph.ancestors(job_id), key=lambda j: self.a.graph.ancestors(job_id)[j])
        for cand in candidates:
            st, job = states[cand], jobs[cand]
            depth = 0 if cand == job_id else self.a.graph.ancestors(job_id)[cand]
            if st.failed_attempts:
                f = st.failed_attempts[-1]
                hyps.append({"job_id": cand, "kind": "failure", "confidence": 0.9 if depth else 0.95,
                             "reason": f"{job.name} ({VENDOR_LABEL[job.vendor.value]}) failed at {_fmt(f.end)} with {f.error_code}: "
                                       f"{(f.message or '')[:140]}",
                             "depth": depth})
            elif cand in anomalies:
                an = anomalies[cand]
                off_path = critical is not None and cand not in critical
                hyps.append({"job_id": cand, "kind": "slow", "confidence": 0.25 if off_path else 0.75,
                             "reason": f"{job.name} ({VENDOR_LABEL[job.vendor.value]}) has run {an['observed_min']} min against a "
                                       f"usual {an['p50_min']} min ({an['ratio']}x)."
                                       + (" It is off the critical path, so it is not driving the delay."
                                          if off_path else ""), "depth": depth})
        # Shared infrastructure: several anomalies on one host/warehouse.
        hosts: dict[str, list[str]] = {}
        for jid in anomalies:
            if jobs[jid].host:
                hosts.setdefault(jobs[jid].host, []).append(jid)
        for host, members in hosts.items():
            shared = len(members) > 1 or host.split(":")[0] in ("snowflake", "databricks", "spark-k8s-risk")
            if shared and set(members) & set(candidates) and (critical is None or set(members) & critical):
                hyps.append({"job_id": members[0], "kind": "shared-resource", "confidence": 0.6,
                             "reason": f"Shared resource '{host}' is slow for {len(members)} job(s): "
                                       + ", ".join(jobs[m].name for m in members), "depth": 0})
        hyps.sort(key=lambda h: (-h["confidence"], -h["depth"]))
        # Deepest failure is the most likely origin: lift it to the top.
        failures = [h for h in hyps if h["kind"] == "failure"]
        if failures:
            origin = max(failures, key=lambda h: h["depth"])
            origin["confidence"] = 0.97
            origin["origin"] = True
            hyps.remove(origin)
            hyps.insert(0, origin)
        return hyps

    def similar_incidents(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        return [{"id": i.id, "date": i.date, "title": i.title, "score": round(s, 2),
                 "root_cause": i.root_cause, "resolution": i.resolution, "mttr_minutes": i.mttr_minutes}
                for i, s in self.a.kb.search(query, k)]

    # ------------------------------------------------------------------ builders
    @property
    def _anomaly_cache(self) -> dict[str, dict[str, Any]]:
        if not hasattr(self, "_anoms"):
            self._anoms = self.anomalies()
        return self._anoms

    def _severity_from_processes(self, procs: list[dict[str, Any]]) -> str:
        if any(p["status"] in ("breach-likely", "breached") and p["criticality"] == "tier-1" for p in procs):
            return "critical"
        if any(p["status"] in ("breach-likely", "breached", "at-risk") for p in procs):
            return "high"
        return "medium" if procs else "low"

    def _failures(self) -> list[Insight]:
        out = []
        jobs = self.a.estate.jobs()
        for jid, st in self.a.states.items():
            if not st.failed_attempts:
                continue
            job, f = jobs[jid], st.failed_attempts[-1]
            impact = self.impact_of(jid)
            sim = self.similar_incidents(f"{f.error_code} {job.name} {f.message} {job.vendor.value}")
            rerun_state = ("A rerun is in progress since " + _fmt(st.start)) if st.status == RunStatus.RUNNING else (
                "Recovered" if st.done else "No rerun yet")
            recs = []
            if sim:
                recs.append({"id": f"rec-kb-{jid}", "title": f"Apply the fix from {sim[0]['id']}",
                             "rationale": sim[0]["resolution"], "source": "knowledge-base"})
            if st.status == RunStatus.FAILED:
                recs.append({"id": f"rec-rerun-{jid}", "title": f"Rerun {job.name} after the data fix",
                             "rationale": "Restart from the failed step once the input is corrected.",
                             "action": {"job_id": jid, "action": "rerun"}})
            recs += self._sla_recs(impact)
            out.append(Insight(
                id=f"ins-fail-{job.native_id}", type="failure",
                severity=self._severity_from_processes(impact["processes"]),
                title=f"{job.name} failed in {self.a.estate.schedulers[job.scheduler_id].name.split(' (')[0]}"
                      f" ({f.error_code})",
                summary=(f"{job.name} failed at {_fmt(f.end)} with {f.error_code}. {rerun_state}. "
                         f"It feeds {impact['downstream_jobs']} downstream jobs in "
                         + ", ".join(self.a.estate.schedulers[x].name.split(' (')[0]
                                     for x in impact['downstream_by_scheduler'])
                         + f", which support {len(impact['processes'])} business processes."),
                detected_at=f.end or self.a.estate.now, job_ids=[jid],
                process_ids=[p["id"] for p in impact["processes"]],
                scheduler_ids=sorted({job.scheduler_id, *impact["downstream_by_scheduler"]}),
                evidence=[f"{f.error_code}: {f.message}"], impact=impact,
                root_cause=self.root_cause_for(jid), similar_incidents=sim, recommendations=recs))
        return out

    def _sla_recs(self, impact: dict[str, Any]) -> list[dict[str, Any]]:
        recs = []
        for p in impact["processes"]:
            if p["status"] not in ("at-risk", "breach-likely"):
                continue
            fc = self.a.proc_fc[p["id"]]
            nxt = [j for j in fc.critical_path if not self.a.states[j].done
                   and self.a.states[j].status != RunStatus.RUNNING
                   and self.a.estate.jobs()[j].kind != JobKind.SENSOR]
            seen_sched = set()
            for j in nxt:
                job = self.a.estate.jobs()[j]
                if job.scheduler_id in seen_sched:
                    continue
                seen_sched.add(job.scheduler_id)
                recs.append({"id": f"rec-boost-{p['id']}-{job.scheduler_id}",
                             "title": f"Boost priority / capacity for {job.container} in {VENDOR_LABEL[job.vendor.value]}",
                             "rationale": f"{job.name} is the next job on the critical path for "
                                          f"'{p['name']}'. Historical boosts recovered around 20-25 minutes.",
                             "action": {"job_id": j, "action": "boost_priority"}})
            bp = self.a.mapper.processes[p["id"]]
            recs.append({"id": f"rec-notify-{p['id']}", "title": f"Pre-alert {bp.owner}",
                         "rationale": f"Projected finish {p['projected_p50']} against the {p['sla']} SLA "
                                      f"({int(p['breach_probability'] * 100)}% breach probability).",
                         "action": {"process_id": p["id"], "action": "notify"}})
            if bp.regulatory and p["breach_probability"] >= 0.5:
                recs.append({"id": f"rec-ext-{p['id']}", "title": "Prepare a regulator extension notice",
                             "rationale": "Past incident INC-20260702-0233 needed an extension. Drafting it now "
                                          "keeps the option open without committing to it."})
        return recs

    def _sla_risks(self) -> list[Insight]:
        out = []
        for pid, fc in self.a.proc_fc.items():
            if fc.status not in ("at-risk", "breach-likely", "breached") or (
                    fc.status == "breached" and all(self.a.states[x].done for x in self.a.mapper.processes[pid].anchor_jobs)):
                continue
            bp = self.a.mapper.processes[pid]
            anchor = bp.anchor_jobs[0]
            rc = self.root_cause_for(anchor, set(fc.critical_path))
            impact = {"processes": [{"id": pid, "name": bp.name, "criticality": bp.criticality,
                                     "status": fc.status, "breach_probability": fc.breach_probability,
                                     "sla": bp.sla_deadline.strftime("%H:%M"), "projected_p50": _fmt(fc.p50_end),
                                     "regulatory": bp.regulatory}],
                      "services": [self.a.services[s].name for s in bp.services]}
            origin = rc[0] if rc else None
            jobs = self.a.estate.jobs()
            path_scheds = sorted({jobs[j].scheduler_id for j in fc.critical_path})
            sim = self.similar_incidents(origin["reason"] if origin else bp.name)
            sev = "critical" if (fc.breach_probability >= 0.6 and bp.criticality == "tier-1") else (
                "high" if fc.breach_probability >= 0.4 else "medium")
            out.append(Insight(
                id=f"ins-sla-{pid}", type="sla_risk", severity=sev,
                title=f"{bp.name}: {int(fc.breach_probability * 100)}% chance of missing {bp.sla_deadline.strftime('%H:%M')}",
                summary=(f"Projected finish {_fmt(fc.p50_end)} (P90 {_fmt(fc.p90_end)}) against an SLA of "
                         f"{bp.sla_deadline.strftime('%H:%M')}; it usually finishes around {_fmt(fc.usual_end)}. "
                         f"The critical path crosses {len(path_scheds)} schedulers."
                         + (f" Most likely cause: {origin['reason']}" if origin else "")),
                detected_at=self.a.estate.now, job_ids=fc.critical_path, process_ids=[pid],
                scheduler_ids=path_scheds,
                evidence=[f"Monte Carlo over {400} simulations using 30 nights of history",
                          f"Slack at P50: {fc.slack_min:+.0f} min"],
                impact=impact, root_cause=rc, similar_incidents=sim, recommendations=self._sla_recs(impact)))
        return out

    def _anomalies(self) -> list[Insight]:
        out = []
        jobs = self.a.estate.jobs()
        for jid, an in self._anomaly_cache.items():
            job = jobs[jid]
            impact = self.impact_of(jid)
            harmful = any(p["status"] in ("at-risk", "breach-likely")
                          and jid in self.a.proc_fc[p["id"]].critical_path for p in impact["processes"])
            sim = self.similar_incidents(f"{job.name} slow duration {job.host} {job.vendor.value}")
            recs = []
            if harmful:
                recs.append({"id": f"rec-scale-{jid}", "title": f"Add capacity on {job.host}",
                             "rationale": "The slowdown sits on the critical path. "
                                          + (sim[0]["resolution"] if sim else ""),
                             "action": {"job_id": jid, "action": "boost_priority"}})
                recs += self._sla_recs(impact)
            else:
                recs.append({"id": f"rec-monitor-{jid}", "title": "No action needed: monitor only",
                             "rationale": "Downstream jobs are bound by other inputs, so this delay does not "
                                          "move any business SLA. The overlay suppresses the page."})
            out.append(Insight(
                id=f"ins-anom-{job.native_id}", type="anomaly",
                severity="high" if harmful else "low",
                title=f"{job.name} is running {an['ratio']}x its usual duration",
                summary=(f"{'Running' if an['running'] else 'Ran'} {an['observed_min']} min against a usual "
                         f"{an['p50_min']} min (robust z={an['robust_z']}). "
                         + ("It is on a critical path and is moving an SLA." if harmful else
                            "It is not on any at-risk critical path: downstream jobs are waiting on other inputs.")),
                detected_at=self.a.estate.now, job_ids=[jid],
                process_ids=[p["id"] for p in impact["processes"]], scheduler_ids=[job.scheduler_id],
                evidence=[f"Baseline from {len(self.a.baselines[jid].samples_min)} successful runs",
                          f"P95 {an['p95_min']} min"],
                impact=impact, root_cause=self.root_cause_for(jid), similar_incidents=sim, recommendations=recs))
        return out

    def _correlations(self) -> list[Insight]:
        out = []
        jobs = self.a.estate.jobs()
        for d in self.a.estate.dependencies().values():
            if d.review_state != "suggested":
                continue
            s, t = jobs[d.source], jobs[d.target]
            out.append(Insight(
                id=f"ins-corr-{d.id}", type="correlation", severity="info",
                title=f"Hidden dependency: {t.name} ({VENDOR_LABEL[t.vendor.value]}) depends on {s.name} ({VENDOR_LABEL[s.vendor.value]})",
                summary=("No scheduler declares this link. It was inferred with "
                         f"{int(d.confidence * 100)}% confidence. Confirm it to make it part of the lineage."),
                detected_at=self.a.estate.now, job_ids=[d.source, d.target],
                process_ids=self.a.mapper.processes_for(d.target), scheduler_ids=[s.scheduler_id, t.scheduler_id],
                evidence=[e.detail for e in d.evidence],
                recommendations=[{"id": f"rec-confirm-{d.id}", "title": "Confirm the dependency",
                                  "rationale": "Confirmed links feed impact analysis and SLA forecasts.",
                                  "action": {"dependency_id": d.id, "action": "confirm"}}]))
        return out
