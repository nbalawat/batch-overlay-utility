"""Onboarding: what each connector delivered, and a sandbox to try a new scheduler export.

The sandbox runs the real adapter translators over pasted content through a
static client, so it exercises exactly the code a live connector would. It does
not change the estate: it reports what was parsed, what the static rules say
about it, and which links to the live estate the recommender would propose.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from batchiq.adapters import registry
from batchiq.knowledge.builder import KGInputs, KnowledgeGraphBuilder
from batchiq.linking.evidence import DefinitionArtifactMatch, LinkContext
from batchiq.views.common import VENDOR_LABEL

if TYPE_CHECKING:
    from batchiq.service import EstateService

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "catalog" / "samples"
SAMPLES = {
    "autosys-ae2": {"vendor": "autosys", "file": "autosys_ae2.jil", "scheduler_id": "autosys-ae2",
                    "name": "AutoSys AE2 (Wealth)", "format": "JIL (autorep -J ALL -q)"},
    "ctm-mtg": {"vendor": "control-m", "file": "controlm_ctmmtg.json", "scheduler_id": "ctm-mtg",
                "name": "Control-M CTMMTG (Mortgage)", "format": "Automation API JSON (ctm deploy jobs::get)"},
    "airflow-reg": {"vendor": "airflow", "file": "airflow_regulatory.json", "scheduler_id": "airflow-reg",
                    "name": "Airflow (Regulatory)", "format": "REST API: /dags, /dags/{id}/tasks, /datasets"},
}
TEXT_VENDORS = {"autosys"}
MAX_BYTES = 512 * 1024


class ImportError_(ValueError):
    pass


@dataclass
class StaticClient:
    """A NativeClient over content someone uploaded: definitions only, read-only."""
    id: str
    name: str
    definitions: Any

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "environment": "sandbox", "endpoint": "upload",
                "description": "Imported in the onboarding sandbox", "version": "n/a", "timezone": "n/a"}

    def fetch_definitions(self) -> Any:
        return self.definitions

    def fetch_runs(self) -> Any:
        return {}

    def submit(self, command: dict[str, Any]) -> dict[str, Any]:
        raise PermissionError("The sandbox is read-only")


def samples() -> list[dict[str, Any]]:
    return [{"id": k, **v, "vendor_label": VENDOR_LABEL[v["vendor"]],
             "content": (SAMPLES_DIR / v["file"]).read_text()} for k, v in SAMPLES.items()]


def pipeline(svc: EstateService) -> dict[str, Any]:
    a = svc.a
    return {"connectors": [{"scheduler_id": sid, "name": a.estate.schedulers[sid].name,
                            "vendor": a.estate.schedulers[sid].vendor.value, **stats}
                           for sid, stats in svc.pipeline.items()],
            "stages": [
                {"id": "ingest", "title": "Read definitions and run history", "detail": "Read-only API or export"},
                {"id": "normalise", "title": "Translate to one model", "detail": "Adapter per scheduler dialect"},
                {"id": "mine", "title": "Mine the code each job runs", "detail": "Files, tables, hosts, mail, APIs"},
                {"id": "link", "title": "Recommend links", "detail": f"{len(svc.candidates)} candidates, "
                                                                     f"{svc.link_ms} ms"},
                {"id": "review", "title": "Owners review", "detail": "Approve, reject or ask"},
                {"id": "graph", "title": "Rebuild the knowledge graph", "detail":
                    f"{len(a.kg.nodes)} nodes, {len(a.kg.edges)} edges"},
                {"id": "analyse", "title": "Static and runtime findings", "detail": f"{len(a.findings)} findings"}],
            "totals": {"definitions": sum(p["definitions"] for p in svc.pipeline.values()),
                       "source_files": sum(p["source_files"] for p in svc.pipeline.values()),
                       "mined_facts": sum(p["mined_facts"] for p in svc.pipeline.values()),
                       "runs": sum(p["runs"] for p in svc.pipeline.values())}}


def _parse(vendor: str, content: str) -> Any:
    if vendor in TEXT_VENDORS:
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ImportError_(f"Expected JSON for {VENDOR_LABEL.get(vendor, vendor)}: {e.msg} at line {e.lineno}") from e


def import_sandbox(svc: EstateService, vendor: str, content: str, scheduler_id: str, name: str) -> dict[str, Any]:
    if vendor not in registry.registered():
        raise ImportError_(f"No adapter for '{vendor}'. Registered: {', '.join(registry.registered())}")
    if len(content.encode()) > MAX_BYTES:
        raise ImportError_("Export too large for the sandbox (512 KB). Connect the scheduler instead.")
    if scheduler_id in svc.a.estate.schedulers:
        raise ImportError_(f"'{scheduler_id}' is already connected; pick another id")
    adapter = registry.create(vendor, StaticClient(scheduler_id, name, _parse(vendor, content)))
    try:
        jobs, deps = adapter.normalise_definitions(adapter.client.fetch_definitions())
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        raise ImportError_(f"Could not read this {VENDOR_LABEL[vendor]} export: {type(e).__name__} {e}") from e
    if not jobs:
        raise ImportError_(f"No jobs found in this {VENDOR_LABEL[vendor]} export")
    live = svc.a.estate.jobs()
    by_id = {j.id: j for j in jobs}
    # Cross-match the new definitions against the live estate, both directions.
    ctx = LinkContext({**live, **by_id}, list(svc.a.estate.dependencies().values()) + deps, {}, {}, [])
    proposed = []
    for s in DefinitionArtifactMatch().signals(ctx):
        if (s.source in by_id) == (s.target in by_id):
            continue
        a, b = (live.get(s.source) or by_id[s.source]), (live.get(s.target) or by_id[s.target])
        proposed.append({"source": {"id": s.source, "name": a.name, "scheduler_id": a.scheduler_id},
                         "target": {"id": s.target, "name": b.name, "scheduler_id": b.scheduler_id},
                         "artifact": s.artifact, "probability": s.evidence.weight, "evidence": s.evidence.model_dump(),
                         "direction": "into the new scheduler" if s.target in by_id else "out of the new scheduler"})
    kg = KnowledgeGraphBuilder().build(KGInputs({scheduler_id: adapter.scheduler()}, by_id, deps, {}))
    checks = []
    for j in jobs:
        for c in j.unresolved_conditions:
            checks.append({"severity": "high", "job": j.name,
                           "message": f"Waits on {c}, which nothing in this export provides"})
        if j.alerting is False:
            checks.append({"severity": "medium", "job": j.name, "message": "No failure alert configured"})
    produced = {a.canonical for j in jobs for a in j.produces}
    consumed = {a.canonical for j in jobs for a in j.consumes}
    external_in = sorted(consumed - produced)
    return {
        "scheduler": {"id": scheduler_id, "name": name, "vendor": vendor, "vendor_label": VENDOR_LABEL[vendor]},
        "jobs": [{"id": j.id, "name": j.name, "container": j.container, "host": j.host, "team": j.team,
                  "schedule": j.schedule, "produces": [a.canonical for a in j.produces],
                  "consumes": [a.canonical for a in j.consumes], "alerting": j.alerting,
                  "unresolved_conditions": j.unresolved_conditions} for j in jobs],
        "dependencies": [{"source": d.source, "target": d.target, "artifact": d.artifact} for d in deps],
        "graph": kg.stats(), "checks": checks, "external_inputs": external_in,
        "proposed_links": sorted(proposed, key=lambda p: -p["probability"]),
        "next_steps": ["Connect the scheduler read-only so run history flows in",
                       "Point the overlay at the job scripts' repository so their code can be mined",
                       f"Owners review the {len(proposed)} proposed link(s) to the live estate"]}
