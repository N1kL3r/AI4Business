export type Status = "found" | "missing" | "inferred" | "needs_review";

export interface Field {
  value: unknown;
  status: Status;
  note?: string | null;
  evidence?: string | null;
}

export interface PastQuote {
  part_number: string;
  description: string;
  price: number;
  currency: string;
  quantity: string;
  quoted_date: string;
  customer: string;
  quote_id: string;
  similarity: number;
  source_row: number;
}

export type Item = Record<string, Field>;

export interface Issue {
  where: string;
  field: string;
  severity: "blocking" | "check" | "assumption" | "info";
  message: string;
}

export interface Result {
  case_id: string;
  text: string;
  sources: string[];
  warnings: string[];
  saved: boolean;
  ready: boolean;
  counts: Record<Issue["severity"], number>;
  history: HistoryInfo;
  header: ({ name: string } & Field)[];
  items: Item[];
  issues: Issue[];
  client_email: string | null;
  evidence: Record<string, string>[];
}

export interface HistoryInfo {
  count: number;
  file: string;
  is_example: boolean;
  error: string | null;
}

export interface ServerStatus {
  model: { ok: boolean; message: string };
  history: HistoryInfo;
  samples: string[];
}

export interface Settings {
  mode: "ai" | "rules";
  model: string;
}
