"""Internal contracts shared by planning components."""
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from ..models.schemas import Location, TripRequest


@dataclass(frozen=True)
class PlanningContext:
    """Immutable request facts used during one planning run."""

    city: str
    amap_city: str = ""
    city_center: Optional[Location] = None
    radius_km: float = 0.0
    target_adcode: Optional[str] = None
    request: Optional[TripRequest] = None
    # 定向替换餐饮/景点时，被改那天的就近锚点（酒店或已定位景点/餐点）。
    anchor: Optional[Location] = None


@dataclass
class PlanningState:
    """Mutable state accumulated during one planning run."""

    cached_pois: list[dict[str, Any]] = field(default_factory=list)
    validated_plan: Any = None
    evidence_ids: dict[str, set[str]] = field(default_factory=dict)
    evidence_records: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    search_history: set[str] = field(default_factory=set)
    searched_purposes: set[str] = field(default_factory=set)
    refresh_count: dict[str, int] = field(default_factory=dict)
    invalid_response_count: int = 0
    validation_attempts: int = 0
    evidence_preloaded: bool = False
    preloaded_evidence: str = ""


@dataclass(frozen=True)
class POIRecord:
    """Minimal immutable POI value returned by an attraction resolver."""

    name: str
    address: str = ""
    location: Optional[Location] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    poi_id: str = ""
    type: str = ""
    category: Optional[str] = None
    description: str = ""
    rating: Optional[float] = None
    photos: tuple[str, ...] = ()
    image_url: Optional[str] = None
    ticket_price: int = 0


@dataclass(frozen=True)
class DateUpdate:
    start_date: str
    end_date: str

    @classmethod
    def from_fields(cls, fields: Mapping[str, Any]) -> "DateUpdate":
        return cls(start_date=str(fields["start_date"]), end_date=str(fields["end_date"]))
