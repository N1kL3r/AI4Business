"""Tests for matching new parts against past quotes. Run with: python -m pytest tests"""
from quotetool.matching import match_items
from quotetool.schema import Field, Status

HISTORY = [
    {"part_number": "G42D2365", "description": "OUTER BUSH ECCENTRIC", "price": 420},
    {"part_number": "X99Z0001", "description": "VALVE HOUSING", "price": 150},
]


def item(part_number, description):
    return {"part_number": Field(value=part_number, status=Status.FOUND),
            "description": Field(value=description, status=Status.FOUND)}


def test_exact_match_ignores_case_and_spaces():
    [it] = match_items([item(" g42d2365 ", "anything")], HISTORY)
    assert it["match_tier"].value == "exact"
    assert it["reference_price"].value == 420


def test_similar_description_needs_review():
    [it] = match_items([item("NEW-1", "OUTER BUSH ECCENTRIC")], HISTORY)
    assert it["match_tier"].value == "similar"
    assert it["reference_price"].status == Status.NEEDS_REVIEW
    assert it["matched_part_number"].value == "G42D2365"


def test_nothing_close_gives_no_price():
    [it] = match_items([item("NEW-2", "GEAR WHEEL")], HISTORY)
    assert it["match_tier"].value == "none"
    assert it["reference_price"].value is None


def test_missing_part_number_and_description():
    [it] = match_items([item(None, None)], HISTORY)
    assert it["match_tier"].value == "none"


def test_empty_or_unusable_history():
    for history in ([], [{"part_number": "A1"}], [{"part_number": "A1", "description": "", "price": 5}]):
        [it] = match_items([item("B2", "VALVE")], history)
        assert it["match_tier"].value == "none"
    [it] = match_items([item("A1", "")], [{"part_number": "A1", "description": "", "price": 5}])
    assert it["match_tier"].value == "exact"


def test_load_history(tmp_path):
    from quotetool.history import load_history
    f = tmp_path / "h.csv"
    f.write_text("Part_Number,Description,Price,extra\n A1 ,RING,10,x\n,NOPART,5,x\nB2,SLEEVE,abc,x\nC3,,7.5,x\n")
    rows = load_history(f)
    assert [(r["part_number"], r["description"], r["price"], r["source_row"]) for r in rows] == \
        [("A1", "RING", 10.0, 2), ("C3", "", 7.5, 5)]
    assert rows[0]["quote_id"] == "" and rows[0]["currency"] == ""  # optional columns default to empty
    f.write_text("part_number,description\nA1,RING\n")
    try:
        load_history(f)
    except ValueError as e:
        assert "price" in str(e)
    else:
        raise AssertionError("missing column not reported")


def test_exact_lists_every_past_quote_newest_first():
    from quotetool.matching import match_issues
    history = [{"part_number": "A1", "description": "RING", "price": 10, "quoted_date": "2024-01-01", "quote_id": "Q1"},
               {"part_number": "A1", "description": "RING", "price": 12, "quoted_date": "2025-06-01", "quote_id": "Q2"}]
    items = match_items([item("A1", "RING")], history)
    assert [q["quote_id"] for q in items[0]["past_quotes"].value] == ["Q2", "Q1"]
    assert items[0]["reference_price"].value == 12  # the latest
    [issue] = match_issues(items)
    assert "2 time(s)" in issue.message and "Q2" in issue.message and issue.severity == "info"


def test_similar_issue_is_a_check_and_names_the_source():
    from quotetool.matching import match_issues
    history = [{"part_number": "A1", "description": "OUTER BUSH ECCENTRIC", "price": 10, "quote_id": "Q9"}]
    [issue] = match_issues(match_items([item("B2", "OUTER BUSH ECCENTRIC")], history))
    assert issue.severity == "check" and "Q9" in issue.message
