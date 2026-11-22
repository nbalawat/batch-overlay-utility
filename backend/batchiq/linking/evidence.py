"""Evidence strategies for job-to-job links.

Each strategy looks at one kind of signal and emits `Signal`s: "job A probably
feeds job B, because ...". Strategies are independent and pluggable, so a
client can switch one off, re-weight it, or add their own (for example a
CMDB-based one) without touching the recommender.

Discovery strategies can propose a new pair. Enrichers only add evidence to
pairs that some discovery strategy already proposed, so weak signals (timing
order, incident co-mentions) never create links on their own.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from batchiq.discovery.miner import MinedFact
from batchiq.domain.models import ArtifactType, Dependency, Evidence, Incident, Job

_DATA = {ArtifactType.DATASET, ArtifactType.TABLE}
_VENDOR = {"control-m": "Control-M", "autosys": "AutoSys", "airflow": "Airflow", "azure-data-factory": "ADF"}


@dataclass
class Signal:
    source: str
    target: str
    evidence: Evidence
    artifact: str | None = None
    definitional: bool = False      # both sides come from scheduler definitions (exact or prefix artifact match)


@dataclass
class LinkContext:
    jobs: dict[str, Job]
    declared: list[Dependency]
    mined: dict[str, list[MinedFact]]
    windows: dict[str, dict[str, tuple[datetime, datetime]]]   # job -> business date -> (start, end)
    incidents: list[Incident]
    known: dict[str, set[str]] = field(default_factory=dict)   # adjacency of links already known for sure

    def reachable(self, a: str, b: str) -> bool:
        seen, stack = set(), [a]
        while stack:
            n = stack.pop()
            if n == b:
                return True
            for m in self.known.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        return False

    def label(self, jid: str) -> str:
        j = self.jobs[jid]
        return f"{j.name} ({_VENDOR[j.vendor.value]})"


class Strategy(Protocol):
    id: str
    title: str

    def signals(self, ctx: LinkContext) -> Iterable[Signal]: ...


class Enricher(Protocol):
    id: str
    title: str

    def enrich(self, ctx: LinkContext, pairs: set[tuple[str, str]]) -> Iterable[Signal]: ...


# ====================================================================== discovery strategies
class DefinitionArtifactMatch:
    """Producer and consumer both declared in scheduler definitions (file, dataset, table, blob prefix)."""
    id, title = "definition-artifact", "Scheduler definitions name the same file or dataset"

    def signals(self, ctx: LinkContext) -> Iterable[Signal]:
        producers = [(j, a) for j in ctx.jobs.values() for a in j.produces]
        for c in ctx.jobs.values():
            for ca in c.consumes:
                for p, pa in producers:
                    if p.id == c.id:
                        continue
                    exact = pa.canonical == ca.canonical
                    prefix = ca.match == "prefix" and pa.canonical.startswith(ca.canonical)
                    if not (exact or prefix):
                        continue
                    if pa.type != ca.type and {pa.type, ca.type} <= _DATA:
                        ev = Evidence(kind="data-name-match", weight=0.7,
                                      detail=f"{_VENDOR[p.vendor.value]} publishes {pa.type.value} '{pa.raw}'; "
                                             f"{_VENDOR[c.vendor.value]} reads {ca.type.value} '{ca.raw}'")
                        yield Signal(p.id, c.id, ev, pa.canonical, definitional=False)
                    elif prefix and not exact:
                        ev = Evidence(kind="file-prefix-match", weight=0.9,
                                      detail=f"'{pa.raw}' matches the trigger prefix '{ca.raw}'")
                        yield Signal(p.id, c.id, ev, pa.canonical, definitional=True)
                    else:
                        ev = Evidence(kind=f"{pa.type.value}-match", weight=1.0,
                                      detail=f"{ctx.label(p.id)} produces '{pa.raw}', "
                                             f"{ctx.label(c.id)} consumes it as '{ca.raw}'")
                        yield Signal(p.id, c.id, ev, pa.canonical, definitional=True)


class CodeArtifactMatch:
    """A file or table written by one job's code and read by another's (at least one side mined from source)."""
    id, title = "code-artifact", "Job code writes and reads the same file or table"

    def signals(self, ctx: LinkContext) -> Iterable[Signal]:
        writers: dict[str, list[tuple[str, str]]] = defaultdict(list)   # key -> [(job, how)]
        readers: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for j in ctx.jobs.values():
            for a in j.produces:
                writers[a.canonical].append((j.id, "definition"))
            for a in j.consumes:
                if a.match == "exact":
                    readers[a.canonical].append((j.id, "definition"))
        for jid, facts in ctx.mined.items():
            for f in facts:
                if f.object_type in ("file", "dataset"):
                    loc = f"{f.path}:{f.line}"
                    if f.relation == "writes":
                        writers[f.key].append((jid, loc))
                    elif f.relation == "reads":
                        readers[f.key].append((jid, loc))
        for key, ws in writers.items():
            pairs: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
            for w, w_how in ws:
                for r, r_how in readers.get(key, []):
                    if w != r and not ctx.reachable(w, r):   # skip self, and pairs already linked upstream
                        hw, hr = pairs.setdefault((w, r), ([], []))
                        hw.append(w_how)
                        hr.append(r_how)
            for (w, r), (hw, hr) in pairs.items():
                if set(hw) == {"definition"} and set(hr) == {"definition"}:
                    continue                                 # definitions alone: DefinitionArtifactMatch's job
                code_w = sorted(h for h in set(hw) if h != "definition")
                code_r = sorted(h for h in set(hr) if h != "definition")
                both_code = "definition" not in hw and "definition" not in hr
                how = lambda hs, code: ("its definition" + (" and code at " + code[0] if code else "")  # noqa: E731
                                        if "definition" in hs else "code at " + code[0])
                yield Signal(w, r, Evidence(
                    kind="code-artifact-match", weight=0.75 if both_code else 0.8,
                    detail=f"'{key.split(':', 1)[1]}': {ctx.label(w)} writes it ({how(hw, code_w)}); "
                           f"{ctx.label(r)} reads it ({how(hr, code_r)})"), key)


class QueueMatch:
    id, title = "queue", "One job puts messages on a queue another job reads"

    def signals(self, ctx: LinkContext) -> Iterable[Signal]:
        puts: dict[str, list[MinedFact]] = defaultdict(list)
        gets: dict[str, list[MinedFact]] = defaultdict(list)
        for facts in ctx.mined.values():
            for f in facts:
                if f.object_type == "queue":
                    (puts if f.relation == "publishes" else gets)[f.key].append(f)
        for q, ps in puts.items():
            for p in ps:
                for g in gets.get(q, []):
                    if p.job_id != g.job_id and not ctx.reachable(p.job_id, g.job_id):
                        yield Signal(p.job_id, g.job_id, Evidence(
                            kind="queue-match", weight=0.85,
                            detail=f"MQ queue {p.label}: put by {ctx.label(p.job_id)} ({p.path}:{p.line}), "
                                   f"read by {ctx.label(g.job_id)} ({g.path}:{g.line})"), q)


class EventMatch:
    id, title = "event", "A job's code publishes the event another job's trigger listens for"

    def signals(self, ctx: LinkContext) -> Iterable[Signal]:
        listeners = [(j, a) for j in ctx.jobs.values() for a in j.consumes if a.type == ArtifactType.EVENT]
        for jid, facts in ctx.mined.items():
            for f in facts:
                if f.object_type != "event":
                    continue
                for j, a in listeners:
                    if j.id != jid and f.key.startswith(a.canonical):
                        yield Signal(jid, j.id, Evidence(
                            kind="event-match", weight=0.85,
                            detail=f"{ctx.label(jid)} publishes event '{f.label}' ({f.path}:{f.line}); "
                                   f"{ctx.label(j.id)} is triggered by events starting '{a.raw}'"), f.key)


def _lags(ctx: LinkContext, a: str, b: str) -> list[float]:
    wa, wb = ctx.windows.get(a, {}), ctx.windows.get(b, {})
    return [(wb[n][0] - wa[n][1]).total_seconds() / 60 for n in set(wa) & set(wb)]


class TemporalFollow:
    """For jobs nothing explains (no schedule, no known upstream): who do they reliably start right after?"""
    id, title = "temporal", "Starts minutes after another job ends, night after night"

    def __init__(self, window_min: float = 10.0, min_support: float = 0.9, min_nights: int = 10) -> None:
        self.window, self.min_support, self.min_nights = window_min, min_support, min_nights

    def signals(self, ctx: LinkContext) -> Iterable[Signal]:
        has_up = {t for ts in ctx.known.values() for t in ts}
        for b in ctx.jobs.values():
            if b.id in has_up or b.scheduled_time is not None:
                continue
            best = None
            for a in ctx.jobs.values():
                if a.scheduler_id == b.scheduler_id:
                    continue
                lags = _lags(ctx, a.id, b.id)
                if len(lags) < self.min_nights:
                    continue
                support = sum(0 <= x <= self.window for x in lags) / len(lags)
                if support >= self.min_support:
                    score = (support, -statistics.pstdev(lags))
                    if best is None or score > best[0]:
                        best = (score, a, lags)
            if best:
                (support, _), a, lags = best
                yield Signal(a.id, b.id, Evidence(
                    kind="temporal", weight=round(0.5 + 0.3 * support, 2),
                    detail=f"In {round(support * len(lags))}/{len(lags)} nights {b.name} started "
                           f"{statistics.median(lags):.1f} min (median) after {a.name} ended; "
                           f"lag stdev {statistics.pstdev(lags):.1f} min"))


_STOP = {"load", "job", "run", "daily", "file", "feed", "gen", "calc", "to", "the", "wait", "build", "publish",
         "sync", "pl", "box", "data", "copy", "refresh", "eod", "send", "extract", "cbk", "pay", "trs", "crd", "ln",
         "hk", "mis", "aml", "dq", "lake", "list", "model", "raw"}
_SYN = {"statements": "stmt", "statement": "stmt", "stmts": "stmt", "archival": "archive", "txns": "txn",
        "transactions": "txn", "transaction": "txn"}


def _tokens(*names: str) -> set[str]:
    out = set()
    for n in names:
        for t in re.split(r"[^a-z0-9]+", n.lower()):
            t = _SYN.get(t, t)
            if len(t) > 2 and t not in _STOP:
                out.add(t)
    return out


class NameSimilarity:
    """Weak by design: shared business words in names, plus a consistent order. Always needs a human."""
    id, title = "name", "Names share business terms and the order is consistent"

    def signals(self, ctx: LinkContext) -> Iterable[Signal]:
        best: dict[str, tuple[float, str, set[str]]] = {}
        has_up = {t for ts in ctx.known.values() for t in ts}
        for b in ctx.jobs.values():
            if b.id in has_up or b.scheduled_time is None:
                continue          # only jobs that start on their own clock can hide an undeclared upstream
            tb = _tokens(b.name)
            for a in ctx.jobs.values():
                if a.scheduler_id == b.scheduler_id or ctx.reachable(a.id, b.id):
                    continue
                common = _tokens(a.name) & tb
                if not common:
                    continue
                lags = _lags(ctx, a.id, b.id)
                if len(lags) < 10 or sum(x >= 0 for x in lags) / len(lags) < 0.9:
                    continue
                score = len(common) / len(tb | _tokens(a.name))
                if score >= 0.25 and score > best.get(b.id, (0.0,))[0]:
                    best[b.id] = (score, a.id, common)
        for b, (score, a, common) in best.items():
            yield Signal(a, b, Evidence(kind="name-similarity", weight=0.3,
                                        detail=f"Both names mention {', '.join(sorted(common))}; "
                                               f"{ctx.jobs[a].name} finishes before {ctx.jobs[b].name} starts "
                                               f"(similarity {score:.2f})"))


# ====================================================================== enrichers
class RuntimeOrder:
    """Does the target actually start after the source finishes? Also counts nights it did not (a race)."""
    id, title = "runtime-order", "Run history is consistent with the link"

    def enrich(self, ctx: LinkContext, pairs: set[tuple[str, str]]) -> Iterable[Signal]:
        for a, b in pairs:
            if ctx.jobs[b].kind.value == "sensor":     # sensors start early and wait: compare finish times
                wa, wb = ctx.windows.get(a, {}), ctx.windows.get(b, {})
                lags = [(wb[n][1] - wa[n][1]).total_seconds() / 60 for n in set(wa) & set(wb)]
            else:
                lags = _lags(ctx, a, b)
            if not lags:
                continue
            ok = sum(x >= 0 for x in lags)
            race = len(lags) - ok
            n = len(lags)
            weight = (0.3 if n >= 10 else 0.15) if ok / n >= 0.9 else (0.1 if ok / n >= 0.7 else 0.0)
            detail = (f"In {ok}/{n} nights {ctx.jobs[b].name} started after {ctx.jobs[a].name} finished "
                      f"(median gap {statistics.median(lags):.0f} min).")
            if n < 10:
                detail += f" Only {n} nights of history so far."
            if race:
                detail += f" On {race} night(s) it started first: it would have read incomplete or stale data."
            yield Signal(a, b, Evidence(kind="runtime-order", weight=weight, detail=detail))


class IncidentCoMention:
    id, title = "incident", "A past incident names both jobs"

    def enrich(self, ctx: LinkContext, pairs: set[tuple[str, str]]) -> Iterable[Signal]:
        for a, b in pairs:
            ja, jb = ctx.jobs[a], ctx.jobs[b]
            for inc in ctx.incidents:
                text = " ".join((inc.title, inc.symptoms, inc.root_cause, " ".join(inc.jobs)))
                hit_b = jb.name in text or b in inc.jobs
                hit_a = ja.name in text or a in inc.jobs or re.search(rf"\b{re.escape(ja.container)}\b", text)
                if hit_a and hit_b:
                    yield Signal(a, b, Evidence(kind="incident", weight=0.35,
                                                detail=f"{inc.id} ({inc.date}) names both: {inc.title}"))
                    break


DISCOVERY: tuple[Strategy, ...] = (DefinitionArtifactMatch(), CodeArtifactMatch(), QueueMatch(), EventMatch(),
                                   TemporalFollow(), NameSimilarity())
ENRICHERS: tuple[Enricher, ...] = (RuntimeOrder(), IncidentCoMention())
