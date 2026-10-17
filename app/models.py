"""Data shapes shared by extraction, scoring, the group pick and the API.

Field names follow the extraction schema in CLAUDE.md. Any fact can be None (or "unknown"),
which the app shows as "unknown". We never guess a value.
"""
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

Laundry = Literal["in_unit", "shared", "none", "unknown"]
Parking = Literal["included", "paid", "none", "unknown"]


class ListingFacts(BaseModel):
    """Facts read from the listing text (see extract.py). Only what the text states."""

    address: Optional[str] = None
    rent_total_monthly: Optional[float] = Field(None, description="Monthly rent for the whole unit, US dollars")
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


class Roommate(BaseModel):
    name: str
    budget: float = Field(..., gt=0, description="Most this person wants to pay per month")
    weights: Weights = Field(default_factory=Weights)


class ParseRequest(BaseModel):
    text: str


class DecideRequest(BaseModel):
    listings: list[Listing]
    roommates: list[Roommate]
