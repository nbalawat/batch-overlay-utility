"""Simulated Control-M Automation API.

Definitions follow the Automation API JSON "jobs-as-code" shape (folders with
jobs, eventsToWaitFor / eventsToAdd). Runs follow `GET /run/jobs/status`.
"""
from __future__ import annotations

from typing import Any

from batchiq.domain.models import RunStatus
from batchiq.simulation.base import SimulatedClient

_STATUS = {
    RunStatus.SUCCEEDED: "Ended OK",
    RunStatus.FAILED: "Ended Not OK",
    RunStatus.RUNNING: "Executing",
}


def _ctm_path(artifact: str) -> str:
    return artifact.split(":", 1)[1].replace("{date}", "%%ODATE")


class ControlMSimulator(SimulatedClient):
    def fetch_definitions(self) -> dict[str, Any]:
        folders: dict[str, Any] = {}
        for s in self.specs:
            folder = folders.setdefault(s.container, {
                "Type": "Folder", "ControlmServer": "CTMPRD", "OrderMethod": "Automatic",
                "SiteStandard": "BANK_STD_V4"})
            job: dict[str, Any] = {
                "Type": "Job:Command", "Command": s.command, "Host": s.host, "RunAs": "BATCHPRD",
                "Application": s.app, "SubApplication": s.container, "CreatedBy": s.owner,
                "Description": s.description or s.name.replace("_", " ").title(),
            }
            if s.at:
                job["When"] = {"FromTime": s.at.strftime("%H%M"), "WeekDays": ["ALL"]}
            variables = [{"OUTFILE": _ctm_path(a)} for a in s.produces] + \
                        [{"INFILE": _ctm_path(a)} for a in s.consumes]
            if variables:
                job["Variables"] = variables
            if s.after:
                job["eventsToWaitFor"] = {"Type": "WaitForEvents",
                                          "Events": [{"Event": f"{p}-TO-{s.name}"} for p in s.after]}
            succ = [o.name for o in self.specs if s.name in o.after]
            if succ:
                job["eventsToAdd"] = {"Type": "AddEvents",
                                      "Events": [{"Event": f"{s.name}-TO-{n}"} for n in succ]}
            folder[s.name] = job
        return folders

    def fetch_runs(self) -> dict[str, Any]:
        statuses = []
        for r in self.runs:
            spec = next(s for s in self.specs if s.key == r.key)
            statuses.append({
                "jobId": f"CTMPRD:{self.short_id(r.key, str(r.business_date), str(r.attempt))}",
                "folder": spec.container, "name": spec.name, "type": "Command",
                "orderDate": r.business_date.strftime("%y%m%d"),
                "status": _STATUS[r.status], "numberOfRuns": r.attempt, "host": spec.host,
                "startTime": r.start.strftime("%Y%m%d%H%M%S") if r.start else "",
                "endTime": r.end.strftime("%Y%m%d%H%M%S") if r.end else "",
                "completionCode": r.error_code or ("0" if r.status == RunStatus.SUCCEEDED else ""),
                "outputSnippet": r.message or "",
            })
        return {"statuses": statuses, "returned": len(statuses), "total": len(statuses)}
