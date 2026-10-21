"""Plain-code checks after extraction: verify the evidence, apply YC's defaults, decide what blocks the quote.

The LLM says what is in the email. These rules decide what that means, the same way every time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .emails import Email
from .schema import Extraction, Field, Status

# What happens when a field is missing.
BLOCKING_LINE_FIELDS = ("part_number", "quantity", "material", "drawing_ref")  # cannot quote without it
DEFAULTS = {  # YC's usual terms: filled in, but shown on the quote as an assumption. Confirm with YC sales.
    "currency": "USD",
    "incoterm": "FOB Shanghai",
}
PIECE_UNITS = {"EA", "PC", "PCS", "PIECE", "PIECES"}
NO_EVIDENCE_NEEDED = {"language", "urgency"}  # judgements, not quotes from the text


@dataclass
class Issue:
    where: str      # "header" or "line 2 (4P100651)"
    field: str
    severity: str   # blocking | check | assumption | info
    message: str


@dataclass
class CheckResult:
    email: Email
    extraction: Extraction           # the checked copy (statuses may be downgraded, defaults filled)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ready_to_quote(self) -> bool:
        return not any(i.severity == "blocking" for i in self.issues)

    @property
    def client_email(self) -> str | None:
        return draft_client_email(self)


def _norm_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[\w.\-/#]+|[^\w\s]", text.lower())
    return [t.rstrip(".") or t for t in tokens]  # "material." and "material" are the same word


def _piece_in_text(piece: str, text: str) -> bool:
    """Exact match (ignoring spacing), else the words in order with small gaps
    (table columns can interleave text from the next column)."""
    if " ".join(piece.lower().split()) in " ".join(text.lower().split()):
        return True
    ev_tokens, tokens = _norm_tokens(piece), _norm_tokens(text)
    if not ev_tokens:
        return True
    max_span = 2 * len(ev_tokens) + 5
    for start in (i for i, t in enumerate(tokens) if t == ev_tokens[0]):
        j, pos = 1, start + 1
        while j < len(ev_tokens) and pos < len(tokens) and pos - start < max_span:
            if tokens[pos] == ev_tokens[j]:
                j += 1
            pos += 1
        if j == len(ev_tokens):
            return True
    return False


def evidence_in_text(evidence: str, text: str) -> bool:
    """Is the evidence really in the email?"""
    if _piece_in_text(evidence, text):
        return True
    pieces = [p for p in re.split(r"\.\.\.|…", evidence) if p.strip()]  # model shortened a quote with "..."
    if len(pieces) > 1:
        return all(_piece_in_text(p, text) for p in pieces)
    # Table cell quoted with its column header, e.g. "QTY 144": the header word and the cell are on
    # different lines. Accept when the header word is in the email and the rest is found on its own.
    words = evidence.split(maxsplit=1)
    if len(words) == 2 and re.fullmatch(r"[A-Za-z]{2,12}:?", words[0]):
        return _piece_in_text(words[0].rstrip(":"), text) and _piece_in_text(words[1], text)
    return False
    for piece in re.split(r"\.\.\.|…", evidence):  # model shortened a quote with "..."
        ev_tokens, tokens = _norm_tokens(piece), _norm_tokens(text)
        if not ev_tokens:
            continue
        max_span = 2 * len(ev_tokens) + 5
        found = False
        for start in (i for i, t in enumerate(tokens) if t == ev_tokens[0]):
            j, pos = 1, start + 1
            while j < len(ev_tokens) and pos < len(tokens) and pos - start < max_span:
                if tokens[pos] == ev_tokens[j]:
                    j += 1
                pos += 1
            if j == len(ev_tokens):
                found = True
                break
        if not found:
            return False
    return True


DATE_FIELDS = {"received_date", "deadline"}


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text))


def value_in_evidence(name: str, value, evidence: str) -> bool | None:
    """Does the quoted evidence actually contain the value? None = cannot tell (e.g. translated text)."""
    if isinstance(value, list):
        results = [value_in_evidence(name, v, evidence) for v in value]
        return None if None in results else all(results)
    tokens = set(_norm_tokens(evidence))
    if name in DATE_FIELDS:  # "2026-05-15" is written as "Friday 15 May": look for the day number
        m = re.fullmatch(r"\d{4}-\d{2}-(\d{2})", str(value))
        return m is None or str(int(m.group(1))) in tokens or m.group(1) in tokens
    if isinstance(value, (int, float)):
        n = int(value) if float(value).is_integer() else value
        return str(n) in tokens or f"{float(n)}" in tokens
    flat = lambda s: re.sub(r"[^0-9a-z一-鿿]", "", str(s).lower())
    if flat(value) and flat(value) in flat(evidence):
        return True
    if _has_cjk(evidence) and not _has_cjk(str(value)):
        return None  # the model may have translated, e.g. 铜 -> bronze
    return False


def _links_to_email_text(value, evidence: str, text: str) -> bool:
    """A value taken from elsewhere in the email and linked through the evidence, e.g. the text says
    "drawing D2365" and the value is the attachment "D2365 REV-1.pdf". Text values only, never numbers."""
    if not isinstance(value, str) or len(value) < 4:
        return False
    flat = lambda s: re.sub(r"[^0-9a-z]", "", s.lower())
    if flat(value) not in flat(text):
        return False
    shared = set(re.findall(r"[a-z0-9]{3,}", value.lower())) & set(re.findall(r"[a-z0-9]{3,}", evidence.lower()))
    return any(re.search(r"\d", t) for t in shared)  # share a code like d2365, not just a common word


def _verify(name: str, f: Field, email: Email) -> None:
    """Downgrade a field's status if the claim does not hold up. Changes the field in place."""
    if f.status in (Status.FOUND, Status.NEEDS_REVIEW) and (
            f.value in (None, "", []) or (isinstance(f.value, str) and f.value in {s.value for s in Status})):  # status word put into value
        f.status, f.value, f.evidence = Status.MISSING, None, None
        return
    if f.status not in (Status.FOUND, Status.NEEDS_REVIEW) or name in NO_EVIDENCE_NEEDED:
        return
    if not f.evidence:
        f.status, f.note = Status.NEEDS_REVIEW, "no evidence given by extractor"
        return
    if not evidence_in_text(f.evidence, email.text):
        f.status, f.note = Status.NEEDS_REVIEW, "evidence not found in the email text: possibly invented"
        return
    supported = value_in_evidence(name, f.value, f.evidence)
    if supported is False and _links_to_email_text(f.value, f.evidence, email.text):
        supported = True
    if supported is False:
        # The quoted text is real but does not contain the value: the model filled it in itself.
        f.status, f.note = Status.MISSING, f"model suggested {f.value!r}, but the quoted text does not say so"
        f.value, f.evidence = None, None
    elif supported is None:
        f.status, f.note = Status.NEEDS_REVIEW, f.note or "value is a translation or reading of the text: confirm"


