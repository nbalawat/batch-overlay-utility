"""The batch estate ontology: what things exist, and how they may relate.

One vocabulary across Control-M, AutoSys, Airflow and ADF. A Control-M folder,
an AutoSys box, an Airflow DAG and an ADF pipeline are all a `Container`; a job,
a task and an activity are all a `Job`. Every edge records where we learned it
(`Provenance`) and how sure we are, so a reader can always tell a scheduler fact
from a mined fact from an inference that people approved.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NodeType(StrEnum):
    SCHEDULER = "Scheduler"
    CONTAINER = "Container"
    JOB = "Job"
    SCHEDULE = "Schedule"
    HOST = "Host"
    APPLICATION = "Application"
    TEAM = "Team"
    FILE = "File"
    DATASET = "Dataset"
    QUEUE = "Queue"
    EVENT = "Event"
    ENDPOINT = "Endpoint"
    COMMUNICATION = "Communication"
    BUSINESS_PROCESS = "BusinessProcess"
    SERVICE = "Service"
    INCIDENT = "Incident"


class EdgeType(StrEnum):
    CONTAINS = "CONTAINS"
    FEEDS = "FEEDS"                  # job -> job: the target needs the source to have run
    SCHEDULED_BY = "SCHEDULED_BY"
    RUNS_ON = "RUNS_ON"
    BELONGS_TO = "BELONGS_TO"
    OWNED_BY = "OWNED_BY"
    READS = "READS"
    WRITES = "WRITES"
    PUBLISHES = "PUBLISHES"
    TRIGGERED_BY = "TRIGGERED_BY"    # container -> event / file prefix that starts it
    TRANSFERS_TO = "TRANSFERS_TO"
    FETCHES_FROM = "FETCHES_FROM"
    CALLS = "CALLS"
    NOTIFIES = "NOTIFIES"
    DELIVERS = "DELIVERS"            # anchor job -> business process (the process is done when it ends)
    PART_OF = "PART_OF"              # job -> business process (derived supply chain)
    SUPPORTS = "SUPPORTS"            # business process -> service
    AFFECTED = "AFFECTED"            # incident -> job


class Provenance(StrEnum):
    DEFINITION = "definition"        # the scheduler's own export
    CODE = "code"                    # mined from the job's source code
    RUNTIME = "runtime"              # observed in run records
    CATALOG = "catalog"              # business catalogue / CMDB / directory
    APPROVED = "approved"            # recommended link, approved by its owners
    PROPOSED = "proposed"            # recommended link, still in review
    DERIVED = "derived"              # computed from other edges (e.g. process membership)
    INCIDENT = "incident"            # knowledge base


@dataclass(frozen=True)
class NodeSpec:
    type: NodeType
    description: str
    examples: str


@dataclass(frozen=True)
class EdgeSpec:
    type: EdgeType
    source: tuple[NodeType, ...]
    target: tuple[NodeType, ...]
    description: str


N = NodeType
NODES: tuple[NodeSpec, ...] = (
    NodeSpec(N.SCHEDULER, "One scheduler instance (an ecosystem)", "Control-M CTMPRD, AutoSys AE1, Airflow, ADF"),
    NodeSpec(N.CONTAINER, "The grouping a scheduler uses", "Control-M folder, AutoSys box, Airflow DAG, ADF pipeline"),
    NodeSpec(N.JOB, "The unit a scheduler runs", "Control-M job, AutoSys CMD job, Airflow task, ADF activity"),
    NodeSpec(N.SCHEDULE, "What starts a job", "Daily 23:30, on condition, on blob created, on dataset update"),
    NodeSpec(N.HOST, "Where it runs", "z/OS LPAR, Linux agent, Snowflake warehouse, Spark or Databricks cluster"),
    NodeSpec(N.APPLICATION, "Application code or tag", "CORE, PAYMENTS, finance, risk"),
    NodeSpec(N.TEAM, "Owning team, from the scheduler's owner fields", "core-batch-ops, fraud-analytics"),
    NodeSpec(N.FILE, "A file, matched across dialects by its canonical name", "gl_extract_{date}.dat"),
    NodeSpec(N.DATASET, "A table or dataset", "finance.gl_mart, risk.fraud_scores"),
    NodeSpec(N.QUEUE, "A message queue", "PAY.SETTLE.OUT"),
    NodeSpec(N.EVENT, "An event that triggers work", "customer360_refresh"),
    NodeSpec(N.ENDPOINT, "A host or API outside the scheduler, internal or external", "fedline.frb.example"),
    NodeSpec(N.COMMUNICATION, "Who gets told", "cfo-office@bank.example"),
    NodeSpec(N.BUSINESS_PROCESS, "An outcome the business cares about, with an SLA", "Regulatory liquidity reporting"),
    NodeSpec(N.SERVICE, "A business service a process supports", "Payments Hub"),
    NodeSpec(N.INCIDENT, "A past incident in the knowledge base", "INC-20260914-0412"),
)

E = EdgeType
EDGES: tuple[EdgeSpec, ...] = (
    EdgeSpec(E.CONTAINS, (N.SCHEDULER, N.CONTAINER), (N.CONTAINER, N.JOB), "Hierarchy inside one ecosystem"),
    EdgeSpec(E.FEEDS, (N.JOB,), (N.JOB,), "Downstream needs upstream: declared, artifact match, or approved link"),
    EdgeSpec(E.SCHEDULED_BY, (N.JOB,), (N.SCHEDULE,), "What starts the job"),
    EdgeSpec(E.RUNS_ON, (N.JOB,), (N.HOST,), "Declared machine or pool, and hosts observed at runtime"),
    EdgeSpec(E.BELONGS_TO, (N.JOB,), (N.APPLICATION,), "Application or tag"),
    EdgeSpec(E.OWNED_BY, (N.JOB, N.BUSINESS_PROCESS), (N.TEAM,), "Who to call, and who reviews links"),
    EdgeSpec(E.READS, (N.JOB,), (N.FILE, N.DATASET, N.QUEUE), "Inputs from definitions and code"),
    EdgeSpec(E.WRITES, (N.JOB,), (N.FILE, N.DATASET), "Outputs from definitions and code"),
    EdgeSpec(E.PUBLISHES, (N.JOB,), (N.QUEUE, N.EVENT), "Messages and events sent"),
    EdgeSpec(E.TRIGGERED_BY, (N.CONTAINER, N.JOB), (N.EVENT, N.FILE), "Event and blob triggers"),
    EdgeSpec(E.TRANSFERS_TO, (N.JOB,), (N.ENDPOINT,), "Files pushed out (SFTP, MFT, copy sinks)"),
    EdgeSpec(E.FETCHES_FROM, (N.JOB,), (N.ENDPOINT,), "Files pulled in"),
    EdgeSpec(E.CALLS, (N.JOB,), (N.ENDPOINT,), "HTTP APIs called"),
    EdgeSpec(E.NOTIFIES, (N.JOB,), (N.COMMUNICATION,), "E-mails and messages sent"),
    EdgeSpec(E.DELIVERS, (N.JOB,), (N.BUSINESS_PROCESS,), "The process is complete when this job ends"),
    EdgeSpec(E.PART_OF, (N.JOB,), (N.BUSINESS_PROCESS,), "Everything upstream of an anchor, across ecosystems"),
    EdgeSpec(E.SUPPORTS, (N.BUSINESS_PROCESS,), (N.SERVICE,), "Business services the process supports"),
    EdgeSpec(E.AFFECTED, (N.INCIDENT,), (N.JOB,), "Jobs named in an incident"),
)

EDGE_SPECS = {e.type: e for e in EDGES}

PROVENANCE_HELP = {
    Provenance.DEFINITION: "From the scheduler's own definitions export",
    Provenance.CODE: "Mined from the job's source code (file and line kept)",
    Provenance.RUNTIME: "Observed in run records",
    Provenance.CATALOG: "From the business catalogue or the people directory",
    Provenance.APPROVED: "Recommended by the overlay and approved by the owning teams",
    Provenance.PROPOSED: "Recommended by the overlay, awaiting review",
    Provenance.DERIVED: "Computed from other edges",
    Provenance.INCIDENT: "From the incident knowledge base",
}


def allowed(edge: EdgeType, source: NodeType, target: NodeType) -> bool:
    spec = EDGE_SPECS[edge]
    return source in spec.source and target in spec.target
