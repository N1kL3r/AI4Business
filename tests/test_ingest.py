import io
import zipfile

from quotetool.ingest import clean, ingest, looks_like_chat

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


def test_plain_text_with_odd_encodings():
    assert ingest([("a.txt", "Qty 3 é".encode("cp1252"))], "c").email.text == "Qty 3 é"
    assert ingest([("a.txt", "Qty 3 é".encode("utf-16"))], "c").email.text == "Qty 3 é"


def test_whatsapp_chat_is_recognised_and_cleaned():
    chat = "[12/05/2026, 10:14:02] Anna: Hi\n[12/05/2026, 10:15:10] Anna: 50 pcs‎ G42D2365\n[12/05/2026, 10:16:00] Bob: ok\n"
    assert looks_like_chat(chat)
    got = ingest([("chat.txt", chat.encode())], "c")
    assert "chat log" in got.sources[0] and "‎" not in got.email.text


def test_word_document_and_zip():
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("order.docx", make_docx("Qty 144"))
        z.writestr("__MACOSX/._order.docx", b"junk")
    got = ingest([("pack.zip", inner.getvalue())], "c")
    assert "Qty 144" in got.email.text and not got.warnings


def test_eml_attachment_text_is_included():
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"], msg["Subject"] = "a@b.c", "RFQ"
    msg.set_content("See attached order.")
    msg.add_attachment(make_docx("Quantity 144 sets"), maintype="application", subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename="order.docx")
    got = ingest([("rfq.eml", msg.as_bytes())], "c")
    assert "Quantity 144 sets" in got.email.text and got.email.headers["subject"] == "RFQ"


def test_unreadable_files_warn_instead_of_failing():
    got = ingest([("scan.png", b"\x89PNG"), ("broken.docx", b"junk"), ("ok.txt", b"hello")], "c")
    assert got.email.text == "hello" and len(got.warnings) == 2


def test_several_files_are_labelled_and_header_kept_on_top():
    eml = b"From: a@b.c\nSubject: RFQ\n\nPlease quote."
    got = ingest([("rfq.txt", eml), ("sheet.txt", b"Qty 5")], "c")
    assert got.email.headers.get("subject") == "RFQ" and "Qty 5" in got.email.text


def test_clean_removes_invisible_characters():
    assert clean("a‎b c\r\n") == "ab c"


def test_customer_price_and_quote_document():
    import io as _io
    from docx import Document
    import quotetool as qt
    from quotetool.emails import parse_email_text
    from quotetool.matching import match_customer, same_customer
    from quotetool.quotedoc import build_quote
    from quotetool.schema import Extraction, Field, Status

    assert same_customer("Customer T", "customer t (Australia)") and not same_customer("Customer T", "Customer K")
    hist = [{"part_number": "P1", "description": "x", "price": 100, "customer": "Customer T", "quoted_date": "2025-01-01", "source_row": 2},
            {"part_number": "P1", "description": "x", "price": 120, "customer": "Customer T", "quoted_date": "2026-01-01", "source_row": 3},
            {"part_number": "P1", "description": "x", "price": 90, "customer": "Customer K", "quoted_date": "2026-06-01", "source_row": 4}]
    f = lambda v: Field(value=v, status=Status.FOUND, evidence=str(v))
    ex = Extraction(header={"customer": f("Customer T"), "currency": f("USD")},
                    items=[{"part_number": f("P1"), "quantity": f(10), "description": f("Bush"), "material": f("C93200")}]).complete()
    match_customer(ex.items, hist, "Customer T")
    assert ex.items[0]["customer_price"].value == 120  # newest, and not Customer K's 90
    result = qt.check(ex, parse_email_text("Hello", "c"))
    doc = Document(_io.BytesIO(build_quote(result, [120.0])))
    assert "1,200.00" in "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
