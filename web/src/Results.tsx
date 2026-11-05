import { useMemo, useState } from "react";
import { Download, Copy, CheckCircle2, OctagonAlert } from "lucide-react";
import { downloadQuotation } from "./api";
import type { Issue, PastQuote, Result } from "./types";
import { Badge, Table, Td, TINT, fieldCell, labelOf, show } from "./ui";

const BLOCKING = ["part_number", "quantity", "material", "drawing_ref"];
const TIER: Record<string, [string, "ok" | "warn" | "mute"]> = {
  exact: ["Same part number", "ok"], similar: ["Similar part", "warn"], none: ["No match", "mute"],
};
const SEVERITY: Record<Issue["severity"], [string, "bad" | "warn" | "info" | "mute"]> = {
  blocking: ["Blocking", "bad"], check: ["Check", "warn"], assumption: ["Assumption", "info"], info: ["Note", "mute"],
};
const TABS = ["Parts", "Inquiry", "Past quotes", "Review items", "Quotation", "Customer reply", "Evidence"] as const;

export function Results({ r }: { r: Result }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Parts");
  const h = (name: string) => r.header.find((f) => f.name === name);
  const block: [string, string, string?][] = [
    ["Case", r.case_id, "font-mono"], ["Customer", show(h("customer")?.value)], ["Received", show(h("received_date")?.value), "font-mono"],
    ["Deadline", show(h("deadline")?.value), "font-mono"],
    ["Terms", [show(h("currency")?.value), show(h("incoterm")?.value)].filter(Boolean).join(" / "), "font-mono"],
    ["Spec", show(h("specifications")?.value), "font-mono"],
  ];
  const counts: [number, string][] = [[r.items.length, "Parts"], [r.counts.blocking, "Blocking"], [r.counts.check, "Check"], [r.counts.assumption, "Assumed"]];

  return (
    <div className="sheet">
      <div className="grid grid-cols-2 border-b border-ink md:grid-cols-6">
        {block.map(([l, v, cls], i) => (
          <div key={l} className={`min-w-0 px-4 py-3 ${i ? "md:border-l border-line" : ""}`}>
            <div className="cap">{l}</div>
            <div className={`mt-0.5 truncate text-[13.5px] font-medium ${cls ?? ""} ${v ? "" : "text-slate-300"}`} title={v}>{v || "–"}</div>
          </div>
        ))}
      </div>

      <div className="flex items-stretch border-b border-ink">
        <div className={`w-4 shrink-0 ${r.ready ? "bg-ok" : "hazard"}`} />
        <div className="flex flex-1 flex-wrap items-center justify-between gap-4 px-5 py-4">
          <div>
            <div className="font-cond text-[26px] font-bold uppercase leading-none tracking-[0.04em]">
              {r.ready ? "Ready for pricing" : "On hold: information required"}
            </div>
            <div className="mt-1.5 text-[13px] text-muted">
              {r.ready ? "Nothing essential is missing. Review the checks before a price is set."
                : `${r.counts.blocking} essential item(s) missing. A draft reply to the customer is under Customer reply.`}
              {r.saved && " Saved answer reused."}
            </div>
          </div>
          <div className="flex gap-6">
            {counts.map(([v, l]) => (
              <div key={l} className="text-right">
                <div className="font-mono text-[26px] font-medium leading-none tabular-nums">{v}</div>
                <div className="cap mt-1">{l}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap border-b border-line px-2">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`-mb-px border-b-[3px] px-4 py-3 font-cond text-[15px] font-semibold uppercase tracking-[0.1em] ${tab === t ? "border-signal-dark text-ink" : "border-transparent text-muted hover:text-ink"}`}>
            {t}
          </button>
        ))}
      </div>
      <div className="p-5">
        {tab === "Inquiry" && <InquiryTab r={r} />}
        {tab === "Parts" && <PartsTab r={r} />}
        {tab === "Past quotes" && <PastTab r={r} />}
        {tab === "Review items" && <IssuesTab r={r} />}
        {tab === "Quotation" && <QuotationTab r={r} />}
        {tab === "Customer reply" && <ReplyTab r={r} />}
        {tab === "Evidence" && <EvidenceTab r={r} />}
      </div>
    </div>
  );
}

const Legend = ({ children }: { children?: React.ReactNode }) => (
  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
    <Badge kind="warn">Check</Badge><Badge kind="bad">Missing</Badge><Badge kind="info">Assumed</Badge>{children}
  </div>
);

function InquiryTab({ r }: { r: Result }) {
  return (
    <>
      <div className="grid gap-x-8 md:grid-cols-3">
        {r.header.map((f) => {
          const empty = !show(f.value);
          return (
            <div key={f.name} className="border-b border-line py-2.5">
              <div className="cap">{labelOf(f.name)}</div>
              <div className={`mt-0.5 ${empty ? "text-slate-400" : ""} ${f.status === "missing" ? "" : TINT[f.status].replace(/bg-\S+/, "")}`}>
                {show(f.value) || "Not stated"}
              </div>
            </div>
          );
        })}
      </div>
      <Legend>Uncoloured values were stated in the inquiry.</Legend>
    </>
  );
}

