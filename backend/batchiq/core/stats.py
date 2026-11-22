"""Historical baselines per job (durations and timing)."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from batchiq.core.store import InMemoryEstate
from batchiq.domain.models import RunStatus


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


@dataclass
class JobBaseline:
    samples_min: list[float]
    p50: float
    p90: float
    p95: float
    mad: float
    end_offsets_min: list[float]      # minutes after the night anchor
    failure_rate: float
    nights: int

    @property
    def typical_end_offset(self) -> float | None:
        return statistics.median(self.end_offsets_min) if self.end_offsets_min else None


def night_anchor(business_date: str) -> datetime:
    return datetime.fromisoformat(business_date) + timedelta(hours=20)


def compute_baselines(estate: InMemoryEstate) -> dict[str, JobBaseline]:
    out = {}
    for jid in estate.jobs():
        hist = estate.history_runs(jid)
        ok = [r for r in hist if r.status == RunStatus.SUCCEEDED and r.duration_s is not None]
        durs = [r.duration_s / 60 for r in ok]
        med = statistics.median(durs) if durs else 0.0
        mad = statistics.median([abs(d - med) for d in durs]) if durs else 0.0
        ends = [(r.end - night_anchor(r.business_date)).total_seconds() / 60 for r in ok if r.end]
        nights = len({r.business_date for r in hist})
        fails = len({r.business_date for r in hist if r.status == RunStatus.FAILED})
        out[jid] = JobBaseline(durs, med, _pct(durs, 0.9), _pct(durs, 0.95), mad, ends,
                               fails / nights if nights else 0.0, nights)
    return out
