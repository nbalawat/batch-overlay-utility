export type RunStatus = "succeeded" | "failed" | "running" | "waiting" | "scheduled" | "cancelled";
export type ProcessStatus = "done" | "on-track" | "at-risk" | "breach-likely" | "breached";

export interface Scenario { id: string; name: string }
export interface Meta {
  scenario: { id: string; name: string; summary: string; talking_points: string[] };
  now: string;
  business_date: string;
  timezone: string;
  scenarios: Scenario[];
  adapters_registered: string[];
}

export interface JobBrief {
  id: string; name: string; container: string; scheduler_id: string; vendor: string; kind: string;
  status: RunStatus; start: string | null; end: string | null; elapsed_min: number | null;
  failed_attempts: number; projected_end: string | null; projected_end_p90: string | null;
  p50_min: number; processes: string[]; anomalous: boolean; critical?: boolean;
}

export interface Evidence { kind: string; detail: string; weight: number }
export interface Dependency {
  id: string; source: string; target: string; origin: "declared" | "artifact" | "inferred";
  cross_scheduler: boolean; confidence: number; artifact: string | null; evidence: Evidence[];
  review_state: "auto" | "suggested" | "confirmed" | "rejected"; active?: boolean; critical?: boolean;
}

export interface Connector {
  id: string; vendor: string; name: string; environment: string; endpoint: string; description: string;
  jobs: number; dependencies: number; runs: number; last_sync: string; status: string; mode: string;
  tonight: Record<RunStatus, number>; failed_tonight: number; anomalies: number; cross_links: number;
}

export interface ServiceRef { id: string; name: string; owner: string; tier: number }
export interface ProcessBrief {
  id: string; name: string; description: string; owner: string; criticality: string; regulatory: boolean;
  sla: string; sla_description: string; deadline: string; status: ProcessStatus; breach_probability: number;
  projected_p50: string; projected_p90: string; usual_end: string | null; slack_min: number;
  services: ServiceRef[]; job_count: number; jobs_done: number; jobs_by_scheduler: Record<string, number>;
  failed_jobs: string[]; critical_path: string[]; anchor_jobs: string[];
}

export interface Recommendation {
  id: string; title: string; rationale: string; source?: string;
  action?: { action: string; job_id?: string; process_id?: string; link_id?: string };
}
export interface Hypothesis { job_id: string; kind: string; confidence: number; reason: string; depth: number; origin?: boolean }
export interface SimilarIncident {
  id: string; date: string; title: string; score: number; root_cause: string; resolution: string; mttr_minutes: number;
}
export interface Impact {
  downstream_jobs?: number; downstream_by_scheduler?: Record<string, number>; cross_scheduler_hops?: number;
  processes: { id: string; name: string; criticality: string; status: ProcessStatus; breach_probability: number;
    sla: string; projected_p50: string; regulatory: boolean }[];
  services: string[];
}
export interface Insight {
  id: string; type: "failure" | "sla_risk" | "anomaly" | "correlation" | "stale_data";
  severity: "critical" | "high" | "medium" | "low" | "info";
  title: string; summary: string; detected_at: string; job_ids: string[]; process_ids: string[];
  scheduler_ids: string[]; evidence: string[]; impact: Impact; root_cause: Hypothesis[];
  similar_incidents: SimilarIncident[]; recommendations: Recommendation[];
}

export interface Overview {
  meta: Meta;
  kpis: Record<string, number>;
  connectors: Connector[];
  processes: ProcessBrief[];
  insights: Insight[];
}

export interface Graph { nodes: JobBrief[]; edges: Dependency[]; schedulers: { id: string; vendor: string; name: string }[] }

export interface JobRun {
  id: string; job_id: string; business_date: string; attempt: number; status: RunStatus;
  start: string | null; end: string | null; duration_s: number | null; error_code: string | null; message: string | null;
}
export interface JobDetail extends JobBrief {
  definition: Record<string, unknown> & { owner?: string; host?: string; command?: string; schedule?: string;
    application?: string; produces: { raw: string; canonical: string }[]; consumes: { raw: string; canonical: string }[] };
  baseline: { p50: number; p90: number; p95: number; failure_rate: number; nights: number };
  runs: JobRun[];
  upstream: { dependency: Dependency; job: JobBrief }[];
  downstream: { dependency: Dependency; job: JobBrief }[];
  impact: Impact; root_cause: Hypothesis[];
  anomaly: { observed_min: number; p50_min: number; ratio: number } | null;
  insights: string[];
}

export interface TimelineRow extends JobBrief { usual_end_offset_min: number | null; failed_runs: JobRun[] }
export interface ProcessDetail extends ProcessBrief {
  timeline: TimelineRow[]; graph: Graph; insights: Insight[];
  history: { business_date: string; end: string; slack_min: number }[];
}

export interface ActionReceipt {
  at: string; actor: string; action: string; command: string; receipt: Record<string, unknown>;
  api_call?: Record<string, unknown>; message?: string; vendor?: string;
}

export interface AskResponse {
  answer: string; provider: string; model: string; note: string | null;
  tool_trace: { tool: string; input: Record<string, unknown> }[];
}

