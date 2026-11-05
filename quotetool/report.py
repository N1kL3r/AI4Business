"""Tables for showing results in a notebook."""
from __future__ import annotations

import pandas as pd

from .checks import CheckResult
from .schema import Extraction, Status

LABELS = {Status.FOUND: "found", Status.MISSING: "missing", Status.INFERRED: "assumed", Status.NEEDS_REVIEW: "check"}
MARKS = {Status.FOUND: "", Status.MISSING: "[missing]", Status.INFERRED: "[assumed]", Status.NEEDS_REVIEW: "[check]"}


def _show(value) -> str:
    if isinstance(value, list):
        return ", ".join(map(str, value))
    return "" if value is None else str(value)


def header_table(ex: Extraction) -> pd.DataFrame:
    return pd.DataFrame([{"field": k, "value": _show(f.value), "status": LABELS[f.status],
                          "evidence": f.evidence or "", "note": f.note or ""} for k, f in ex.header.items()])


def items_table(ex: Extraction, fields=("part_number", "description", "quantity", "unit", "pieces_per_unit",
                                        "material", "drawing_ref", "machine_model")) -> pd.DataFrame:
    """One row per part. A value that is not plainly found carries a [missing] / [assumed] / [check] mark."""
    rows = []
    for item in ex.items:
        rows.append({k: f"{_show(item[k].value)} {MARKS[item[k].status]}".strip() for k in fields})
    return pd.DataFrame(rows)


def issues_table(result: CheckResult) -> pd.DataFrame:
    order = {"blocking": 0, "check": 1, "assumption": 2, "info": 3}
    df = pd.DataFrame([vars(i) for i in result.issues], columns=["where", "field", "severity", "message"])
    return df.sort_values("severity", key=lambda s: s.map(order), kind="stable").reset_index(drop=True)


def evidence_table(ex: Extraction) -> pd.DataFrame:
    """Every value with the email text it was taken from, header first, then each part."""
    rows = [{"where": "inquiry", "field": k, "value": _show(f.value), "status": LABELS[f.status],
             "evidence": f.evidence or "", "note": f.note or ""} for k, f in ex.header.items()]
    for item in ex.items:
        part = item["part_number"].value or "?"
        rows += [{"where": part, "field": k, "value": _show(f.value), "status": LABELS[f.status],
                  "evidence": f.evidence or "", "note": f.note or ""} for k, f in item.items()
                  if k != "past_quotes"]  # listed in full in its own table
    return pd.DataFrame(rows)
