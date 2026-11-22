import type {
  ActionReceipt, AskResponse, Connector, Graph, Insight, JobBrief, JobDetail, Meta, Overview, ProcessBrief,
  ProcessDetail,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

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
  act: (body: { action: string; job_id?: string; process_id?: string; dependency_id?: string; note?: string }) =>
    request<ActionReceipt>("/actions", { method: "POST", body: JSON.stringify(body) }),
  audit: () => request<ActionReceipt[]>("/actions"),
  ask: (question: string, history: { role: "user" | "assistant"; content: string }[]) =>
    request<AskResponse>("/assistant/ask", { method: "POST", body: JSON.stringify({ question, history }) }),
  assistantInfo: () => request<{ provider: string; model: string }>("/assistant/info"),
};
