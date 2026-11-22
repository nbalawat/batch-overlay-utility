"""Azure Data Factory adapter: management API payloads -> unified model."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from batchiq.adapters.base import ActionCommand, SchedulerAdapter
from batchiq.adapters.registry import register
from batchiq.config import settings
from batchiq.core.artifacts import file_artifact, table_artifact
from batchiq.discovery.sources import SourceRef
from batchiq.domain.models import (
    Artifact,
    ArtifactType,
    Dependency,
    DependencyOrigin,
    Job,
    JobKind,
    JobRun,
    RunStatus,
    Scheduler,
    Vendor,
)

_STATUS = {"Succeeded": RunStatus.SUCCEEDED, "Failed": RunStatus.FAILED, "InProgress": RunStatus.RUNNING,
           "Queued": RunStatus.WAITING, "Cancelled": RunStatus.CANCELLED}
_KIND = {"Copy": JobKind.TRANSFER, "DatabricksNotebook": JobKind.TRANSFORM}


def _local(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v).astimezone(ZoneInfo(settings.estate_timezone)).replace(tzinfo=None)


@register(Vendor.ADF.value)
class ADFAdapter(SchedulerAdapter):
    def scheduler(self) -> Scheduler:
        d = self.client.describe()
        return Scheduler(id=d["id"], vendor=Vendor.ADF, name=d["name"], environment=d["environment"],
                         endpoint=d["endpoint"], description=d["description"])

    def _jid(self, pipe: str, act: str) -> str:
        return f"{self.client.describe()['id']}::{pipe}/{act}"

    def normalise_definitions(self, native: dict[str, Any]) -> tuple[list[Job], list[Dependency]]:
        sid = self.client.describe()["id"]
        datasets = {d["name"]: d["properties"] for d in native["datasets"]}
        trig_by_pipe: dict[str, dict] = {}
        for t in native["triggers"]:
            for p in t["properties"]["pipelines"]:
                trig_by_pipe[p["pipelineReference"]["referenceName"]] = t
        jobs, deps = [], []
        for p in native["pipelines"]:
            name, props = p["name"], p["properties"]
            trig = trig_by_pipe.get(name, {}).get("properties", {})
            ttype = trig.get("type")
            for a in props["activities"]:
                jid = self._jid(name, a["name"])
                consumes = []
                for i in a.get("inputs", []):
                    ds = datasets.get(i["referenceName"], {})
                    tp = ds.get("typeProperties", {})
                    if "table" in tp:
                        consumes.append(table_artifact(tp["schema"], tp["table"]))
                at = None
                schedule = "Manual"
                if not a["dependsOn"]:
                    if ttype == "BlobEventsTrigger":
                        consumes.append(file_artifact(trig["typeProperties"]["blobPathBeginsWith"], prefix=True))
                        schedule = "On blob created: " + trig["typeProperties"]["blobPathBeginsWith"]
                    elif ttype == "ScheduleTrigger":
                        s = trig["typeProperties"]["recurrence"]["schedule"]
                        at = time(s["hours"][0], s["minutes"][0])
                        schedule = f"Daily at {at.strftime('%H:%M')}"
                    elif ttype == "CustomEventsTrigger":
                        subject = trig["typeProperties"]["subjectBeginsWith"]
                        consumes.append(Artifact(type=ArtifactType.EVENT, raw=subject,
                                                 canonical=f"event:{subject.lower()}", match="prefix"))
                        schedule = "On custom event: " + subject
                else:
                    schedule = "After upstream activity"
                jobs.append(Job(
                    id=jid, scheduler_id=sid, vendor=Vendor.ADF, native_id=f"{name}/{a['name']}",
                    name=a["name"], container=name, kind=_KIND.get(a["type"], JobKind.COMMAND),
                    application=(props["annotations"] or [None])[0],
                    owner=props.get("description", "").replace("owner=", "") or None,
                    host=a.get("description"), command=f"{a['type']} activity",
                    schedule=schedule, scheduled_time=at, tags=props["annotations"], consumes=consumes))
                for d in a["dependsOn"]:
                    src = self._jid(name, d["activity"])
                    deps.append(Dependency(id=f"{src}->{jid}", source=src, target=jid,
                                           origin=DependencyOrigin.DECLARED, cross_scheduler=False))
        return jobs, deps

    def normalise_runs(self, native: dict[str, Any], jobs: dict[str, Job]) -> list[JobRun]:
        out = []
        for r in native["value"]:
            start, end = _local(r["activityRunStart"]), _local(r["activityRunEnd"])
            err = r.get("error") or {}
            out.append(JobRun(
                id=f"{r['pipelineRunId']}/{r['activityName']}", job_id=self._jid(r["pipelineName"], r["activityName"]),
                business_date=(start - timedelta(hours=20)).date().isoformat() if start else "",
                attempt=(r.get("retryAttempt") or 0) + 1, status=_STATUS.get(r["status"], RunStatus.WAITING),
                start=start, end=end, duration_s=r["durationInMs"] / 1000 if r["durationInMs"] else None,
                error_code=err.get("errorCode"), message=err.get("message")))
        return out

    def source_refs(self, job: Job) -> list[SourceRef]:
        # The pipeline's ARM/JSON definition in git; referenced notebooks are followed by the miner.
        return [SourceRef(f"pipeline/{job.container}.json", section=job.name)]

    def build_action(self, job: Job, action: str) -> ActionCommand:
        rg, df = "rg-cust-prd", "adf-cust-prd"
        table = {
            "rerun": (f"az datafactory pipeline create-run -g {rg} --factory-name {df} --name {job.container} "
                      f"--is-recovery true --start-activity-name {job.name}",
                      {"method": "POST", "path": f"/pipelines/{job.container}/createRun",
                       "query": {"isRecovery": True, "startActivityName": job.name}}),
            "hold": (f"az datafactory trigger stop -g {rg} --factory-name {df} --name tr_{job.container}_*",
                     {"method": "POST", "path": f"/triggers/tr_{job.container}/stop"}),
            "release": (f"az datafactory trigger start -g {rg} --factory-name {df} --name tr_{job.container}_*",
                        {"method": "POST", "path": f"/triggers/tr_{job.container}/start"}),
            "kill": (f"az datafactory pipeline-run cancel -g {rg} --factory-name {df} --run-id <runId>",
                     {"method": "POST", "path": "/pipelineruns/<runId>/cancel"}),
            "boost_priority": (f"az databricks cluster resize --cluster {job.host} --num-workers 16",
                               {"method": "POST", "path": "/databricks/clusters/resize",
                                "body": {"num_workers": 16}}),
        }
        cmd, api = table[action]
        return ActionCommand(action, job.id, Vendor.ADF.value, cmd, api)
