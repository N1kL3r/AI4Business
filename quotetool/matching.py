"""Compare a new inquiry's parts against a history of past quotes.

Three possible outcomes per part, in order of confidence:
  - exact: the part number matches a past quote exactly (every past quote of that part is listed)
  - similar: no exact match, but the description is close to something quoted before (found with TF-IDF
    text similarity). A different part, so a person must check it.
  - none: nothing close enough was found -- we say so, we never guess a price

Each item also gets `past_quotes`: the past quotes behind the result, with their quote id, customer, date and
row in the history file, so every reference price can be traced back to where it came from.
"""
from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .checks import Issue
from .schema import Field, Status

# How similar a description must be (0 to 1) before we offer it as "similar".
# Tune this once real history data is loaded.
SIMILARITY_THRESHOLD = 0.5
MAX_SIMILAR = 3  # how many similar past quotes to list per part


def _normalize(part_number) -> str:
    return str(part_number or "").strip().upper()


def _set_none(item: dict, note: str) -> None:
    item["match_tier"] = Field(value="none", status=Status.INFERRED, note=note)
    item["matched_part_number"] = Field(status=Status.MISSING)
    item["reference_price"] = Field(status=Status.MISSING)
    item["past_quotes"] = Field(value=[], status=Status.MISSING)


def _newest(quote: dict) -> tuple:
    """Sort key that puts the newest quote first (ISO dates sort as text)."""
    d = quote.get("quoted_date") or ""
    return tuple(-ord(c) for c in d), -(quote.get("source_row") or 0)


def _money(quote: dict) -> str:
    return f"{quote['price']:g} {quote.get('currency') or ''}".strip()


def _origin(quote: dict) -> str:
    """Short human-readable pointer to the original quote."""
    parts = [quote.get("quote_id"), quote.get("customer"), quote.get("quoted_date")]
    return ", ".join(str(p) for p in parts if p) or f"row {quote.get('source_row', '?')}"


def match_items(items: list[dict], history: list[dict]) -> list[dict]:
    """Add reference_price, matched_part_number, match_tier and past_quotes to every item,
    by comparing it against a list of past quotes (the "history").

    Each entry in `history` should look like:
        {"part_number": "G42D2365", "description": "OUTER BUSH ECCENTRIC", "price": 420}
    plus, if known, currency, quoted_date, customer, quote_id, quantity and source_row (see history.py).
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

        # Tier 1: exact part number match. List every past quote of this part, newest first.
        exact = [h for h in history if part_number and _normalize(h["part_number"]) == part_number]
        if exact:
            exact.sort(key=lambda h: (h.get("quoted_date") or "", h.get("source_row") or 0), reverse=True)
            latest, prices = exact[0], [h["price"] for h in exact]
            note = f"latest of {len(exact)} past quotes ({min(prices):g} to {max(prices):g})" if len(exact) > 1 \
                else "price from the matched past quote"
            item["match_tier"] = Field(value="exact", status=Status.INFERRED,
                                       note="same part number as a past quote")
            item["matched_part_number"] = Field(value=latest["part_number"], status=Status.INFERRED)
            item["reference_price"] = Field(value=latest["price"], status=Status.INFERRED, note=note)
            item["past_quotes"] = Field(value=[{**h, "similarity": 1.0} for h in exact], status=Status.INFERRED)
            continue

        # Tier 2: similar description (TF-IDF cosine similarity)
        ranked = []
        if description and history_vectors is not None:
            scores = cosine_similarity(vectorizer.transform([description]), history_vectors)[0]
            ranked = sorted(((float(s), i) for i, s in enumerate(scores)), reverse=True)
        best_score = ranked[0][0] if ranked else 0.0

        if best_score >= SIMILARITY_THRESHOLD:
            similar, seen = [], set()  # best-scoring part first, each part once with its newest quote
            for s, i in sorted(ranked, key=lambda r: (-round(r[0], 6), _newest(history[r[1]]))):
                if s < SIMILARITY_THRESHOLD or len(similar) == MAX_SIMILAR:
                    break
                if _normalize(history[i]["part_number"]) not in seen:
                    seen.add(_normalize(history[i]["part_number"]))
                    similar.append({**history[i], "similarity": round(s, 2)})
            best = similar[0]
            note = f"description similarity {best_score:.2f}; a different part, check before using"
            item["match_tier"] = Field(value="similar", status=Status.NEEDS_REVIEW, note=note)
            item["matched_part_number"] = Field(value=best["part_number"], status=Status.NEEDS_REVIEW, note=note)
            item["reference_price"] = Field(value=best["price"], status=Status.NEEDS_REVIEW,
                                            note="price of the closest similar past quote, not of this part")
            item["past_quotes"] = Field(value=similar, status=Status.NEEDS_REVIEW)
        else:
            # Tier 3: nothing close enough -- say so, never invent a number
            _set_none(item, f"no past quote close enough (best score {best_score:.2f})")

    return items


def match_issues(items: list[dict]) -> list[Issue]:
    """One line per part saying what was found in the archive and where."""
    issues = []
    for n, item in enumerate(items, 1):
        if "match_tier" not in item:
            continue
        where = f"line {n} ({item['part_number'].value or '?'})"
        tier, quotes = item["match_tier"].value, item["past_quotes"].value or []
        if tier == "exact":
            prices = [q["price"] for q in quotes]
            span = f", range {min(prices):g} to {max(prices):g}" if len(quotes) > 1 else ""
            issues.append(Issue(where, "past_quotes", "info",
                                f"Quoted {len(quotes)} time(s) before{span}. Latest: {_money(quotes[0])} "
                                f"({_origin(quotes[0])})."))
        elif tier == "similar":
            q = quotes[0]
            issues.append(Issue(where, "past_quotes", "check",
                                f"No past quote for this part number. Closest is {q['part_number']} "
                                f"({q['description']}) at {_money(q)} ({_origin(q)}): a different part, "
                                "check before using its price."))
        else:
            issues.append(Issue(where, "past_quotes", "info", "No similar past quote found."))
    return issues