const PART_COLS = ["part_number", "description", "quantity", "unit", "pieces_per_unit", "material", "drawing_ref"];

function PartsTab({ r }: { r: Result }) {
  if (!r.items.length) return <p>No parts were found.</p>;
  const mono = ["part_number", "drawing_ref"], num = ["quantity", "pieces_per_unit"];
  return (
    <>
      <Table head={[...PART_COLS.map((k) => (k === "pieces_per_unit" ? "Pcs / unit" : labelOf(k))), "Past match", "Ref. price", "Customer price"]}>
        {r.items.map((item, i) => (
          <tr key={i}>
            {PART_COLS.map((k) => {
              const c = fieldCell(item[k], BLOCKING.includes(k), item[k]?.status === "missing" && BLOCKING.includes(k) ? "Not stated" : "");
              return <Td key={k} cls={`${c.cls} ${mono.includes(k) ? "font-mono text-[13px]" : ""} ${num.includes(k) ? "text-right tabular-nums" : ""}`}>{c.text}</Td>;
            })}
            <Td><Badge kind={(TIER[show(item.match_tier?.value)] ?? TIER.none)[1]}>{(TIER[show(item.match_tier?.value)] ?? TIER.none)[0]}</Badge></Td>
            <Td cls={`text-right font-mono tabular-nums ${item.reference_price ? TINT[item.reference_price.status] : ""}`}>{show(item.reference_price?.value)}</Td>
            <Td cls="text-right font-mono tabular-nums">{show(item.customer_price?.value)}</Td>
          </tr>
        ))}
      </Table>
      <Legend>Reference price is the latest past quote of the same part, or of a similar part when marked so.</Legend>
    </>
  );
}

function PastTab({ r }: { r: Result }) {
  const rows = r.items.flatMap((item) =>
    ((item.past_quotes?.value as PastQuote[]) ?? []).map((q) => ({ part: show(item.part_number.value), tier: show(item.match_tier.value), q })));
  const tiers = r.items.map((i) => show(i.match_tier?.value));
  const n = (t: string) => tiers.filter((x) => x === t).length;
  return (
    <>
      <p className="mb-4 text-sm">
        Compared with <b>{r.history.count} past quotes</b> in <code className="font-mono text-[13px]">{r.history.file}</code>:{" "}
        <b>{n("exact")}</b> part(s) quoted before with the same part number, <b>{n("similar")}</b> only with a similar description (check),{" "}
        <b>{n("none")}</b> not found.
      </p>
      {rows.length ? (
        <>
          <Table head={["Part in inquiry", "Match", "Past part number", "Past description", "Price", "Currency", "Quantity", "Quoted on", "Customer", "Quote id", "Similarity", "Row in file"]}>
            {rows.map(({ part, tier, q }, i) => (
              <tr key={i}>
                <Td cls="font-mono text-[13px]">{part}</Td>
                <Td><Badge kind={(TIER[tier] ?? TIER.none)[1]}>{(TIER[tier] ?? TIER.none)[0]}</Badge></Td>
                <Td cls="font-mono text-[13px]">{q.part_number}</Td><Td>{q.description}</Td>
                <Td cls="text-right font-mono tabular-nums">{q.price}</Td><Td>{q.currency}</Td><Td cls="text-right tabular-nums">{q.quantity}</Td>
                <Td cls="whitespace-nowrap">{q.quoted_date}</Td><Td>{q.customer}</Td><Td cls="font-mono text-[13px]">{q.quote_id}</Td>
                <Td cls="text-right tabular-nums">{q.similarity}</Td><Td cls="text-right tabular-nums">{q.source_row}</Td>
              </tr>
            ))}
          </Table>
          <p className="mt-3 text-xs text-muted">Newest first. “Row in file” is the row in the past-quotes file, so the original quote can be looked up. A similar match is a different part: its price is only a pointer.</p>
        </>
      ) : <p>No past quotes found for any part.</p>}
    </>
  );
}

function IssuesTab({ r }: { r: Result }) {
  if (!r.issues.length) return <p>Nothing needs attention.</p>;
  return (
    <Table head={["Where", "Field", "Severity", "Message"]}>
      {r.issues.map((i, k) => (
        <tr key={k}><Td cls="whitespace-nowrap font-mono text-[13px]">{i.where}</Td><Td>{labelOf(i.field)}</Td>
          <Td><Badge kind={SEVERITY[i.severity][1]}>{SEVERITY[i.severity][0]}</Badge></Td><Td>{i.message}</Td></tr>
      ))}
    </Table>
  );
}

