"""Link recommender and review workflow, on small hand-built estates."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from batchiq.core.artifacts import dataset_artifact, file_artifact, table_artifact
from batchiq.discovery.miner import MinedFact
from batchiq.domain.models import Artifact, ArtifactType, Dependency, DependencyOrigin, Job, Vendor
from batchiq.linking.evidence import LinkContext
from batchiq.linking.recommender import Candidate, LinkRecommender, noisy_or
from batchiq.linking.review import Directory, LinkState, ReviewError, ReviewPolicy, ReviewStore

NOW = datetime(2026, 11, 22, 7, 0)


def job(sid: str, name: str, vendor: Vendor = Vendor.AUTOSYS, *, owner: str | None = None, at: time | None = None,
        produces: list[Artifact] | None = None, consumes: list[Artifact] | None = None, container: str = "C") -> Job:
    return Job(id=f"{sid}::{name}", scheduler_id=sid, vendor=vendor, native_id=name, name=name, container=container,
               owner=owner, scheduled_time=at, produces=produces or [], consumes=consumes or [])


def fact(jid: str, relation: str, otype: str, key: str, line: int = 3) -> MinedFact:
    return MinedFact(jid, relation, otype, key, key.split(":", 1)[1], f"/src/{jid}.sh", line, "test", "snippet")


def windows(start_min: float, dur: float, nights: int = 20, jitter: float = 0.0):
    base = datetime(2026, 10, 1, 22, 0)
    return {(base.date() + timedelta(days=i)).isoformat():
            (base + timedelta(days=i, minutes=start_min + (jitter * (i % 3))),
             base + timedelta(days=i, minutes=start_min + dur + (jitter * (i % 3)))) for i in range(nights)}


def ctx(jobs: list[Job], **kw) -> LinkContext:
    return LinkContext({j.id: j for j in jobs}, kw.get("declared", []), kw.get("mined", {}), kw.get("windows", {}),
                       kw.get("incidents", []))


# ---------------------------------------------------------------------- probability
def test_noisy_or_combines_independent_evidence():
    assert noisy_or([0.5, 0.5]) == 0.75
    assert noisy_or([]) == 0.0
    assert noisy_or([1.0, 0.2]) == 1.0


def test_probability_counts_each_kind_once():
    from batchiq.domain.models import Evidence
    c = Candidate("a", "b", [Evidence(kind="temporal", detail="x", weight=0.5),
                             Evidence(kind="temporal", detail="y", weight=0.7)])
    assert c.probability == 0.7


# ---------------------------------------------------------------------- discovery
def test_exact_file_match_inside_one_scheduler_is_a_fact_across_is_a_candidate():
    f = "/xfer/x_$$(BUSDATE).dat"
    a = job("s1", "A", produces=[file_artifact(f)])
    b = job("s1", "B", consumes=[file_artifact(f)])
    c = job("s2", "C", Vendor.CONTROL_M, consumes=[file_artifact("/xfer/x_%%ODATE.dat")])
    facts, cands = LinkRecommender().run(ctx([a, b, c]))
    assert [d.id for d in facts] == ["s1::A->s1::B"] and facts[0].review_state == "auto"
    cand = next(x for x in cands if x.target == "s2::C")
    assert cand.definitional and cand.probability == 1.0 and cand.kinds == ["file-match"]


def test_dataset_and_table_names_match_across_conventions():
    a = job("af", "publish", Vendor.AIRFLOW, produces=[dataset_artifact("warehouse://risk/fraud_scores")])
    b = job("adf", "merge", Vendor.ADF, consumes=[table_artifact("risk", "fraud_scores")])
    _, cands = LinkRecommender().run(ctx([a, b]))
    assert cands[0].kinds == ["data-name-match"] and not cands[0].definitional


def test_code_queue_and_event_evidence():
    a, b, c = job("s1", "PUT"), job("s2", "GET", Vendor.CONTROL_M), job("s3", "WRITER", Vendor.AIRFLOW)
    ev = job("s4", "LISTENER", Vendor.ADF, consumes=[Artifact(type=ArtifactType.EVENT, raw="c360/",
                                                             canonical="event:c360/", match="prefix")])
    mined = {a.id: [fact(a.id, "publishes", "queue", "queue:pay.out")],
             b.id: [fact(b.id, "reads", "queue", "queue:pay.out"), fact(b.id, "reads", "dataset", "data:x.y")],
             c.id: [fact(c.id, "writes", "dataset", "data:x.y"), fact(c.id, "publishes", "event", "event:c360/scores")]}
    _, cands = LinkRecommender().run(ctx([a, b, c, ev], mined=mined))
    by = {x.id: x for x in cands}
    assert by["s1::PUT->s2::GET"].kinds == ["queue-match"]
    assert by["s3::WRITER->s2::GET"].kinds == ["code-artifact-match"]
    assert by["s3::WRITER->s4::LISTENER"].kinds == ["event-match"]
    assert "/src/s1::PUT.sh:3" in by["s1::PUT->s2::GET"].evidence[0].detail, "evidence cites file and line"


def test_temporal_follow_only_for_jobs_nothing_explains():
    a = job("s1", "UP")
    b = job("s2", "DOWN", Vendor.CONTROL_M)                    # no schedule, no upstream: unexplained
    c = job("s3", "CLOCKED", Vendor.AIRFLOW, at=time(22, 30))  # starts on its own clock
    w = {a.id: windows(0, 30), b.id: windows(33, 10, jitter=1), c.id: windows(33, 10)}
    _, cands = LinkRecommender().run(ctx([a, b, c], windows=w))
    ids = {x.id for x in cands}
    assert "s1::UP->s2::DOWN" in ids and "s1::UP->s3::CLOCKED" not in ids
    t = next(x for x in cands if x.id == "s1::UP->s2::DOWN")
    assert {"temporal", "runtime-order"} <= set(t.kinds)


def test_runtime_order_reports_race_nights():
    f = "/xfer/x_$$(BUSDATE).dat"
    a = job("s1", "A", produces=[file_artifact(f)])
    b = job("s2", "B", Vendor.CONTROL_M, at=time(23, 0), consumes=[file_artifact("/xfer/x_%%ODATE.dat")])
    wa = windows(0, 50)
    wb = windows(60, 10)
    for k in list(wb)[:3]:                                     # three nights B started before A finished
        s, e = wb[k]
        wb[k] = (s - timedelta(minutes=30), e - timedelta(minutes=30))
    _, cands = LinkRecommender().run(ctx([a, b], windows={a.id: wa, b.id: wb}))
    ro = next(e for e in cands[0].evidence if e.kind == "runtime-order")
    assert "On 3 night(s) it started first" in ro.detail and ro.weight == 0.1


def test_name_similarity_is_weak_and_dropped_when_stronger_evidence_exists():
    a = job("s1", "PAY_SETTLE_RECON")
    b = job("s2", "PAY_FEDWIRE_RECON", Vendor.CONTROL_M, at=time(23, 30))
    w = {a.id: windows(0, 20), b.id: windows(90, 10)}
    _, cands = LinkRecommender().run(ctx([a, b], windows=w))
    c = next(x for x in cands if x.target == b.id)
    assert "name-similarity" in c.kinds and c.probability < 0.7
    mined = {a.id: [fact(a.id, "publishes", "queue", "queue:q1")], b.id: [fact(b.id, "reads", "queue", "queue:q1")]}
    _, cands = LinkRecommender().run(ctx([a, b], windows=w, mined=mined))
    c = next(x for x in cands if x.target == b.id)
    assert "name-similarity" not in c.kinds and "queue-match" in c.kinds


def test_already_linked_pairs_are_not_reproposed():
    a, b = job("s1", "A"), job("s2", "B", Vendor.CONTROL_M)
    mined = {a.id: [fact(a.id, "publishes", "queue", "queue:q")], b.id: [fact(b.id, "reads", "queue", "queue:q")]}
    declared = [Dependency(id="x", source=a.id, target=b.id, origin=DependencyOrigin.DECLARED, cross_scheduler=True)]
    _, cands = LinkRecommender().run(ctx([a, b], mined=mined, declared=declared))
    assert cands == []


# ---------------------------------------------------------------------- review workflow
@pytest.fixture
def directory(tmp_path) -> Directory:
    p = tmp_path / "people.yaml"
    p.write_text("""teams:
  - {id: up-team, name: Upstream Team, members: [{id: ua, name: Una Up, title: Lead}]}
  - {id: down-team, name: Downstream Team, members: [{id: db, name: Dee Down, title: Lead}]}
  - {id: other, name: Other Team, members: [{id: ox, name: Oz Other, title: Eng}]}
  - {id: batch-coe, name: Batch CoE, governance: true, members: [{id: coe, name: Cee Oh, title: Lead}]}
