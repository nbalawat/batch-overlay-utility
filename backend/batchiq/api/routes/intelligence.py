from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from batchiq.adapters.base import SUPPORTED_ACTIONS
from batchiq.api.deps import get_assistant, get_service
from batchiq.assistant.agent import Assistant
from batchiq.service import EstateService

router = APIRouter(tags=["intelligence"])


@router.get("/processes")
def processes(svc: EstateService = Depends(get_service)):
    return [svc.process_brief(p) for p in svc.a.mapper.processes]


@router.get("/processes/{process_id}")
def process(process_id: str, svc: EstateService = Depends(get_service)):
    if process_id not in svc.a.mapper.processes:
        raise HTTPException(404, "Unknown process")
    return svc.process_detail(process_id)


@router.get("/insights")
def insights(type: str | None = None, svc: EstateService = Depends(get_service)):
    return svc.insights(type)


@router.get("/insights/{insight_id:path}")
def insight(insight_id: str, svc: EstateService = Depends(get_service)):
    i = svc.insight(insight_id)
    if not i:
        raise HTTPException(404, "Unknown insight")
    return i


class ActionRequest(BaseModel):
    action: str
    job_id: str | None = None
    process_id: str | None = None
    dependency_id: str | None = None
    actor: str = "demo.operator"
    note: str = ""


@router.post("/actions")
def act(req: ActionRequest, svc: EstateService = Depends(get_service)):
    """Human-approved actions, translated into each scheduler's native command.
    In the prototype the simulators accept them and return a receipt."""
    if req.action in SUPPORTED_ACTIONS and req.job_id:
        if req.job_id not in svc.a.estate.jobs():
            raise HTTPException(404, "Unknown job")
        return svc.execute_action(req.job_id, req.action, req.actor, req.note)
    if req.action == "notify" and req.process_id:
        return svc.notify(req.process_id, req.actor)
    if req.action in ("confirm", "reject") and req.dependency_id:
        if req.dependency_id not in svc.a.estate.dependencies():
            raise HTTPException(404, "Unknown dependency")
        return svc.review_dependency(req.dependency_id, req.action, req.actor)
    raise HTTPException(400, "Unsupported action or missing target")


@router.get("/actions")
def audit(svc: EstateService = Depends(get_service)):
    return svc.audit()


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=20)


@router.post("/assistant/ask")
def ask(req: AskRequest, assistant: Assistant = Depends(get_assistant)):
    res = assistant.ask(req.question, [t.model_dump() for t in req.history])
    return {"answer": res.answer, "provider": res.provider, "model": res.model,
            "tool_trace": res.tool_trace, "note": res.note}


@router.get("/assistant/info")
def info(assistant: Assistant = Depends(get_assistant)):
    return {"provider": assistant.provider.name, "model": assistant.provider.model}
