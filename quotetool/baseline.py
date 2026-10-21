"""Rule-based extractor (no AI), as a baseline to compare the LLM against.

The rules were written while looking at the three sample emails, so this baseline is optimistic:
a new customer with a different email layout will break it. That is the point of the comparison.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .emails import Email
from .schema import Extraction, Field, Status

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def _found(value, evidence) -> Field:
    return Field(value=value, status=Status.FOUND, evidence=evidence.strip())


def _parse_date(text: str) -> date | None:
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if not m:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(" ".join(m.groups()), fmt).date()
        except ValueError:
            pass
    return None


def _header(email: Email) -> dict[str, Field]:
    h: dict[str, Field] = {}
    body, sender = email.body, email.headers.get("from", "")

    if m := re.search(r"\[(Customer \w+)\]", sender):
        h["customer"] = _found(m.group(1), m.group(0))
    if m := re.match(r"\s*([^<(]+?)\s*[<(]", sender):
        h["contact"] = _found(m.group(1), m.group(1))

    received = _parse_date(email.headers.get("date", ""))
    if received:
        h["received_date"] = _found(received.isoformat(), email.headers["date"])

    if m := re.search(rf"\bby\b[^.\n]{{0,30}}?\b(\d{{1,2}})\s+((?:{MONTHS})[a-z]*)(?:\s+(\d{{4}}))?", body, re.I):
        year = m.group(3) or (received.year if received else None)
        if year and (d := _parse_date(f"{m.group(1)} {m.group(2)} {year}")):
            h["deadline"] = _found(d.isoformat(), m.group(0))

    if m := re.search(r"urgent\w*|asap|as soon as possible|尽快|紧急", body, re.I):
        h["urgency"] = _found("high", m.group(0))
    elif "deadline" in h and received and (date.fromisoformat(h["deadline"].value) - received).days <= 3:
        h["urgency"] = _found("high", h["deadline"].evidence)

    if m := re.search(r"\b(USD|EUR|RMB|CNY|AUD|JPY)\b", body):
        h["currency"] = _found(m.group(1), m.group(0))
    if m := re.search(r"\b(FOB|CIF|CFR|EXW|DAP|DDP|FCA)\b", body):
        h["incoterm"] = _found(m.group(1), m.group(0))

    specs = []
    for m in re.finditer(r"\b(JEP\d{3,}|AMS\s?\d{4}|ASTM\s?[A-Z]\d+|DIN\s?\d+)\b", body):
        if m.group(1) not in specs:
            specs.append(m.group(1))
    if specs:
        h["specifications"] = _found(specs, " ... ".join(specs))

    cjk = len(re.findall(r"[一-鿿]", body))
    h["language"] = _found("zh" if cjk > 10 else "en", "(character count)")
    return h


def _items(email: Email) -> list[dict[str, Field]]:
    # Group body lines into one block per part: a line that starts a part, plus indented continuation lines.
    blocks: list[tuple[str, list[str]]] = []  # (part number, lines)
    for line in email.body.splitlines():
        if m := re.search(r"\bPart\s+([A-Z0-9][A-Z0-9-]{4,})", line):
            blocks.append((m.group(1), [line]))
        elif (m := re.match(r"([A-Z0-9][A-Z0-9-]{5,})\s+\S", line)) and re.search(r"\d", m.group(1)):
            blocks.append((m.group(1), [line]))
        elif blocks and line.startswith(" ") and line.strip():
            blocks[-1][1].append(line)

    items = []
    for part, lines in blocks:
        text = " ".join(l.strip() for l in lines)
        first = lines[0].strip()
        item: dict[str, Field] = {"part_number": _found(part, part)}

        if m := re.search(r"Part\s+\S+,\s*([^,]+)", first):
            item["description"] = _found(m.group(1).strip(), m.group(0))
        else:  # table layout: description is the first column after the part number
            rest = first[len(part):].strip()
            desc = [re.split(r"\s{2,}", rest)[0]] + [re.split(r"\s{2,}", l.strip())[0] for l in lines[1:]]
            item["description"] = _found(" ".join(desc), " ... ".join(desc))

        if m := re.search(r"\bQty\s+(\d+)", text, re.I):
            item["quantity"] = _found(int(m.group(1)), m.group(0))
        elif m := re.search(r"\b(SET|EA|PCS|PC)\s+(\d+)\b", text):
            item["unit"] = _found(m.group(1), m.group(0))
            item["quantity"] = _found(int(m.group(2)), m.group(0))
        if m := re.search(r"SET OF (\d+)\s*PC", text, re.I):
            item["pieces_per_unit"] = _found(int(m.group(1)), m.group(0))

        if m := re.search(r"\bC\d{5}\b", text):
            item["material"] = _found(m.group(0), m.group(0))

        if m := re.search(r"\bdrawing\s+(D\d+)", text, re.I):
            item["drawing_ref"] = _found(m.group(1), m.group(0))
        else:
            for att in email.attachments:
                stem = att.rsplit(".", 1)[0]
                if part.endswith(stem):
                    item["drawing_ref"] = _found(att, att)
                    break

        if m := re.search(r"\b([A-Z]+\d+-[A-Z]+)\b", text[len(part):]):
            item["machine_model"] = _found(m.group(1), m.group(1))
        items.append(item)
    return items


def extract_baseline(email: Email) -> Extraction:
    return Extraction(header=_header(email), items=_items(email), extractor="baseline (rules)").complete()
