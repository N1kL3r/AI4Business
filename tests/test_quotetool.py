"""Tests that need no sample data and no LLM. Run with: python -m pytest tests"""
import json

from quotetool.checks import check, evidence_in_text
from quotetool.emails import Email
from quotetool.evaluate import score, summary
from quotetool.extract import output_schema, parse_reply
from quotetool.schema import Status

EMAIL = Email(
    case_id="t",
    text="From: A.B. <[Customer X]>\nDate: 1 March 2026\nSubject: RFQ 1\nAttachments: 7A.pdf\n\n"
         "Please quote USD.\nXY-7A  RING  SET  10  C95510\n            (ONE SET = 2 PC)",
    headers={"from": "A.B. <[Customer X]>", "subject": "RFQ 1", "attachments": "7A.pdf"},
)


def field(value, status="found", evidence=None):
    return {"value": value, "status": status, "evidence": evidence, "note": None}


def reply(**items):
    return json.dumps({
        "header": {"currency": field("USD", evidence="quote USD"), "deadline": field(None, "missing")},
        "items": [{"part_number": field("XY-7A", evidence="XY-7A"), **items}],
    })


def test_evidence_matching_tolerates_spacing_and_gaps():
    assert evidence_in_text("SET 10", EMAIL.text)
    assert evidence_in_text("RING SET 10 C95510 ONE SET = 2 PC", EMAIL.text)  # spans a wrapped table row
    assert not evidence_in_text("quantity 500 pieces", EMAIL.text)


def test_parse_reply_accepts_fenced_json_and_bare_values():
    ex = parse_reply("```json\n" + json.dumps({"header": {"currency": "USD"}, "items": []}) + "\n```")
    assert ex.header["currency"].value == "USD"
    assert ex.header["deadline"].status == Status.MISSING  # filled in by complete()


def test_invented_evidence_is_downgraded():
    ex = parse_reply(reply(quantity=field(500, evidence="500 pcs")))
    q = check(ex, EMAIL).extraction.items[0]["quantity"]
    assert q.status == Status.NEEDS_REVIEW


def test_missing_blocking_fields_and_defaults():
    ex = parse_reply(reply(quantity=field(10, evidence="SET 10"), unit=field("SET", evidence="SET"),
                           pieces_per_unit=field(2, evidence="ONE SET = 2 PC")))
    result = check(ex, EMAIL)
    blocking = {i.field for i in result.issues if i.severity == "blocking"}
    assert blocking == {"material", "drawing_ref"}
    assert result.extraction.header["incoterm"].status == Status.INFERRED
    assert any("20 pieces" in i.message for i in result.issues)
    assert "material grade" in result.client_email and "by when" in result.client_email


def test_score_counts_gaps_and_invented_lines():
    ex = parse_reply(json.dumps({"header": {"deadline": field("2026-03-05", evidence="x")},
                                 "items": [{"part_number": field("XY-7A")}, {"part_number": field("ZZ-1")}]}))
    key = {"header": {"deadline": None, "currency": None}, "items": [{"part_number": "XY-7A", "quantity": None}]}
    s = score(ex, key, "t")
    assert set(s["outcome"]) == {"invented", "correct (missing)", "correct"}
    assert summary(s).loc["t", "invented"] == 2  # made-up deadline + made-up line


def test_output_schema_lists_every_field():
    schema = output_schema()
    assert "deadline" in schema["properties"]["header"]["required"]
    assert "pieces_per_unit" in schema["properties"]["items"]["items"]["required"]


def test_extract_llm_round_trip_with_simulated_ollama(monkeypatch, tmp_path):
    """Checks the request/response plumbing and the cache, not model quality."""
    from quotetool import extract, llm

    sent = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": reply(quantity=field(10, evidence="SET 10"))}}

    def fake_post(url, json=None, timeout=None, **kw):
        sent.update(url=url, payload=json)
        return FakeResponse()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    config = llm.LLMConfig()
    ex = extract.extract_llm(EMAIL, config, cache_dir=tmp_path)
    assert sent["url"].endswith("/api/chat") and sent["payload"]["format"]["required"] == ["header", "items"]
    assert ex.items[0]["quantity"].value == 10 and ex.extractor == "ollama:qwen2.5:7b"

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not cached")))
    assert extract.extract_llm(EMAIL, config, cache_dir=tmp_path).items[0]["part_number"].value == "XY-7A"