def _to_number(value):
    if isinstance(value, (int, float)):
        return value
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*", str(value))
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    return int(n) if n.is_integer() else n


def check(extraction: Extraction, email: Email) -> CheckResult:
    ex = extraction.model_copy(deep=True).complete()
    result = CheckResult(email=email, extraction=ex)
    add = result.issues.append

    for name, f in ex.header.items():
        _verify(name, f, email)
    for item in ex.items:
        for name, f in item.items():
            _verify(name, f, email)

    # Header: defaults and informational gaps.
    for name, default in DEFAULTS.items():
        f = ex.header[name]
        if f.status == Status.MISSING:
            ex.header[name] = Field(value=default, status=Status.INFERRED, note="YC default terms (assumption)")
            add(Issue("header", name, "assumption", f"Not stated by customer; using {default}. State this on the quote."))
    if ex.header["deadline"].status == Status.MISSING:
        add(Issue("header", "deadline", "info", "No deadline given. Do not assume one; ask if it matters."))
    for name, f in ex.header.items():
        if f.status == Status.NEEDS_REVIEW:
            add(Issue("header", name, "check", f"Check value {f.value!r}: {f.note or 'flagged by extractor'}"))

    if not ex.items:
        add(Issue("header", "items", "blocking", "No parts found in the email."))

    specs = ex.header["specifications"].value if ex.header["specifications"].present else None
    zips = [a for a in email.attachments if a.lower().endswith((".zip", ".rar", ".7z"))]

    for n, item in enumerate(ex.items, 1):
        pn = item["part_number"].value
        where = f"line {n} ({pn})" if pn else f"line {n}"

        # Quantity: must be a number; units like SET need a pieces count.
        q = item["quantity"]
        if q.present:
            num = _to_number(q.value)
            if num is None:
                q.status, q.note = Status.NEEDS_REVIEW, f"quantity {q.value!r} is not a number"
            else:
                q.value = num
                unit = str(item["unit"].value or "").upper().strip()
                ppu = _to_number(item["pieces_per_unit"].value) if item["pieces_per_unit"].present else None
                if ppu:
                    add(Issue(where, "quantity", "check",
                              f"{num} {unit or 'units'} x {ppu} pieces = {num * ppu} pieces. Confirm which count to price."))
                elif unit and unit not in PIECE_UNITS:
                    add(Issue(where, "quantity", "check", f"Unit is {unit}: how many pieces per {unit}?"))

        for name in BLOCKING_LINE_FIELDS:
            f = item[name]
            if f.status == Status.MISSING:
                hint = ""
                if name == "material" and specs:
                    hint = f" May be defined by spec {', '.join(map(str, specs))}: check the spec and archive first."
                if name == "quantity" and zips:
                    hint = " May be inside the attached archive files: check them before asking."
                add(Issue(where, name, "blocking", f"Missing.{hint}"))

        for name, f in item.items():
            if f.status == Status.NEEDS_REVIEW:
                add(Issue(where, name, "check", f"Check value {f.value!r}: {f.note or 'flagged by extractor'}"))

    return result


QUESTIONS = {
    "part_number": "the part number for {parts}",
    "quantity": "the required quantity for {parts}",
    "material": "the material grade for {parts}",
    "drawing_ref": "the drawing for {parts}",
}


def draft_client_email(result: CheckResult) -> str | None:
    """Draft a reply asking the customer for missing information. A person reviews and sends it."""
    missing: dict[str, list[str]] = {}
    for i in result.issues:
        if i.severity == "blocking" and i.field in QUESTIONS:
            missing.setdefault(i.field, []).append(i.where.split("(")[-1].rstrip(")") if "(" in i.where else i.where)
    if not missing:
        return None

    total = len(result.extraction.items)
    lines = []
    for name, parts in missing.items():
        which = "all items" if len(parts) == total and total > 1 else ", ".join(parts)
        lines.append("- " + QUESTIONS[name].format(parts=which))
    if result.extraction.header["deadline"].status == Status.MISSING:
        lines.append("- by when you would like to receive our quotation")

    contact = result.extraction.header["contact"].value or "Sir or Madam"
    subject = result.email.headers.get("subject", "your inquiry")
    return (
        f"Subject: RE: {subject}\n\n"
        f"Dear {contact},\n\n"
        "Thank you for your inquiry. To prepare an accurate quotation, could you please confirm:\n"
        + "\n".join(lines)
        + "\n\nBest regards,\n[YC sales]"
    )
