import asyncio

from app.api.complaints import _CHUNK, _read_bounded
from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.core import Tenant
from app.services.media import MAX_UPLOAD_BYTES, MediaTooLarge


def _form(**over):
    body = {"description": "A large pothole on the main road near the school gate",
            "citizen_email": "citizen@example.com"}
    body.update(over)
    return body


def test_submitting_a_complaint_returns_a_tracking_id(client):
    response = client.post("/complaints/", data=_form())
    assert response.status_code == 201
    assert response.json()["tracking_id"].startswith("CIV-")
    assert response.json()["status"] == "submitted"


def test_the_complaint_is_persisted_with_a_tenant(client, db_session):
    """route_node fails closed on a tenant-less complaint."""
    client.post("/complaints/", data=_form())
    stored = db_session.query(Complaint).one()
    assert stored.tenant_id == db_session.query(Tenant).one().id


def test_submission_schedules_the_graph_run(client):
    client.post("/complaints/", data=_form())
    assert len(client.captured_runs) == 1


def test_the_citizen_is_not_made_to_wait_for_the_graph(client):
    """The response must not depend on the run. v1 got this right and it is the
    one architectural decision worth carrying forward unchanged."""
    response = client.post("/complaints/", data=_form())
    assert response.status_code == 201
    assert response.json()["status"] == "submitted"


def test_a_too_short_description_is_rejected(client):
    response = client.post("/complaints/", data=_form(description="hi"))
    assert response.status_code == 422


def test_an_uploaded_image_is_stored_and_linked(client, db_session):
    response = client.post(
        "/complaints/", data=_form(),
        files=[("files", ("photo.jpg", b"fake-jpeg", "image/jpeg"))],
    )
    assert response.status_code == 201
    media = db_session.query(ComplaintMedia).one()
    assert media.media_type == "image"
    assert media.original_filename == "photo.jpg"
    assert "photo" not in media.file_path, "the stored name must be generated"


def test_a_disallowed_upload_type_is_rejected(client):
    response = client.post(
        "/complaints/", data=_form(),
        files=[("files", ("payload.exe", b"MZ", "application/octet-stream"))],
    )
    assert response.status_code == 400
    assert "exe" in response.json()["detail"]


def test_tracking_returns_the_complaint(client):
    tracking_id = client.post("/complaints/", data=_form()).json()["tracking_id"]
    response = client.get(f"/complaints/track/{tracking_id}")
    assert response.status_code == 200
    assert response.json()["tracking_id"] == tracking_id
    assert response.json()["status"] == "submitted"


def test_tracking_an_unknown_id_is_404(client):
    assert client.get("/complaints/track/CIV-NOPE0000").status_code == 404


def test_tracking_id_is_not_guessable_in_sequence(client):
    ids = {client.post("/complaints/", data=_form()).json()["tracking_id"] for _ in range(5)}
    assert len(ids) == 5


def test_an_empty_string_tenant_id_is_treated_as_not_provided(client, db_session):
    """resolve_tenant_id's `if requested:` check already treats "" the same as
    None by accident (a review of Task 1 flagged this). A multipart form
    readily sends tenant_id="" for a field the citizen never filled in, so
    the route normalises "" to None explicitly rather than relying on that
    truthiness quirk — the empty string is deliberately treated as "not
    provided" and resolved against the single seeded tenant, exactly as
    omitting the field would be."""
    response = client.post("/complaints/", data=_form(tenant_id=""))
    assert response.status_code == 201
    stored = db_session.query(Complaint).one()
    assert stored.tenant_id == db_session.query(Tenant).one().id


def test_an_empty_string_tenant_id_still_fails_closed_when_ambiguous(client, db_session):
    """Pinning that the normalisation is "treat as not provided", not "always
    succeed": with a second tenant present, an empty tenant_id must fail the
    same way an omitted one would, not silently pick either tenant."""
    from app.db.models.core import Tenant as TenantModel

    db_session.add(TenantModel(name="Second Municipal Corporation"))
    db_session.commit()

    response = client.post("/complaints/", data=_form(tenant_id=""))
    assert response.status_code == 400


def test_an_oversized_upload_is_rejected(client):
    """The read is bounded: a client must not be able to choose how much memory
    we allocate on a public endpoint."""
    response = client.post(
        "/complaints/", data=_form(),
        files=[("files", ("big.jpg", b"x" * (MAX_UPLOAD_BYTES + 1024), "image/jpeg"))],
    )
    assert response.status_code == 400


def test_a_rejected_batch_leaves_no_orphaned_files(client, db_session):
    """A later file failing must not leave the earlier ones on disk with nothing
    referencing them."""
    response = client.post(
        "/complaints/", data=_form(),
        files=[
            ("files", ("good.jpg", b"fake-jpeg", "image/jpeg")),
            ("files", ("payload.exe", b"MZ", "application/octet-stream")),
        ],
    )
    assert response.status_code == 400
    assert db_session.query(Complaint).count() == 0
    assert db_session.query(ComplaintMedia).count() == 0
    assert list(client.upload_root.iterdir()) == [], "the accepted file was left behind"
