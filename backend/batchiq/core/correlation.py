"""Cross-scheduler correlation engine.

Builds the dependencies that no single scheduler knows about:

1. **Artifact matching**: a job in one scheduler produces a file or dataset
   that a job in another scheduler consumes (exact or prefix match on the
   canonical key).
2. **Name matching across artifact types**: a dataset produced in Airflow and a
   table read by ADF share a name. Plausible, so it is marked *inferred*.
3. **Temporal evidence**: across run history, a job that has no declared
   trigger consistently starts minutes after another scheduler's job ends.

Inferred links carry evidence and a confidence score and start as
"suggested", so an operator can confirm or reject them (human in the loop).
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from batchiq.core.store import InMemoryEstate
from batchiq.domain.models import ArtifactType, Dependency, DependencyOrigin, Evidence, Job, RunStatus

_DATA_TYPES = {ArtifactType.DATASET, ArtifactType.TABLE}


def _combine(*ps: float) -> float:
    q = 1.0
    for p in ps:
        q *= 1 - p
    return round(1 - q, 3)


class CorrelationEngine:
    def __init__(self, estate: InMemoryEstate, temporal_window_min: float = 10.0,
                 temporal_min_support: float = 0.9, temporal_min_nights: int = 10) -> None:
        self.estate = estate
        self.window = temporal_window_min
        self.min_support = temporal_min_support
        self.min_nights = temporal_min_nights

    def run(self) -> list[Dependency]:
        links = self._artifact_links()
        self._temporal_links(links)
        return list(links.values())

    # ------------------------------------------------------------------ artifacts
    def _artifact_links(self) -> dict[tuple[str, str], Dependency]:
        jobs = self.estate.jobs()
        producers = [(j, a) for j in jobs.values() for a in j.produces]
        links: dict[tuple[str, str], Dependency] = {}
        for consumer in jobs.values():
            for ca in consumer.consumes:
                for prod, pa in producers:
                    if prod.id == consumer.id:
                        continue
                    exact = pa.canonical == ca.canonical
                    prefix = ca.match == "prefix" and pa.canonical.startswith(ca.canonical)
                    if not (exact or prefix):
                        continue
                    cross_type = pa.type != ca.type and {pa.type, ca.type} <= _DATA_TYPES
                    if cross_type:
                        origin, conf = DependencyOrigin.INFERRED, 0.7
                        ev = Evidence(kind="data-name-match", weight=0.7,
                                      detail=f"{prod.vendor.value} publishes {pa.type.value} '{pa.raw}'; "
                                             f"{consumer.vendor.value} reads {ca.type.value} '{ca.raw}'")
                    elif prefix and not exact:
                        origin, conf = DependencyOrigin.ARTIFACT, 0.9
                        ev = Evidence(kind="file-prefix-match", weight=0.9,
                                      detail=f"'{pa.raw}' matches trigger prefix '{ca.raw}'")
                    else:
                        origin, conf = DependencyOrigin.ARTIFACT, 1.0
                        ev = Evidence(kind=f"{pa.type.value}-match", weight=1.0,
                                      detail=f"produces '{pa.raw}', consumed as '{ca.raw}'")
                    key = (prod.id, consumer.id)
                    links[key] = Dependency(
                        id=f"{prod.id}->{consumer.id}", source=prod.id, target=consumer.id, origin=origin,
                        cross_scheduler=prod.scheduler_id != consumer.scheduler_id, confidence=conf,
                        artifact=pa.canonical, evidence=[ev],
                        review_state="suggested" if origin == DependencyOrigin.INFERRED else "auto")
        return links

    # ------------------------------------------------------------------ temporal
    def _windows(self) -> dict[str, dict[str, tuple]]:
        """job -> business_date -> (start, end) of the successful attempt."""
        out: dict[str, dict[str, tuple]] = defaultdict(dict)
        for jid in self.estate.jobs():
            for r in self.estate.history_runs(jid):
                if r.status == RunStatus.SUCCEEDED and r.start and r.end:
                    out[jid][r.business_date] = (r.start, r.end)
        return out

    def _untriggered(self, links: dict) -> list[Job]:
        """Jobs whose native definition explains neither a schedule nor an upstream."""
        has_up = {d.target for d in self.estate.dependencies().values()} | {t for (_, t) in links}
        return [j for j in self.estate.jobs().values()
                if j.id not in has_up and j.scheduled_time is None
                and not any(a.match == "prefix" for a in j.consumes)]

    def _temporal_links(self, links: dict[tuple[str, str], Dependency]) -> None:
        windows = self._windows()
        jobs = self.estate.jobs()
        targets = self._untriggered(links)
        # Also strengthen existing inferred links with timing evidence.
        targets += [jobs[t] for (_, t), d in links.items() if d.origin == DependencyOrigin.INFERRED]
        for b in {t.id: t for t in targets}.values():
            best = None
            for a in jobs.values():
                if a.scheduler_id == b.scheduler_id:
                    continue
                nights = set(windows[a.id]) & set(windows[b.id])
                if len(nights) < self.min_nights:
                    continue
                lags = [(windows[b.id][n][0] - windows[a.id][n][1]).total_seconds() / 60 for n in nights]
                support = sum(0 <= x <= self.window for x in lags) / len(lags)
                if support >= self.min_support:
                    score = (support, -statistics.pstdev(lags))
                    if best is None or score > best[0]:
                        best = (score, a, lags, len(nights))
            if best is None:
                continue
            (support, _), a, lags, n = best
            ev = Evidence(kind="temporal", weight=round(0.5 + 0.3 * support, 2),
                          detail=f"In {round(support * n)}/{n} nights, started {statistics.median(lags):.1f} min "
                                 f"(median) after {a.name} ended. Lag stdev {statistics.pstdev(lags):.1f} min.")
            key = (a.id, b.id)
            if key in links:
                d = links[key]
                d.evidence.append(ev)
                d.confidence = _combine(d.confidence, ev.weight)
            else:
                links[key] = Dependency(id=f"{a.id}->{b.id}", source=a.id, target=b.id,
                                        origin=DependencyOrigin.INFERRED, cross_scheduler=True,
                                        confidence=ev.weight, evidence=[ev], review_state="suggested")
