"""The quote template: which fields we want from an inquiry, and how sure we are of each one.

Every field carries a status, so "not in the email" is a result we can show,
not a gap we silently fill with a guess.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field as PydField


class Status(str, Enum):
    FOUND = "found"                # stated in the email, with evidence
    MISSING = "missing"            # not in the email; value stays empty
    INFERRED = "inferred"          # filled from elsewhere (default, archive), source in `note`
    NEEDS_REVIEW = "needs_review"  # ambiguous, conflicting or unverifiable: a person must check


class Field(BaseModel):
    value: Any = None
    status: Status = Status.MISSING
    evidence: str | None = None  # exact text copied from the email
    note: str | None = None

    @property
    def present(self) -> bool:
        """True if the email itself supplied a value (inferred values do not count)."""
        return self.value not in (None, "", []) and self.status in (Status.FOUND, Status.NEEDS_REVIEW)


# Field name -> description. The descriptions are shown to the LLM, so they double as instructions.
HEADER_FIELDS: dict[str, str] = {
    "customer": "Customer company name as written (masked names like 'Customer T' are fine).",
    "contact": "Name or initials of the person who sent the inquiry.",
    "received_date": "Date the email was sent, as YYYY-MM-DD.",
    "deadline": "Date by which the customer wants the quote, as YYYY-MM-DD. Only if an actual date is given; "
                "words like 'urgent' or 'asap' are NOT a deadline.",
    "urgency": "One of: low, normal, high. 'urgent', 'asap', short deadlines mean high.",
    "currency": "Currency the customer wants the price in (e.g. USD, EUR, RMB).",
    "incoterm": "Trade term requested (e.g. FOB, CIF, EXW, DAP).",
    "specifications": "List of specification or standard documents the parts must meet (company spec numbers, "
                      "AMS/ASTM/DIN numbers). Machine or series codes are NOT specifications.",
    "language": "Language of the email body, as a code: en, zh, de, ...",
}

LINE_FIELDS: dict[str, str] = {
    "part_number": "The customer's part number / item code for this line.",
    "description": "Part description as written (keep abbreviations). In tables the description can wrap onto "
                   "the next lines: join those parts.",
    "quantity": "Number ordered, as a number, in the unit the customer uses.",
    "unit": "Unit of the quantity, e.g. EA, PC, SET.",
    "pieces_per_unit": "If the text says one unit equals several pieces (e.g. one set = 2 pieces), that number.",
    "material": "Material or alloy grade the customer asks for on this line, exactly as written. Generic words "
                "like 'bronze' count, but use status needs_review. If no material is written, it is missing.",
    "material_alternatives": "List of other materials the customer says are acceptable substitutes.",
    "drawing_ref": "Drawing number or attachment file name that belongs to this line.",
    "machine_model": "Machine model, pump series or equipment code the part belongs to.",
}


class Extraction(BaseModel):
    """A filled quote template for one inquiry email."""

    header: dict[str, Field] = PydField(default_factory=dict)
    items: list[dict[str, Field]] = PydField(default_factory=list)
    extractor: str = ""  # which extractor produced this (e.g. "baseline (rules)", "ollama:qwen3.5:9b")

    def complete(self) -> "Extraction":
        """Make sure every template field exists; anything the extractor skipped counts as missing."""
        for name in HEADER_FIELDS:
            self.header.setdefault(name, Field(note="not found by extractor"))
        for item in self.items:
            for name in LINE_FIELDS:
                item.setdefault(name, Field(note="not found by extractor"))
        return self
