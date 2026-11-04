"""Compare a new inquiry's parts against a history of past quotes.

Three possible outcomes per part, in order of confidence:
  - exact: the part number matches a past quote exactly
  - similar: no exact match, but the description is close to something
    quoted before (found with TF-IDF text similarity). A different part, so a person must check it.
  - none: nothing close enough was found -- we say so, we never guess a price
"""
from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .schema import Field, Status

# How similar a description must be (0 to 1) before we offer it as "similar".
# Tune this once real history data is loaded.
SIMILARITY_THRESHOLD = 0.5


def _normalize(part_number) -> str:
    return str(part_number or "").strip().upper()


def _set_none(item: dict, note: str) -> None:
    item["match_tier"] = Field(value="none", status=Status.INFERRED, note=note)
    item["matched_part_number"] = Field(status=Status.MISSING)
    item["reference_price"] = Field(status=Status.MISSING)


def match_items(items: list[dict], history: list[dict]) -> list[dict]:
    """Add reference_price, matched_part_number and match_tier to every item,
    by comparing it against a list of past quotes (the "history").

    Each entry in `history` should look like:
        {"part_number": "G42D2365", "description": "OUTER BUSH ECCENTRIC", "price": 420}
    Entries without a part number or price are ignored.
    """
    history = [h for h in history if h.get("part_number") and h.get("price") is not None]
    if not history:
        for item in items:
            _set_none(item, "no history available")
        return items

    # Descriptions can only be compared if the history has usable words in them.
    vectorizer, history_vectors = TfidfVectorizer(), None
    try:
        history_vectors = vectorizer.fit_transform([h.get("description") or "" for h in history])
    except ValueError:  # empty vocabulary: no entry has any usable description
        pass

    for item in items:
        part_number = _normalize(item["part_number"].value)
        description = item["description"].value or ""

        # Tier 1: exact part number match
        exact = next((h for h in history if _normalize(h["part_number"]) == part_number), None) if part_number else None
        if exact is not None:
            item["match_tier"] = Field(value="exact", status=Status.INFERRED,
                                       note="same part number as a past quote")
            item["matched_part_number"] = Field(value=exact["part_number"], status=Status.INFERRED)
            item["reference_price"] = Field(value=exact["price"], status=Status.INFERRED,
                                            note="price from the matched past quote")
            continue

        # Tier 2: similar description (TF-IDF cosine similarity)
        best_score, best_index = 0.0, None
        if description and history_vectors is not None:
            scores = cosine_similarity(vectorizer.transform([description]), history_vectors)[0]
            best_index = int(scores.argmax())
            best_score = float(scores[best_index])

        if best_index is not None and best_score >= SIMILARITY_THRESHOLD:
            best_match = history[best_index]
            note = f"description similarity {best_score:.2f}; a different part, check before using"
            item["match_tier"] = Field(value="similar", status=Status.NEEDS_REVIEW, note=note)
            item["matched_part_number"] = Field(value=best_match["part_number"], status=Status.NEEDS_REVIEW, note=note)
            item["reference_price"] = Field(value=best_match["price"], status=Status.NEEDS_REVIEW,
                                            note="price of the closest similar past quote, not of this part")
        else:
            # Tier 3: nothing close enough -- say so, never invent a number
            _set_none(item, f"no past quote close enough (best score {best_score:.2f})")

    return items
