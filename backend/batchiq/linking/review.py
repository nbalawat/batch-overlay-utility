"""Review workflow for recommended links: nobody's lineage changes without its owners agreeing.

A candidate link needs sign-off from the teams that own each end of it (the
owner fields the schedulers already carry). Strong, definition-level matches
can be fast-tracked to the consuming team alone. Any owner can reject a link or
ask for more information, and every step is kept as history. Rejections are
remembered: the recommender does not propose the same link again unless new
kinds of evidence turn up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from batchiq.domain.models import Job
from batchiq.linking.recommender import Candidate


class LinkState(StrEnum):
    PROPOSED = "proposed"          # no review yet
    IN_REVIEW = "in_review"        # some, not all, required approvals
    NEEDS_INFO = "needs_info"      # a reviewer asked a question
    APPROVED = "approved"
    REJECTED = "rejected"


DEP_STATE = {LinkState.APPROVED: "confirmed", LinkState.REJECTED: "rejected"}   # anything else: "suggested"


@dataclass
class Person:
    id: str
    name: str
    title: str
    team: str
    governance: bool = False


class Directory:
    def __init__(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text())
        self.teams: dict[str, dict[str, Any]] = {}
        self.people: dict[str, Person] = {}
        for t in data["teams"]:
            self.teams[t["id"]] = {"id": t["id"], "name": t["name"], "governance": bool(t.get("governance"))}
            for m in t["members"]:
                self.people[m["id"]] = Person(m["id"], m["name"], m["title"], t["id"], bool(t.get("governance")))

    def team_name(self, team: str) -> str:
        return self.teams.get(team, {}).get("name", team)

    def members(self, team: str) -> list[Person]:
        return [p for p in self.people.values() if p.team == team]


@dataclass
class ReviewPolicy:
    fast_track_min_probability: float = 0.9   # definition-level matches this strong need only the consumer's owner

    def required_teams(self, c: Candidate, jobs: dict[str, Job]) -> list[str]:
        src, tgt = jobs[c.source].team or "unowned", jobs[c.target].team or "unowned"
        if c.definitional and c.probability >= self.fast_track_min_probability:
            return [tgt]
        return list(dict.fromkeys([src, tgt]))

    def describe(self) -> list[str]:
        return ["Each link needs approval from the owning team at both ends.",
                f"Links where both scheduler definitions name the same file or dataset "
                f"(probability ≥ {self.fast_track_min_probability:.0%}) need only the consuming team.",
                "Any owner can reject a link or ask for more information.",
                "A rejected link is not proposed again unless new kinds of evidence appear.",
                "The Batch CoE can reopen any decision."]


@dataclass
class LinkRecord:
    link_id: str
    state: LinkState = LinkState.PROPOSED
    required: list[str] = field(default_factory=list)
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)   # team -> {person, at, comment}
    history: list[dict[str, Any]] = field(default_factory=list)
    evidence_kinds: list[str] = field(default_factory=list)
    proposed_at: datetime | None = None


class ReviewError(ValueError):
    pass


class ReviewStore:
    """In-memory; at a client this is a table, and every decision also lands in the audit log."""

    def __init__(self, directory: Directory, policy: ReviewPolicy | None = None) -> None:
        self.directory = directory
        self.policy = policy or ReviewPolicy()
        self.records: dict[str, LinkRecord] = {}

    # ------------------------------------------------------------------ sync with the recommender
    def sync(self, candidates: list[Candidate], jobs: dict[str, Job], now: datetime) -> None:
        for c in candidates:
            rec = self.records.get(c.id)
            if rec is None:
                rec = self.records[c.id] = LinkRecord(c.id, proposed_at=now)
                rec.history.append({"at": now, "actor": "link-recommender", "event": "proposed",
                                    "detail": f"{c.probability:.0%} from {', '.join(c.kinds)}"})
            elif rec.state == LinkState.REJECTED and set(c.kinds) - set(rec.evidence_kinds):
                new = sorted(set(c.kinds) - set(rec.evidence_kinds))
                rec.state, rec.approvals = LinkState.PROPOSED, {}
                rec.history.append({"at": now, "actor": "link-recommender", "event": "re-proposed",
                                    "detail": "new evidence: " + ", ".join(new)})
            rec.required = self.policy.required_teams(c, jobs)
            rec.evidence_kinds = c.kinds
            self._recompute(rec)

    # ------------------------------------------------------------------ decisions
    def decide(self, link_id: str, person_id: str, decision: str, comment: str, now: datetime) -> LinkRecord:
        rec = self.records.get(link_id)
        if rec is None:
            raise ReviewError(f"Unknown link {link_id}")
        p = self.directory.people.get(person_id)
        if p is None:
            raise ReviewError(f"Unknown reviewer {person_id}")
        owner = p.team in rec.required
        if decision in ("approve", "reject", "needs_info") and not (owner or p.governance):
            raise ReviewError(f"{p.name} is not on an owning team for this link "
                              f"(needs: {', '.join(self.directory.team_name(t) for t in rec.required)})")
        if decision in ("reject", "needs_info") and not comment.strip():
            raise ReviewError("Say why: a comment is required to reject or to ask for information")
        entry = {"at": now, "actor": p.id, "actor_name": p.name, "team": p.team, "event": decision,
                 "detail": comment}
        if decision == "approve":
            if not owner:
                raise ReviewError("Governance can reopen decisions but not approve on a team's behalf")
            rec.approvals[p.team] = {"person": p.id, "name": p.name, "at": now, "comment": comment}
        elif decision == "reject":
            rec.state = LinkState.REJECTED
        elif decision == "needs_info":
            rec.state = LinkState.NEEDS_INFO
        elif decision == "reopen":
            if not p.governance:
                raise ReviewError("Only the Batch CoE can reopen a decision")
            rec.approvals, rec.state = {}, LinkState.PROPOSED
        elif decision != "comment":
            raise ReviewError(f"Unknown decision '{decision}'")
        rec.history.append(entry)
        if decision in ("approve", "comment", "reopen"):
            self._recompute(rec, answered=decision == "comment")
        return rec

    def _recompute(self, rec: LinkRecord, answered: bool = False) -> None:
        if rec.state == LinkState.REJECTED:
            return
        if rec.state == LinkState.NEEDS_INFO and not answered:
            return
        if all(t in rec.approvals for t in rec.required):
            rec.state = LinkState.APPROVED
        elif rec.approvals or (rec.state == LinkState.NEEDS_INFO and answered):
            rec.state = LinkState.IN_REVIEW
        else:
            rec.state = LinkState.PROPOSED

    # ------------------------------------------------------------------ seeding history
    def seed(self, link_id: str, events: list[tuple[int, str, str, str]], now: datetime) -> None:
        """events: (days_ago, person_id, decision, comment). Applied in order, back-dated."""
        rec = self.records.get(link_id)
        if rec is None:
            return
        first = now - timedelta(days=max(e[0] for e in events) + 1)
        rec.proposed_at = first
        rec.history[0]["at"] = first
        for days, who, decision, comment in events:
            self.decide(link_id, who, decision, comment, now - timedelta(days=days))

    def dependency_state(self, link_id: str) -> str:
        rec = self.records.get(link_id)
        return DEP_STATE.get(rec.state, "suggested") if rec else "suggested"
