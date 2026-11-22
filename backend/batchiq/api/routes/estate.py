from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from batchiq.api.deps import get_service
from batchiq.service import EstateService
from batchiq.simulation.scenarios import SCENARIOS

router = APIRouter(tags=["estate"])


@router.get("/meta")
def meta(svc: EstateService = Depends(get_service)):
    return svc.meta()


@router.post("/scenarios/{scenario_id}/activate")
def activate(scenario_id: str, svc: EstateService = Depends(get_service)):
    if scenario_id not in SCENARIOS:
        raise HTTPException(404, f"Unknown scenario {scenario_id}")
    svc.load(scenario_id)
    from batchiq.api.deps import reset_assistant
    reset_assistant()
    return svc.meta()


@router.get("/overview")
def overview(svc: EstateService = Depends(get_service)):
    return svc.overview()


@router.get("/connectors")
def connectors(svc: EstateService = Depends(get_service)):
    return svc.connectors()


@router.get("/connectors/{scheduler_id}/native")
def native(scheduler_id: str, svc: EstateService = Depends(get_service)):
    if scheduler_id not in svc.adapters:
        raise HTTPException(404, "Unknown connector")
    return svc.native_sample(scheduler_id)


@router.get("/jobs")
def jobs(scheduler: str | None = None, q: str | None = None, process: str | None = None,
         svc: EstateService = Depends(get_service)):
    return svc.jobs(scheduler, q, process)


@router.get("/jobs/{job_id:path}")
def job(job_id: str, svc: EstateService = Depends(get_service)):
    if job_id not in svc.a.estate.jobs():
        raise HTTPException(404, "Unknown job")
    return svc.job_detail(job_id)


@router.get("/graph")
def graph(process: str | None = None, cross_only: bool = False, svc: EstateService = Depends(get_service)):
    return svc.graph(process, cross_only)
