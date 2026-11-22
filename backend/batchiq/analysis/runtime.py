"""Runtime analysis: what 30 nights of run history say about how the estate behaves.

Static analysis says what could go wrong. Run history says what does, how
often, and what it costs. Each rule yields `Finding`s with the numbers behind
them.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from batchiq.analysis.context import AnalysisInputs
from batchiq.analysis.findings import SEVERITY_ORDER, Finding
from batchiq.analysis.static import race_nights
from batchiq.domain.models import DependencyOrigin, JobKind, RunStatus

Rule = Callable[[AnalysisInputs], Iterable[Finding]]


def _night_offset(bd: str, t: datetime) -> float:
    return (t - (datetime.fromisoformat(bd) + timedelta(hours=20))).total_seconds() / 60


def _hhmm(offset_min: float) -> str:
    return (datetime(2000, 1, 1, 20) + timedelta(minutes=offset_min)).strftime("%H:%M")


def sensor_waste(x: AnalysisInputs) -> Iterable[Finding]:
    for j in x.jobs.values():
        if j.kind != JobKind.SENSOR:
            continue
        runs = [r for r in x.estate.history_runs(j.id) if r.status == RunStatus.SUCCEEDED and r.duration_s]
        if len(runs) < 10:
            continue
        waits = [r.duration_s / 60 for r in runs]
        med = statistics.median(waits)
        if med < 30:
            continue
        ends = sorted(_night_offset(r.business_date, r.end) for r in runs)
        p10 = ends[max(0, len(ends) // 10 - 1)]
        mode = j.attributes.get("mode", "poke")
        yield Finding(
            f"rt-sensor-{j.id}", "runtime", "sensor-waste", "medium" if med > 120 else "low",
            f"{j.name} pokes for {med / 60:.1f} hours a night",
            f"{j.name} starts {f'at {j.scheduled_time:%H:%M}' if j.scheduled_time else 'when its DAG is triggered'} in {mode} mode and holds a worker slot until its input "
            f"lands, a median {med:.0f} minutes ({med * 30 / 60:.0f} slot-hours a month). The input arrived "
            f"after {_hhmm(p10)} on 9 nights out of 10.",
            f"Switch to mode='reschedule' or a deferrable sensor, or start it at {_hhmm(p10 - 10)}. "
            "Better still, trigger on the upstream's completion instead of polling.",
            j.scheduler_id, [j.id], x.mapper.processes_for(j.id),
            metrics={"median_wait_min": round(med), "slot_hours_month": round(med * 30 / 60),
                     "suggested_start": _hhmm(p10 - 10)})


def duration_trends(x: AnalysisInputs) -> Iterable[Finding]:
    for j in x.jobs.values():
        if j.kind == JobKind.SENSOR:
            continue
        runs = sorted((r for r in x.estate.history_runs(j.id) if r.status == RunStatus.SUCCEEDED and r.duration_s),
                      key=lambda r: r.business_date)
        if len(runs) < 20:
            continue
        ys = [r.duration_s / 60 for r in runs]
        xs = list(range(len(ys)))
        slope, intercept = statistics.linear_regression(xs, ys)
        fit = [intercept + slope * i for i in xs]
        ss_res = sum((y - f) ** 2 for y, f in zip(ys, fit, strict=True))
        ss_tot = sum((y - statistics.fmean(ys)) ** 2 for y in ys) or 1.0
        r2 = 1 - ss_res / ss_tot
        weekly = slope * 7 / max(statistics.fmean(ys), 1e-6)
        if weekly < 0.03 or r2 < 0.4:
            continue
        procs = [p for p in x.mapper.processes_for(j.id) if j.id in x.proc_fc[p].critical_path] or \
            x.mapper.processes_for(j.id)
        detail = (f"{j.name}'s duration grew from about {fit[0]:.0f} to {fit[-1]:.0f} minutes over {len(ys)} "
                  f"nights, about {weekly:.0%} a week (R² {r2:.2f}).")
        sev, weeks = "low", None
        for p in procs:
            fc = x.proc_fc[p]
            if fc.usual_end:
                slack = (fc.deadline - fc.usual_end).total_seconds() / 60
                if slope > 0 and slack > 0:
                    weeks = slack / (slope * 7)
                    bp = x.mapper.processes[p]
                    detail += (f" '{bp.name}' usually finishes {slack:.0f} minutes before its "
                               f"{bp.sla_deadline:%H:%M} SLA; at this rate that margin is gone in about "
                               f"{weeks:.0f} weeks.")
                    sev = "high" if weeks < 6 else "medium" if weeks < 16 else "low"
                    break
        yield Finding(
            f"rt-trend-{j.id}", "runtime", "duration-trend", sev, f"{j.name} gets slower every night", detail,
            "Find what is growing (input volume, data skew, cluster size) and act before the SLA does it for you.",
            j.scheduler_id, [j.id], procs,
            metrics={"weekly_growth": round(weekly, 3), "r2": round(r2, 2),
                     "weeks_to_sla": round(weeks, 1) if weeks else None,
                     "series": [round(y, 1) for y in ys]})


def queueing_delays(x: AnalysisInputs) -> Iterable[Finding]:
    for j in x.jobs.values():
        parents = x.graph.parents(j.id)
        if not parents or j.kind == JobKind.SENSOR:
            continue
        gaps = []
        for night, (start, _) in x.windows.get(j.id, {}).items():
            ends = [x.windows[p][night][1] for p in parents if night in x.windows.get(p, {})]
            if len(ends) == len(parents):
                ready = max(ends)
                if j.scheduled_time:
                    sd = datetime.combine(datetime.fromisoformat(night).date(), j.scheduled_time)
                    ready = max(ready, sd if sd.hour >= 20 else sd + timedelta(days=1))
                gaps.append((start - ready).total_seconds() / 60)
        if len(gaps) >= 10 and statistics.median(gaps) > 5:
            med = statistics.median(gaps)
            yield Finding(
                f"rt-queue-{j.id}", "runtime", "queueing-delay", "medium" if x.tier1_processes(j.id) else "low",
                f"{j.name} waits {med:.0f} minutes after its inputs are ready",
                f"Every input of {j.name} is ready, then it starts a median {med:.0f} minutes later "
                f"(P90 {sorted(gaps)[int(len(gaps) * 0.9) - 1]:.0f}). That is time on the critical path doing nothing.",
                f"Look at the hand-off: file transfer (MFT) latency, agent or machine load on {j.host}, or a "
                "polling interval.", j.scheduler_id, [j.id], x.mapper.processes_for(j.id),
                metrics={"median_delay_min": round(med, 1)})


def failure_hotspots(x: AnalysisInputs) -> Iterable[Finding]:
    for j in x.jobs.values():
        fails = [r for r in x.estate.history_runs(j.id) if r.status == RunStatus.FAILED]
        nights = len({r.business_date for r in fails})
        if nights < 2:
            continue
        codes = Counter(r.error_code for r in fails)
        incidents = [i.id for i in x.estate.incidents if j.id in i.jobs]
        yield Finding(
            f"rt-fail-{j.id}", "runtime", "failure-hotspot", "medium" if nights >= 3 else "low",
            f"{j.name} failed on {nights} of the last 30 nights",
            f"Errors: {', '.join(f'{c} ×{n}' for c, n in codes.most_common())}."
            + (f" Related incidents: {', '.join(incidents)}." if incidents else ""),
            "Fix the cause rather than rerunning. A repeat failure on a critical path costs its rerun time "
            "every time it happens.", j.scheduler_id, [j.id], x.mapper.processes_for(j.id),
            metrics={"failed_nights": nights})


def critical_path_leverage(x: AnalysisInputs) -> Iterable[Finding]:
    for pid, fc in x.proc_fc.items():
        if fc.status == "done" or not fc.critical_path:
            continue
        bp = x.mapper.processes[pid]
        path = [j for j in fc.critical_path if x.jobs[j].kind != JobKind.SENSOR and x.baselines[j].p50 > 0]
        if not path:
            continue
        top = max(path, key=lambda j: x.baselines[j].p50)
        save = x.baselines[top].p50 * 0.2
        share = x.baselines[top].p50 / max(sum(x.baselines[j].p50 for j in path), 1)
        scheds = {x.jobs[j].scheduler_id for j in fc.critical_path}
        yield Finding(
            f"rt-lever-{pid}", "runtime", "critical-path-leverage", "info",
            f"{bp.name}: {x.jobs[top].name} is the biggest lever",
            f"The critical path has {len(fc.critical_path)} jobs across {len(scheds)} scheduler(s). "
            f"{x.jobs[top].name} is {share:.0%} of its run time. Cutting it by 20% gives back about "
            f"{save:.0f} minutes of slack. Speeding up anything off the path gives back nothing.",
            f"Tune {x.jobs[top].name} first (parallelism, warehouse size, input pruning).",
            "cross" if len(scheds) > 1 else x.jobs[top].scheduler_id, list(fc.critical_path), [pid],
            metrics={"minutes_saved": round(save), "share": round(share, 2)})


def stale_reads(x: AnalysisInputs) -> Iterable[Finding]:
    for d in x.estate.dependencies().values():
        if d.origin != DependencyOrigin.INFERRED or x.link_states.get(d.id) in (None, "rejected"):
            continue
        tgt = x.jobs[d.target]
        if tgt.scheduled_time is None:
            continue
        races, n, dates = race_nights(x, d.source, d.target)
        if races == 0:
            continue
        yield Finding(
            f"rt-stale-{d.id}", "runtime", "stale-read", "high" if races >= 3 else "medium",
            f"{tgt.name} ran before its data was ready on {races} nights",
            f"On {races} of {n} nights {tgt.name} started at {tgt.scheduled_time:%H:%M}, before "
            f"{x.jobs[d.source].name} had finished: {', '.join(dates[-4:])}. Its output those nights was built on "
            "stale or partial data.",
            "Approve the link and add the dependency in the scheduler, or move the start time past the upstream's "
            "P95 finish.", tgt.scheduler_id, [d.source, d.target], x.mapper.processes_for(d.target),
            metrics={"race_nights": races, "nights": n, "dates": dates}, link_id=d.id)


def host_load(x: AnalysisInputs) -> Iterable[Finding]:
    by_host: dict[str, list] = defaultdict(list)
    for jid, wins in x.windows.items():
        h = x.jobs[jid].host
        if h and x.jobs[jid].kind != JobKind.SENSOR:
            for night, (s, e) in wins.items():
                by_host[h].append((night, s, e))
    for host, rows in by_host.items():
        nights = defaultdict(list)
        for night, s, e in rows:
            nights[night].append((s, e))
        peaks = []
        for spans in nights.values():
            events = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans])
            cur = best = 0
            when = None
            for t, d in events:
                cur += d
                if cur > best:
                    best, when = cur, t
            peaks.append((best, when))
        med_peak = statistics.median(p for p, _ in peaks)
        if med_peak >= 4:
            members = [j for j in x.jobs if x.jobs[j].host == host]
            scheds = {x.jobs[j].scheduler_id for j in members}
            scope = scheds.pop() if len(scheds) == 1 else "cross"
            hours = Counter(w.strftime("%H:00") for _, w in peaks if w)
            yield Finding(
                f"rt-host-{host}", "runtime", "host-load", "low",
                f"{host} peaks at {med_peak:.0f} concurrent jobs",
                f"On a typical night {med_peak:.0f} jobs run at once on {host}, usually around "
                f"{hours.most_common(1)[0][0]}.",
                "If anything on this host runs slow at that hour, check contention before blaming the job.",
                scope, members,
                metrics={"median_peak": med_peak})


RULES: tuple[Rule, ...] = (sensor_waste, duration_trends, queueing_delays, failure_hotspots, critical_path_leverage,
                           stale_reads, host_load)


def run_runtime(x: AnalysisInputs, rules: tuple[Rule, ...] = RULES) -> list[Finding]:
    out = [f for rule in rules for f in rule(x)]
    return sorted(out, key=lambda f: (SEVERITY_ORDER[f.severity], f.category))
