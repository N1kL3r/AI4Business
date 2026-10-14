"""Tables for showing results in a notebook."""
from __future__ import annotations

import pandas as pd

from .checks import CheckResult
from .schema import Extraction, Status

ICONS = {Status.FOUND: "✅ found", Status.MISSING: "❌ missing",
         Status.INFERRED: "🔵 inferred", Status.NEEDS_REVIEW: "⚠️ check"}


def _show(value):
    if isinstance(value, list):
        return ", ".join(map(str, value))
    return "" if value is None else value


def header_table(ex: Extraction) -> pd.DataFrame:
    return pd.DataFrame([{"field": k, "value": _show(f.value), "status": ICONS[f.status],
                          "evidence": f.evidence or "", "note": f.note or ""} for k, f in ex.header.items()])


def items_table(ex: Extraction, fields=("part_number", "description", "quantity", "unit", "pieces_per_unit",
                                        "material", "drawing_ref", "machine_model")) -> pd.DataFrame:
    """One row per part. Each cell shows the value with a status icon."""
    rows = []
    for item in ex.items:
        rows.append({k: f"{ICONS[item[k].status].split()[0]} {_show(item[k].value)}".strip() for k in fields})
    return pd.DataFrame(rows)


def issues_table(result: CheckResult) -> pd.DataFrame:
    order = {"blocking": 0, "check": 1, "assumption": 2, "info": 3}
    df = pd.DataFrame([vars(i) for i in result.issues], columns=["where", "field", "severity", "message"])
    return df.sort_values("severity", key=lambda s: s.map(order), kind="stable").reset_index(drop=True)
