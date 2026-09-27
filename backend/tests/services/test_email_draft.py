"""The department email draft.

v1 branched three ways on provider inside generate_email_draft and prompted for
free text. Here it is one structured chain that retrieves the category's SOP and
cites the clause making this the department's job — so the officer can check the
claim before signing their name to it.
"""

import pytest
from langchain_core.runnables import RunnableLambda

from app.ai.schemas import EmailDraft
from app.db.models.complaint import Complaint
from app.services.email_draft import draft_department_email
from app.services.seed import seed_database
from tests.ai.graph.conftest import raises, returns
from tests.ai.graph.test_retrieval import FakeRetriever, _hit


@pytest.fixture
def complaint(db_session):
    seeded = seed_database(db_session)
    row = Complaint(tracking_id="CIV-DRAFT001", tenant_id=seeded["tenant_id"],
                    citizen_email="a@b.com", description="Huge pothole outside the school gate",
                    category="ROADS", risk_level="high", priority_score=70, status="assigned",
                    district="South Bangalore")
    db_session.add(row)
    db_session.commit()
    return row


def _sop():
    return FakeRetriever([_hit("Public Works owns road surface defects and potholes.",
                               "sop_roads.md", ["Roads SOP", "Ownership"])])


def _draft(subject="Pothole at the school gate — action required",
           body="Under the Roads SOP [1] this is Public Works' responsibility."):
    return returns(EmailDraft(subject=subject, body=body,
                              citations=["sop_roads.md › Roads SOP › Ownership"]))


def _run(db_session, complaint, **over):
    kwargs = dict(complaint_id=complaint.id, session_factory=lambda: db_session,
                  chain=_draft(), retriever=_sop())
    kwargs.update(over)
    return draft_department_email(**kwargs)


def test_the_draft_cites_the_department_sop(db_session, complaint):
    seen = {}

    def capture(payload):
        seen.update(payload)
        return EmailDraft(subject="Pothole at the school gate — action required",
                          body="Under the Roads SOP [1] this is Public Works' responsibility.",
                          citations=["sop_roads.md › Roads SOP › Ownership"])

    _run(db_session, complaint, chain=RunnableLambda(capture))

    assert seen["department"] == "Public Works Department"
    assert seen["category"] == "ROADS"
    assert seen["tracking_id"] == "CIV-DRAFT001"
    assert seen["sla_hours"] == 24, "the tenant's window for a high-risk complaint"
    assert "[1] sop_roads.md › Roads SOP › Ownership" in seen["evidence"]

    db_session.expire_all()
    stored = db_session.query(Complaint).one()
    assert "Public Works" in stored.email_draft
    assert "action required" in stored.email_draft
    assert stored.email_approved is False, "a draft is never pre-approved"


def test_the_sop_is_filtered_to_the_complaint_category(db_session, complaint):
    sop = _sop()
    _run(db_session, complaint, retriever=sop)
    assert sop.calls[0]["filters"] == {"doc_type": "sop", "category": "ROADS"}


def test_an_approved_draft_is_never_overwritten(db_session, complaint):
    """An officer has signed off on that wording. Regenerating over it would
    silently change what they approved."""
    complaint.email_draft = "The wording the officer approved."
    complaint.email_approved = True
    db_session.commit()

    result = _run(db_session, complaint, chain=raises(AssertionError("must not be invoked")))
    assert result.body == "The wording the officer approved."
    db_session.expire_all()
    assert db_session.query(Complaint).one().email_draft == "The wording the officer approved."


def test_a_missing_sop_still_produces_a_draft(db_session, complaint):
    """Retrieval is a soft dependency here as everywhere: the officer still
    needs an email, and the evidence block says nothing was found."""
    seen = {}

    def capture(payload):
        seen.update(payload)
        return EmailDraft(subject="s", body="b", citations=[])

    _run(db_session, complaint, retriever=None, chain=RunnableLambda(capture))
    assert "No supporting documents were retrieved." in seen["evidence"]
    db_session.expire_all()
    assert db_session.query(Complaint).one().email_draft


def test_a_failed_chain_raises_rather_than_storing_half_an_email(db_session):
    """Unlike the briefing, there is no useful template for this: an email sent
    to a department on the municipality's behalf is either drafted or not."""
    from app.services.email_draft import EmailDraftFailed

    seeded = seed_database(db_session)
    row = Complaint(tracking_id="CIV-DRAFT002", tenant_id=seeded["tenant_id"],
                    citizen_email="a@b.com", description="Streetlight out for a week",
                    category="ELECTRICITY", risk_level="medium", status="assigned")
    db_session.add(row)
    db_session.commit()

    with pytest.raises(EmailDraftFailed, match="quota"):
        _run(db_session, row, chain=raises(RuntimeError("quota")))
    db_session.expire_all()
    assert db_session.query(Complaint).filter_by(id=row.id).one().email_draft is None


def test_an_unknown_complaint_is_an_error(db_session):
    with pytest.raises(ValueError, match="no-such-id"):
        draft_department_email(complaint_id="no-such-id", session_factory=lambda: db_session,
                              chain=_draft(), retriever=_sop())


def test_an_unclassified_complaint_cannot_be_drafted(db_session):
    """The department comes from the category, so there is nobody to write to."""
    seeded = seed_database(db_session)
    row = Complaint(tracking_id="CIV-DRAFT003", tenant_id=seeded["tenant_id"],
                    citizen_email="a@b.com", description="something is wrong somewhere",
                    status="submitted")
    db_session.add(row)
    db_session.commit()

    with pytest.raises(ValueError, match="category"):
        _run(db_session, row)
