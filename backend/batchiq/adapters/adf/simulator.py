"""Simulated Azure Data Factory REST API (pipelines, triggers, datasets, activity runs).

Any cloud-native orchestrator (AWS Step Functions, GCP Cloud Composer/Workflows)
would plug in the same way; ADF is the example here.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from batchiq.domain.models import JobKind, RunStatus
from batchiq.simulation.base import SimulatedClient

_STATUS = {RunStatus.SUCCEEDED: "Succeeded", RunStatus.FAILED: "Failed", RunStatus.RUNNING: "InProgress"}
_TYPE = {JobKind.TRANSFER: "Copy", JobKind.TRANSFORM: "DatabricksNotebook", JobKind.COMMAND: "Script"}


class ADFSimulator(SimulatedClient):
    def fetch_definitions(self) -> dict[str, Any]:
        pipes: dict[str, list] = defaultdict(list)
        for s in self.specs:
            pipes[s.container].append(s)
        pipelines, triggers, datasets = [], [], []
        for name, specs in pipes.items():
            acts = []
            for s in specs:
                inputs = []
                for a in s.consumes:
                    if a.startswith("table:"):
                        schema, table = a.split(":", 1)[1].split(".")
                        ds = f"ds_{schema}_{table}"
                        datasets.append({"name": ds, "properties": {
                            "type": "SnowflakeTable", "linkedServiceName": {"referenceName": "ls_snowflake_prd"},
                            "typeProperties": {"schema": schema, "table": table}}})
                        inputs.append({"referenceName": ds, "type": "DatasetReference"})
                acts.append({"name": s.name, "type": _TYPE.get(s.kind, "Script"),
                             "dependsOn": [{"activity": p, "dependencyConditions": ["Succeeded"]} for p in s.after],
                             "inputs": inputs, "linkedServiceName": {"referenceName": f"ls_{s.host.split(':')[0]}"},
                             "description": s.host})
            pipelines.append({"name": name, "properties": {
                "activities": acts, "annotations": sorted({s.app for s in specs}),
                "folder": {"name": specs[0].app}, "description": f"owner={specs[0].owner}"}})
            root = specs[0]
            blob = next((a for a in root.consumes if a.startswith("file:")), None)
            if blob:
                triggers.append({"name": f"tr_{name}_blob", "properties": {
                    "type": "BlobEventsTrigger", "runtimeState": "Started",
                    "typeProperties": {"blobPathBeginsWith": "/" + blob.split(":", 1)[1].replace(
                        "landing/", "landing/blobs/"), "events": ["Microsoft.Storage.BlobCreated"]},
                    "pipelines": [{"pipelineReference": {"referenceName": name}}]}})
            elif root.at:
                triggers.append({"name": f"tr_{name}_daily", "properties": {
                    "type": "ScheduleTrigger", "runtimeState": "Started",
                    "typeProperties": {"recurrence": {"frequency": "Day", "interval": 1, "timeZone":
                                       "Eastern Standard Time", "schedule": {
                                           "hours": [root.at.hour], "minutes": [root.at.minute]}}},
                    "pipelines": [{"pipelineReference": {"referenceName": name}}]}})
            else:
                triggers.append({"name": f"tr_{name}_event", "properties": {
                    "type": "CustomEventsTrigger", "runtimeState": "Started",
                    "typeProperties": {"subjectBeginsWith": name.replace("pl_", ""), "events": ["refresh"]},
                    "pipelines": [{"pipelineReference": {"referenceName": name}}]}})
        return {"pipelines": pipelines, "triggers": triggers, "datasets": datasets}

    def fetch_runs(self) -> dict[str, Any]:
        value = []
        for r in self.runs:
            spec = next(s for s in self.specs if s.key == r.key)
            run_id = self.short_id(spec.container, str(r.business_date), str(r.attempt))
            value.append({
                "pipelineName": spec.container, "pipelineRunId": f"{run_id}-0000-4000-8000-{run_id}0000",
                "activityName": spec.name, "activityType": _TYPE.get(spec.kind, "Script"),
                "activityRunStart": self.to_utc(r.start), "activityRunEnd": self.to_utc(r.end),
                "durationInMs": int((r.end - r.start).total_seconds() * 1000) if r.start and r.end else None,
                "status": _STATUS[r.status], "retryAttempt": r.attempt - 1 or None,
                "error": {"errorCode": r.error_code, "message": r.message} if r.error_code else {},
            })
        return {"value": value}
