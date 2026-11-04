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
