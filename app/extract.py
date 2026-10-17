"""Step 2: pasted listing text -> validated facts, plus Gemini's plain-English explanations.

Gemini reads the text and returns each fact with an exact quote ("evidence") from the listing.
Our code then checks every quote. A fact with no quote, a quote that is not in the text, or a
quote that does not contain the claimed number is thrown away and shown as "unknown".
Gemini never produces scores, rankings or distances.

Try it on a file:  .venv/bin/python -m app.extract data/samples/listing1.txt
"""
import json
import os
import re
import sys
from typing import Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from . import cache

Laundry = Literal["in_unit", "shared", "none", "unknown"]
Parking = Literal["included", "paid", "none", "unknown"]

# Fields that need an evidence quote when they have a value.
FACT_FIELDS = [
    "address", "rent_total_monthly", "bedrooms", "bathrooms",
    "laundry", "parking", "utilities_included", "available_from",
]

# Bump this when the prompt changes, so old cached replies are not reused.
PROMPT_VERSION = "extract-v2"

EXTRACT_PROMPT = """You extract facts from a rental listing for students. Return JSON only.

Rules:
- Use only facts stated in the listing text. If a fact is not stated, use null (or "unknown").
- Never estimate or fill in anything from general knowledge.
- rent_total_monthly: the monthly rent for the WHOLE unit in US dollars. If the price is only
  per bed or per room, use null.
- laundry: "in_unit" (washer/dryer inside the unit), "shared" (building or coin laundry),
  "none" (listing says no laundry), else "unknown". Hookups without machines are "unknown".
- parking: "included", "paid" (extra monthly cost), "none", else "unknown".
- available_from: YYYY-MM-DD only if the listing gives a full date including the year, else null.
- evidence: for EVERY field you fill in, copy the exact words from the listing that state it,
  character for character (a short phrase, under 20 words). Include the label or nearby words so
  the quote shows what it is about: "Parking None", not just "None". Do not add or change any
  words, symbols or punctuation. Leave evidence null for null fields.

Listing text:
"""


class Evidence(BaseModel):
    """One exact quote per field. Kept as named fields because Gemini's schema needs fixed keys."""

    address: Optional[str] = None
    rent_total_monthly: Optional[str] = None
    bedrooms: Optional[str] = None
    bathrooms: Optional[str] = None
    laundry: Optional[str] = None
    parking: Optional[str] = None
    utilities_included: Optional[str] = None
    available_from: Optional[str] = None


class GeminiReply(BaseModel):
    """The exact shape we ask Gemini for."""

    address: Optional[str] = None
    rent_total_monthly: Optional[float] = Field(None, ge=0)
    bedrooms: Optional[int] = Field(None, ge=0)
    bathrooms: Optional[float] = Field(None, ge=0)
    laundry: Laundry = "unknown"
    parking: Parking = "unknown"
    utilities_included: Optional[bool] = None
    available_from: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    evidence: Evidence = Field(default_factory=Evidence)


class Extracted(BaseModel):
    """Checked facts, the schema from CLAUDE.md. Every non-null fact has a verified quote."""

    address: Optional[str] = None
    rent_total_monthly: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    laundry: Laundry = "unknown"
    parking: Parking = "unknown"
    utilities_included: Optional[bool] = None
    available_from: Optional[str] = None
    evidence: dict[str, str] = Field(default_factory=dict)
    rejected: list[str] = Field(default_factory=list, description="Fields Gemini filled but we threw out")


# ---------- Checking the quotes (plain code, no model) ----------

