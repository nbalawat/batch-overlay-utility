"""Tools the operations assistant can call. They are thin, read-only views over
EstateService, so every answer is grounded in the unified estate."""
from __future__ import annotations

import json
import re
from typing import Any

from batchiq.assistant.graph_tools import GRAPH_TOOL_INDEX, GRAPH_TOOLS
from batchiq.llm.base import ToolSpec
from batchiq.service import EstateService

_OBJ = {"type": "object", "additionalProperties": False}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {**_OBJ, "properties": props, "required": required or []}


TOOLS: list[ToolSpec] = [
    ToolSpec("get_estate_overview", "Tonight's headline numbers, connector status and business process health.",
             _schema({})),
    ToolSpec("list_insights", "AI insights (failures, SLA risks, anomalies, suggested hidden dependencies), "
             "most severe first.", _schema({"type": {"type": "string",
                                                     "enum": ["failure", "sla_risk", "anomaly", "correlation", "stale_data"]}})),
    ToolSpec("get_business_process", "Status, SLA forecast, critical path and jobs of one business process. "
             "Accepts an id or words from its name, e.g. 'regulatory' or 'payments'.",
             _schema({"process": {"type": "string"}}, ["process"])),
    ToolSpec("search_jobs", "Find jobs across all schedulers by name, DAG, folder or application.",
             _schema({"query": {"type": "string"}}, ["query"])),
    ToolSpec("get_job", "Full detail for one job: unified definition, tonight's status, baseline, "
             "upstream and downstream links. Accepts a job id or name.", _schema({"job": {"type": "string"}}, ["job"])),
    ToolSpec("get_impact", "Downstream impact of a job across schedulers, business processes and services.",
             _schema({"job": {"type": "string"}}, ["job"])),
    ToolSpec("get_root_cause", "Ranked root-cause hypotheses for a job that failed, is slow or is late, or for "
             "a business process at risk (pass `process`; hypotheses are then scoped to its critical path).",
             _schema({"job": {"type": "string"}, "process": {"type": "string"}})),
    ToolSpec("search_incident_history", "Search the knowledge base of past incidents and their resolutions.",
             _schema({"query": {"type": "string"}}, ["query"])),
    *(t.spec for t in GRAPH_TOOLS),
]


class ToolBox:
    def __init__(self, svc: EstateService) -> None:
        self.svc = svc

    # ------------------------------------------------------------------ resolution
    def resolve_job(self, text: str) -> str | None:
        jobs = self.svc.a.estate.jobs()
        if text in jobs:
            return text
        t = text.lower().strip()
        exact = [j for j, job in jobs.items() if job.name.lower() == t or job.native_id.lower() == t]
        if exact:
            return exact[0]
        part = [j for j in jobs if t in j.lower()]
        return part[0] if part else None

    def resolve_process(self, text: str) -> str | None:
        procs = self.svc.a.mapper.processes
        if text in procs:
            return text
        words = set(re.findall(r"[a-z0-9]+", text.lower()))
        best, score = None, 0
        for pid, bp in procs.items():
            hay = set(re.findall(r"[a-z0-9]+", f"{pid} {bp.name} {bp.description}".lower()))
            s = len(words & hay)
            if s > score:
                best, score = pid, s
        return best

    # ------------------------------------------------------------------ dispatch
    def execute(self, name: str, args: dict[str, Any]) -> str:
        return json.dumps(self.call(name, args), default=str)

    def call(self, name: str, args: dict[str, Any]) -> Any:
        svc = self.svc
        if name in GRAPH_TOOL_INDEX:
            return GRAPH_TOOL_INDEX[name].run(svc, args)
        if name == "get_estate_overview":
            o = svc.overview()
            return {"kpis": o["kpis"], "now": o["meta"]["now"],
                    "processes": [{k: p[k] for k in ("id", "name", "status", "breach_probability", "sla",
                                                     "projected_p50", "jobs_by_scheduler")} for p in o["processes"]],
                    "connectors": [{k: c[k] for k in ("id", "name", "vendor", "status", "jobs", "failed_tonight")}
                                   for c in o["connectors"]]}
        if name == "list_insights":
            return [{k: i[k] for k in ("id", "type", "severity", "title", "summary")}
                    for i in svc.insights(args.get("type"))]
        if name == "get_business_process":
            pid = self.resolve_process(args["process"])
            if not pid:
                return {"error": f"No process matches '{args['process']}'"}
            d = svc.process_detail(pid)
            d.pop("graph", None)
            d["timeline"] = [{k: t[k] for k in ("id", "vendor", "status", "start", "end", "projected_end",
                                                "critical", "failed_attempts")} for t in d["timeline"]]
            d["insights"] = [{k: i[k] for k in ("id", "title", "summary")} for i in d["insights"]]
            d["history"] = d["history"][-7:]
            return d
        if name == "search_jobs":
            return svc.jobs(q=args["query"])[:25]
        jid = self.resolve_job(args.get("job", "")) if args.get("job") else None
        crit = None
        if name == "get_root_cause" and args.get("process"):
            pid = self.resolve_process(args["process"])
            if pid:
                crit = set(svc.a.proc_fc[pid].critical_path)
                jid = jid or svc.a.mapper.processes[pid].anchor_jobs[0]
        if name in ("get_job", "get_impact", "get_root_cause") and not jid:
            return {"error": f"No job matches '{args.get('job')}'"}
        if name == "get_job":
            d = svc.job_detail(jid)
            d["runs"] = d["runs"][-8:]
            return d
        if name == "get_impact":
            return {"job": svc.job_brief(jid), "impact": svc.a.engine.impact_of(jid)}
        if name == "get_root_cause":
            hyps = svc.a.engine.root_cause_for(jid, crit)
            query = hyps[0]["reason"] if hyps else svc.a.estate.jobs()[jid].name
            return {"job": svc.job_brief(jid), "hypotheses": hyps,
                    "similar_incidents": svc.a.engine.similar_incidents(query)}
        if name == "search_incident_history":
            return svc.a.engine.similar_incidents(args["query"], k=4)
        return {"error": f"Unknown tool {name}"}
