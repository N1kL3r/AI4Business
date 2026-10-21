"""Email -> filled quote template, using a language model as the first reader of the email."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import llm
from .emails import Email
from .schema import HEADER_FIELDS, LINE_FIELDS, Extraction, Field, Status

SYSTEM_PROMPT = """You read customer inquiry emails (requests for quotation) for a foundry and machining \
company that makes custom bronze and copper-alloy parts to drawing. You fill in a quote template.

Rules:
- Use ONLY information in the email. Never guess or fill in typical values.
- For every field return: value, status, evidence, note.
  - status "found": the email states it. "evidence" must be an exact, short copy of the email text it came from.
  - status "missing": the email does not state it. value and evidence are null.
  - status "needs_review": the email says something relevant but it is ambiguous, generic or conflicting.
    Give your best reading as value, the text as evidence, and explain in note.
- Never fill in a default. If no quantity is written, quantity is missing: do NOT assume 1.
  If no unit is written, unit is missing: do NOT assume EA. If no material is written, material is missing.
- The value must be in the evidence you quote (dates and translations excepted).
- "value" holds the data only. Never write a status word such as "missing" or "needs_review" into value.
- Make one line item per part the customer asks for.
- Quantities: if the text says one unit equals several pieces (e.g. "one set = 2 pc"), put that number in
  pieces_per_unit. Keep quantity in the customer's own unit.
- Long material paragraphs may be background information. Put the grade the customer asks for in material,
  and grades they say are acceptable substitutes in material_alternatives.
- Drawings can be linked through drawing numbers in the text or through attachment file names.
- The email may be in any language; keep part numbers and codes exactly as written.
- Dates as YYYY-MM-DD. If the year is not written, use the year of the email date."""


def _field_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "value": {"anyOf": [{"type": "string"}, {"type": "number"},
                                {"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
            "status": {"type": "string", "enum": ["found", "missing", "needs_review"]},
            "evidence": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["value", "status", "evidence"],
    }


def output_schema() -> dict:
    """JSON schema of the answer we want back; local models are constrained to it."""
    f = _field_schema()
    return {
        "type": "object",
        "properties": {
            "header": {"type": "object", "properties": {k: f for k in HEADER_FIELDS}, "required": list(HEADER_FIELDS)},
            "items": {"type": "array", "items": {"type": "object", "properties": {k: f for k in LINE_FIELDS},
                                                 "required": list(LINE_FIELDS)}},
        },
        "required": ["header", "items"],
    }


def build_user_prompt(email: Email) -> str:
    header_desc = "\n".join(f"- {k}: {v}" for k, v in HEADER_FIELDS.items())
    line_desc = "\n".join(f"- {k}: {v}" for k, v in LINE_FIELDS.items())
    return (
        "Fill in the quote template for the email below.\n\n"
        f"Header fields (once per email):\n{header_desc}\n\n"
        f"Line item fields (once per part):\n{line_desc}\n\n"
        'Answer with JSON: {"header": {field: {value, status, evidence, note}}, '
        '"items": [{field: {value, status, evidence, note}}, ...]}\n\n'
        f"=== EMAIL ===\n{email.text}\n=== END EMAIL ==="
    )


def parse_reply(text: str, extractor: str = "") -> Extraction:
    """Turn the model's reply into an Extraction, tolerating small format slips."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)  # model wrapped the JSON in prose or ``` fences
        if not match:
            raise ValueError(f"No JSON found in model reply: {text[:200]!r}")
        data = json.loads(match.group(0))

    def to_field(raw) -> Field:
        if isinstance(raw, dict) and ("value" in raw or "status" in raw):
            status = raw.get("status")
            if status not in {s.value for s in Status}:
                status = Status.NEEDS_REVIEW
            return Field(value=raw.get("value"), status=status, evidence=raw.get("evidence"), note=raw.get("note"))
        # Model returned a bare value: accept it, but without evidence the checks will flag it.
        return Field(value=raw, status=Status.FOUND if raw not in (None, "", []) else Status.MISSING)

    header = {k: to_field(v) for k, v in (data.get("header") or {}).items() if k in HEADER_FIELDS}
    items = [{k: to_field(v) for k, v in item.items() if k in LINE_FIELDS}
             for item in (data.get("items") or []) if isinstance(item, dict)]
    return Extraction(header=header, items=items, extractor=extractor).complete()


def extract_llm(email: Email, config: llm.LLMConfig, cache_dir: str | Path | None = None,
                refresh: bool = False) -> Extraction:
    """Ask the model to fill the template. Replies are cached so notebooks re-run without the model."""
    cache = None
    if cache_dir is not None:
        safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", config.name)
        cache = Path(cache_dir) / f"{email.case_id}.{safe_model}.json"
        if cache.exists() and not refresh:
            return parse_reply(cache.read_text(encoding="utf-8"), extractor=config.name)

    reply = llm.complete(config, SYSTEM_PROMPT, build_user_prompt(email), json_schema=output_schema())
    extraction = parse_reply(reply, extractor=config.name)  # parse before caching: never cache a broken reply
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(reply, encoding="utf-8")
    return extraction
