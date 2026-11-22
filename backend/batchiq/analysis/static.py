"""Static analysis: what the definitions, the code and the links say, before anything runs.

Each rule is a small function over `AnalysisInputs` that yields `Finding`s with
evidence. Rules look inside one ecosystem (scope = scheduler id) or across them
(scope = "cross"). Add a rule by appending a function to `RULES`.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable

from batchiq.analysis.context import AnalysisInputs
from batchiq.analysis.findings import SEVERITY_ORDER, Finding
from batchiq.domain.models import DependencyOrigin
from batchiq.knowledge.ontology import EdgeType, NodeType

_V = {"control-m": "Control-M", "autosys": "AutoSys", "airflow": "Airflow", "azure-data-factory": "ADF"}
Rule = Callable[[AnalysisInputs], Iterable[Finding]]


def _name(x: AnalysisInputs, jid: str) -> str:
    j = x.jobs[jid]
    return f"{j.name} ({_V[j.vendor.value]})"


def race_nights(x: AnalysisInputs, a: str, b: str) -> tuple[int, int, list[str]]:
    """Nights where b started before a finished: (races, nights compared, dates)."""
    wa, wb = x.windows.get(a, {}), x.windows.get(b, {})
    common = sorted(set(wa) & set(wb))
    bad = [n for n in common if wb[n][0] < wa[n][1]]
    return len(bad), len(common), bad


# ---------------------------------------------------------------------- intra-ecosystem rules
def dead_conditions(x: AnalysisInputs) -> Iterable[Finding]:
    for j in x.jobs.values():
        if not j.unresolved_conditions:
            continue
        ran = len({r.business_date for r in x.estate.history_runs(j.id)})
        yield Finding(
            f"st-dead-{j.id}", "static", "dead-condition", "medium" if ran == 0 else "high",
            f"{j.name} waits on a condition nothing provides",
            f"{_name(x, j.id)} waits for {', '.join(j.unresolved_conditions)}, but no job in "
            f"{x.estate.schedulers[j.scheduler_id].name} adds it. It has run on {ran} of the last 30 nights.",
            "Remove the condition or retire the job. If its work still matters, find the job that replaced the "
            "decommissioned upstream and wait on that instead.",
            j.scheduler_id, [j.id], evidence=[f"Unresolved: {c}" for c in j.unresolved_conditions],
            metrics={"runs_30d": ran})


def missing_dependencies(x: AnalysisInputs) -> Iterable[Finding]:
    """Code reads another job's output, but the job starts on its own clock and nothing makes it wait."""
    for d in x.deps():
        state = x.link_states.get(d.id)
        if d.origin != DependencyOrigin.INFERRED or state in (None, "rejected"):
            continue
        tgt, src = x.jobs[d.target], x.jobs[d.source]
        kinds = {e.kind for e in d.evidence}
        if tgt.scheduled_time is None or not kinds & {"code-artifact-match", "queue-match"}:
            continue
        races, n, dates = race_nights(x, d.source, d.target)
        sev = "high" if races >= 3 or (races and x.tier1_processes(d.target)) else "medium" if races else "low"
        what = d.artifact.split(":", 1)[1] if d.artifact else "its output"
        changed = x.change_for_job.get(d.target)
        scope = tgt.scheduler_id if src.scheduler_id == tgt.scheduler_id else "cross"
        yield Finding(
            f"st-missing-{d.id}", "static", "missing-dependency", sev,
            f"{tgt.name} reads {what} from {src.name} but does not wait for it",
            f"{_name(x, d.target)} starts at {tgt.scheduled_time:%H:%M} on its own clock. Its code reads {what}, "
            f"which {_name(x, d.source)} produces. In {races} of {n} nights it started before that was ready."
            + (f" The time-based start was introduced by {changed}." if changed else ""),
            ("The owners confirmed the link, so the overlay now forecasts and alerts on it. The scheduler still "
             "does not enforce it: add a condition or a file/dataset trigger." if state == "approved" else
             "Make the dependency explicit: a condition or file/dataset trigger in the scheduler, or approve the "
             "link so the overlay forecasts and alerts on it."),
            scope, [d.source, d.target], x.mapper.processes_for(d.target),
            evidence=[e.detail for e in d.evidence if e.kind != "runtime-order"],
            metrics={"race_nights": races, "nights": n, "race_dates": dates[-5:], "review_state": state},
            link_id=d.id)