// ---------------------------------------------------------------------- v2: ecosystems, knowledge graph, links
export type Severity = "high" | "medium" | "low" | "info";
export interface Finding {
  id: string; kind: "static" | "runtime"; category: string; severity: Severity; title: string; detail: string;
  recommendation: string; scope: string; job_ids: string[]; process_ids: string[]; evidence: string[];
  metrics: Record<string, unknown>; link_id: string | null;
}
export interface FindingsResponse {
  findings: Finding[];
  summary: { total: number; shown: number; by_kind: Record<string, number>; by_severity: Record<Severity, number>;
    by_scope: Record<string, number>; categories: { kind: string; category: string; title: string; count: number }[] };
}

export interface PipelineStats {
  definitions: number; declared_dependencies: number; runs: number; source_files: number; source_repo: string;
  mined_facts: number; ingest_ms: number; mine_ms: number;
}
export interface EcosystemBrief {
  id: string; name: string; vendor: string; vendor_label: string; environment: string; description: string;
  container_kind: string; containers: number; jobs: number; hosts: number; teams: number; intra_links: number;
  cross_links: number; cross_pending: number; processes: number; findings: Record<Severity, number>;
  pipeline: PipelineStats;
}
export interface EcoJob extends JobBrief {
  team: string | null; host: string | null; schedule: string | null; alerting: boolean | null;
  unresolved_conditions: string[]; mined_facts: number;
}
export interface EcosystemDetail {
  id: string; name: string; vendor: string; vendor_label: string; environment: string; description: string;
  container_kind: string; containers: { name: string; jobs: EcoJob[] }[];
  graph: Graph & { nodes: (JobBrief & { external: boolean })[] };
  stats: Record<string, number>; hosts: { host: string; jobs: number }[];
  outputs: { id: string; label: string; type: string; writers: number }[];
  inputs: { id: string; label: string; type: string; readers: number }[];
  findings: Finding[]; pipeline: PipelineStats; suggested_questions: string[];
}

export interface KgNode { id: string; type: string; label: string; props: Record<string, unknown> }
export interface KgEdge {
  id: string; source: string; target: string; type: string; provenance: string[]; confidence: number;
  refs: string[]; props: Record<string, unknown>;
}
export interface Ontology {
  nodes: { type: string; description: string; examples: string; count: number }[];
  edges: { type: string; source: string[]; target: string[]; description: string; count: number }[];
  provenance: { id: string; description: string; count: number }[];
  stats: { nodes: number; edges: number };
}
export interface KgNodeDetail {
  node: KgNode;
  relations: { direction: "in" | "out"; type: string; edges: (KgEdge & { other: KgNode })[] }[];
}
export interface KgSubgraph { center: string; nodes: KgNode[]; edges: KgEdge[]; truncated: boolean }
export interface KgPaths { from: KgNode; to: KgNode; directed: boolean; paths: { hops: KgNode[]; edges: KgEdge[] }[] }

export type LinkState = "proposed" | "in_review" | "needs_info" | "approved" | "rejected";
export interface Person { id: string; name: string; title: string; team: string; governance: boolean; team_name?: string; waiting?: number }
export interface LinkJob {
  id: string; name: string; container: string; scheduler_id: string; vendor: string; vendor_label: string;
  team: string | null; team_name: string | null; scheduled_time: string | null; processes: string[];
}
export interface ReviewEvent { at: string; actor: string; actor_name?: string; team?: string; event: string; detail: string }
export interface LinkCard {
  id: string; source: LinkJob; target: LinkJob; probability: number; state: LinkState; dependency_state: string;
  cross_scheduler: boolean; artifact: string | null; definitional: boolean; fast_track: boolean; kinds: string[];
  evidence: (Evidence & { source: string })[];
  required: { team: string; name: string; approved: boolean; approval: { name: string; at: string; comment: string } | null;
    members: Person[] }[];
  proposed_at: string | null; last_event: ReviewEvent | null; findings: string[];
  history?: ReviewEvent[];
  impact?: { process_id: string; name: string; jobs_gained: number; jobs: string[] }[];
  race_nights?: { races: number; nights: number; dates: string[] };
}
export interface LinkQueue { links: LinkCard[]; counts: Record<LinkState, number>; policy: string[]; person: Person | null }

export interface ChangeEntry {
  sync: string; business_date: string; nodes_before: number; nodes_after: number; edges_before: number; edges_after: number;
  changes: { job_id: string; name: string; scheduler_id: string; kind: string; details: string[];
    change: { id: string; ticket: string; author: string; summary: string } | null;
    follow_ups: { link_id: string; probability: number; state: LinkState | null }[] }[];
}

export interface Onboarding {
  connectors: (PipelineStats & { scheduler_id: string; name: string; vendor: string })[];
  stages: { id: string; title: string; detail: string }[];
  totals: { definitions: number; source_files: number; mined_facts: number; runs: number };
}
export interface Sample { id: string; vendor: string; vendor_label: string; file: string; scheduler_id: string; name: string; format: string; content: string }
export interface ImportResult {
  scheduler: { id: string; name: string; vendor: string; vendor_label: string };
  jobs: { id: string; name: string; container: string; host: string | null; team: string | null; schedule: string | null;
    produces: string[]; consumes: string[]; alerting: boolean | null; unresolved_conditions: string[] }[];
  dependencies: { source: string; target: string; artifact: string | null }[];
  graph: { nodes: number; edges: number; nodes_by_type: Record<string, number> };
  checks: { severity: Severity; job: string; message: string }[];
  external_inputs: string[];
  proposed_links: { source: { id: string; name: string; scheduler_id: string }; target: { id: string; name: string; scheduler_id: string };
    artifact: string; probability: number; evidence: Evidence; direction: string }[];
  next_steps: string[];
}
