"""Data shapes shared by the parser, the scoring code and the API.

Any field can be None, which the app shows as "unknown". We never guess a value.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

PriceType = Literal["whole_unit", "per_room", "per_bed", "unknown"]
Laundry = Literal["in_unit", "in_building", "none", "unknown"]
Parking = Literal["included", "extra_cost", "none", "unknown"]


class ListingFields(BaseModel):
    """What Gemini extracts from pasted listing text. Only facts stated in the text."""

    title: Optional[str] = Field(None, description="Short name for the listing, e.g. '2BR on Gayley Ave'")
    address: Optional[str] = Field(None, description="Street address as written in the listing")
    price: Optional[float] = Field(None, description="Monthly rent in US dollars, exactly as listed")
    price_type: PriceType = Field("unknown", description="Whether the price is for the whole unit, one room, or one bed")
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    laundry: Laundry = "unknown"
    parking: Parking = "unknown"
    red_flags: list[str] = Field(default_factory=list, description="Scam or pricing warning signs stated or implied by the text")


class Listing(ListingFields):
    """A listing plus facts that come from map APIs, not from the model."""

    id: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    walk_minutes: Optional[float] = None
    bike_minutes: Optional[float] = None
    grocery_walk_minutes: Optional[float] = None


class Weights(BaseModel):
    """How much each factor matters to one roommate, from 0 (don't care) to 5 (deal-breaker)."""

    rent: float = Field(3, ge=0, le=5)
    walk: float = Field(3, ge=0, le=5)
    laundry: float = Field(3, ge=0, le=5)
    parking: float = Field(3, ge=0, le=5)
    grocery: float = Field(3, ge=0, le=5)


class Roommate(BaseModel):
    name: str
    budget: float = Field(..., gt=0, description="Most this person wants to pay per month")
    weights: Weights = Field(default_factory=Weights)


class ParseRequest(BaseModel):
    text: str


class DecideRequest(BaseModel):
    listings: list[Listing]
    roommates: list[Roommate]
