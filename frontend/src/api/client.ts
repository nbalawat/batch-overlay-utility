import type {
  ActionReceipt, AskResponse, ChangeEntry, Connector, EcosystemBrief, EcosystemDetail, FindingsResponse, Graph,
  ImportResult, Insight, JobBrief, JobDetail, KgNode, KgNodeDetail, KgPaths, KgSubgraph, LinkCard, LinkQueue, Meta,
  Onboarding, Ontology, Overview, Person, ProcessBrief, ProcessDetail, Sample,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(`${status}: ${detail}`); }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try { detail = JSON.parse(body).detail ?? body; } catch { /* not JSON */ }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;
const qs = (params: Record<string, string | number | boolean | undefined | null>) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => [k, String(v)])).toString();

export const api = {
  meta: () => request<Meta>("/meta"),
  activateScenario: (id: string) => request<Meta>(`/scenarios/${enc(id)}/activate`, { method: "POST" }),
  overview: () => request<Overview>("/overview"),
  connectors: () => request<Connector[]>("/connectors"),
  native: (id: string) => request<{ vendor: string; definitions: unknown; runs: unknown }>(`/connectors/${enc(id)}/native`),
  jobs: (params: { scheduler?: string; q?: string; process?: string } = {}) =>
    request<JobBrief[]>(`/jobs?${new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][])}`),
  job: (id: string) => request<JobDetail>(`/jobs/${id}`),
  graph: (process?: string, crossOnly = false) =>
    request<Graph>(`/graph?${new URLSearchParams({ ...(process ? { process } : {}), cross_only: String(crossOnly) })}`),
  processes: () => request<ProcessBrief[]>("/processes"),
  process: (id: string) => request<ProcessDetail>(`/processes/${enc(id)}`),
  insights: (type?: string) => request<Insight[]>(`/insights${type ? `?type=${enc(type)}` : ""}`),
  act: (body: { action: string; job_id?: string; process_id?: string; note?: string }) =>
    request<ActionReceipt>("/actions", { method: "POST", body: JSON.stringify(body) }),
  audit: () => request<ActionReceipt[]>("/actions"),
  ask: (question: string, history: { role: "user" | "assistant"; content: string }[]) =>
    request<AskResponse>("/assistant/ask", { method: "POST", body: JSON.stringify({ question, history }) }),
  assistantInfo: () => request<{ provider: string; model: string }>("/assistant/info"),

  ecosystems: () => request<EcosystemBrief[]>("/ecosystems"),
  ecosystem: (id: string) => request<EcosystemDetail>(`/ecosystems/${enc(id)}`),
  ontology: () => request<Ontology>("/kg/ontology"),
  kgSearch: (q: string, type?: string) => request<(KgNode & { degree: number })[]>(`/kg/search?${qs({ q, type })}`),
  kgNode: (id: string) => request<KgNodeDetail>(`/kg/node?${qs({ id })}`),
  kgNeighbourhood: (id: string, depth = 1, types?: string) =>
    request<KgSubgraph>(`/kg/neighbourhood?${qs({ id, depth, types })}`),
  kgPaths: (from: string, to: string, directed = true, types?: string) =>
    request<KgPaths>(`/kg/paths?${qs({ from, to, directed, types })}`),
  people: () => request<Person[]>("/people"),
  links: (params: { state?: string; person?: string; scope?: string } = {}) => request<LinkQueue>(`/links?${qs(params)}`),
  link: (id: string) => request<LinkCard>(`/links/${enc(id)}`),
  review: (id: string, body: { person: string; decision: string; comment: string }) =>
    request<LinkCard>(`/links/${enc(id)}/review`, { method: "POST", body: JSON.stringify(body) }),
  findings: (params: { kind?: string; scope?: string; category?: string; severity?: string; job?: string } = {}) =>
    request<FindingsResponse>(`/findings?${qs(params)}`),
  changelog: () => request<ChangeEntry[]>("/changelog"),
  onboarding: () => request<Onboarding>("/onboarding"),
  samples: () => request<Sample[]>("/onboarding/samples"),
  importSandbox: (body: { vendor: string; content: string; scheduler_id: string; name: string }) =>
    request<ImportResult>("/onboarding/import", { method: "POST", body: JSON.stringify(body) }),
};
