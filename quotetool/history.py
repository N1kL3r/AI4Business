"""Load the archive of past quotes that parts are compared against (see matching.py)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ("part_number", "description", "price")


def load_history(path: str | Path) -> list[dict]:
    """Read a CSV (or Excel) file with one row per past quote.

    Needs the columns part_number, description and price; any others (e.g. quoted_date) are ignored.
    Rows without a part number or with a price that is not a number are skipped.
    """
    path = Path(path)
    df = pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} is missing the column(s): {', '.join(missing)}")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["part_number"] = df["part_number"].astype("string").str.strip()
    df = df.dropna(subset=["part_number", "price"])
    df = df[df["part_number"] != ""]
    df["description"] = df["description"].fillna("").astype(str)
    return df[list(REQUIRED)].to_dict("records")
