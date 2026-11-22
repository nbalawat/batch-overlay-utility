import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AskResponse } from "../api/types";
import { Card, MiniMarkdown } from "../components/ui";
import { useApi } from "../lib/estate";

const SUGGESTIONS = [
  "What needs my attention right now?",
  "Why is regulatory reporting at risk?",
  "What is the impact of CBK_GL_EXTRACT?",
  "Has a GL extract S0C7 happened before? How was it fixed?",
  "Which processes might miss their SLA tonight?",
  "Are there hidden dependencies between schedulers?",
];

type Msg = { role: "user" | "assistant"; content: string; meta?: AskResponse };

export function Ask() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: info } = useApi(api.assistantInfo);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  async function send(q: string) {
    if (!q.trim() || busy) return;
    const history = msgs.map(({ role, content }) => ({ role, content })).slice(-10);
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setBusy(true);
    try {
      const r = await api.ask(q, history);
      setMsgs((m) => [...m, { role: "assistant", content: r.answer, meta: r }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", content: `Something went wrong: ${e}` }]);
    } finally { setBusy(false); }
  }

  return (
    <div className="page ask">
      <h1>Ask the estate</h1>
      <p className="muted">Natural-language questions over the unified, correlated estate. The assistant answers with
        tools that read the same facts as the rest of the console, so it cites real jobs, times and probabilities.
        {info && <> Provider: <b>{info.provider}</b> ({info.model}).</>}</p>
      <Card className="chat">
        <div className="chat-log">
          {msgs.length === 0 && (
            <div className="suggestions">
              {SUGGESTIONS.map((s) => <button key={s} className="suggestion" onClick={() => send(s)}>{s}</button>)}
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg msg-${m.role}`}>
              {m.role === "assistant" ? <MiniMarkdown text={m.content} /> : m.content}
              {m.meta && (
                <div className="msg-meta">
                  {m.meta.tool_trace.map((t, k) => <span key={k} className="chip mono">⚙ {t.tool}</span>)}
                  <span className="muted small">{m.meta.provider} · {m.meta.model}</span>
                  {m.meta.note && <div className="muted small">{m.meta.note}</div>}
                </div>
              )}
            </div>
          ))}
          {busy && <div className="msg msg-assistant muted">Thinking…</div>}
          <div ref={end} />
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="e.g. What happens to payments if PAY_SETTLE_NET fails?" />
          <button className="btn btn-primary" disabled={busy}>Ask</button>
        </form>
      </Card>
    </div>
  );
}
