"""A roommate's own words -> what they want, plus the facts to score it. Used by the iMessage bot.

People write anything: "laundry 5, rent 3" or "i want to be close to a gym, laundry included,
need gas and water included". We turn that into:
- importance for our five built-in criteria (rent, commute, laundry, parking, bedrooms),
- "near" wishes: a kind of place close by (gym, Trader Joe's). Google finds the nearest one
  and the real walk time (maps_lookup.nearest_place),
- "feature" wishes: something the listing has (gas included, pets allowed). Answered only
  from the listing's own text, with an exact quote, else unknown,
- things nobody can check (quiet, safe, good vibes). We say so instead of guessing.

Gemini only reads words and copies quotes. Our code checks every quote is really in the text,
turns importance words into weights (IMPORTANCE_WEIGHTS), and scoring.py does all the math.
Short texts like "laundry 5, rent 3" are read by plain code with no Gemini call.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from . import cache, maps_lookup
from .extract import _client, _model, _normalize, _numbers_in, quote_in_text
from .models import Listing, Roommate, TravelMode, Want
from .scoring import CRITERIA

PROMPT_VERSION = "wishes-v3"
FEATURE_PROMPT_VERSION = "features-v1"

# How an importance word becomes a 0-5 weight. Our numbers, not the model's.
Importance = Literal["must", "high", "medium", "low", "none"]
# Built-in criteria start at 3, so saying you want something ("medium") must count for more than 3.
IMPORTANCE_WEIGHTS = {"must": 5, "high": 4.5, "medium": 4, "low": 2, "none": 0}
LEVEL_NAMES = {5: "must-have", 4.5: "important", 4: "wanted", 3: "wanted", 2: "nice to have", 1: "nice to have",
               0: "don't care"}

# A specific ask only counts if their own words say it (Gemini can't add it on its own).
STRICT_WORDS = {
    "in_unit_laundry": ("in unit", "in-unit", "inunit", "washer", "w/d", "in the unit", "in my unit",
                        "in the apartment", "inside"),
    "included_parking": ("free", "included", "incl", "no extra", "comes with"),
}
STRICT_CRITERION = {"in_unit_laundry": "laundry", "included_parking": "parking"}

# Words people use for our built-in criteria in short "laundry 5" style texts.
_CRITERION_WORDS = {"rent": "rent", "price": "rent", "commute": "commute", "walk": "commute",
                    "laundry": "laundry", "parking": "parking", "bedrooms": "bedrooms",
                    "beds": "bedrooms", "bedroom": "bedrooms"}

MAX_WANTS = 8  # Same cap as Roommate.wants; the newest wishes are kept.


class Wishes(BaseModel):
    """What one text asked for, after every quote was checked."""

    weights: dict[str, float] = Field(default_factory=dict)  # Only the built-in criteria they mentioned.
    strict: list[str] = Field(default_factory=list)  # "in_unit_laundry" / "included_parking" they asked for.
    wants: list[Want] = Field(default_factory=list)
    drop: list[Want] = Field(default_factory=list)  # Wishes they no longer care about ("don't need a gym").
    budget: Optional[float] = None
    place: Optional[str] = None
    travel_mode: Optional[TravelMode] = None
    cannot_check: list[str] = Field(default_factory=list)  # Their words; nothing we have can verify these.
    evidence: dict[str, str] = Field(default_factory=dict)
    not_understood: list[str] = Field(default_factory=list)  # Parts Gemini returned that failed our checks.

    def is_empty(self) -> bool:
        return not (self.weights or self.wants or self.drop or self.budget or self.place
                    or self.travel_mode or self.cannot_check)


# ---------- Short texts: plain code, no model ----------

_PAIR = re.compile(r"\b(" + "|".join(_CRITERION_WORDS) + r")\s*[:=]?\s*([0-5])\b")


def quick_parse(text: str) -> Optional[Wishes]:
    """"laundry 5, rent 3" -> Wishes. None if the text says anything else (then Gemini reads it)."""
    lowered = text.casefold()
    pairs = list(_PAIR.finditer(lowered))
    if not pairs:
        return None
    leftover = _PAIR.sub(" ", lowered)
    if re.sub(r"[\s,;.&!]|\band\b", "", leftover):
        return None  # More than just "criterion number" pairs.
    out = Wishes()
    for m in pairs:
        criterion = _CRITERION_WORDS[m.group(1)]
        out.weights[criterion] = float(m.group(2))
        out.evidence[criterion] = text[m.start():m.end()]
    return out


# ---------- Longer texts: Gemini extracts, our code checks ----------

WISH_PROMPT = """A student is telling their roommate group what they want in an apartment. Sort what they
said into the JSON fields. Return JSON only.

