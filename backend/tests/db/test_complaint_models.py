import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.workflow import Escalation, Notification, WorkOrder


def test_complaint_requires_a_tracking_id(db_session):
    complaint = Complaint(
        tracking_id="CIV-ABC12345",
        citizen_email="a@b.com",
        description="Pothole on the main road",
    )
    db_session.add(complaint)
    db_session.commit()
    assert complaint.status == "submitted"
    assert complaint.reopen_count == 0


def test_tracking_id_is_unique(db_session):
    for _ in range(2):
        db_session.add(Complaint(
            tracking_id="CIV-DUPLICATE",
            citizen_email="a@b.com",
            description="x" * 20,
        ))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_complaint_carries_graph_metadata(db_session):
    complaint = Complaint(
        tracking_id="CIV-GRAPH001",
        citizen_email="a@b.com",
        description="Streetlight is out",
        graph_thread_id="thread-abc",
        pipeline_version="v2.0",
        evidence=[{"source": "sop_roads.md", "score": 0.81}],
    )
    db_session.add(complaint)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.query(Complaint).one()
    assert reloaded.graph_thread_id == "thread-abc"
    assert reloaded.evidence[0]["source"] == "sop_roads.md"


def test_media_links_back_to_its_complaint(db_session):
    complaint = Complaint(
        tracking_id="CIV-MEDIA001",
        citizen_email="a@b.com",
        description="Broken bench in the park",
    )
    db_session.add(complaint)
    db_session.flush()
    db_session.add(ComplaintMedia(
        complaint_id=complaint.id,
        file_path="uploads/x.jpg",
        media_type="image",
    ))
    db_session.commit()
    db_session.expire_all()

    assert len(db_session.query(Complaint).one().media) == 1


def test_work_order_flags_clusters_with_a_boolean(db_session):
    """v1 detected clusters with a LIKE query against a free-text notes column."""
    complaint = Complaint(
        tracking_id="CIV-WO000001",
        citizen_email="a@b.com",
        description="Waterlogging near the junction",
    )
    db_session.add(complaint)
    db_session.flush()

    order = WorkOrder(complaint_id=complaint.id, is_cluster=True)
    db_session.add(order)
    db_session.commit()

    assert order.status == "created"
    assert order.is_cluster is True


def test_a_complaint_cannot_have_two_work_orders(db_session):
    """Complaint.work_order is uselist=False; the schema must enforce it."""
    complaint = Complaint(
        tracking_id="CIV-DUPWO001",
        citizen_email="a@b.com",
        description="Streetlight out on the corner",
    )
    db_session.add(complaint)
    db_session.flush()

    db_session.add(WorkOrder(complaint_id=complaint.id))
    db_session.add(WorkOrder(complaint_id=complaint.id))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_notification_dedupe_key_is_unique(db_session):
    """v1 Bug 4: SLA warnings re-sent every 5 minutes with no idempotency key."""
    for _ in range(2):
        db_session.add(Notification(
            recipient_email="a@b.com",
            notification_type="sla_warning",
            message="SLA approaching",
            dedupe_key="complaint-1:sla_warning:50",
        ))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_escalation_records_the_jurisdiction_hop(db_session):
    complaint = Complaint(
        tracking_id="CIV-ESC00001",
        citizen_email="a@b.com",
        description="Open manhole outside the school",
    )
    db_session.add(complaint)
    db_session.flush()

    db_session.add(Escalation(
        complaint_id=complaint.id,
        from_level="ward",
        to_level="block",
        reason="SLA breached",
    ))
    db_session.commit()
    assert db_session.query(Escalation).one().to_level == "block"
