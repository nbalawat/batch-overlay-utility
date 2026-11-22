"""AutoSys adapter: parses JIL text and AEWS run info into the unified model."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any

from batchiq.adapters.base import ActionCommand, SchedulerAdapter
from batchiq.adapters.registry import register
from batchiq.core.artifacts import file_artifact
from batchiq.domain.models import Dependency, DependencyOrigin, Job, JobRun, RunStatus, Scheduler, Vendor

_STATUS = {"SUCCESS": RunStatus.SUCCEEDED, "FAILURE": RunStatus.FAILED, "RUNNING": RunStatus.RUNNING,
           "ACTIVATED": RunStatus.WAITING, "STARTING": RunStatus.RUNNING, "TERMINATED": RunStatus.CANCELLED,
           "ON_HOLD": RunStatus.WAITING, "INACTIVE": RunStatus.SCHEDULED}
_COND = re.compile(r"\b(?:s|success)\(([\w.]+)\)")


def parse_jil(text: str) -> list[dict[str, str]]:
    """Minimal JIL parser: one dict of attributes per insert_job block."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    jobs: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("insert_job:"):
            m = re.match(r"insert_job:\s*(\S+)\s+job_type:\s*(\S+)", line)
            cur = {"insert_job": m.group(1), "job_type": m.group(2)}
            jobs.append(cur)
        elif cur is not None and ":" in line:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip().strip('"')
    return jobs


@register(Vendor.AUTOSYS.value)
class AutoSysAdapter(SchedulerAdapter):
    def scheduler(self) -> Scheduler:
        d = self.client.describe()
        return Scheduler(id=d["id"], vendor=Vendor.AUTOSYS, name=d["name"], environment=d["environment"],
                         endpoint=d["endpoint"], description=d["description"])

    def _jid(self, name: str) -> str:
        return f"{self.client.describe()['id']}::{name}"

    def normalise_definitions(self, native: str) -> tuple[list[Job], list[Dependency]]:
        sid = self.client.describe()["id"]
        jobs, deps = [], []
        for j in parse_jil(native):
            if j["job_type"] == "BOX":
                continue
            cmd = j.get("command", "")
            produces = [file_artifact(p) for p in re.findall(r"--out\s+(\S+)", cmd)]
            consumes = [file_artifact(p) for p in re.findall(r"--in\s+(\S+)", cmd)]
            st = j.get("start_times")
            jid = self._jid(j["insert_job"])
            jobs.append(Job(
                id=jid, scheduler_id=sid, vendor=Vendor.AUTOSYS, native_id=j["insert_job"],
                name=j["insert_job"], container=j.get("box_name", "-"), application=j.get("application"),
                owner=j.get("owner"), host=j.get("machine"), command=cmd,
                scheduled_time=time.fromisoformat(st) if st else None,
                schedule=f"Daily at {st}" if st else "On condition",
                tags=[t for t in (j.get("application"), j.get("box_name")) if t],
                produces=produces, consumes=consumes))
            for up in _COND.findall(j.get("condition", "")):
                deps.append(Dependency(id=f"{self._jid(up)}->{jid}", source=self._jid(up), target=jid,
                                       origin=DependencyOrigin.DECLARED, cross_scheduler=False,
                                       artifact=f"s({up})"))
        return jobs, deps

    def normalise_runs(self, native: dict[str, Any], jobs: dict[str, Job]) -> list[JobRun]:
        out = []
        for r in native["jobRuns"]:
            start = datetime.strptime(r["startTime"], "%m/%d/%Y %H:%M:%S") if r["startTime"] else None
            end = datetime.strptime(r["endTime"], "%m/%d/%Y %H:%M:%S") if r["endTime"] else None
            # AutoSys has no business date: derive it from the batch night the run started in.
            bd = (start - timedelta(hours=20)).date().isoformat() if start else ""
            code, msg = None, None
            if r.get("alarm"):
                code, _, msg = r["alarm"]["text"].partition(": ")
            out.append(JobRun(
                id=f"{r['jobName']}#{r['runNum']}/{r['ntry']}", job_id=self._jid(r["jobName"]),
                business_date=bd, attempt=r["ntry"], status=_STATUS.get(r["status"], RunStatus.WAITING),
                start=start, end=end, duration_s=(end - start).total_seconds() if start and end else None,
                error_code=code, message=msg))
        return out

    def build_action(self, job: Job, action: str) -> ActionCommand:
        event = {"rerun": "FORCE_STARTJOB", "hold": "JOB_ON_HOLD", "release": "JOB_OFF_HOLD",
                 "kill": "KILLJOB", "boost_priority": "CHANGE_PRIORITY"}[action]
        extra = " -q 1" if action == "boost_priority" else ""
        return ActionCommand(action, job.id, Vendor.AUTOSYS.value, f"sendevent -E {event} -J {job.name}{extra}",
                             {"method": "POST", "path": "/AEWS/event/sendevent",
                              "body": {"eventType": event, "jobName": job.name}})
