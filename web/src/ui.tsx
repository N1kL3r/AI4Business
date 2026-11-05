import type { ReactNode } from "react";
import type { Field, Status } from "./types";

export const show = (v: unknown): string =>
  v === null || v === undefined || v === "" ? "" : Array.isArray(v) ? v.join(", ") : String(v);

export const labelOf = (name: string) => name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export const TINT: Record<Status, string> = {
  found: "",
  missing: "bg-red-50 text-bad font-medium",
  needs_review: "bg-[#fff6bf] text-[#5c4b00] font-medium",
  inferred: "bg-blue-50 text-info font-medium",
};

const BADGE = {
  ok: "bg-ok text-white", bad: "bg-bad text-white", warn: "bg-signal text-ink",
  info: "bg-info text-white", mute: "bg-sub text-muted ring-1 ring-inset ring-line",
};

export function Badge({ kind, children }: { kind: keyof typeof BADGE; children: ReactNode }) {
  return (
    <span className={`inline-block whitespace-nowrap px-1.5 py-[3px] font-cond text-[12px] font-bold uppercase leading-none tracking-[0.08em] ${BADGE[kind]}`}>
      {children}
    </span>
  );
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto border border-line">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="bg-sub">
            {head.map((h) => (
              <th key={h} className="cap whitespace-nowrap border-b border-ink px-3 py-2 text-left !text-ink">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_tr:hover]:bg-sub/70 [&_tr:last-child_td]:border-b-0">{children}</tbody>
      </table>
    </div>
  );
}

export const Td = ({ children, cls = "" }: { children?: ReactNode; cls?: string }) => (
  <td className={`border-b border-line px-3 py-2.5 align-top ${cls}`}>{children || <span className="text-slate-300">–</span>}</td>
);

/** Missing only matters (red) when the quote cannot go ahead without the field. */
export const fieldCell = (f: Field | undefined, blocking: boolean, fallback = "") => ({
  text: show(f?.value) || fallback,
  cls: f && (f.status !== "missing" || blocking) ? TINT[f.status] : "",
});

/** Section label drawn like a dimension line. */
export function Dim({ children }: { children: ReactNode }) {
  return (
    <div className="mb-3 flex items-center gap-3">
      <span className="h-3 w-px bg-ink" /><span className="h-px flex-1 bg-ink" />
      <span className="cap !text-ink">{children}</span>
      <span className="h-px flex-1 bg-ink" /><span className="h-3 w-px bg-ink" />
    </div>
  );
}
