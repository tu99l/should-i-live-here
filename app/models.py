"""Data shapes shared by extraction, scoring, the group pick and the API.

Field names follow the extraction schema in CLAUDE.md. Any fact can be None (or "unknown"),
which the app shows as "unknown". We never guess a value.
"""
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

Laundry = Literal["in_unit", "shared", "none", "unknown"]
Parking = Literal["included", "paid", "none", "unknown"]
TravelMode = Literal["WALK", "BICYCLE", "TRANSIT", "DRIVE"]


class ListingFacts(BaseModel):
    """Facts read from the listing text (see extract.py). Only what the text states."""

    address: Optional[str] = None
    rent_total_monthly: Optional[float] = Field(None, description="Monthly rent for the whole unit, US dollars")
    rent_per_person_listed: Optional[float] = Field(
        None, description="Monthly price the listing states per bed or per room (each person pays this)")
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    laundry: Laundry = "unknown"
    parking: Parking = "unknown"
    utilities_included: Optional[bool] = None
    available_from: Optional[str] = Field(None, description="YYYY-MM-DD")


class Listing(ListingFacts):
    """A listing plus facts from map APIs (never from the model)."""

    id: str
    title: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    walk_minutes: Optional[float] = None
    bike_minutes: Optional[float] = None
    grocery_walk_minutes: Optional[float] = Field(None, description="Real walk time to the nearest grocery store")
    grocery_count: Optional[int] = Field(None, description="Grocery stores within 1 km, straight line")
    nearest_grocery: Optional[str] = None
    red_flags: list[str] = Field(default_factory=list)
    # The listing's own words (pasted text, or the notes saved for demo listings).
    # "Does it have X?" questions are answered only from this text, with a quote.
    source_text: Optional[str] = None
    # Where the listing came from: "demo", "pasted" or "rentcast" (a live search, see rentcast.py).
    source: Optional[str] = None
    property_type: Optional[str] = None
    square_feet: Optional[float] = None
    # The price exactly as listed. Usually the same as rent_total_monthly; when rentcast.py suspects
    # the price is for ONE room (see price_check), rent_total_monthly is left unknown and only this is kept.
    listed_price: Optional[float] = None
    price_check: Optional[Literal["possible_per_room"]] = None
    # Where walk_minutes / bike_minutes are measured to. None = the default destination (campus).
    commute_to: Optional[str] = None
    evidence: dict[str, str] = Field(default_factory=dict, description="Exact quote from the listing for each extracted fact")


class Weights(BaseModel):
    """How much each criterion matters to one roommate, 0 (don't care) to 5 (deal-breaker).

    Scoring re-normalizes these to sum to 1. "walk" is accepted as the old name for "commute".
    Unknown keys (e.g. an old "grocery" slider) are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    rent: float = Field(3, ge=0, le=5)
    commute: float = Field(3, ge=0, le=5, validation_alias=AliasChoices("commute", "walk"))
    laundry: float = Field(3, ge=0, le=5)
    parking: float = Field(3, ge=0, le=5)
    bedrooms: float = Field(3, ge=0, le=5)


class Want(BaseModel):
    """Something specific a roommate asked for, in their own words (see wishes.py).

    kind "near":    a kind of place close by ("gym", "Trader Joe's"). Real walk time from Google.
    kind "feature": something the listing has ("gas included", "pets allowed"). Read from the
                    listing text with an exact quote, else unknown.
    """

    kind: Literal["near", "feature", "bathroom"]  # "bathroom" = they want their own bathroom.
    what: str = Field(..., min_length=1, max_length=100)
    weight: float = Field(3, ge=0, le=5)
    quote: Optional[str] = Field(None, description="The roommate's own words that asked for it")


class Roommate(BaseModel):
    name: str
    budget: float = Field(..., gt=0, description="Most this person wants to pay per month")
    weights: Weights = Field(default_factory=Weights)
    # Where this roommate needs to get to (campus, work, the beach...). Blank = the default campus.
    place: Optional[str] = Field(None, max_length=200)
    travel_mode: TravelMode = "WALK"
    wants: list[Want] = Field(default_factory=list, max_length=8)
    # Specific asks: "in-unit laundry" means shared laundry doesn't count for them,
    # "free parking" means paid parking doesn't count. See scoring.STRICT_SCORES.
    strict: list[Literal["in_unit_laundry", "included_parking"]] = Field(default_factory=list)


class ParseRequest(BaseModel):
    text: str
    # The group's place ("Santa Monica Pier"). Walk/bike times on the card go there. Blank = campus.
    destination: Optional[str] = Field(None, max_length=200)


class DecideRequest(BaseModel):
    listings: list[Listing]
    roommates: list[Roommate]
    # How many people will share rent and bedrooms, if more than the roommates sent (not everyone added yet).
    group_size: Optional[int] = Field(None, ge=1, le=10)
