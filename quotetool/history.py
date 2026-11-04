"""Load the archive of past quotes that parts are compared against (see matching.py)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ("part_number", "description", "price")
OPTIONAL = ("currency", "quoted_date", "customer", "quote_id", "quantity")


def load_history(path: str | Path) -> list[dict]:
    """Read a CSV (or Excel) file with one row per past quote.

    Needs the columns part_number, description and price. The optional columns currency, quoted_date, customer,
    quote_id and quantity are kept so a match can be traced to the original quote; `source_row` is the row
    number in the file (header = row 1). Rows without a part number or with a price that is not a number are skipped.
    """
    path = Path(path)
    df = pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} is missing the column(s): {', '.join(missing)}")
    df["source_row"] = df.index + 2
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["part_number"] = df["part_number"].astype("string").str.strip()
    df = df.dropna(subset=["part_number", "price"])
    df = df[df["part_number"] != ""]
    df["description"] = df["description"].fillna("").astype(str)
    for c in OPTIONAL:
        df[c] = df[c].astype("string").fillna("") if c in df.columns else ""
    return df[[*REQUIRED, *OPTIONAL, "source_row"]].to_dict("records")
