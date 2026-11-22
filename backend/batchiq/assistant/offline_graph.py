"""Offline routing and rendering for knowledge-graph questions.

`route` spots what a question is about (a scheduler, a host, a file or table, a
job, a process) and what it asks (lineage, paths, outages, e-mails, transfers,
findings, changes, link reviews), calls the same tools an LLM would, and writes
the answer from their output. It returns None when the question is not one of
these, so the general router can take it.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from batchiq.assistant.graph_tools import mentioned_scheduler
from batchiq.knowledge.ontology import NodeType

Call = Callable[..., Any]
_DATA = {NodeType.FILE, NodeType.DATASET, NodeType.QUEUE, NodeType.COMMUNICATION, NodeType.ENDPOINT}


def _stem(label: str) -> str:
    return re.split(r"_\{date\}|\*", label)[0].lower()


def spot_host(kg, q: str) -> str | None:
    hits = [n for n in kg.nodes.values() if n.type == NodeType.HOST and n.label.lower() in q]
    return max(hits, key=lambda n: len(n.label)).label if hits else None


def spot_data(kg, q: str) -> str | None:
    hits = [n for n in kg.nodes.values() if n.type in _DATA and len(_stem(n.label)) >= 6 and _stem(n.label) in q]
    return max(hits, key=lambda n: len(_stem(n.label))).id if hits else None


_GENERIC = {"team", "teams", "operations", "engineering", "data", "technology", "batch", "ops"}


def spot_team(kg, q: str) -> str | None:
    words = set(re.findall(r"[a-z0-9]+", q))
    best, score = None, 0
    for n in kg.nodes.values():
        if n.type != NodeType.TEAM:
            continue
        name = set(re.findall(r"[a-z0-9]+", f"{n.label} {n.props.get('team_id', '')}".lower())) - _GENERIC
        hit = len({w for w in name if len(w) > 2} & words)
        if hit > score:
            best, score = n.id, hit
    return best


def route(q: str, question: str, job: str | None, proc: str | None, kg, call: Call) -> str | None:
    sched = mentioned_scheduler(q)
    host = spot_host(kg, q)
    data = spot_data(kg, q)
    if re.search(r"\bchang(e|ed|es)\b|changelog|what'?s new|modified", q):
        return changes(call("list_changes", **({"job": job.split("::")[-1].split(".")[-1].split("/")[-1]}
                                                  if job else {})))
    if host and re.search(r"\b(down|outage|lose|lost|fails?|offline|break|breaks|unavailable|went)\b", q):
        return outage(call("host_outage_impact", host=host))
    if re.search(r"leav\w* the bank|outside the bank|external|egress|sftp|transfer|send\w* (data|files?) out", q):
        return comms(call("find_communications", kind="egress", **({"scheduler": sched} if sched else {})),
                     "Data leaving the bank")
    if re.search(r"\be-?mails?\b|\bmail\b|notif", q) and not job:
        return comms(call("find_communications", kind="email", **({"scheduler": sched} if sched else {})),
                     "E-mails sent by jobs")
    if re.search(r"\bapis?\b|endpoints?|\bhttp", q) and not job:
        return comms(call("find_communications", kind="api", **({"scheduler": sched} if sched else {})),
                     "API calls made by jobs")
    if re.search(r"\breview|candidate|recommend\w* link|hidden|approv|pending link|\blinks?\b", q):
        name = job.split("::")[-1].split(".")[-1].split("/")[-1] if job else None
        return links(call("list_link_candidates", **({"job": name} if name else {})))
    if re.search(r"\b(own|owns|owned|owner|owners|team)\b", q) and not job and (team := spot_team(kg, q)):
        return entity(call("describe_entity", entity=team, relation="OWNED_BY"))
    if job and proc and re.search(r"\b(how|path|connect\w*|related|reach|get to)\b", q):
        return path(call("find_path", source=job, target=f"process:{proc}", relations="FEEDS,DELIVERS"))
    if job and re.search(r"depend|upstream|lineage|downstream|feeds? into|rel(y|ies) on|everything (before|after)"
                         r"|waits? (on|for)", q):
        down = bool(re.search(r"downstream|feeds? into|rel(y|ies) on it|depends? on it|after", q))
        return lineage(call("trace_lineage", job=job, direction="down" if down else "up"))
    if re.search(r"silent|unmonitored|no alert", q):
        return findings(call("list_findings", category="unmonitored", **({"scheduler": sched} if sched else {})),
                        "Jobs that fail silently")
    if re.search(r"finding|issues?|problems?|wrong with|improve|optimi[sz]|waste|stale|secret|password|smell|"
                 r"health ?check|bottleneck", q):
        args: dict[str, Any] = {}
        if sched:
            args["scheduler"] = sched
        if re.search(r"improve|optimi[sz]|waste|runtime|bottleneck|slow", q):
            args["kind"] = "runtime"
        return findings(call("list_findings", **args), "Findings")
    if (host or data) and not job:
        return entity(call("describe_entity", entity=host or data))
    if sched and not job:
        return ecosystem(call("get_ecosystem", scheduler=sched), q)
    return None


# ---------------------------------------------------------------------- renderers
def _plural(word: str, n: int) -> str:
    return word if n == 1 else word + ("es" if word.endswith(("x", "s")) else "s")


def _err(d: Any) -> str | None:
    return d["error"] if isinstance(d, dict) and "error" in d else None


def changes(rows: list[dict]) -> str:
    if not rows:
        return "No definition changes were detected in the last 30 syncs."
    out = ["Definition changes detected between syncs, newest first:"]
    for r in rows:
        ticket = f" ({r['ticket']}, {r['author']})" if r["ticket"] else ""
        out.append(f"- **{r['detected']}** {r['job']} in {r['scheduler']}: {r['kind']}{ticket}. "
                   f"{'; '.join(r['details'])}")
        for f in r["follow_ups"]:
            if f["state"] in ("approved", "rejected"):
                continue
            out.append(f"  - Follow-up link to review: {f['link_id']} ({f['probability']:.0%}, {f['state']})")
    return "\n".join(out)


def outage(d: dict) -> str:
    if (e := _err(d)):
        return e
    procs = ", ".join(f"{p['name']} ({p['criticality']}, SLA {p['sla']})" for p in d["processes"]) or "none mapped"
    return (f"If **{d['host']}** ({d['kind']}) goes down, {len(d['jobs_on_host'])} jobs run there "
            f"({', '.join(d['jobs_on_host'])}) and {d['downstream_jobs']} more downstream stop, across "
            f"{', '.join(d['schedulers_affected'])}.\n\nBusiness processes hit: {procs}."
            + (f"\n\nServices exposed: {', '.join(d['services'])}." if d["services"] else ""))


def comms(rows: list[dict], title: str) -> str:
    if not rows:
        return f"{title}: none found in the mined code."
    out = [f"**{title}** ({len(rows)}), mined from job code:"]
    for r in rows[:20]:
        extra = r["subject"] or r["path"] or r["method"] or ""
        ext = " (external)" if r["external"] else ""
        out.append(f"- {r['job']} ({r['scheduler']}) → {r['to']}{ext}{': ' + extra if extra else ''}"
                   f" [{r['source']}]")
    return "\n".join(out)


def links(d: dict) -> str:
    c = d["counts"]
    out = [f"The review queue has {c['proposed']} proposed, {c['in_review']} in review and {c['needs_info']} "
           f"waiting for information ({c['approved']} approved, {c['rejected']} rejected so far)."]
    for x in d["links"][:8]:
        out.append(f"- **{x['from']} → {x['to']}**: {x['probability']:.0%} from {', '.join(x['evidence'])}. "
                   f"{x['state'].replace('_', ' ')}, waiting on {', '.join(x['waiting_on']) or 'nobody'}.")
    out.append("\nOpen Link review to approve, reject or ask a question.")
    return "\n".join(out)


def path(d: dict) -> str:
    if (e := _err(d)):
        return e
    if not d["paths"]:
        return f"I found no connection between {d['from']['label']} and {d['to']['label']} in the knowledge graph."
    p = d["paths"][0]
    hops = " → ".join(f"{h['label']}" + (f" ({h['scheduler']})" if h.get("scheduler") else "") for h in p["hops"])
    pending = [v for v in p["via"] if v.get("review") and v["review"] != "approved"]
    out = [f"**{d['from']['label']}** reaches **{d['to']['label']}** in {len(p['via'])} hops: {hops}."]
    if pending:
        out.append(f"\n{len(pending)} hop(s) on this path are recommended links still in review.")
    if len(d["paths"]) > 1:
        out.append(f"\nThere are {len(d['paths'])} paths; the shortest is shown.")
    return "\n".join(out)


def lineage(d: dict) -> str:
    if (e := _err(d)):
        return e
    j = d["job"]
    if d["count"]:
        out = [f"**{j['label']}** ({j['scheduler']}) has {d['count']} confirmed jobs {d['direction']}, across "
               f"{', '.join(d['schedulers'])}:"]
    else:
        out = [f"**{j['label']}** ({j['scheduler']}) has no confirmed jobs {d['direction']}: no scheduler "
               "condition, file match or approved link ties it to another job."]
    for level in d["by_depth"][:6]:
        names = ", ".join(f"{x['job']} ({x['scheduler']})" for x in level["jobs"][:8])
        out.append(f"- {level['depth']} hop{'s' if level['depth'] > 1 else ''}: {names}")
    if d["pending_links_not_counted"]:
        out.append("\nNot counted yet, because the link is still in review: " + ", ".join(
            f"{p['other']} ({p['probability']:.0%})" for p in d["pending_links_not_counted"]) + ".")
    return "\n".join(out)


def findings(rows: list[dict], title: str) -> str:
    if not rows:
        return f"{title}: nothing found."
    out = [f"**{title}** ({len(rows)}), most severe first:"]
    out += [f"- [{r['severity']}] **{r['title']}**. {r['recommendation']}" for r in rows[:10]]
    return "\n".join(out)


def entity(d: dict) -> str:
    if (e := _err(d)):
        return e
    n = d["node"]
    out = [f"**{n['label']}** ({n['type']}):"]
    for r in d["relations"]:
        verb = r["type"].lower().replace("_", " ")
        names = ", ".join(f"{i['label']}" + (f" ({i['scheduler']})" if i.get("scheduler") else "")
                          + f" [{'/'.join(i['provenance'])}]" for i in r["items"][:10])
        out.append(f"- {'←' if r['direction'] == 'in' else '→'} {verb}: {names}")
    if d.get("people"):
        out.append("\nPeople: " + ", ".join(f"{p['name']} ({p['title']})" for p in d["people"]) + ".")
    return "\n".join(out)


def ecosystem(d: dict, q: str) -> str:
    if (e := _err(d)):
        return e
    s = d["stats"]
    out = [f"**{d['name']}** has {s['jobs']} jobs in {s['containers']} {_plural(d['container_kind'], s['containers'])}, linked by "
           f"{s['intra_links']} internal dependencies and {s['boundary_links']} links to other schedulers "
           f"({s['pending_boundary_links']} still in review)."]
    if re.search(r"depend|outside|other|cross|boundary|external", q):
        out.append("\nLinks across its boundary:")
        out += [f"- {b['source'].split('::')[1]} → {b['target'].split('::')[1]} ({b['origin']}, "
                f"{b['review_state']})" for b in d["boundary_links"][:10]]
    if re.search(r"host|server|machine|run on", q):
        out.append("\nHosts: " + ", ".join(f"{h['host']} ({h['jobs']} jobs)" for h in d["hosts"]))
    if d["unmonitored"]:
        out.append(f"\nNo failure alert: {', '.join(d['unmonitored'])}.")
    if d["unresolved"]:
        out.append("Waits on something nothing provides: " + ", ".join(
            f"{u['job']} ({', '.join(u['waits_on'])})" for u in d["unresolved"]) + ".")
    if d["findings"]:
        out.append("\nTop findings:")
        out += [f"- [{f['severity']}] {f['title']}" for f in d["findings"][:5]]
    return "\n".join(out)
