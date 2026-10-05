"""The public dashboard's shapes, built by exclusion.

The officer schemas in `admin.py` list what to include. These do the opposite: they
are the only place in the application where an unauthenticated caller gets complaint
data, so each field here is one somebody decided was safe to publish, and the absent
ones are absent on purpose.

Deliberately not here:

- `citizen_email`, `citizen_phone`, `citizen_name` — the obvious ones.
- `description` — a citizen writes "the drain outside number 14 has been blocked
  since my husband's operation". A complaint description is unreviewed free text
  about a real street, and publishing it verbatim publishes whatever they put in it.
- `address`, `ward`, `latitude`, `longitude` at full precision — a complaint is
  tied to a place, and a place plus a date is often a household.
- `routing_justification` and `evidence` — internal reasoning an officer is
  accountable for, which the public reading it would only mislead.
- `media_url` is present because the existing frontend asks for it, and is **always
  null**: see `public.py`'s route docstring.
"""

from datetime import datetime

from pydantic import BaseModel


class PublicComplaint(BaseModel):
    """A complaint as a stranger may see it: what kind of problem, roughly where,
    and how it is going."""

    id: str
    category: str | None = None
    status: str
    risk_level: str | None = None
    district: str | None = None
    state: str | None = None
    created_at: datetime
    resolved: bool = False
    media_url: str | None = None
    """Always null. The field exists so the current frontend renders; publishing
    citizen photographs needs a review step that does not exist yet."""


class HeatmapPoint(BaseModel):
    """A coarsened location and how many complaints fall in it.

    Coordinates are rounded, so a point is a neighbourhood rather than a doorstep,
    and points with a single complaint are still published — the rounding is what
    protects the household, not the count.
    """

    lat: float
    lng: float
    weight: int
    category: str | None = None


class PublicDashboard(BaseModel):
    total_complaints: int = 0
    resolved_complaints: int = 0
    resolution_rate: float | None = None
    """None when nothing has been filed. 0.0 would read as a municipality that
    resolves nothing rather than one with nothing to resolve."""
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    recent_complaints: list[PublicComplaint] = []
    heatmap_data: list[HeatmapPoint] = []
