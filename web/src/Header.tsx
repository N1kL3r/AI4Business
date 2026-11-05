import type { ServerStatus, Settings } from "./types";

const Dot = ({ ok }: { ok: boolean }) => <i className={`inline-block h-2 w-2 ${ok ? "bg-ok" : "bg-signal-dark"}`} />;

export function TopBar({ status, settings }: { status: ServerStatus | null; settings: Settings }) {
  return (
    <header className="flex h-12 items-center justify-between border-b border-ink bg-white px-5">
      <div className="flex items-center gap-3">
        <span className="grid h-6 w-6 place-items-center bg-ink font-cond text-[13px] font-bold tracking-wider text-signal">QA</span>
        <span className="font-cond text-[17px] font-bold uppercase tracking-[0.08em]">Quote Assistant</span>
      </div>
      <div className="flex items-center gap-6 font-mono text-[11.5px] text-muted">
        <span className="flex items-center gap-2">
          <Dot ok={settings.mode === "rules" || !!status?.model.ok} />
          {settings.mode === "rules" ? "Reader: rules" : status?.model.ok ? `Model: ${settings.model}` : "Model: not running"}
        </span>
        <span className="flex items-center gap-2">
          <Dot ok={!!status && !status.history.is_example && !status.history.error} />
          {status ? `Archive: ${status.history.count} quotes${status.history.is_example ? " (example data)" : ""}` : "Backend: not reachable"}
        </span>
      </div>
    </header>
  );
}