- core: wishes about our built-in criteria. criterion is one of:
  rent (price, cheap, budget), commute (close to campus / UCLA / class, short walk to school),
  laundry, parking, bedrooms (own room, enough bedrooms).
- near: a kind of place they want close to the apartment, other than campus (gym, grocery store,
  Trader Joe's, park, church, coffee shop). place = a short search phrase for a map, in their words.
- features: something the apartment itself or the lease should have, other than laundry and parking
  (gas included, water included, utilities included, wifi included, pets allowed, A/C, furnished,
  balcony, dishwasher). One entry per thing: "gas and water included" is two entries,
  "gas included" and "water included".
- budget: the most they will pay per month, only if they state a dollar amount. A budget alone is
  NOT a rent wish: add a core rent entry only if they say how much price matters (cheap, rent matters most).
- destination: a specific place they travel to regularly that is NOT campus (work, an internship),
  with travel_mode WALK, BICYCLE, TRANSIT or DRIVE if they say how they get there.
- cannot_check: things no listing or map can confirm (quiet, safe, nice landlord, good vibes, natural light).
- specific (core only): "in_unit_laundry" if they ask for laundry IN the apartment (in-unit, washer/dryer
  in the unit); "included_parking" if they ask for free or included parking. Otherwise null.
- importance: "must" (need, must, required, deal-breaker), "high" (really want, important),
  "medium" (want, would like, prefer), "low" (nice to have, bonus), "none" (don't care, don't need).
  If they give a number from 0 to 5: 5 must, 4 high, 3 medium, 1 or 2 low, 0 none.
- quote: copy their exact words for each entry, character for character, a short phrase.
- Only include what they actually said. Never add wishes they did not mention.

Their message:
"""


class CoreAsk(BaseModel):
    criterion: Literal["rent", "commute", "laundry", "parking", "bedrooms"]
    importance: Importance
    quote: str
    specific: Optional[Literal["in_unit_laundry", "included_parking"]] = None


class NearAsk(BaseModel):
    place: str = Field(..., min_length=1, max_length=100)
    importance: Importance
    quote: str


class FeatureAsk(BaseModel):
    feature: str = Field(..., min_length=1, max_length=100)
    importance: Importance
    quote: str


class WishReply(BaseModel):
    """The exact shape we ask Gemini for."""

    core: list[CoreAsk] = Field(default_factory=list)
    near: list[NearAsk] = Field(default_factory=list)
    features: list[FeatureAsk] = Field(default_factory=list)
    budget: Optional[float] = Field(None, ge=0)  # ge, not gt: Gemini's schema rejects gt.
    budget_quote: Optional[str] = None
    destination: Optional[str] = None
    travel_mode: Optional[TravelMode] = None
    destination_quote: Optional[str] = None
    cannot_check: list[str] = Field(default_factory=list)


_STOP = {"a", "an", "the", "to", "of", "in", "and", "near", "close", "by", "my", "is", "be", "for", "with"}


def _shares_a_word(name: str, quote: str) -> bool:
    """The thing Gemini named must use at least one of the person's own words ("gym" in "close to a gym")."""
    words = [w for w in re.findall(r"[a-z0-9']+", _normalize(name)) if w not in _STOP]
    q = _normalize(quote)
    return any(w in q or w.rstrip("s") in q for w in words)


def validate_wishes(raw_json: str, text: str) -> Wishes:
    """Keep only the parts of Gemini's reply backed by the person's own words.

    Raises ValidationError if the JSON itself is malformed (the caller retries once).
    """
    reply = WishReply.model_validate_json(raw_json)
    out = Wishes()

    for ask in reply.core:
        if quote_in_text(ask.quote, text):
            out.weights[ask.criterion] = float(IMPORTANCE_WEIGHTS[ask.importance])
            out.evidence[ask.criterion] = ask.quote
            q = _normalize(ask.quote)
            if (ask.specific and STRICT_CRITERION[ask.specific] == ask.criterion and ask.importance != "none"
                    and any(word in q for word in STRICT_WORDS[ask.specific])):
                out.strict.append(ask.specific)
        else:
            out.not_understood.append(ask.quote)

    for kind, asks, field in (("near", reply.near, "place"), ("feature", reply.features, "feature")):
        for ask in asks:
            what = getattr(ask, field).strip()
            if quote_in_text(ask.quote, text) and _shares_a_word(what, ask.quote):
                want = Want(kind=kind, what=what, weight=IMPORTANCE_WEIGHTS[ask.importance], quote=ask.quote)
                (out.drop if ask.importance == "none" else out.wants).append(want)
            else:
                out.not_understood.append(ask.quote)

    if reply.budget is not None:
        q = reply.budget_quote or ""
        nums = _numbers_in(q)
        said_k = "k" in _normalize(q) and reply.budget / 1000 in nums  # "$1.2k" means 1200.
        if quote_in_text(q, text) and (reply.budget in nums or said_k):
            out.budget = reply.budget
            out.evidence["budget"] = q
        else:
            out.not_understood.append(q or str(reply.budget))

    if reply.destination:
        q = reply.destination_quote or ""
        if quote_in_text(q, text) and _shares_a_word(reply.destination, q):
            out.place = reply.destination.strip()
            out.travel_mode = reply.travel_mode
            out.evidence["place"] = q
        else:
            out.not_understood.append(q or reply.destination)

    # A budget is not a rent importance; only keep a rent rating that has its own words.
    if "budget" in out.evidence and out.evidence.get("rent") == out.evidence["budget"]:
        del out.weights["rent"], out.evidence["rent"]

    out.cannot_check = [q for q in reply.cannot_check if quote_in_text(q, text)]
    return out


def _call_gemini(prompt: str, schema) -> str:
    response = _client().models.generate_content(
        model=_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema, temperature=0),
    )
    return response.text or ""


