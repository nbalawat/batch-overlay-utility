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
  action?: { action: string; job_id?: string; process_id?: string; dependency_id?: string };
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
  id: string; type: "failure" | "sla_risk" | "anomaly" | "correlation";
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
