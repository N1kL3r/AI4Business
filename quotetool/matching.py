"""Compare a new inquiry's parts against a history of past quotes.

Three possible outcomes per part, in order of confidence:
  - exact: the part number matches a past quote exactly
  - similar: no exact match, but the description is close to something
    quoted before (found with TF-IDF text similarity)
  - none: nothing close enough was found -- we say so, we never guess a price
"""
from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .schema import Field, Status

# How similar a description must be (0 to 1) before we trust it as "similar".
# Tune this once real history data is loaded; 0.3 is a starting guess.
SIMILARITY_THRESHOLD = 0.3


def match_items(items: list[dict], history: list[dict]) -> list[dict]:
    """Add reference_price, matched_part_number and match_tier to every item,
    by comparing it against a list of past quotes (the "history").

    Each entry in `history` should look like:
        {"part_number": "G42D2365", "description": "OUTER BUSH ECCENTRIC", "price": 420}
    """
    if not history:
        for item in items:
            item["match_tier"] = Field(value="none", status=Status.INFERRED, note="no history available")
            item["matched_part_number"] = Field(status=Status.MISSING)
            item["reference_price"] = Field(status=Status.MISSING)
        return items

    history_descriptions = [h["description"] for h in history]
    vectorizer = TfidfVectorizer()
    history_vectors = vectorizer.fit_transform(history_descriptions)

    for item in items:
        part_number = item["part_number"].value
        description = item["description"].value or ""

        # Tier 1: exact part number match
        exact = next((h for h in history if h["part_number"] == part_number), None)
        if exact is not None:
            item["match_tier"] = Field(value="exact", status=Status.INFERRED,
                                        note="same part number as a past quote")
            item["matched_part_number"] = Field(value=exact["part_number"], status=Status.INFERRED)
            item["reference_price"] = Field(value=exact["price"], status=Status.INFERRED,
                                             note="price from the matched past quote")
            continue

        # Tier 2: similar description (TF-IDF cosine similarity)
        best_score = 0.0
        best_index = None
        if description:
            query_vector = vectorizer.transform([description])
            scores = cosine_similarity(query_vector, history_vectors)[0]
            best_index = int(scores.argmax())
            best_score = float(scores[best_index])

        if description and best_score >= SIMILARITY_THRESHOLD:
            best_match = history[best_index]
            item["match_tier"] = Field(value="similar", status=Status.INFERRED,
                                        note=f"description similarity {best_score:.2f}")
            item["matched_part_number"] = Field(value=best_match["part_number"], status=Status.INFERRED)
            item["reference_price"] = Field(value=best_match["price"], status=Status.INFERRED,
                                             note="price from the closest similar past quote")
        else:
            # Tier 3: nothing close enough -- say so, never invent a number
            item["match_tier"] = Field(value="none", status=Status.INFERRED,
                                        note=f"no past quote close enough (best score {best_score:.2f})")
            item["matched_part_number"] = Field(status=Status.MISSING)
            item["reference_price"] = Field(status=Status.MISSING)

    return items