def parse_wishes(text: str) -> Wishes:
    """A roommate's message -> checked Wishes. Short "laundry 5" texts skip Gemini. Cached by text."""
    quick = quick_parse(text)
    if quick is not None:
        return quick

    key = f"{PROMPT_VERSION}|{_model()}|{text}"
    cached = cache.get("wishes", key)
    if cached is not None:
        return Wishes.model_validate(cached)

    result = None
    for _attempt in range(2):
        raw = _call_gemini(WISH_PROMPT + text, WishReply)  # Setup errors (no key) are raised, not hidden.
        try:
            result = validate_wishes(raw, text)
        except ValidationError:
            continue
        if not result.not_understood:
            break
    if result is None:
        return Wishes(not_understood=[text])  # Not cached, so a later try can work.
    cache.put("wishes", key, result.model_dump())
    return result


def apply_wishes(roommate: Roommate, wishes: Wishes) -> Roommate:
    """A copy of the roommate with this message's wishes added. Things not mentioned stay as they were."""
    r = roommate.model_copy(deep=True)
    for criterion, weight in wishes.weights.items():
        setattr(r.weights, criterion, weight)
        # Mentioning laundry/parking again replaces any earlier specific ask for it.
        r.strict = [x for x in r.strict if STRICT_CRITERION[x] != criterion]
    r.strict += [x for x in wishes.strict if x not in r.strict]
    if wishes.budget is not None:
        r.budget = wishes.budget
    if wishes.place:
        r.place = wishes.place
    if wishes.travel_mode:
        r.travel_mode = wishes.travel_mode

    def same(a: Want, b: Want) -> bool:
        return a.kind == b.kind and _normalize(a.what) == _normalize(b.what)

    gone = wishes.wants + wishes.drop  # A newer wish replaces the old one with the same name.
    r.wants = [w for w in r.wants if not any(same(w, g) for g in gone)] + wishes.wants
    r.wants = r.wants[-MAX_WANTS:]
    return r


# ---------- "Does this listing have X?" Gemini quotes the listing, our code checks the quote ----------

FEATURE_PROMPT = """For each feature in the list, say whether this rental listing states the apartment has it.
Return JSON only.

- answer "yes" only if the listing text clearly says so, "no" only if it clearly says it does not,
  else "unknown". Never infer from general knowledge or from what similar apartments usually have.
- quote: the exact words from the listing that show the answer, character for character, a short
  phrase. Leave quote null when the answer is "unknown".
- Copy each feature name exactly as given.

Features: {features}

Listing text:
"""


class FeatureAnswer(BaseModel):
    feature: str
    answer: Literal["yes", "no", "unknown"]
    quote: Optional[str] = None


class FeatureReply(BaseModel):
    answers: list[FeatureAnswer] = Field(default_factory=list)


