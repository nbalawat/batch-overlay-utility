import { NavLink, Route, Routes } from "react-router-dom";
import { JobDrawer } from "./components/JobDrawer";
import { useEstate } from "./lib/estate";
import { Ask } from "./pages/Ask";
import { Changes } from "./pages/Changes";
import { EcosystemDetailPage, EcosystemList } from "./pages/Ecosystems";
import { Findings } from "./pages/Findings";
import { Knowledge } from "./pages/Knowledge";
import { Links } from "./pages/Links";
import { OnboardingPage } from "./pages/Onboarding";
import { CommandCenter } from "./pages/CommandCenter";
import { Connectors } from "./pages/Connectors";
import { Insights } from "./pages/Insights";
import { Lineage } from "./pages/Lineage";
import { ProcessDetailPage, ProcessList } from "./pages/Processes";

const NAV: [string, string, string][] = [
  ["/", "Command center", "◎"],
  ["/processes", "Business processes", "▤"],
  ["/ecosystems", "Ecosystems", "▦"],
  ["/lineage", "Cross-scheduler lineage", "⇄"],
  ["/knowledge", "Knowledge graph", "⬡"],
  ["/links", "Link review", "✓"],
  ["/findings", "Findings", "⚑"],
  ["/insights", "AI insights", "✦"],
  ["/changes", "What changed", "↻"],
  ["/ask", "Ask the estate", "?"],
  ["/onboarding", "Onboarding", "⇪"],
  ["/connectors", "Connectors", "⛁"],
];

function TopBar() {
  const { meta, switchScenario } = useEstate();
  if (!meta) return <header className="topbar" />;
  const night = new Date(meta.business_date + "T12:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return (
    <header className="topbar">
      <div className="clock">
        <span className="clock-dot" aria-hidden />
        <span className="muted">Batch night {night} · simulated time</span>
        <b className="mono">{meta.now.slice(11, 16)}</b>
        <span className="muted small">{meta.timezone}</span>
      </div>
      <label className="scenario-pick">
        <span className="muted small">Demo scenario</span>
        <select value={meta.scenario.id} onChange={(e) => switchScenario(e.target.value)}>
          {meta.scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
    </header>
  );
}

function Receipts() {
  const { receipts, dismissReceipt } = useEstate();
  return (
    <div className="toasts">
      {receipts.map((r, i) => (
        <div key={i} className="toast">
          <button className="drawer-close" onClick={() => dismissReceipt(i)} aria-label="Dismiss">✕</button>
          <div className="toast-title">✓ {r.action} sent{r.vendor ? ` to ${r.vendor}` : ""} (simulated)</div>
          <code className="toast-cmd">{r.command}</code>
          {r.message && <div className="small">{r.message}</div>}
          <div className="muted small">Recorded in the audit log as {r.actor}</div>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div><div className="brand-name">Batch Intelligence</div><div className="brand-sub">AI overlay · prototype</div></div>
        </div>
        {NAV.map(([to, label, icon]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `nav ${isActive ? "active" : ""}`}>
            <span className="nav-icon" aria-hidden>{icon}</span>{label}
          </NavLink>
        ))}
        <div className="sidebar-foot muted small">All scheduler integrations are simulated. No client data.</div>
      </nav>
      <main className="main">
        <TopBar />
        <Routes>
          <Route path="/" element={<CommandCenter />} />
          <Route path="/processes" element={<ProcessList />} />
          <Route path="/processes/:id" element={<ProcessDetailPage />} />
          <Route path="/lineage" element={<Lineage />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/connectors" element={<Connectors />} />
          <Route path="/ecosystems" element={<EcosystemList />} />
          <Route path="/ecosystems/:id" element={<EcosystemDetailPage />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/links" element={<Links />} />
          <Route path="/findings" element={<Findings />} />
          <Route path="/changes" element={<Changes />} />
          <Route path="/onboarding" element={<OnboardingPage />} />
        </Routes>
      </main>
      <JobDrawer />
      <Receipts />
    </div>
  );
}
