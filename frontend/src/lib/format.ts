/** Formatting helpers and the shared visual vocabulary (vendor + status encodings). */

export const hhmm = (iso: string | null | undefined): string => (iso ? iso.slice(11, 16) : "—");
export const pct = (x: number): string => `${Math.round(x * 100)}%`;
export const mins = (m: number | null | undefined): string =>
  m == null ? "—" : m >= 60 ? `${Math.floor(m / 60)}h ${Math.round(m % 60)}m` : `${Math.round(m)}m`;

/** Vendor identity. Colour is always paired with the short code (secondary encoding). */
export const VENDORS: Record<string, { code: string; label: string; color: string }> = {
  "control-m": { code: "CTM", label: "Control-M", color: "var(--v-ctm)" },
  autosys: { code: "ASYS", label: "AutoSys", color: "var(--v-asys)" },
  airflow: { code: "AF", label: "Airflow", color: "var(--v-af)" },
  "azure-data-factory": { code: "ADF", label: "Azure Data Factory", color: "var(--v-adf)" },
};
export const SCHEDULER_VENDOR: Record<string, string> = {
  "ctm-prd": "control-m", "autosys-ae1": "autosys", "airflow-dp": "airflow", "adf-prd": "azure-data-factory",
};
export const vendorOf = (schedulerId: string) => VENDORS[SCHEDULER_VENDOR[schedulerId] ?? schedulerId];

export const STATUS_META: Record<string, { icon: string; label: string; tone: string }> = {
  succeeded: { icon: "✓", label: "Succeeded", tone: "good" },
  running: { icon: "▶", label: "Running", tone: "info" },
  failed: { icon: "✕", label: "Failed", tone: "critical" },
  waiting: { icon: "◷", label: "Waiting", tone: "muted" },
  scheduled: { icon: "○", label: "Scheduled", tone: "muted" },
  cancelled: { icon: "–", label: "Cancelled", tone: "muted" },
  done: { icon: "✓", label: "Done", tone: "good" },
  "on-track": { icon: "✓", label: "On track", tone: "good" },
  "at-risk": { icon: "!", label: "At risk", tone: "warning" },
  "breach-likely": { icon: "▲", label: "Breach likely", tone: "critical" },
  breached: { icon: "✕", label: "Breached", tone: "critical" },
  critical: { icon: "▲", label: "Critical", tone: "critical" },
  high: { icon: "!", label: "High", tone: "serious" },
  medium: { icon: "!", label: "Medium", tone: "warning" },
  low: { icon: "i", label: "Low", tone: "muted" },
  info: { icon: "i", label: "Review", tone: "info" },
};

export const shortJob = (id: string) => id.split("::")[1] ?? id;
