"""Deterministic offline assistant.

Used when no LLM is configured (air-gapped demo, no API key). It routes the
question to the same tools the LLM would use and writes a templated answer, so
the demo never depends on network access. Answers are shorter and less fluent
than an LLM's, but they come from the same grounded facts.
"""
from __future__ import annotations

import re
from typing import Any

from batchiq.assistant import offline_graph
from batchiq.assistant.tools import ToolBox
from batchiq.llm.base import AssistantResult, LLMProvider, ToolExecutor, ToolSpec


def _hhmm(iso: str | None) -> str:
    return iso[11:16] if iso else "n/a"


class OfflineProvider(LLMProvider):
    name = "offline"
    model = "rules-v2"

    def __init__(self, toolbox: ToolBox) -> None:
        self.tb = toolbox

    def answer(self, system: str, history: list[dict[str, str]], question: str,
               tools: list[ToolSpec], execute: ToolExecutor) -> AssistantResult:
        trace: list[dict[str, Any]] = []

        def call(name: str, **args: Any) -> Any:
            trace.append({"tool": name, "input": args})
            return self.tb.call(name, args)

        q = question.lower()
        job = self._find_job(question)
        proc = self._find_process(q)
        why = re.search(r"\b(why|cause|caused|root|fail|failed|broke|wrong)\b", q)
        impact = re.search(r"impact|affect|what happens|what if|blast", q)
        graph_answer = None
        if not ((proc and why and not job) or (job and (why or impact))):
            graph_answer = offline_graph.route(q, question, job, proc, self.tb.svc.a.kg, call)
        if graph_answer is not None:
            text = graph_answer
        elif proc and why and not job:
            d = call("get_business_process", process=proc)
            text = self._process(d).split("\n")[0] + "\n\n" + self._root_cause(
                call("get_root_cause", process=proc)).split("\n", 1)[1].strip()
        elif job and re.search(r"impact|affect|what happens|what if|blast", q):
            text = self._impact(call("get_impact", job=job))
        elif job and why:
            text = self._root_cause(call("get_root_cause", job=job))
        elif job and re.search(r"impact|affect|downstream|what happens|blast", q):
            text = self._impact(call("get_impact", job=job))
        elif re.search(r"similar|before|history|happened|past incident", q):
            text = self._incidents(call("search_incident_history", query=question))
        elif proc:
            text = self._process(call("get_business_process", process=proc))
        elif re.search(r"risk|sla|late|miss|breach", q):
            text = self._risks(call("get_estate_overview"))
        elif re.search(r"anomal|slow|unusual|longer", q):
            text = self._list(call("list_insights", type="anomaly"), "No duration anomalies tonight.")
        elif re.search(r"hidden|correlat|depend|link", q):
            text = self._list(call("list_insights", type="correlation"), "No suggested links to review.")
        elif job:
            text = self._job(call("get_job", job=job))
        else:
            text = self._summary(call("get_estate_overview"), call("list_insights"))
        return AssistantResult(text, self.name, self.model, trace,
                               note="Offline mode: set ANTHROPIC_API_KEY (or LLM_PROVIDER) for conversational answers.")

    # ------------------------------------------------------------------ entity spotting
    def _find_job(self, question: str) -> str | None:
        jobs = self.tb.svc.a.estate.jobs()
        ql = question.lower()
        hits = [j for j, job in jobs.items() if job.name.lower() in ql]
        return max(hits, key=lambda j: len(jobs[j].name)) if hits else None

    def _find_process(self, q: str) -> str | None:
        keys = {"payment": "bp-payments-settlement", "ach": "bp-payments-settlement",
                "ledger": "bp-gl-close", "gl close": "bp-gl-close", "regulat": "bp-reg-liquidity",
                "liquidity": "bp-reg-liquidity", "lcr": "bp-reg-liquidity", "2052": "bp-reg-liquidity",
                "fraud": "bp-fraud-scoring", "statement": "bp-customer-statements",
                "c360": "bp-customer-360", "customer 360": "bp-customer-360"}
        return next((v for k, v in keys.items() if k in q), None)

    # ------------------------------------------------------------------ renderers
    def _summary(self, ov: dict, insights: list[dict]) -> str:
        k = ov["kpis"]
        lines = [f"As of {_hhmm(ov['now'])}, I'm watching {k['jobs']} jobs across {k['schedulers']} schedulers, "
                 f"linked by {k['cross_scheduler_links']} cross-scheduler dependencies. {k['succeeded']} jobs have "
                 f"finished, {k['running']} are running and {k['failed']} failed tonight. "
                 f"{k['processes_at_risk']} business processes are at risk."]
        top = [i for i in insights if i["severity"] in ("critical", "high")][:4]
        if top:
            lines.append("\nWhat needs attention:")
            lines += [f"- **{i['title']}**. {i['summary']}" for i in top]
        return "\n".join(lines)

    def _risks(self, ov: dict) -> str:
        risky = [p for p in ov["processes"] if p["status"] in ("at-risk", "breach-likely", "breached")]
        if not risky:
            return "All business processes are on track for their SLAs."
        return "\n".join(["These processes are at risk tonight:"] + [
            f"- **{p['name']}**: projected {_hhmm(p['projected_p50'])} against the {p['sla']} SLA "
            f"({int(p['breach_probability'] * 100)}% breach probability). Its jobs run in "
            f"{', '.join(p['jobs_by_scheduler'])}." for p in risky])

    def _process(self, d: dict) -> str:
        if "error" in d:
            return d["error"]
        crit = [t for t in d["timeline"] if t["critical"]]
        path = " → ".join(f"{t['id'].split('::')[1]} ({t['vendor']})" for t in crit)
        out = [f"**{d['name']}** is **{d['status']}**. It is projected to finish {_hhmm(d['projected_p50'])} "
               f"(P90 {_hhmm(d['projected_p90'])}) against the {d['sla']} SLA, a "
               f"{int(d['breach_probability'] * 100)}% breach probability. It usually finishes around "
               f"{_hhmm(d['usual_end'])}.",
               f"\nIt spans {d['job_count']} jobs across {len(d['jobs_by_scheduler'])} schedulers "
               f"({', '.join(f'{k}: {v}' for k, v in d['jobs_by_scheduler'].items())}).",
               f"\nCritical path: {path}"]
        if d["insights"]:
            out.append("\nRelated insights:")
            out += [f"- {i['title']}" for i in d["insights"][:4]]
        return "\n".join(out)

    def _root_cause(self, d: dict) -> str:
        if "error" in d:
            return d["error"]
        j = d["job"]
        out = [f"**{j['name']}** ({j['vendor']}) is **{j['status']}**."]
        if d["hypotheses"]:
            out.append("\nMost likely causes:")
            out += [f"{n}. {h['reason']} (confidence {int(h['confidence'] * 100)}%)"
                    for n, h in enumerate(d["hypotheses"][:3], 1)]
        else:
            out.append("I found no failures or anomalies upstream of it tonight.")
        if d["similar_incidents"]:
            s = d["similar_incidents"][0]
            out.append(f"\nThe closest past incident is {s['id']} ({s['date']}): {s['title']}. "
                       f"Resolution: {s['resolution']}")
        return "\n".join(out)

    def _impact(self, d: dict) -> str:
        if "error" in d:
            return d["error"]
        j, im = d["job"], d["impact"]
        out = [f"**{j['name']}** feeds {im['downstream_jobs']} downstream jobs "
               f"({', '.join(f'{k}: {v}' for k, v in im['downstream_by_scheduler'].items()) or 'none'})."]
        for p in im["processes"]:
            when = "finished" if p["status"] == "done" else "projected"
            out.append(f"- {p['name']} ({p['criticality']}): {p['status']}, {when} {p['projected_p50']} "
                       f"against the {p['sla']} SLA")
        if im["services"]:
            out.append(f"\nServices exposed: {', '.join(im['services'])}.")
        return "\n".join(out)

    def _incidents(self, hits: list[dict]) -> str:
        if not hits:
            return "I found no similar past incidents."
        return "\n".join(["Similar past incidents:"] + [
            f"- **{h['id']}** ({h['date']}): {h['title']}. Fix: {h['resolution']} (MTTR {h['mttr_minutes']} min)"
            for h in hits])

    def _list(self, items: list[dict], empty: str) -> str:
        return "\n".join([f"- **{i['title']}**. {i['summary']}" for i in items]) if items else empty

    def _job(self, d: dict) -> str:
        return (f"**{d['name']}** ({d['vendor']}, {d['container']}) is **{d['status']}**. Usual duration "
                f"{d['baseline']['p50']} min. It has {len(d['upstream'])} upstream and {len(d['downstream'])} "
                f"downstream links, and supports: {', '.join(d['processes']) or 'no mapped process'}.")
