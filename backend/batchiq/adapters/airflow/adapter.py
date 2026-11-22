"""Airflow adapter: REST API payloads -> unified model."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from batchiq.adapters.base import ActionCommand, SchedulerAdapter
from batchiq.adapters.registry import register
from batchiq.config import settings
from batchiq.core.artifacts import dataset_artifact, file_artifact
from batchiq.domain.models import (Dependency, DependencyOrigin, Job, JobKind, JobRun, RunStatus,
                                   Scheduler, Vendor)

_STATE = {"success": RunStatus.SUCCEEDED, "failed": RunStatus.FAILED, "running": RunStatus.RUNNING,
          "queued": RunStatus.WAITING, "scheduled": RunStatus.SCHEDULED,
          "upstream_failed": RunStatus.CANCELLED, "deferred": RunStatus.RUNNING}
_KIND = {"FileSensor": JobKind.SENSOR, "ExternalTaskSensor": JobKind.SENSOR,
         "SnowflakeOperator": JobKind.TRANSFORM, "SparkKubernetesOperator": JobKind.TRANSFORM}


def _local(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v).astimezone(ZoneInfo(settings.estate_timezone)).replace(tzinfo=None)


@register(Vendor.AIRFLOW.value)
class AirflowAdapter(SchedulerAdapter):
    def scheduler(self) -> Scheduler:
        d = self.client.describe()
        return Scheduler(id=d["id"], vendor=Vendor.AIRFLOW, name=d["name"], environment=d["environment"],
                         endpoint=d["endpoint"], description=d["description"])

    def _jid(self, dag: str, task: str) -> str:
        return f"{self.client.describe()['id']}::{dag}.{task}"

    def normalise_definitions(self, native: dict[str, Any]) -> tuple[list[Job], list[Dependency]]:
        sid = self.client.describe()["id"]
        dag_meta = {d["dag_id"]: d for d in native["dags"]}
        consumed: dict[str, list[str]] = {}
        for ds in native["datasets"]:
            for c in ds["consuming_dags"]:
                consumed.setdefault(c["dag_id"], []).append(ds["uri"])
        jobs: list[Job] = []
        deps: list[Dependency] = []
        for dag_id, tasks in native["tasks"].items():
            meta = dag_meta[dag_id]
            sched = meta["schedule_interval"]
            upstream_ids = {d for t in tasks for d in t["downstream_task_ids"]}
            for t in tasks:
                consumes = []
                fp = t.get("rendered_fields", {}).get("filepath")
                for p in ([fp] if isinstance(fp, str) else fp or []):
                    consumes.append(file_artifact(p))
                if t["task_id"] not in upstream_ids:  # root task of a dataset-triggered DAG
                    consumes += [dataset_artifact(u) for u in consumed.get(dag_id, [])]
                at = None
                if sched["__type"] == "CronExpression":
                    m, h = sched["value"].split()[:2]
                    at = time(int(h), int(m)) if t["task_id"] not in upstream_ids else None
                jobs.append(Job(
                    id=self._jid(dag_id, t["task_id"]), scheduler_id=sid, vendor=Vendor.AIRFLOW,
                    native_id=f"{dag_id}.{t['task_id']}", name=t["task_id"], container=dag_id,
                    kind=_KIND.get(t["operator_name"], JobKind.COMMAND),
                    application=(meta["tags"][0]["name"] if meta["tags"] else None), owner=t["owner"],
                    host=t["queue"], command=f"{t['operator_name']} in {meta['fileloc']}",
                    schedule=meta["timetable_description"], scheduled_time=at,
                    tags=[x["name"] for x in meta["tags"]],
                    produces=[dataset_artifact(u) for u in t.get("outlets", [])], consumes=consumes))
                for d in t["downstream_task_ids"]:
                    src, tgt = self._jid(dag_id, t["task_id"]), self._jid(dag_id, d)
                    deps.append(Dependency(id=f"{src}->{tgt}", source=src, target=tgt,
                                           origin=DependencyOrigin.DECLARED, cross_scheduler=False))
        return jobs, deps

    def normalise_runs(self, native: dict[str, Any], jobs: dict[str, Job]) -> list[JobRun]:
        out = []
        for ti in native["task_instances"]:
            start, end = _local(ti["start_date"]), _local(ti["end_date"])
            status = _STATE.get(ti["state"], RunStatus.WAITING)
            note = ti.get("note") or ""
            code, _, msg = note.partition(": ")
            out.append(JobRun(
                id=f"{ti['dag_id']}.{ti['task_id']}@{ti['dag_run_id']}#{ti['try_number']}",
                job_id=self._jid(ti["dag_id"], ti["task_id"]), business_date=ti["execution_date"][:10],
                attempt=ti["try_number"], status=status, start=start, end=end, duration_s=ti["duration"],
                error_code=code or None, message=msg or None))
        return out

    def build_action(self, job: Job, action: str) -> ActionCommand:
        dag, task = job.container, job.name
        table = {
            "rerun": (f"airflow tasks clear {dag} -t '^{task}$' -s <ds> -e <ds> -y",
                      {"method": "POST", "path": f"/dags/{dag}/clearTaskInstances",
                       "body": {"task_ids": [task], "only_failed": False, "dry_run": False}}),
            "hold": (f"airflow dags pause {dag}", {"method": "PATCH", "path": f"/dags/{dag}",
                                                   "body": {"is_paused": True}}),
            "release": (f"airflow dags unpause {dag}", {"method": "PATCH", "path": f"/dags/{dag}",
                                                        "body": {"is_paused": False}}),
            "kill": (f"airflow tasks state {dag} {task} <ds> --set failed",
                     {"method": "PATCH", "path": f"/dags/{dag}/dagRuns/<run_id>/taskInstances/{task}",
                      "body": {"new_state": "failed"}}),
            "boost_priority": (f"airflow pools set {job.host or 'default_pool'} 64 'batch window boost'",
                               {"method": "PATCH", "path": f"/pools/{job.host or 'default_pool'}",
                                "body": {"slots": 64}}),
        }
        cmd, api = table[action]
        return ActionCommand(action, job.id, Vendor.AIRFLOW.value, cmd, api)