""")
    return Directory(p)


def _setup(directory, definitional=False, kinds=("temporal",)):
    from batchiq.domain.models import Evidence
    a = job("s1", "A", owner="up-team@AE1")
    b = job("s2", "B", Vendor.CONTROL_M, owner="down-team")
    c = Candidate(a.id, b.id, [Evidence(kind=k, detail=k, weight=0.95 if definitional else 0.6) for k in kinds],
                  definitional=definitional)
    store = ReviewStore(directory)
    jobs = {a.id: a, b.id: b}
    store.sync([c], jobs, NOW)
    return store, c, jobs


def test_both_owning_teams_must_approve(directory):
    store, c, _ = _setup(directory)
    rec = store.records[c.id]
    assert rec.required == ["up-team", "down-team"] and rec.state == LinkState.PROPOSED
    store.decide(c.id, "ua", "approve", "", NOW)
    assert rec.state == LinkState.IN_REVIEW and store.dependency_state(c.id) == "suggested"
    store.decide(c.id, "db", "approve", "looks right", NOW)
    assert rec.state == LinkState.APPROVED and store.dependency_state(c.id) == "confirmed"
    assert [h["event"] for h in rec.history] == ["proposed", "approve", "approve"]


def test_strong_definitional_links_are_fast_tracked_to_the_consumer(directory):
    store, c, _ = _setup(directory, definitional=True, kinds=("file-match",))
    assert store.records[c.id].required == ["down-team"]
    assert any("only the consuming team" in line for line in ReviewPolicy().describe())


def test_non_owner_cannot_decide_and_governance_cannot_approve(directory):
    store, c, _ = _setup(directory)
    with pytest.raises(ReviewError, match="not on an owning team"):
        store.decide(c.id, "ox", "approve", "", NOW)
    with pytest.raises(ReviewError, match="not approve on a team's behalf"):
        store.decide(c.id, "coe", "approve", "", NOW)
    with pytest.raises(ReviewError, match="Unknown reviewer"):
        store.decide(c.id, "nobody", "approve", "", NOW)


def test_reject_and_needs_info_require_a_reason(directory):
    store, c, _ = _setup(directory)
    for d in ("reject", "needs_info"):
        with pytest.raises(ReviewError, match="comment is required"):
            store.decide(c.id, "db", d, "  ", NOW)


def test_needs_info_then_answer_returns_to_review(directory):
    store, c, _ = _setup(directory)
    store.decide(c.id, "db", "needs_info", "Which file exactly?", NOW)
    assert store.records[c.id].state == LinkState.NEEDS_INFO
    store.decide(c.id, "ua", "approve", "", NOW)          # an approval alone does not clear the question
    assert store.records[c.id].state == LinkState.NEEDS_INFO
    store.decide(c.id, "ua", "comment", "The settlement file, see line 12", NOW)
    assert store.records[c.id].state == LinkState.IN_REVIEW
    store.decide(c.id, "db", "approve", "", NOW)
    assert store.records[c.id].state == LinkState.APPROVED


def test_rejection_sticks_until_new_kinds_of_evidence_appear(directory):
    from batchiq.domain.models import Evidence
    store, c, jobs = _setup(directory)
    store.decide(c.id, "db", "reject", "Unrelated jobs", NOW)
    assert store.dependency_state(c.id) == "rejected"
    store.sync([c], jobs, NOW)                              # same evidence next sync: still rejected
    assert store.records[c.id].state == LinkState.REJECTED
    c.evidence.append(Evidence(kind="queue-match", detail="MQ", weight=0.85))
    store.sync([c], jobs, NOW)
    rec = store.records[c.id]
    assert rec.state == LinkState.PROPOSED and rec.history[-1]["event"] == "re-proposed"
    assert "queue-match" in rec.history[-1]["detail"]


def test_only_governance_can_reopen(directory):
    store, c, _ = _setup(directory)
    store.decide(c.id, "db", "reject", "No", NOW)
    with pytest.raises(ReviewError, match="Only the Batch CoE"):
        store.decide(c.id, "db", "reopen", "", NOW)
    store.decide(c.id, "coe", "reopen", "Reviewing again after the incident", NOW)
    assert store.records[c.id].state == LinkState.PROPOSED and store.records[c.id].approvals == {}