function QuotationTab({ r }: { r: Result }) {
  const suggest = (item: Result["items"][number]) =>
    (item.customer_price?.value as number | null) ?? (show(item.match_tier?.value) === "exact" ? (item.reference_price?.value as number) : null);
  const basis = (item: Result["items"][number]) =>
    item.customer_price?.value != null ? "Last price to this customer"
      : show(item.match_tier?.value) === "exact" ? "Latest past price" : "No reference";
  const [prices, setPrices] = useState<string[]>(() => r.items.map((i) => String(suggest(i) ?? "")));
  const [company, setCompany] = useState("[Company name]");
  const [error, setError] = useState("");
  const nums = prices.map((p) => (p.trim() === "" || isNaN(Number(p)) ? null : Number(p)));
  const total = useMemo(() => r.items.reduce((s, it, i) => s + (nums[i] ?? 0) * (Number(it.quantity?.value) || 0), 0), [prices]);

  if (!r.ready) return <p>The quotation can be prepared once the missing information is in. See Review items and Customer reply.</p>;
  return (
    <>
      <p className="mb-4 max-w-3xl text-sm text-muted">
        Set the unit price per line. The suggestion is the last price quoted to this customer for the same part, else the latest past price of that part.
        The price is your decision; the tool never sets it.
      </p>
      <Table head={["Part", "Qty", "Unit price", "Basis", "Line total"]}>
        {r.items.map((item, i) => (
          <tr key={i}>
            <Td cls="font-mono text-[13px]">{show(item.part_number.value)}</Td>
            <Td cls="tabular-nums">{show(item.quantity.value)}</Td>
            <Td><input value={prices[i]} inputMode="decimal" onChange={(e) => setPrices(prices.map((p, j) => (j === i ? e.target.value : p)))}
              className="w-32 border border-line bg-white px-3 py-1.5 text-right font-mono outline-none focus:border-ink" /></Td>
            <Td cls="text-muted">{basis(item)}</Td>
            <Td cls="text-right font-mono tabular-nums">{nums[i] != null ? (nums[i]! * (Number(item.quantity.value) || 0)).toLocaleString(undefined, { minimumFractionDigits: 2 }) : ""}</Td>
          </tr>
        ))}
      </Table>
      <div className="mt-3 text-right font-mono text-lg font-medium">Total {total.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
      <div className="mt-6 flex flex-wrap items-end gap-4">
        <label className="block"><span className="cap">Company name on the quotation</span>
          <input value={company} onChange={(e) => setCompany(e.target.value)} className="mt-1 block w-72 border border-line bg-white px-3 py-2.5 outline-none focus:border-ink" /></label>
        <button onClick={() => downloadQuotation(r.case_id, nums, company).then(() => setError(""), (e) => setError(String(e.message)))}
          className="flex items-center gap-2 bg-signal px-6 py-3 font-cond text-[16px] font-bold uppercase tracking-[0.1em] text-ink hover:bg-signal-dark">
          <Download size={15} /> Download quotation (.docx)
        </button>
      </div>
      {error && <div className="mt-3 border-l-4 border-signal-dark bg-[#fff6bf] px-4 py-2.5 text-[13px]">{error}</div>}
      <p className="mt-3 text-xs text-muted">Opens in Word for editing. It carries a signature line and is not valid until a person signs it.</p>
    </>
  );
}

function ReplyTab({ r }: { r: Result }) {
  const [text, setText] = useState(r.client_email ?? "");
  if (!r.client_email) return <p>Nothing essential is missing, so there is no need to ask the customer.</p>;
  const save = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    Object.assign(document.createElement("a"), { href: url, download: `reply_${r.case_id}.txt` }).click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <div className="cap mb-2">Edit before sending</div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12}
        className="w-full max-w-3xl border border-line bg-sub p-4 font-mono text-[13px] leading-relaxed outline-none focus:border-ink" />
      <div className="mt-3 flex gap-3">
        <button onClick={() => navigator.clipboard.writeText(text)} className="flex items-center gap-2 border border-ink px-5 py-2 font-cond text-[15px] font-semibold uppercase tracking-[0.1em] hover:bg-ink hover:text-white"><Copy size={14} /> Copy</button>
        <button onClick={save} className="flex items-center gap-2 border border-ink px-5 py-2 font-cond text-[15px] font-semibold uppercase tracking-[0.1em] hover:bg-ink hover:text-white"><Download size={14} /> Download (.txt)</button>
      </div>
    </>
  );
}

function EvidenceTab({ r }: { r: Result }) {
  return (
    <>
      <p className="mb-3 text-sm text-muted">Every value with the exact text it was taken from.</p>
      <Table head={["Where", "Field", "Value", "Status", "Evidence", "Note"]}>
        {r.evidence.map((e, i) => (
          <tr key={i}><Td cls="font-mono text-[13px]">{e.where}</Td><Td>{labelOf(e.field)}</Td><Td>{e.value}</Td><Td>{e.status}</Td>
            <Td cls="font-mono text-xs text-muted">{e.evidence}</Td><Td cls="text-muted">{e.note}</Td></tr>
        ))}
      </Table>
    </>
  );
}
