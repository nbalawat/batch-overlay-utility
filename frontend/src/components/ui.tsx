import type { ReactNode } from "react";
import { STATUS_META, VENDORS, vendorOf } from "../lib/format";

export function StatusPill({ status, compact = false }: { status: string; compact?: boolean }) {
  const m = STATUS_META[status] ?? { icon: "•", label: status, tone: "muted" };
  return (
    <span className={`pill tone-${m.tone}`} title={m.label}>
      <span aria-hidden>{m.icon}</span>{!compact && <span>{m.label}</span>}
    </span>
  );
}

export function VendorTag({ vendor, schedulerId, full = false }: { vendor?: string; schedulerId?: string; full?: boolean }) {
  const v = vendor ? VENDORS[vendor] : schedulerId ? vendorOf(schedulerId) : undefined;
  if (!v) return null;
  return (
    <span className="vendor-tag" style={{ ["--vc" as string]: v.color }}>
      <span className="vendor-dot" aria-hidden />{full ? v.label : v.code}
    </span>
  );
}

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head"><h3>{title}</h3><div className="card-actions">{actions}</div></header>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className={`kpi ${tone ? `tone-text-${tone}` : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Loading({ error }: { error?: string | null }) {
  return <div className="loading">{error ? `Could not load: ${error}` : "Loading…"}</div>;
}

export function ProbabilityBar({ p }: { p: number }) {
  const tone = p >= 0.6 ? "critical" : p >= 0.2 ? "warning" : "good";
  return (
    <div className="prob" title={`${Math.round(p * 100)}% probability of missing the SLA`}>
      <div className={`prob-fill bg-${tone}`} style={{ width: `${Math.max(p * 100, 2)}%` }} />
    </div>
  );
}

/** Very small markdown subset for assistant answers: **bold**, lists, paragraphs. */
export function MiniMarkdown({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>);
  const LIST = /^\s*([-*]|\d+\.)\s/;
  const out: ReactNode[] = [];
  blocks.forEach((b, i) => {
    let para: string[] = [];
    let items: string[] = [];
    const flush = () => {
      if (para.length) out.push(<p key={`${i}-p${out.length}`}>{para.map((l, k) =>
        <span key={k}>{inline(l)}{k < para.length - 1 && <br />}</span>)}</p>);
      if (items.length) out.push(<ul key={`${i}-u${out.length}`}>{items.map((l, k) =>
        <li key={k}>{inline(l.replace(LIST, ""))}</li>)}</ul>);
      para = []; items = [];
    };
    for (const l of b.split("\n")) {
      if (LIST.test(l)) { if (para.length) flush(); items.push(l); }
      else { if (items.length) flush(); para.push(l); }
    }
    flush();
  });
  return <div className="md">{out}</div>;
}