_NUMBER_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _normalize(s: str) -> str:
    """Lowercase, straighten curly quotes and dashes, collapse spaces, so line breaks don't break a match."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().casefold()


def quote_in_text(quote: str, text: str) -> bool:
    q = _normalize(quote)
    return bool(q) and q in _normalize(text)


def _numbers_in(quote: str) -> list[float]:
    """All numbers in a quote, reading "$3,250" as 3250 and "1.5" as 1.5."""
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", quote.replace(",", ""))]


def value_matches_quote(field: str, value, quote: str) -> bool:
    """For numbers, the quote must actually contain that number. Catches made-up values."""
    q = _normalize(quote)
    if field == "rent_total_monthly":
        return float(value) in _numbers_in(q)
    if field in ("bedrooms", "bathrooms"):
        if float(value) in _numbers_in(q):
            return True
        if float(value).is_integer() and _NUMBER_WORDS.get(int(value), "@") in q:
            return True
        return field == "bedrooms" and value == 0 and "studio" in q
    return True  # Text and category fields: the quote being in the listing is the check.


def validate_reply(raw_json: str, text: str) -> Extracted:
    """Parse Gemini's JSON and keep only facts backed by a real quote.

    Raises ValidationError if the JSON itself is malformed (the caller retries once).
    """
    reply = GeminiReply.model_validate_json(raw_json)
    quotes = reply.evidence.model_dump()
    out = Extracted()
    for field in FACT_FIELDS:
        value = getattr(reply, field)
        if value is None or value == "unknown":
            continue
        quote = quotes.get(field)
        if quote and quote_in_text(quote, text) and value_matches_quote(field, value, quote):
            setattr(out, field, value)
            out.evidence[field] = quote
        else:
            out.rejected.append(field)  # Left as null / "unknown". Never guessed.
    return out


def rent_per_person(rent_total_monthly: float | None, roommates: int) -> float | None:
    """Rent per person is computed here, never by the model. Roommate count comes from the user."""
    if roommates < 1:
        raise ValueError("Need at least one roommate.")
    if rent_total_monthly is None:
        return None
    return round(rent_total_monthly / roommates, 2)


# ---------- Calling Gemini ----------

_gemini: genai.Client | None = None


def _client() -> genai.Client:
    # One shared client: a temporary one gets closed before its request finishes.
    global _gemini
    if _gemini is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
        _gemini = genai.Client(api_key=key)
    return _gemini


def _model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


def _call_gemini(text: str) -> str:
    """One Gemini call. Returns its raw JSON text."""
    response = _client().models.generate_content(
        model=_model(),
        contents=EXTRACT_PROMPT + text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GeminiReply,
            temperature=0,
        ),
    )
    return response.text or ""


def merge_attempts(attempts: list[Extracted]) -> Extracted:
    """Keep every fact that passed the check in any attempt. Earlier attempts win ties.

    Every kept fact still has its own verified quote, so nothing unchecked gets in.
    """
    merged = attempts[0].model_copy(deep=True)
    for later in attempts[1:]:
        for field, quote in later.evidence.items():
            if field not in merged.evidence:
                setattr(merged, field, getattr(later, field))
                merged.evidence[field] = quote
    merged.rejected = [f for f in FACT_FIELDS
                       if f not in merged.evidence and any(f in a.rejected for a in attempts)]
    return merged


def extract_listing(text: str) -> Extracted:
    """Pasted text -> checked facts. Cached by input.

    Gemini is asked a second time (once only) if its reply is malformed or any quote fails the check.
    """
    key = f"{PROMPT_VERSION}|{_model()}|{text}"
    cached = cache.get("extract", key)
    if cached is not None:
        return Extracted.model_validate(cached)

    attempts: list[Extracted] = []
    for _attempt in range(2):
        raw = _call_gemini(text)
        try:
            attempts.append(validate_reply(raw, text))
        except ValidationError:
            continue
        if not attempts[-1].rejected:
            break

    if not attempts:
        # Two malformed replies: show everything as unknown rather than guess. Not cached, so it can retry later.
        return Extracted(rejected=["malformed_reply"])
    result = merge_attempts(attempts)
    cache.put("extract", key, result.model_dump())
    return result


def to_listing_fields(e: Extracted) -> dict:
    """TEMPORARY bridge to the current Listing shape in models.py, so the map keeps working.

    Remove in step 3 when models.py switches to the brief's schema.
    """
    return {
        "title": e.address or "Pasted listing",
        "address": e.address,
        "price": e.rent_total_monthly,
        "price_type": "whole_unit" if e.rent_total_monthly is not None else "unknown",
        "bedrooms": e.bedrooms,
        "bathrooms": e.bathrooms,
        "laundry": {"shared": "in_building"}.get(e.laundry, e.laundry),
        "parking": {"paid": "extra_cost"}.get(e.parking, e.parking),
        "red_flags": [],
    }


# ---------- Explanations (Gemini writes words about a decision our code already made) ----------

def explain_decision(decision: dict) -> str:
    prompt = (
        "Explain this apartment decision to a group of student roommates in 3 short sentences. "
        "Use only the numbers given. Say which place was picked, why it is fair, and who gives up "
        "the most and on what.\n\n" + json.dumps(decision)
    )
    response = _client().models.generate_content(model=_model(), contents=prompt)
    return (response.text or "").strip()


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    for path in sys.argv[1:]:
        with open(path) as f:
            print(f"== {path}")
            print(extract_listing(f.read()).model_dump_json(indent=2))
