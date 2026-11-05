import { useRef, useState } from "react";
import { Loader2, Paperclip, X } from "lucide-react";
import type { Input } from "./api";
import type { ServerStatus, Settings } from "./types";

type Tab = "upload" | "paste" | "sample";
const TABS: [Tab, string][] = [["upload", "Files"], ["paste", "Text"], ["sample", "Samples"]];

interface Props {
  status: ServerStatus | null;
  settings: Settings;
  onSettings: (s: Settings) => void;
  loading: boolean;
  onRun: (input: Input) => void;
  messages: { warnings: string[]; sources: string[] };
}

export function InputPanel({ status, settings, onSettings, loading, onRun, messages }: Props) {
  const [tab, setTab] = useState<Tab>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [pasted, setPasted] = useState("");
  const [sample, setSample] = useState("");
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const add = (list: FileList | null) => list && setFiles((f) => [...f, ...Array.from(list)]);
  const chosenSample = sample || status?.samples[0] || "";
  const ready = tab === "upload" ? files.length > 0 : tab === "paste" ? pasted.trim().length > 0 : !!chosenSample;
  const run = () =>
    onRun({ files: tab === "upload" ? files : [], pasted: tab === "paste" ? pasted : "", sample: tab === "sample" ? chosenSample : "" });

  return (
    <div className="flex h-full flex-col gap-6 p-5">
      <section>
        <div className="cap mb-2">01 &nbsp;Inquiry</div>
        <div className="grid grid-cols-3 border border-ink">
          {TABS.map(([id, name]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`py-2 font-cond text-[14px] font-semibold uppercase tracking-[0.1em] ${tab === id ? "bg-ink text-white" : "text-muted hover:bg-sub hover:text-ink"} ${id !== "upload" ? "border-l border-ink" : ""}`}>
              {name}
            </button>
          ))}
        </div>

        <div className="mt-3">
          {tab === "upload" && (
            <>
              <div onClick={() => inputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
                onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
                className={`cursor-pointer border border-dashed px-4 py-8 text-center transition ${drag ? "border-ink bg-signal/30" : "border-slate-400 bg-sub hover:border-ink"}`}>
                <div className="font-cond text-[17px] font-semibold uppercase tracking-wide">Drop files or click</div>
                <div className="mt-1.5 text-[12px] leading-snug text-muted">
                  .eml .msg .mbox · WhatsApp, Teams, Slack exports · Word · Excel · PDF · text · HTML · ZIP.
                  Several files are read as one inquiry.
                </div>
                <input ref={inputRef} type="file" multiple hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
              </div>
              {files.length > 0 && (
                <ul className="mt-2 divide-y divide-line border border-line">
                  {files.map((f, i) => (
                    <li key={i} className="flex items-center gap-2 px-2.5 py-1.5">
                      <Paperclip size={13} className="shrink-0 text-muted" />
                      <span className="flex-1 truncate font-mono text-[12px]">{f.name}</span>
                      <span className="font-mono text-[11px] text-muted">{(f.size / 1024).toFixed(0)}K</span>
                      <button aria-label="Remove" onClick={() => setFiles(files.filter((_, j) => j !== i))} className="text-muted hover:text-bad"><X size={14} /></button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {tab === "paste" && (
            <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={11}
              placeholder="Paste an email, a chat conversation or notes. From, Date and Subject lines are optional."
              className="w-full resize-y border border-line bg-sub p-3 font-mono text-[12px] leading-relaxed outline-none focus:border-ink" />
          )}
          {tab === "sample" && (
            <select value={chosenSample} onChange={(e) => setSample(e.target.value)}
              className="w-full border border-line bg-sub p-2.5 font-mono text-[12px] outline-none focus:border-ink">
              {status?.samples.map((s) => <option key={s}>{s}</option>)}
            </select>
          )}

          {messages.sources.map((s) => <div key={s} className="mt-2 font-mono text-[11px] text-muted">▸ {s}</div>)}
          {messages.warnings.map((w) => (
            <div key={w} className="mt-2 border-l-[3px] border-signal-dark bg-[#fff6bf] px-3 py-2 text-[12px] leading-snug">{w}</div>
          ))}
        </div>
      </section>

      <section>
        <div className="cap mb-2">02 &nbsp;Reader</div>
        <div className="grid grid-cols-2 border border-ink">
          {(["ai", "rules"] as const).map((m) => (
            <button key={m} onClick={() => onSettings({ ...settings, mode: m })}
              className={`py-2 font-cond text-[14px] font-semibold uppercase tracking-[0.1em] ${settings.mode === m ? "bg-ink text-white" : "text-muted hover:bg-sub hover:text-ink"} ${m === "rules" ? "border-l border-ink" : ""}`}>
              {m === "ai" ? "AI model" : "Rules only"}
            </button>
          ))}
        </div>
        {settings.mode === "ai" && (
          <input value={settings.model} onChange={(e) => onSettings({ ...settings, model: e.target.value })} spellCheck={false}
            className="mt-2 w-full border border-line bg-white px-2.5 py-2 font-mono text-[12px] outline-none focus:border-ink" />
        )}
        <p className="mt-2 text-[12px] leading-snug text-muted">
          {settings.mode === "ai" ? status?.model.message : "Fixed patterns, no AI. Faster, but only reliable for familiar layouts."}
        </p>
      </section>

      <button onClick={run} disabled={!ready || loading}
        className="flex items-center justify-center gap-2 bg-signal py-3.5 font-cond text-[17px] font-bold uppercase tracking-[0.12em] text-ink transition hover:bg-signal-dark disabled:cursor-not-allowed disabled:bg-sub disabled:text-slate-400">
        {loading && <Loader2 size={16} className="animate-spin" />}
        {loading ? "Reading" : "Read inquiry"}
      </button>

      <p className="mt-auto text-[11.5px] leading-snug text-muted">
        Everything stays on this computer. Answers are saved in data/lake/. A person signs every quotation.
      </p>
    </div>
  );
}