def redundant_dependencies(x: AnalysisInputs) -> Iterable[Finding]:
    declared = defaultdict(set)
    for d in x.deps():
        if d.origin == DependencyOrigin.DECLARED:
            declared[d.target].add(d.source)
    for tgt, ups in declared.items():
        for a in ups:
            others = ups - {a}
            # a is redundant if it is already upstream of another direct parent
            via = next((o for o in others if a in x.graph.ancestors(o)), None)
            if via:
                yield Finding(
                    f"st-redundant-{a}->{tgt}", "static", "redundant-dependency", "low",
                    f"{x.jobs[tgt].name} waits on {x.jobs[a].name} twice",
                    f"{_name(x, tgt)} has a direct condition on {x.jobs[a].name}, which is already upstream "
                    f"through {x.jobs[via].name}.",
                    "Drop the direct condition. It adds nothing, and it makes the flow harder to read and change.",
                    x.jobs[tgt].scheduler_id, [a, via, tgt])


def unmonitored(x: AnalysisInputs) -> Iterable[Finding]:
    for j in x.jobs.values():
        if j.alerting is False:
            t1 = x.tier1_processes(j.id)
            yield Finding(
                f"st-unmonitored-{j.id}", "static", "unmonitored", "high" if t1 else "medium",
                f"{j.name} raises no alert when it fails",
                f"{_name(x, j.id)} has alerting switched off in its definition"
                + (f" and supports {len(t1)} tier-1 process(es)." if t1 else "."),
                "Turn on the scheduler's failure alert, or let the overlay own alerting for this job.",
                j.scheduler_id, [j.id], x.mapper.processes_for(j.id))


def plaintext_secrets(x: AnalysisInputs) -> Iterable[Finding]:
    for jid, facts in x.mined.items():
        for f in facts:
            if f.object_type == "secret":
                yield Finding(
                    f"st-secret-{jid}", "static", "plaintext-secret", "high",
                    f"{x.jobs[jid].name} has a password in its script",
                    f"{f.path} line {f.line} assigns {f.detail.get('variable', 'a credential')} as a string "
                    f"literal. The value is not shown here.",
                    "Move it to the vault the scheduler already uses and rotate the credential.",
                    x.jobs[jid].scheduler_id, [jid], evidence=[f"{f.path}:{f.line} ({f.rule})"])


def data_boundaries(x: AnalysisInputs) -> Iterable[Finding]:
    """Outputs nobody reads and inputs nobody in the estate produces."""
    kg = x.kg
    for sid in x.estate.schedulers:
        orphans, externals = [], []
        for n in kg.nodes.values():
            if n.type not in (NodeType.FILE, NodeType.DATASET):
                continue
            writers = [e.source for e in kg.edges_of(n.id, "in", {EdgeType.WRITES})]
            readers = [e.source for e in kg.edges_of(n.id, "in", {EdgeType.READS, EdgeType.TRIGGERED_BY})]
            if writers and not readers and x.jobs[writers[0]].scheduler_id == sid:
                orphans.append((n.label, writers[0]))
            if readers and not writers and any(x.jobs[r].scheduler_id == sid for r in readers):
                externals.append((n.label, [r for r in readers if x.jobs[r].scheduler_id == sid]))
        if orphans:
            yield Finding(
                f"st-orphan-{sid}", "static", "orphan-output", "low",
                f"{len(orphans)} output(s) in {x.estate.schedulers[sid].name} that no job reads",
                "; ".join(f"{label} (written by {x.jobs[w].name})" for label, w in orphans),
                "Confirm each output has a consumer outside the batch estate (MFT, a downstream system) and record "
                "it, or stop producing it.", sid, [w for _, w in orphans])
        if externals:
            yield Finding(
                f"st-external-{sid}", "static", "external-input", "info",
                f"{len(externals)} input(s) in {x.estate.schedulers[sid].name} come from outside the batch estate",
                "; ".join(f"{label} (read by {', '.join(x.jobs[r].name for r in rs)})" for label, rs in externals),
                "These are source systems or manual loads. Record their owners so an outage upstream is visible.",
                sid, [r for _, rs in externals for r in rs])


def egress(x: AnalysisInputs) -> Iterable[Finding]:
    by_sched: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for e in x.kg.edges.values():
        if e.type in (EdgeType.TRANSFERS_TO, EdgeType.CALLS) and not x.kg.nodes[e.target].props.get("internal", True):
            by_sched[x.jobs[e.source].scheduler_id].append((e.source, x.kg.nodes[e.target].label, e.type.value))
    for sid, rows in by_sched.items():
        yield Finding(
            f"st-egress-{sid}", "static", "external-egress", "info",
            f"{len(rows)} job(s) in {x.estate.schedulers[sid].name} send data outside the bank",
            "; ".join(f"{x.jobs[j].name} → {host}" for j, host, _ in rows),
            "None of this shows in the scheduler. Check each against the third-party data-sharing register.",
            sid, [j for j, _, _ in rows], evidence=[f"{x.jobs[j].name} {rel.lower()} {h}" for j, h, rel in rows])


