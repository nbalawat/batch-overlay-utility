"""Simulated AutoSys AE: JIL definitions (text) and AEWS-style run info (JSON)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from batchiq.domain.models import RunStatus
from batchiq.simulation.base import SimulatedClient

_STATUS = {RunStatus.SUCCEEDED: "SUCCESS", RunStatus.FAILED: "FAILURE", RunStatus.RUNNING: "RUNNING"}
_EXIT = {"ERR_FNF": 2, "EXIT_1": 1}


def _as_path(a: str) -> str:
    return a.split(":", 1)[1].replace("{date}", "$$(BUSDATE)")


class AutoSysSimulator(SimulatedClient):
    def fetch_definitions(self) -> str:
        boxes: dict[str, list] = defaultdict(list)
        for s in self.specs:
            boxes[s.container].append(s)
        lines = ["/* ---- JIL export: autorep -J ALL -q ---- */"]
        for box, specs in boxes.items():
            lines += ["", f"insert_job: {box}   job_type: BOX", f"owner: {specs[0].owner}@AE1",
                      "permission: gx,wx", "date_conditions: 1", "days_of_week: all",
                      f"description: \"{box.replace('_', ' ').title()}\"", f"application: {specs[0].app}"]
            for s in specs:
                args = "".join(f" --in {_as_path(a)}" for a in s.consumes) + \
                       "".join(f" --out {_as_path(a)}" for a in s.produces)
                lines += ["", f"insert_job: {s.name}   job_type: CMD", f"box_name: {box}",
                          f"command: {s.command}{args}", f"machine: {s.host}", f"owner: {s.owner}@AE1",
                          f"application: {s.app}", f"alarm_if_fail: {1 if s.alarm else 0}"]
                if s.after:
                    lines.append("condition: " + " & ".join(f"s({p})" for p in s.after))
                if s.at:
                    lines.append(f"start_times: \"{s.at.strftime('%H:%M')}\"")
        return "\n".join(lines) + "\n"

    def fetch_runs(self) -> dict[str, Any]:
        rows = []
        for i, r in enumerate(self.runs):
            spec = next(s for s in self.specs if s.key == r.key)
            rows.append({
                "jobName": spec.name, "boxName": spec.container, "runNum": 40000 + i, "ntry": r.attempt,
                "status": _STATUS[r.status], "machine": spec.host,
                "startTime": r.start.strftime("%m/%d/%Y %H:%M:%S") if r.start else None,
                "endTime": r.end.strftime("%m/%d/%Y %H:%M:%S") if r.end else None,
                "exitCode": _EXIT.get(r.error_code or "", 1) if r.status == RunStatus.FAILED else 0,
                "alarm": {"type": "JOBFAILURE", "text": f"{r.error_code}: {r.message}"} if r.error_code else None,
            })
        return {"jobRuns": rows}
