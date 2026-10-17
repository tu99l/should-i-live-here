"""Gemini's two jobs: pull facts out of pasted listing text, and explain a decision in plain English.

Gemini never produces scores or distances. Those come from scoring.py and commute.py.
"""
import json
import os

from google import genai
from google.genai import types

from .models import ListingFields

EXTRACT_PROMPT = """You extract facts from a rental listing for students.
Rules:
- Only use facts stated in the listing text. If a fact is not stated, leave it null or "unknown".
- Never estimate rent, bedrooms or anything else from general knowledge.
- price_type: "per_bed" if the price is for one bed in a shared room, "per_room" if for one bedroom,
  "whole_unit" if for the entire apartment.
- red_flags: list short warnings such as wire-transfer-only payment, deposit before viewing,
  price far below others nearby, or confusing per-bed pricing. Empty list if none.

Listing text:
"""


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


def extract_listing(text: str) -> ListingFields:
    """Turn pasted listing text into validated fields."""
    response = _client().models.generate_content(
        model=_model(),
        contents=EXTRACT_PROMPT + text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ListingFields,
            temperature=0,
        ),
    )
    # Validate again ourselves so a malformed reply fails loudly instead of showing wrong data.
    return ListingFields.model_validate_json(response.text)


def explain_decision(decision: dict) -> str:
    """Write a short plain-English summary of a decision our own code already made."""
    prompt = (
        "Explain this apartment decision to a group of student roommates in 3 short sentences. "
        "Use only the numbers given. Say which place was picked, why it is fair, and who gives up "
        "the most and on what.\n\n" + json.dumps(decision)
    )
    response = _client().models.generate_content(model=_model(), contents=prompt)
    return response.text.strip()
