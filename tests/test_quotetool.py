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
        status_code, text = 200, ""

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
    assert ex.items[0]["quantity"].value == 10 and ex.extractor == config.name

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not cached")))
    assert extract.extract_llm(EMAIL, config, cache_dir=tmp_path).items[0]["part_number"].value == "XY-7A"


def test_value_not_in_quoted_evidence_becomes_missing():
    """Real failure from a qwen2.5:7b run: quantity 1 and unit EA 'found', quoting a line with no quantity."""
    line = "XY-7A  RING  SET  10  C95510"
    ex = parse_reply(reply(quantity=field(1, evidence=line), unit=field("EA", evidence=line),
                           material=field("needs_review", "needs_review", evidence="RING")))
    result = check(ex, EMAIL)
    item = result.extraction.items[0]
    assert item["quantity"].status == Status.MISSING and "suggested 1" in item["quantity"].note
    assert item["unit"].status == Status.MISSING
    assert item["material"].status == Status.MISSING  # status word written into value
    assert not result.ready_to_quote


def test_dates_and_translations_are_not_rejected():
    from quotetool.checks import value_in_evidence
    assert value_in_evidence("deadline", "2026-05-15", "by EOB Friday 15 May")
    assert value_in_evidence("material", "bronze", "附件是泵用的铜密封件") is None  # cannot tell: review
    assert value_in_evidence("quantity", 144, "SET  144")
    assert not value_in_evidence("quantity", 1, "4P100346      RNG/LANTERN/4.00")


def test_thinking_is_switched_off_and_stripped(monkeypatch):
    from quotetool import llm

    calls = []

    class Resp:
        def __init__(self, status, body):
            self.status_code, self._body, self.text = status, body, json.dumps(body)

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def fake_post(url, json=None, timeout=None, **kw):
        calls.append(dict(json))
        if "think" in json:  # simulate a model without a thinking switch
            return Resp(400, {"error": "model does not support thinking"})
        return Resp(200, {"message": {"content": "<think>hmm {not json}</think>\n{\"ok\": 1}"}})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    out = llm.complete(llm.LLMConfig(), "s", "u")
    assert calls[0]["think"] is False and "think" not in calls[1]
    assert out == '{"ok": 1}'
