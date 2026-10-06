"""Draft the email the officer sends to the department that owns the problem.

v1 built this with a free-text prompt and a three-way `if provider ==` branch
inlined in the function, so the same provider dispatch existed here and in two
other places. Here it is one structured chain: the SOP for the complaint's
category is retrieved, and the model is asked to justify the assignment from
that clause and cite it, so the officer can check the claim before signing their
name to it.

**No HTTP surface yet.** Nothing in `app/api/` authenticates an officer — the
whole API is citizen-facing — so the draft/approve/send endpoints belong with the
officer work in a later phase. This module is the part that does not depend on
that: given a complaint, produce and store the draft. `email_approved` stays
False, and an approved draft is never overwritten.
"""

import logging
from collections.abc import Callable

from app.constants import CATEGORY_DEPARTMENT, Category, RiskLevel

logger = logging.getLogger(__name__)


class EmailDraftFailed(RuntimeError):
    """The chain could not produce a draft.

    Raised rather than falling back to template text, unlike the daily briefing.
    A briefing with the raw counts is still useful to an officer; half an email
    addressed to another department on the municipality's behalf is not, and
    storing one invites it being sent.
    """


def draft_department_email(
    *,
    complaint_id: str,
    session_factory: Callable,
    chain=None,
    retriever=None,
):
    """Write `complaint.email_draft` and return the draft.

    Returns the stored wording untouched when the officer has already approved
    it: regenerating over an approved draft would silently change what they
    signed off on.
    """
    from app.ai.graph.retrieval import format_evidence, retrieve
    from app.ai.schemas import EmailDraft
    from app.db.models.complaint import Complaint
    from app.services.tenancy import sla_hours_for

    session = session_factory()
    try:
        complaint = session.query(Complaint).filter(Complaint.id == complaint_id).one_or_none()
        if complaint is None:
            raise ValueError(f"complaint {complaint_id!r} does not exist")
        if not complaint.category:
            # The department is derived from the category, so there is nobody to
            # write to yet. This is a caller mistake, not a model failure.
            raise ValueError(f"complaint {complaint.tracking_id} has no category to route an email by")

        if complaint.email_approved and complaint.email_draft:
            logger.info("complaint %s already has an approved draft; leaving it alone",
                        complaint.tracking_id)
            return EmailDraft(subject=complaint.email_draft.split("\n", 1)[0],
                              body=complaint.email_draft, citations=[])

        category = Category(complaint.category)
        department = CATEGORY_DEPARTMENT[category]
        risk_level = RiskLevel(complaint.risk_level) if complaint.risk_level else RiskLevel.MEDIUM
        sla_hours = sla_hours_for(_tenant_of(session, complaint), risk_level)

        # Soft dependency, as everywhere: an email without the clause is still an
        # email, and format_evidence says plainly that nothing was retrieved.
        sop = retrieve(retriever, f"which department owns {category.value} complaints",
                       node="email_draft", k=2,
                       filters={"doc_type": "sop", "category": category.value})

        try:
            if chain is None:
                raise RuntimeError("no email draft chain configured")
            draft = chain.invoke({
                "department": department,
                "tracking_id": complaint.tracking_id,
                "category": category.value,
                "risk_level": risk_level.value,
                "sla_hours": sla_hours,
                "description": complaint.description,
                "evidence": format_evidence(sop.chunks),
            })
        except Exception as exc:
            logger.warning("email draft failed for %s", complaint.tracking_id, exc_info=True)
            raise EmailDraftFailed(f"could not draft an email for {complaint.tracking_id}: {exc}") from exc

        complaint.email_draft = f"{draft.subject}\n\n{draft.body}"
        complaint.email_approved = False
        session.commit()
        return draft
    finally:
        session.close()


def _tenant_of(session, complaint):
    from app.db.models.core import Tenant

    return session.get(Tenant, complaint.tenant_id) if complaint.tenant_id else None
