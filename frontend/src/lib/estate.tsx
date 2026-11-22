import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { ActionReceipt, Meta } from "../api/types";

interface EstateCtx {
  meta: Meta | null;
  version: number;                       // bumps whenever estate state changes
  switchScenario: (id: string) => Promise<void>;
  refresh: () => void;
  jobId: string | null;                  // job drawer
  openJob: (id: string | null) => void;
  receipts: ActionReceipt[];
  pushReceipt: (r: ActionReceipt) => void;
  dismissReceipt: (i: number) => void;
  person: string;                        // who is reviewing links (persona switcher)
  setPerson: (id: string) => void;
}

const Ctx = createContext<EstateCtx | null>(null);

export function EstateProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [version, setVersion] = useState(0);
  const [jobId, openJob] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<ActionReceipt[]>([]);
  const [person, setPersonState] = useState<string>(() => localStorage.getItem("batchiq.person") ?? "agarcia");
  const setPerson = useCallback((id: string) => { localStorage.setItem("batchiq.person", id); setPersonState(id); }, []);

  useEffect(() => { api.meta().then(setMeta).catch(console.error); }, []);

  const switchScenario = useCallback(async (id: string) => {
    setMeta(await api.activateScenario(id));
    openJob(null);
    setVersion((v) => v + 1);
  }, []);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const pushReceipt = useCallback((r: ActionReceipt) => setReceipts((rs) => [r, ...rs].slice(0, 3)), []);
  const dismissReceipt = useCallback((i: number) => setReceipts((rs) => rs.filter((_, k) => k !== i)), []);

  return (
    <Ctx.Provider value={{ meta, version, switchScenario, refresh, jobId, openJob, receipts, pushReceipt, dismissReceipt, person, setPerson }}>
      {children}
    </Ctx.Provider>
  );
}

export function useEstate(): EstateCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useEstate outside provider");
  return c;
}

/** Fetch helper that re-runs when the estate version or deps change. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): { data: T | null; error: string | null } {
  const { version } = useEstate();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetcher().then((d) => live && (setData(d), setError(null))).catch((e) => live && setError(String(e)));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, ...deps]);
  return { data, error };
}
