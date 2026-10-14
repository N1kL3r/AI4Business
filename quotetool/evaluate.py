"""Score an extraction against a hand-made answer key.

Answer key conventions (data/test_cases/*.json):
- null means "not in the email": the extractor must report it as missing.
- "a|b" means either answer is accepted.
- Text matches if one contains the other (ignoring case, spaces and punctuation).
- Lists match if every expected entry is found.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .schema import Extraction, Field


def load_key(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _norm(x) -> str:
    return re.sub(r"[^0-9a-z一-鿿]", "", str(x).lower())


def _text_match(expected: str, predicted) -> bool:
    p = _norm(predicted)
    for alt in str(expected).split("|"):
        e = _norm(alt)
        if e and (e in p or (len(p) >= 3 and p in e)):
            return True
    return False


def value_matches(expected, predicted) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(predicted) == float(expected)
        except (TypeError, ValueError):
            return False
    if isinstance(expected, list):
        preds = predicted if isinstance(predicted, list) else [predicted]
        return all(any(_text_match(e, p) for p in preds) for e in expected)
    return _text_match(expected, predicted)


def _outcome(expected, f: Field) -> str:
    if expected is None:
        return "correct (missing)" if not f.present else "invented"
    if not f.present:
        return "missed"
    return "correct" if value_matches(expected, f.value) else "wrong value"


def score(extraction: Extraction, key: dict, case_id: str = "") -> pd.DataFrame:
    """One row per expected field: what was expected, what came out, and the outcome."""
    rows = []

    def row(where, name, expected, f: Field):
        rows.append({"case": case_id, "where": where, "field": name, "expected": expected,
                     "predicted": f.value, "status": f.status.value, "outcome": _outcome(expected, f)})

    for name, expected in key["header"].items():
        row("header", name, expected, extraction.header.get(name, Field()))

    # Pair lines by part number; a part the extractor did not find counts as missed on every field.
    by_part = {_norm(i["part_number"].value): i for i in extraction.items if i["part_number"].present}
    expected_parts = set()
    for exp_item in key["items"]:
        pn = exp_item["part_number"]
        expected_parts.add(_norm(pn))
        got = by_part.get(_norm(pn), {})
        for name, expected in exp_item.items():
            row(f"line {pn}", name, expected, got.get(name, Field()))

    # Lines the extractor made up (not in the answer key) count as one invented value each.
    for item in extraction.items:
        pn = item["part_number"]
        if _norm(pn.value) not in expected_parts:
            rows.append({"case": case_id, "where": f"line {pn.value}", "field": "(whole line)", "expected": None,
                         "predicted": pn.value, "status": pn.status.value, "outcome": "invented"})
    return pd.DataFrame(rows)


def summary(scores: pd.DataFrame) -> pd.DataFrame:
    """Per case: values the email contains vs. values caught, gaps vs. gaps reported, and invented values."""
    s = scores.assign(has_value=scores["expected"].notna() & (scores["field"] != "(whole line)"),
                      ok=scores["outcome"].str.startswith("correct"))
    g = s.groupby("case")
    out = pd.DataFrame({
        "values in email": g["has_value"].sum(),
        "values caught": g.apply(lambda d: (d["has_value"] & d["ok"]).sum(), include_groups=False),
        "gaps": g.apply(lambda d: (d["expected"].isna() & (d["field"] != "(whole line)")).sum(), include_groups=False),
        "gaps reported": g.apply(lambda d: (d["outcome"] == "correct (missing)").sum(), include_groups=False),
        "invented": g.apply(lambda d: (d["outcome"] == "invented").sum(), include_groups=False),
    }).astype(int)
    out.loc["TOTAL"] = out.sum()
    out["values caught %"] = (out["values caught"] / out["values in email"]).map("{:.0%}".format)
    return out
