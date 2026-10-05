"""The one endpoint anybody can call.

Everything else in `app/api/` either belongs to a citizen who proved control of an
email address or to an officer who logged in. This is open, which makes it the only
place where a mistake is published rather than merely exposed to someone who was
already entitled to most of it.

So it is built by exclusion, and three choices are worth stating:

**Rejected complaints are not published.** A rejection is a judgement about
somebody's report — "this is a neighbour dispute, not an infrastructure problem" —
and publishing it would put that judgement next to a date and a district. The Phase 3
eval measured that `validate` rejects 18 of 88 real complaints, so some of those
judgements are also wrong.

**Coordinates are rounded to about a hundred metres.** A complaint is tied to a
place and a place plus a date is often a household. The heatmap still works; the
doorstep does not.

**Media is never published.** The existing frontend asks for a `media_url`, and the
field is always null. A citizen's photograph of a pothole may also contain a house
number, a face, or a number plate, and nothing reviews it. Publishing unreviewed
user-submitted images needs a moderation step that does not exist, so the honest
behaviour is to withhold them and say why rather than to ship the feature.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.complaint import Complaint
from app.db.session import get_db
from app.schemas.public import HeatmapPoint, PublicComplaint, PublicDashboard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])

COORDINATE_PRECISION = 3
"""Three decimal places is roughly 110 m of latitude. Two (~1.1 km) would make the
heatmap useless; four (~11 m) would identify a building."""

RECENT_LIMIT = 20
HEATMAP_LIMIT = 500

# A rejected complaint carries a judgement about the person who filed it, and a
# failed one carries nothing useful. Neither is published.
PUBLISHABLE_STATUSES = ("processed", "assigned", "resolved")
RESOLVED_STATUSES = ("resolved",)


@router.get("/dashboard", response_model=PublicDashboard)
def dashboard(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: str | None = None,
    state: str | None = None,
    district: str | None = None,
    category: str | None = None,
    _limit: Annotated[int, Query(ge=1, le=RECENT_LIMIT, alias="limit")] = RECENT_LIMIT,
) -> PublicDashboard:
    """Open civic statistics, filterable by place and category.

    `tenant_id` is a filter rather than a requirement: the dashboard is the one view
    where aggregating across municipalities is the point, and nothing it returns is
    tenant-confidential once the exclusions above are applied.
    """
    query = db.query(Complaint).filter(Complaint.status.in_(PUBLISHABLE_STATUSES))
    if tenant_id:
        query = query.filter(Complaint.tenant_id == tenant_id)
    if state:
        query = query.filter(Complaint.state == state)
    if district:
        query = query.filter(Complaint.district == district)
    if category:
        query = query.filter(Complaint.category == category)

    total = query.order_by(None).count()
    resolved = query.filter(Complaint.status.in_(RESOLVED_STATUSES)).order_by(None).count()

    def grouped(column) -> dict[str, int]:
        rows = (query.order_by(None).with_entities(column, func.count(Complaint.id))
                .group_by(column).all())
        return {key: count for key, count in rows if key is not None}

    recent = (query.order_by(Complaint.created_at.desc()).limit(_limit).all())
    located = (query.filter(Complaint.latitude.isnot(None), Complaint.longitude.isnot(None))
               .limit(HEATMAP_LIMIT).all())

    return PublicDashboard(
        total_complaints=total,
        resolved_complaints=resolved,
        # None, not 0.0: a municipality with nothing filed has not failed to resolve
        # anything.
        resolution_rate=(resolved / total) if total else None,
        by_status=grouped(Complaint.status),
        by_category=grouped(Complaint.category),
        recent_complaints=[
            PublicComplaint(
                id=c.id,
                category=c.category,
                status=c.status,
                risk_level=c.risk_level,
                district=c.district,
                state=c.state,
                created_at=c.created_at,
                resolved=c.status in RESOLVED_STATUSES,
                media_url=None,  # see the module docstring
            )
            for c in recent
        ],
        heatmap_data=_heatmap(located),
    )


def _heatmap(complaints: list[Complaint]) -> list[HeatmapPoint]:
    """Group complaints onto a coarse grid.

    Rounding before grouping is what makes this publishable: the output says "nine
    complaints near here", never "this complaint is at this address".
    """
    buckets: dict[tuple[float, float, str | None], int] = {}
    for complaint in complaints:
        key = (round(complaint.latitude, COORDINATE_PRECISION),
               round(complaint.longitude, COORDINATE_PRECISION),
               complaint.category)
        buckets[key] = buckets.get(key, 0) + 1
    return [HeatmapPoint(lat=lat, lng=lng, weight=weight, category=category)
            for (lat, lng, category), weight in sorted(buckets.items())]
