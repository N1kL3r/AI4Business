import { useEffect, useState } from "react";
import { analyze, getStatus, type Input } from "./api";
import { TopBar } from "./Header";
import { InputPanel } from "./InputPanel";
import { Results } from "./Results";
import type { Result, ServerStatus, Settings } from "./types";

export default function App() {
  const [settings, setSettings] = useState<Settings>({ mode: "ai", model: "qwen3.5:9b" });
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<{ warnings: string[]; sources: string[] }>({ warnings: [], sources: [] });

  useEffect(() => {
    const t = setTimeout(() => getStatus(settings).then((s) => { setStatus(s); setError(""); }, (e) => { setStatus(null); setError(e.message); }), 300);
    return () => clearTimeout(t);
  }, [settings]);

  const run = async (input: Input) => {
    setLoading(true); setError(""); setResult(null);
    try {
      const out = await analyze(input, settings);
      setMessages({ warnings: out.warnings ?? [], sources: out.sources ?? [] });
      if ("error" in out) setError(out.error); else setResult(out);
    } catch (e) { setError((e as Error).message); }
    setLoading(false);
  };

  return (
    <div className="flex h-screen flex-col">
      <TopBar status={status} settings={settings} />
      <div className="grid min-h-0 flex-1 lg:grid-cols-[360px_1fr]">
        <aside className="overflow-y-auto border-r border-ink bg-white">
          <InputPanel status={status} settings={settings} onSettings={setSettings} loading={loading} onRun={run} messages={messages} />
        </aside>
        <main className="overflow-y-auto p-6 lg:p-8">
          {error && <div className="mb-5 border-l-4 border-bad bg-red-50 px-4 py-3 text-[13px]">{error}</div>}
          {loading ? (
            <div className="sheet grid-paper grid min-h-[360px] place-items-center">
              <div className="w-72 bg-white p-5 text-center">
                <div className="cap !text-ink">Reading inquiry</div>
                <div className="hazard hazard-anim mt-3 h-2" />
                <div className="mt-2 text-[12px] text-muted">With the AI model this can take a minute.</div>
              </div>
            </div>
          ) : result ? (
            <Results key={result.case_id + result.saved} r={result} />
          ) : (
            <div className="sheet grid-paper grid min-h-[420px] place-items-center">
              <div className="bg-white px-8 py-6 text-center">
                <div className="font-cond text-2xl font-bold uppercase tracking-[0.08em]">No inquiry loaded</div>
                <div className="mt-1 text-[13px] text-muted">Add a file, paste text or pick a sample on the left.</div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
