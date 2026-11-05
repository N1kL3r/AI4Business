"""Write the quotation as an editable Word file for the manager to review, change and sign.

The layout is a sensible default; replace it with the firm's own template once we have a sample quotation.
"""
from __future__ import annotations

import io
from datetime import date

from .checks import CheckResult
from .schema import Status


def _text(f) -> str:
    return "" if f.value in (None, "", []) else (", ".join(map(str, f.value)) if isinstance(f.value, list) else str(f.value))


def _money(value) -> str:
    return f"{value:,.2f}"


def build_quote(result: CheckResult, prices: list[float | None], company: str = "[Company name]") -> bytes:
    """`prices` is the unit price per line, in the same order as the items; None leaves the cell empty."""
    try:  # imported here so the rest of the app still works when python-docx is not installed
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor
    except ImportError:
        raise RuntimeError("Writing Word files needs the 'python-docx' package (pip install python-docx)")
    NAVY = RGBColor(0x16, 0x32, 0x4F)
    ex, header = result.extraction, result.extraction.header
    currency = _text(header["currency"]) or "USD"
    doc = Document()
    doc.styles["Normal"].font.name, doc.styles["Normal"].font.size = "Calibri", Pt(10)

    title = doc.add_paragraph()
    run = title.add_run(company.upper())
    run.bold, run.font.size, run.font.color.rgb = True, Pt(11), NAVY
    run = doc.add_paragraph().add_run("QUOTATION")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(22), NAVY

    meta = doc.add_table(rows=0, cols=2)
    for k, v in [("Date", date.today().isoformat()), ("Quotation no.", "[to be assigned]"),
                 ("Customer", _text(header["customer"])), ("Attention", _text(header["contact"])),
                 ("Your reference", result.email.headers.get("subject", "")),
                 ("Required by", _text(header["deadline"]))]:
        if v:
            cells = meta.add_row().cells
            cells[0].text, cells[1].text = k, v
            cells[0].paragraphs[0].runs[0].bold = True

    doc.add_paragraph()
    cols = ["No.", "Part number", "Description", "Material", "Qty", "Unit", f"Unit price ({currency})", f"Total ({currency})"]
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Light Grid Accent 1"
    for c, name in zip(table.rows[0].cells, cols):
        c.text = name
    grand, complete = 0.0, True
    for n, (item, price) in enumerate(zip(ex.items, prices), 1):
        qty = item["quantity"].value
        total = price * qty if price is not None and isinstance(qty, (int, float)) else None
        if total is None:
            complete = False
        else:
            grand += total
        unit = _text(item["unit"]) + (f" ({_text(item['pieces_per_unit'])} pcs)" if _text(item["pieces_per_unit"]) else "")
        row = table.add_row().cells
        for c, v in zip(row, [str(n), _text(item["part_number"]), _text(item["description"]), _text(item["material"]),
                              _text(item["quantity"]), unit, "" if price is None else _money(price),
                              "" if total is None else _money(total)]):
            c.text = v
        for c in row[4:]:
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if complete and ex.items:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.add_run(f"Total: {currency} {_money(grand)}").bold = True

    doc.add_paragraph()
    doc.add_paragraph().add_run("Terms").bold = True
    terms = [f"Currency: {currency}", f"Delivery terms: {_text(header['incoterm'])}",
             "Lead time: [to be confirmed]", "Validity: [30] days from the date above"]
    specs = _text(header["specifications"])
    if specs:
        terms.append(f"Specification: {specs}")
    for t in terms:
        doc.add_paragraph(t, style="List Bullet")

    assumed = [f"{k.replace('_', ' ').capitalize()}: {_text(f)} (not stated by the customer)"
               for k, f in header.items() if f.status == Status.INFERRED]
    assumed += [i.message for i in result.issues if i.severity == "assumption" and i.field not in header]
    if assumed:
        doc.add_paragraph().add_run("Assumptions").bold = True
        for a in assumed:
            doc.add_paragraph(a, style="List Bullet")

    doc.add_paragraph()
    doc.add_paragraph("Approved by: ______________________    Name: ______________________    Date: ______________")
    note = doc.add_paragraph("Draft prepared by the Quote Assistant. Not valid until reviewed and signed by an authorised person.")
    note.runs[0].italic, note.runs[0].font.size = True, Pt(8)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
