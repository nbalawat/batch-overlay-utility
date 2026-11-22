"""Findings view: filter and summarise static and runtime findings."""
from __future__ import annotations

from collections import Counter
from typing import Any

from batchiq.analysis.findings import CATEGORY_TITLES, SEVERITY_ORDER, Finding


def findings(all_: list[Finding], kind: str | None = None, scope: str | None = None, category: str | None = None,
             severity: str | None = None, job: str | None = None) -> dict[str, Any]:
    out = [f for f in all_
           if (not kind or f.kind == kind) and (not category or f.category == category)
           and (not severity or f.severity == severity) and (not job or job in f.job_ids)
           and (not scope or f.scope == scope)]
    cats = Counter((f.kind, f.category) for f in all_)
    return {
        "findings": [f.__dict__ for f in out],
        "summary": {
            "total": len(all_), "shown": len(out),
            "by_kind": dict(Counter(f.kind for f in all_)),
            "by_severity": {s: sum(1 for f in all_ if f.severity == s) for s in SEVERITY_ORDER},
            "by_scope": dict(Counter(f.scope for f in all_)),
            "categories": [{"kind": k, "category": c, "title": CATEGORY_TITLES.get(c, c), "count": n}
                           for (k, c), n in sorted(cats.items())]}}
