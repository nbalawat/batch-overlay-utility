"""Routes for the v2 screens: ecosystems, knowledge graph, link review, findings, changelog, onboarding."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from batchiq.api.deps import get_service
from batchiq.linking.review import ReviewError
from batchiq.service import EstateService
from batchiq.views import ecosystems as eco
from batchiq.views import findings as fnd
from batchiq.views import knowledge as kgv
from batchiq.views import links as lnk
from batchiq.views import onboarding as onb

router = APIRouter(tags=["knowledge"])


# ---------------------------------------------------------------------- ecosystems
@router.get("/ecosystems")
def ecosystems(svc: EstateService = Depends(get_service)):
    return eco.ecosystems(svc)


@router.get("/ecosystems/{scheduler_id}")
def ecosystem(scheduler_id: str, svc: EstateService = Depends(get_service)):
    if scheduler_id not in svc.a.estate.schedulers:
        raise HTTPException(404, "Unknown scheduler")
    return eco.ecosystem(svc, scheduler_id)


# ---------------------------------------------------------------------- knowledge graph
@router.get("/kg/ontology")
def ontology(svc: EstateService = Depends(get_service)):
    return kgv.ontology(svc.a.kg)


@router.get("/kg/search")
def kg_search(q: str = Query(min_length=1, max_length=200), type: str | None = None, limit: int = 25,
              svc: EstateService = Depends(get_service)):
    try:
        return kgv.search(svc.a.kg, q, type, min(limit, 100))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/kg/node")
def kg_node(id: str, svc: EstateService = Depends(get_service)):
    try:
        return kgv.node(svc.a.kg, id)
    except kgv.UnknownNode as e:
        raise HTTPException(404, f"Unknown node {id}") from e


@router.get("/kg/neighbourhood")
def kg_neighbourhood(id: str, depth: int = 1, types: str | None = None, svc: EstateService = Depends(get_service)):
    try:
        return kgv.neighbourhood(svc.a.kg, id, depth, types)
    except kgv.UnknownNode as e:
        raise HTTPException(404, f"Unknown node {id}") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/kg/paths")
def kg_paths(source: str = Query(alias="from"), target: str = Query(alias="to"), directed: bool = True,
             types: str | None = None, svc: EstateService = Depends(get_service)):
    try:
        return kgv.paths(svc.a.kg, source, target, directed, types)
    except kgv.UnknownNode as e:
        raise HTTPException(404, f"Unknown node {e.args[0]}") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------------- link review
@router.get("/people")
def people(svc: EstateService = Depends(get_service)):
    return lnk.people(svc)


@router.get("/links")
def links(state: str | None = None, person: str | None = None, scope: str | None = None,
          svc: EstateService = Depends(get_service)):
    return lnk.link_queue(svc, state, person, scope)


class ReviewRequest(BaseModel):
    person: str = Field(min_length=1, max_length=64)
    decision: Literal["approve", "reject", "needs_info", "comment", "reopen"]
    comment: str = Field(default="", max_length=2000)


@router.post("/links/{link_id:path}/review")
def review(link_id: str, req: ReviewRequest, svc: EstateService = Depends(get_service)):
    if link_id not in svc.candidates:
        raise HTTPException(404, "Unknown link")
    try:
        return lnk.review(svc, link_id, req.person, req.decision, req.comment)
    except ReviewError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/links/{link_id:path}")
def link(link_id: str, svc: EstateService = Depends(get_service)):
    if link_id not in svc.candidates:
        raise HTTPException(404, "Unknown link")
    return lnk.link_card(svc, link_id, detail=True)


# ---------------------------------------------------------------------- findings and changes
@router.get("/findings")
def findings(kind: str | None = None, scope: str | None = None, category: str | None = None,
             severity: str | None = None, job: str | None = None, svc: EstateService = Depends(get_service)):
    return fnd.findings(svc.a.findings, kind, scope, category, severity, job)


@router.get("/changelog")
def changelog(svc: EstateService = Depends(get_service)):
    return svc.changelog_entries or []


# ---------------------------------------------------------------------- onboarding
@router.get("/onboarding")
def onboarding(svc: EstateService = Depends(get_service)):
    return onb.pipeline(svc)


@router.get("/onboarding/samples")
def samples():
    return onb.samples()


class ImportRequest(BaseModel):
    vendor: Literal["control-m", "autosys", "airflow", "azure-data-factory"]
    content: str = Field(min_length=1)
    scheduler_id: str = Field(default="imported", pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")
    name: str = Field(default="Imported scheduler", max_length=80)


@router.post("/onboarding/import")
def import_sandbox(req: ImportRequest, svc: EstateService = Depends(get_service)):
    try:
        return onb.import_sandbox(svc, req.vendor, req.content, req.scheduler_id, req.name)
    except onb.ImportError_ as e:
        raise HTTPException(400, str(e)) from e