# ---------------------------------------------------------------------- cross-ecosystem rules
def single_points_of_failure(x: AnalysisInputs) -> Iterable[Finding]:
    scored = []
    for jid in x.jobs:
        desc = x.graph.descendants(jid)
        procs = {p for d in list(desc) + [jid] for p in x.mapper.processes_for(d)}
        scheds = {x.jobs[d].scheduler_id for d in desc} | {x.jobs[jid].scheduler_id}
        if len(procs) >= 3 and len(scheds) >= 2:
            scored.append((len(procs), len(desc), jid, procs, scheds))
    scored.sort(reverse=True)
    for n_procs, n_desc, jid, procs, scheds in scored[:3]:
        tier1 = sorted(p for p in procs if x.mapper.processes[p].criticality == "tier-1")
        yield Finding(
            f"st-spof-{jid}", "static", "single-point-of-failure", "high" if len(tier1) >= 3 else "medium",
            f"{x.jobs[jid].name} sits under {n_procs} business processes",
            f"{_name(x, jid)} has {n_desc} downstream jobs across {len(scheds)} schedulers and feeds {n_procs} "
            f"processes, {len(tier1)} of them tier-1: {', '.join(x.mapper.processes[p].name for p in tier1)}.",
            "Give it the strongest controls: input validation, a rehearsed restart, pre-alerting of downstream "
            "owners, and the earliest possible start.", "cross", [jid], sorted(procs),
            metrics={"downstream_jobs": n_desc, "processes": n_procs, "schedulers": len(scheds)})


def host_concentration(x: AnalysisInputs) -> Iterable[Finding]:
    per_host: dict[str, set[str]] = defaultdict(set)
    procs: dict[str, set[str]] = defaultdict(set)
    for j in x.jobs.values():
        if j.host:
            per_host[j.host].add(j.id)
            procs[j.host] |= set(x.tier1_processes(j.id))
    for host, jobs in sorted(per_host.items(), key=lambda kv: -len(procs[kv[0]])):
        if len(procs[host]) >= 3:
            yield Finding(
                f"st-host-{host}", "static", "host-concentration", "medium",
                f"{len(procs[host])} tier-1 processes depend on {host}",
                f"{len(jobs)} jobs run on {host}, and they feed "
                f"{', '.join(x.mapper.processes[p].name for p in sorted(procs[host]))}.",
                "Make sure failover for this host is rehearsed inside the batch window, and that the overlay's "
                "impact view is the first thing the on-call engineer opens when it degrades.",
                "cross", sorted(jobs), sorted(procs[host]), metrics={"jobs": len(jobs)})


def cross_coupling(x: AnalysisInputs) -> Iterable[Finding]:
    pairs: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in x.deps():
        if not d.cross_scheduler:
            continue
        state = x.link_states.get(d.id, "approved")
        a, b = x.jobs[d.source].scheduler_id, x.jobs[d.target].scheduler_id
        pairs[(a, b)][state] += 1
    if not pairs:
        return
    lines = []
    for (a, b), states in sorted(pairs.items()):
        s = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in sorted(states.items()))
        lines.append(f"{x.estate.schedulers[a].name} → {x.estate.schedulers[b].name}: {s}")
    pending = sum(n for st in pairs.values() for k, n in st.items() if k not in ("approved", "rejected"))
    yield Finding(
        "st-coupling", "static", "cross-coupling", "medium" if pending else "info",
        f"{sum(sum(s.values()) for s in pairs.values())} links cross ecosystem boundaries, {pending} awaiting review",
        "; ".join(lines),
        "Each pending link changes forecasts and impact analysis once approved. Work the review queue, "
        "starting with the highest probability.", "cross", evidence=lines)


RULES: tuple[Rule, ...] = (dead_conditions, missing_dependencies, redundant_dependencies, unmonitored,
                           plaintext_secrets, data_boundaries, egress, single_points_of_failure,
                           host_concentration, cross_coupling)


def run_static(x: AnalysisInputs, rules: tuple[Rule, ...] = RULES) -> list[Finding]:
    out = [f for rule in rules for f in rule(x)]
    return sorted(out, key=lambda f: (SEVERITY_ORDER[f.severity], f.category))