def _feature_key(text: str, feature: str) -> str:
    return f"{FEATURE_PROMPT_VERSION}|{_model()}|{_normalize(feature)}|{text}"


def validate_features(raw_json: str, text: str, features: list[str]) -> dict[str, dict]:
    """{feature: {"value": True/False/None, "quote"}}. A yes/no without a real quote becomes unknown."""
    reply = FeatureReply.model_validate_json(raw_json)
    by_name = {_normalize(a.feature): a for a in reply.answers}
    out = {}
    for f in features:
        a = by_name.get(_normalize(f))
        if a and a.answer != "unknown" and a.quote and quote_in_text(a.quote, text):
            out[f] = {"value": a.answer == "yes", "quote": a.quote}
        else:
            out[f] = {"value": None, "quote": None}
    return out


def check_features(listing_text: Optional[str], features: list[str]) -> dict[str, dict]:
    """Answer several features for one listing in a single Gemini call. Each answer is cached on its own.

    No listing text, no key or a failed call -> unknown (failures are not cached, so they can retry).
    """
    unknown = {"value": None, "quote": None}
    if not listing_text or not features:
        return {f: dict(unknown) for f in features}
    out, missing = {}, []
    for f in features:
        hit = cache.get("features", _feature_key(listing_text, f))
        if hit is not None:
            out[f] = hit
        else:
            missing.append(f)
    if missing:
        prompt = FEATURE_PROMPT.format(features=json.dumps(missing)) + listing_text
        answers = None
        for _attempt in range(2):
            try:
                raw = _call_gemini(prompt, FeatureReply)
            except Exception:
                break  # No key or no network: unknown for now.
            try:
                answers = validate_features(raw, listing_text, missing)
                break
            except ValidationError:
                continue
        for f in missing:
            if answers is None:
                out[f] = dict(unknown)
            else:
                out[f] = answers[f]
                cache.put("features", _feature_key(listing_text, f), answers[f])
    return out


# ---------- Facts for every (listing, roommate) pair, for group.decide ----------

def want_facts_for(listings: list[Listing], roommates: list[Roommate]) -> dict[tuple[int, int], list]:
    """{(listing index, roommate index): [fact per roommate.wants entry]}.

    Each distinct place or feature is looked up once per listing (cached), however many roommates ask.
    """
    near = sorted({w.what for r in roommates for w in r.wants if w.kind == "near"})
    features = sorted({w.what for r in roommates for w in r.wants if w.kind == "feature"})
    if not near and not features:
        return {}

    def facts_for_listing(listing: Listing) -> tuple[dict, dict]:
        places = {}
        for what in near:
            located = listing.lat is not None and listing.lng is not None
            places[what] = maps_lookup.nearest_place(listing.lat, listing.lng, what) if located else None
        return places, check_features(listing.source_text, features)

    with ThreadPoolExecutor(max_workers=6) as pool:
        per_listing = list(pool.map(facts_for_listing, listings))

    result = {}
    for li, (places, feats) in enumerate(per_listing):
        for ri, r in enumerate(roommates):
            result[(li, ri)] = [places.get(w.what) if w.kind == "near" else feats.get(w.what)
                                for w in r.wants]
    return result


def describe(wishes: Wishes) -> list[str]:
    """Short plain-English lines saying what we understood, for the reply text."""
    labels = {"laundry": "in-unit laundry" if "in_unit_laundry" in wishes.strict else "laundry",
              "parking": "free parking" if "included_parking" in wishes.strict else "parking"}
    lines = []
    for c in CRITERIA:
        if c in wishes.weights:
            w = wishes.weights[c]
            lines.append(f"{labels.get(c, c)}: {LEVEL_NAMES.get(w, f'{w:g}/5')}")
    for w in wishes.wants:
        label = f"near a {w.what}" if w.kind == "near" else w.what
        lines.append(f"{label}: {LEVEL_NAMES.get(w.weight, f'{w.weight:g}/5')}")
    for w in wishes.drop:
        lines.append(f"dropped {w.what}")
    if wishes.budget:
        lines.append(f"budget ${wishes.budget:,.0f}/mo")
    if wishes.place:
        how = {"WALK": "walk", "BICYCLE": "bike", "TRANSIT": "transit", "DRIVE": "drive"}.get(wishes.travel_mode or "", "")
        lines.append(f"commute to {wishes.place}" + (f" by {how}" if how else ""))
    return lines
