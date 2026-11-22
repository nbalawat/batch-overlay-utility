"""Control-M adapter: Automation API payloads -> unified model."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

from batchiq.adapters.base import ActionCommand, SchedulerAdapter
from batchiq.adapters.registry import register
from batchiq.core.artifacts import file_artifact
from batchiq.discovery.sources import SourceRef
from batchiq.domain.models import Dependency, DependencyOrigin, Job, JobRun, RunStatus, Scheduler, Vendor

_STATUS = {"Ended OK": RunStatus.SUCCEEDED, "Ended Not OK": RunStatus.FAILED,
           "Executing": RunStatus.RUNNING, "Wait Condition": RunStatus.WAITING,
           "Wait Time": RunStatus.SCHEDULED}


def _ts(v: str) -> datetime | None:
    return datetime.strptime(v, "%Y%m%d%H%M%S") if v else None


@register(Vendor.CONTROL_M.value)
class ControlMAdapter(SchedulerAdapter):
    def scheduler(self) -> Scheduler:
        d = self.client.describe()
        return Scheduler(id=d["id"], vendor=Vendor.CONTROL_M, name=d["name"],
                         environment=d["environment"], endpoint=d["endpoint"], description=d["description"])

    def _job_id(self, folder: str, name: str) -> str:
        return f"{self.client.describe()['id']}::{folder}/{name}"

    def normalise_definitions(self, native: dict[str, Any]) -> tuple[list[Job], list[Dependency]]:
        sid = self.client.describe()["id"]
        jobs: list[Job] = []
        adders: dict[str, str] = {}
        waiters: list[tuple[str, str]] = []
        for folder, body in native.items():
            for name, j in body.items():
                if not isinstance(j, dict) or not str(j.get("Type", "")).startswith("Job"):
                    continue
                jid = self._job_id(folder, name)
                produces, consumes = [], []
                for var in j.get("Variables", []):
                    for k, v in var.items():
                        (produces if k.startswith("OUT") else consumes).append(file_artifact(v))
                when = j.get("When", {})
                ft = when.get("FromTime")
                jobs.append(Job(
                    id=jid, scheduler_id=sid, vendor=Vendor.CONTROL_M, native_id=f"{folder}/{name}",
                    name=name, container=folder, application=j.get("Application"),
                    owner=j.get("CreatedBy"), host=j.get("Host"), command=j.get("Command"),
                    scheduled_time=time(int(ft[:2]), int(ft[2:])) if ft else None,
                    schedule=f"Daily from {ft[:2]}:{ft[2:]}" if ft else "On condition",
                    tags=[t for t in (j.get("Application"), j.get("SubApplication")) if t],
                    produces=produces, consumes=consumes, description=j.get("Description"),
                    alerting=any(isinstance(v, dict) and str(v.get("Type", "")).startswith("If:") for v in j.values()),
                    attributes={"run_as": j.get("RunAs"), "site_standard": body.get("SiteStandard")}))
                for e in j.get("eventsToAdd", {}).get("Events", []):
                    adders[e["Event"]] = jid
                for e in j.get("eventsToWaitFor", {}).get("Events", []):
                    waiters.append((e["Event"], jid))
        deps = [Dependency(id=f"{adders[ev]}->{jid}", source=adders[ev], target=jid,
                           origin=DependencyOrigin.DECLARED, cross_scheduler=False, artifact=ev)
                for ev, jid in waiters if ev in adders]
        by_id = {j.id: j for j in jobs}
        for ev, jid in waiters:
            if ev not in adders:       # no job in this Control-M adds the event: the job can never start
                by_id[jid].unresolved_conditions.append(f"event {ev}")
        return jobs, deps

    def normalise_runs(self, native: dict[str, Any], jobs: dict[str, Job]) -> list[JobRun]:
        out = []
        for s in native["statuses"]:
            jid = self._job_id(s["folder"], s["name"])
            start, end = _ts(s["startTime"]), _ts(s["endTime"])
            status = _STATUS.get(s["status"], RunStatus.WAITING)
            od = s["orderDate"]
            out.append(JobRun(
                id=s["jobId"] + f"/{s['numberOfRuns']}", job_id=jid,
                business_date=f"20{od[:2]}-{od[2:4]}-{od[4:]}", attempt=s["numberOfRuns"], status=status,
                start=start, end=end, duration_s=(end - start).total_seconds() if start and end else None,
                error_code=s["completionCode"] if status == RunStatus.FAILED else None,
                message=s.get("outputSnippet") or None, host=s.get("host") or None))
        return out

    def source_refs(self, job: Job) -> list[SourceRef]:
        cmd = (job.command or "").strip()
        if cmd.startswith("//"):                       # a JCL job card: the member lives in the JCL library
            return [SourceRef(f"PRD.JCLLIB({cmd[2:].split()[0]})")]
        return [SourceRef(cmd.split()[0])] if cmd.startswith("/") else []

    def build_action(self, job: Job, action: str) -> ActionCommand:
        verb = {"rerun": "rerun", "hold": "hold", "release": "free", "kill": "kill",
                "boost_priority": "setToOk"}[action]
        if action == "boost_priority":
            cmd = f"ctm run job:priority::set CTMPRD {job.container} {job.name} AA"
            api = {"method": "POST", "path": f"/run/job/{job.native_id}/priority", "body": {"priority": "AA"}}
        else:
            cmd = f"ctm run job::{verb} CTMPRD:<jobId>   # {job.native_id}"
            api = {"method": "POST", "path": f"/run/job/<jobId>/{verb}", "body": {}}
        return ActionCommand(action, job.id, Vendor.CONTROL_M.value, cmd, api)
