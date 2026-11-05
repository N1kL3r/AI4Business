import type { Result, ServerStatus, Settings } from "./types";

export async function getStatus(s: Settings): Promise<ServerStatus> {
  const r = await fetch(`/api/status?mode=${s.mode}&model=${encodeURIComponent(s.model)}`);
  if (!r.ok) throw new Error("The backend is not running. Start it with: uvicorn api:app --port 8000");
  return r.json();
}

export interface Input {
  files: File[];
  pasted: string;
  sample: string;
}

export async function analyze(input: Input, s: Settings): Promise<Result | { error: string; warnings?: string[]; sources?: string[] }> {
  const form = new FormData();
  input.files.forEach((f) => form.append("files", f));
  form.append("pasted", input.pasted);
  form.append("sample", input.sample);
  form.append("mode", s.mode);
  form.append("model", s.model);
  const r = await fetch("/api/analyze", { method: "POST", body: form });
  if (!r.ok) throw new Error(`Server error (${r.status})`);
  return r.json();
}

export async function downloadQuotation(caseId: string, prices: (number | null)[], company: string) {
  const r = await fetch("/api/quotation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId, prices, company }),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? "Could not create the quotation");
  const url = URL.createObjectURL(await r.blob());
  Object.assign(document.createElement("a"), { href: url, download: `quotation_${caseId}.docx` }).click();
  URL.revokeObjectURL(url);
}
