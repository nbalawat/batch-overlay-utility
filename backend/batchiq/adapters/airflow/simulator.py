"""Simulated Airflow stable REST API (v1).

Shapes follow /dags, /dags/{id}/tasks, /datasets and /dags/~/dagRuns/~/taskInstances.
Times are UTC, as Airflow reports them.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from batchiq.domain.models import JobKind, RunStatus
from batchiq.simulation.base import SimulatedClient

_STATE = {RunStatus.SUCCEEDED: "success", RunStatus.FAILED: "failed", RunStatus.RUNNING: "running"}


class AirflowSimulator(SimulatedClient):
    def _dags(self) -> dict[str, list]:
        dags: dict[str, list] = defaultdict(list)
        for s in self.specs:
            dags[s.container].append(s)
        return dags

    def fetch_definitions(self) -> dict[str, Any]:
        dags, tasks, datasets = [], {}, {}
        for dag_id, specs in self._dags().items():
            roots = [s for s in specs if not s.after]
            at = next((s.at for s in roots if s.at), None)
            ds_in = sorted({a.split(":", 1)[1] for s in roots for a in s.consumes if a.startswith("dataset:")})
            schedule = ({"__type": "CronExpression", "value": f"{at.minute} {at.hour} * * *"} if at
                        else {"__type": "DatasetTriggered", "value": ds_in})
            dags.append({"dag_id": dag_id, "is_paused": False, "is_active": True,
                         "owners": sorted({s.owner for s in specs}), "schedule_interval": schedule,
                         "tags": [{"name": t} for t in sorted({s.app for s in specs})],
                         "timetable_description": f"At {at.strftime('%H:%M')} (estate time)" if at
                         else "Triggered by datasets", "fileloc": f"/opt/airflow/dags/{dag_id}.py"})
            tasks[dag_id] = []
            for s in specs:
                rendered = {}
                files = [a.split(":", 1)[1].replace("{date}", "{{ ds_nodash }}")
                         for a in s.consumes if a.startswith("file:")]
                if files:
                    rendered["filepath"] = files[0] if len(files) == 1 else files
                tasks[dag_id].append({
                    "task_id": s.name, "owner": s.owner,
                    "operator_name": "FileSensor" if s.kind == JobKind.SENSOR else (
                        "SnowflakeOperator" if s.host.startswith("snowflake") else
                        "SparkKubernetesOperator" if s.host.startswith("spark") else "PythonOperator"),
                    "pool": s.host if not s.host.startswith(("snowflake", "spark")) else "default_pool",
                    "queue": s.host, "downstream_task_ids": [o.name for o in specs if s.name in o.after],
                    "rendered_fields": rendered,
                    "outlets": [a.split(":", 1)[1] for a in s.produces if a.startswith("dataset:")],
                    **({"mode": "poke", "poke_interval": 60, "timeout": 43200} if s.kind == JobKind.SENSOR else {}),
                    "email_on_failure": s.alarm, "retries": 1,
                })
                for a in s.produces:
                    if a.startswith("dataset:"):
                        datasets.setdefault(a.split(":", 1)[1], {"producing_tasks": [], "consuming_dags": []})[
                            "producing_tasks"].append({"dag_id": dag_id, "task_id": s.name})
            for uri in ds_in:
                datasets.setdefault(uri, {"producing_tasks": [], "consuming_dags": []})[
                    "consuming_dags"].append({"dag_id": dag_id})
        return {"dags": dags, "tasks": tasks,
                "datasets": [{"uri": k, **v} for k, v in datasets.items()]}

    def fetch_runs(self) -> dict[str, Any]:
        tis = []
        for r in self.runs:
            spec = next(s for s in self.specs if s.key == r.key)
            tis.append({
                "dag_id": spec.container, "task_id": spec.name,
                "dag_run_id": f"scheduled__{r.business_date.isoformat()}T00:00:00+00:00",
                "execution_date": f"{r.business_date.isoformat()}T00:00:00+00:00",
                "state": _STATE[r.status], "try_number": r.attempt,
                "start_date": self.to_utc(r.start), "end_date": self.to_utc(r.end),
                "duration": (r.end - r.start).total_seconds() if r.start and r.end else None,
                "hostname": f"worker-{self.short_id(spec.host)[:4]}", "queue": spec.host,
                "note": f"{r.error_code}: {r.message}" if r.error_code else None,
            })
        return {"task_instances": tis, "total_entries": len(tis)}
