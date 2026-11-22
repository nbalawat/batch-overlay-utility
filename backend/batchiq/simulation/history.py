"""Generates realistic run history for the estate.

For each business night it walks the true dependency graph (declared, artifact
and hidden couplings), samples durations, applies the scenario's failures and
slowdowns, and records what each scheduler would have logged. Tonight's run is
cut off at the scenario clock, so jobs can be running, waiting or not reached.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from batchiq.domain.models import JobKind, RunStatus
from batchiq.simulation.estate import JOBS, JOBS_BY_KEY, JobSpec
from batchiq.simulation.scenarios import FailAndRerun, Scenario

BATCH_WINDOW_START = time(20, 0)
HISTORY_NIGHTS = 30

# Background noise: rare transient failures, with vendor-flavoured error codes.
_TRANSIENT = {
    "control-m": [("S322", "TIME LIMIT EXCEEDED"), ("U4038", "LE ABEND USER 4038")],
    "autosys": [("EXIT_1", "Command exited with status 1"), ("ERR_FNF", "Input file not found")],
    "airflow": [("AirflowTaskTimeout", "Task timed out"), ("OOMKilled", "Executor OOMKilled")],
    "azure-data-factory": [("2200", "Copy activity failure: user error"),
                           ("DBX_CLUSTER_LAUNCH", "Databricks cluster launch failure")],
}


@dataclass
class RawRun:
    """A vendor-neutral run record that simulators render into native shapes."""
    key: str
    business_date: date
    attempt: int
    status: RunStatus
    start: datetime | None
    end: datetime | None
    error_code: str | None = None
    message: str | None = None


def night_anchor(business_date: date) -> datetime:
    """Batch night for business date D runs from D 20:00 to D+1 morning."""
    return datetime.combine(business_date, BATCH_WINDOW_START)


def at_on_night(business_date: date, t: time) -> datetime:
    base = night_anchor(business_date)
    d = datetime.combine(business_date, t)
    return d if d >= base else d + timedelta(days=1)


def _basename(artifact: str) -> str:
    return artifact.split(":", 1)[1].rstrip("/").rsplit("/", 1)[-1]


def _producer_of(artifact: str) -> str | None:
    for spec in JOBS:
        if artifact in spec.produces:
            return spec.key
    base = _basename(artifact)
    for spec in JOBS:
        for p in spec.produces:
            if _basename(p).startswith(base) and base:
                return spec.key
    return None


def _topo_order() -> list[JobSpec]:
    preds = {s.key: _true_predecessors(s) for s in JOBS}
    done: list[JobSpec] = []
    seen: set[str] = set()

    def visit(k: str) -> None:
        if k in seen:
            return
        seen.add(k)
        for p in preds[k]:
            visit(p)
        done.append(JOBS_BY_KEY[k])

    for s in JOBS:
        visit(s.key)
    return done


def _sibling_key(spec: JobSpec, name: str) -> str:
    return JobSpec(spec.vendor, spec.scheduler_id, spec.container, name, 0).key


def _true_predecessors(spec: JobSpec) -> list[str]:
    preds = [_sibling_key(spec, n) for n in spec.after]
    for a in spec.consumes:
        p = _producer_of(a)
        if p and p != spec.key:
            preds.append(p)
    preds.extend(spec.hidden_after)
    return preds


class HistoryGenerator:
    def __init__(self, seed: int = 7) -> None:
        self.seed = seed

    def generate(self, scenario: Scenario, today: date) -> tuple[list[RawRun], datetime]:
        """Return all runs (history + tonight) and the simulated 'now'."""
        tonight = today - timedelta(days=1)
        now = datetime.combine(today, scenario.clock)
        runs: list[RawRun] = []
        for i in range(HISTORY_NIGHTS, 0, -1):
            bd = tonight - timedelta(days=i)
            rng = random.Random(f"{self.seed}-night-{i}")  # index-based: stable whatever the date
            runs.extend(self._simulate_night(bd, rng, scenario=None, cutoff=None))
        rng = random.Random(f"{self.seed}-tonight-{scenario.id}")
        runs.extend(self._simulate_night(tonight, rng, scenario=scenario, cutoff=now))
        return runs, now

    # ------------------------------------------------------------------ internals
    def _volume_factor(self, bd: date) -> float:
        # Mondays carry the weekend backlog; month-end is heavier.
        f = 1.0
        if bd.weekday() == 0:
            f *= 1.12
        if (bd + timedelta(days=1)).day == 1:
            f *= 1.25
        return f

    def _simulate_night(self, bd: date, rng: random.Random, scenario: Scenario | None,
                        cutoff: datetime | None) -> list[RawRun]:
        ends: dict[str, datetime] = {}
        out: list[RawRun] = []
        vol = self._volume_factor(bd) if scenario is None else 1.0
        failures = {f.job: f for f in (scenario.failures if scenario else ())}
        slow = {s.job: s.factor for s in (scenario.slowdowns if scenario else ())}
        historic_fail_p = 0.0 if scenario else 0.012

        for spec in _topo_order():
            preds = _true_predecessors(spec)
            pred_ends = [ends[p] for p in preds if p in ends]
            if len(pred_ends) < len(preds):
                # Upstream never completed tonight: this job cannot have started.
                if cutoff is not None:
                    if spec.kind == JobKind.SENSOR and spec.at and at_on_night(bd, spec.at) <= cutoff:
                        # A sensor with its own schedule keeps poking for the missing input.
                        out.append(RawRun(spec.key, bd, 1, RunStatus.RUNNING, at_on_night(bd, spec.at), None))
                    continue
            start = self._start_time(spec, bd, pred_ends, rng)
            minutes = spec.minutes if spec.kind != JobKind.SENSOR else 0.0
            if spec.kind != JobKind.SENSOR:
                minutes = spec.minutes * math.exp(rng.gauss(0, spec.jitter)) * (
                    vol if spec.app in ("CORE", "PAYMENTS", "finance", "risk") else 1.0)
                minutes *= slow.get(spec.key, 1.0)
            if spec.kind == JobKind.SENSOR:
                end = max(pred_ends) + timedelta(minutes=1) if pred_ends else start + timedelta(minutes=1)
            else:
                end = start + timedelta(minutes=minutes)

            attempt = 1
            fail = failures.get(spec.key)
            if fail is None and rng.random() < historic_fail_p and spec.kind != JobKind.SENSOR:
                code, msg = rng.choice(_TRANSIENT[spec.vendor.value])
                fail = FailAndRerun(spec.key, minutes * rng.uniform(0.2, 0.8), code, msg, None)
                rerun_gap = rng.uniform(8, 40)
                fail_at = start + timedelta(minutes=fail.fail_after_min)
                out.append(RawRun(spec.key, bd, 1, RunStatus.FAILED, start, fail_at, code, msg))
                start = fail_at + timedelta(minutes=rerun_gap)
                end = start + timedelta(minutes=minutes)
                attempt = 2
            elif fail is not None:
                fail_at = start + timedelta(minutes=fail.fail_after_min)
                if cutoff is None or fail_at <= cutoff:
                    out.append(RawRun(spec.key, bd, 1, RunStatus.FAILED, start, fail_at,
                                      fail.error_code, fail.message))
                    if fail.rerun_at is None:
                        continue  # still broken; downstream blocked
                    start = at_on_night(bd, fail.rerun_at)
                    end = start + timedelta(minutes=spec.minutes * math.exp(rng.gauss(0, spec.jitter)))
                    attempt = 2

            if cutoff is not None and start > cutoff:
                continue
            if cutoff is not None and end > cutoff:
                out.append(RawRun(spec.key, bd, attempt, RunStatus.RUNNING, start, None))
                continue
            ends[spec.key] = end
            out.append(RawRun(spec.key, bd, attempt, RunStatus.SUCCEEDED, start, end))
        return out

    def _start_time(self, spec: JobSpec, bd: date, pred_ends: list[datetime],
                    rng: random.Random) -> datetime:
        lag = timedelta(minutes=rng.uniform(0.3, 1.5))
        if spec.kind == JobKind.SENSOR:
            if spec.at:
                return at_on_night(bd, spec.at)
            return (min(pred_ends) if pred_ends else night_anchor(bd)) + lag
        candidates = [p + lag for p in pred_ends]
        if spec.hidden_after:
            candidates.append(max(pred_ends) + timedelta(minutes=rng.uniform(2, 6)) if pred_ends
                              else night_anchor(bd))
        if spec.at:
            candidates.append(at_on_night(bd, spec.at) + timedelta(seconds=rng.uniform(0, 40)))
        return max(candidates) if candidates else night_anchor(bd)
