"""The public dashboard.

The only unauthenticated view of complaint data, so the central test builds a
complaint with every sensitive field populated and asserts none of them comes back.
"""

import pytest

from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.core import Tenant


def _complaint(db_session, **over):
    from uuid import uuid4

    fields = dict(tracking_id=f"CIV-{uuid4().hex[:8].upper()}",
                  citizen_email="a@b.com", description="a pothole", category="ROADS",
                  risk_level="high", status="assigned", district="South Bangalore",
                  state="Karnataka", latitude=12.971612, longitude=77.594629)
    fields.update(over)
    complaint = Complaint(**fields)
    db_session.add(complaint)
    db_session.flush()
    return complaint


# ── what must never be published ────────────────────────────────────────────


def test_the_dashboard_exposes_no_citizen_data(client, db_session):
    """One complaint, every sensitive field filled, nothing of it in the response."""
    complaint = _complaint(
        db_session,
        citizen_email="rajesh.kumar@example.com",
        citizen_phone="+91 99860 12345",
        citizen_name="Rajesh Kumar",
        description="the drain outside number 14 has been blocked since my operation",
        address="14 Cross, Jayanagar, Bengaluru",
        ward="Jayanagar East",
        routing_justification="Public Works owns road surface defects [1].",
        evidence=[{"node": "route", "source": "sop_roads.md", "headers": ["Ownership"],
                   "snippet": "Public Works owns roads."}],
    )
    db_session.add(ComplaintMedia(complaint_id=complaint.id,
                                  file_path="uploads/front-of-house.jpg",
                                  media_type="image"))
    db_session.commit()

    body = client.get("/public/dashboard").text
    for leaked in ("rajesh.kumar@example.com", "99860", "Rajesh Kumar",
                   "number 14", "my operation", "14 Cross", "Jayanagar",
                   "Public Works", "sop_roads.md", "front-of-house.jpg"):
        assert leaked not in body, f"{leaked!r} reached an unauthenticated response"


def test_coordinates_are_coarsened(client, db_session):
    """A complaint is tied to a place, and a place plus a date is often a
    household."""
    _complaint(db_session, latitude=12.971612, longitude=77.594629)
    db_session.commit()

    body = client.get("/public/dashboard").json()
    point = body["heatmap_data"][0]
    assert point["lat"] == 12.972 and point["lng"] == 77.595
    assert "12.971612" not in client.get("/public/dashboard").text


def test_nearby_complaints_collapse_into_one_weighted_point(client, db_session):
    """The output says "three complaints near here", never "this one is here"."""
    for offset in (0.0, 0.00002, 0.00005):
        _complaint(db_session, latitude=12.971612 + offset, longitude=77.594629)
    db_session.commit()

    points = client.get("/public/dashboard").json()["heatmap_data"]
    assert len(points) == 1
    assert points[0]["weight"] == 3


def test_rejected_complaints_are_not_published(client, db_session):
    """A rejection is a judgement about somebody's report — and the Phase 3 eval
    measured that 18 of 88 of them are wrong."""
    _complaint(db_session, status="rejected", terminal_reason="a neighbour dispute")
    _complaint(db_session, status="assigned")
    db_session.commit()

    body = client.get("/public/dashboard").json()
    assert body["total_complaints"] == 1
    assert "rejected" not in body["by_status"]


def test_failed_and_unprocessed_complaints_are_not_published(client, db_session):
    _complaint(db_session, status="failed")
    _complaint(db_session, status="submitted")
    db_session.commit()
    assert client.get("/public/dashboard").json()["total_complaints"] == 0


def test_media_is_never_published(client, db_session):
    """The field exists so the current frontend renders. Publishing unreviewed
    citizen photographs needs a moderation step that does not exist."""
    complaint = _complaint(db_session)
    db_session.add(ComplaintMedia(complaint_id=complaint.id, file_path="uploads/x.jpg",
                                  media_type="image"))
    db_session.commit()

    recent = client.get("/public/dashboard").json()["recent_complaints"]
    assert recent and all(c["media_url"] is None for c in recent)


# ── what it is for ──────────────────────────────────────────────────────────


def test_the_dashboard_needs_no_token(client, db_session):
    _complaint(db_session)
    db_session.commit()
    assert client.get("/public/dashboard").status_code == 200


def test_it_counts_and_breaks_down_by_status_and_category(client, db_session):
    _complaint(db_session, category="ROADS", status="assigned")
    _complaint(db_session, category="WATER", status="resolved")
    _complaint(db_session, category="WATER", status="resolved")
    db_session.commit()

    body = client.get("/public/dashboard").json()
    assert body["total_complaints"] == 3
    assert body["resolved_complaints"] == 2
    assert body["resolution_rate"] == pytest.approx(2 / 3)
    assert body["by_category"] == {"ROADS": 1, "WATER": 2}


def test_the_resolution_rate_is_null_not_zero_with_nothing_filed(client):
    """0% would read as a municipality that resolves nothing rather than one with
    nothing to resolve."""
    body = client.get("/public/dashboard").json()
    assert body["total_complaints"] == 0
    assert body["resolution_rate"] is None


def test_the_filters_narrow_everything_including_the_heatmap(client, db_session):
    _complaint(db_session, district="South Bangalore", category="ROADS")
    _complaint(db_session, district="North Bangalore", category="WATER",
               latitude=13.08, longitude=77.58)
    db_session.commit()

    body = client.get("/public/dashboard?district=South+Bangalore").json()
    assert body["total_complaints"] == 1
    assert body["by_category"] == {"ROADS": 1}
    assert len(body["heatmap_data"]) == 1


def test_it_can_be_filtered_to_one_tenant_or_aggregate_across_them(client, db_session):
    """Aggregating across municipalities is the point of this view, so tenant_id is
    a filter rather than a requirement."""
    other = Tenant(name="Mysuru City Corporation", config={})
    db_session.add(other)
    db_session.flush()
    _complaint(db_session, tenant_id=other.id)
    _complaint(db_session, tenant_id=None)
    db_session.commit()

    assert client.get("/public/dashboard").json()["total_complaints"] == 2
    assert client.get(f"/public/dashboard?tenant_id={other.id}"
                      ).json()["total_complaints"] == 1


def test_the_recent_list_is_newest_first_and_bounded(client, db_session):
    from app.api.public import RECENT_LIMIT

    for _ in range(RECENT_LIMIT + 5):
        _complaint(db_session)
    db_session.commit()

    body = client.get("/public/dashboard").json()
    assert len(body["recent_complaints"]) == RECENT_LIMIT
    dates = [c["created_at"] for c in body["recent_complaints"]]
    assert dates == sorted(dates, reverse=True)


def test_a_complaint_with_no_coordinates_is_counted_but_not_mapped(client, db_session):
    _complaint(db_session, latitude=None, longitude=None)
    db_session.commit()

    body = client.get("/public/dashboard").json()
    assert body["total_complaints"] == 1
    assert body["heatmap_data"] == []
