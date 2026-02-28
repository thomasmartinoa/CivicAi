"""
OfficerBriefingAgent — runs daily at 8 AM.
Collects stats, uses Gemini to write a readable brief for the village officer,
stores it in the daily_briefings table, and exposes via /admin/briefing endpoint.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session


async def generate_daily_briefing(db: Session):
    from app.models.complaint import Complaint
    from app.models.work_order import WorkOrder
    from app.models.escalation import Escalation
    from app.models.daily_briefing import DailyBriefing

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sla_warning_cutoff = now + timedelta(hours=12)

    # --- Collect stats ---
    new_complaints = db.query(Complaint).filter(
        Complaint.created_at >= today_start
    ).count()

    resolved_today = db.query(Complaint).filter(
        Complaint.status.in_(["resolved", "closed"]),
        Complaint.updated_at >= today_start,
    ).count()

    # SLA at risk = work orders whose deadline is within 12 hours and not done
    active_wos = db.query(WorkOrder).filter(
        WorkOrder.status.in_(["created", "assigned", "in_progress"]),
        WorkOrder.sla_deadline.isnot(None),
    ).all()
    sla_at_risk = 0
    for wo in active_wos:
        deadline = wo.sla_deadline
        if deadline and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline and deadline <= sla_warning_cutoff:
            sla_at_risk += 1

    escalations_today = db.query(Escalation).filter(
        Escalation.escalated_at >= today_start
    ).count()

    # Category breakdown for context
    open_complaints = db.query(Complaint).filter(
        Complaint.status.not_in(["resolved", "closed"])
    ).all()
    category_counts: dict[str, int] = {}
    for c in open_complaints:
        cat = c.category or "UNKNOWN"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    total_open = len(open_complaints)

    # --- Build prompt for Gemini ---
    stats_text = (
        f"Date: {now.strftime('%d %B %Y')}\n"
        f"New complaints today: {new_complaints}\n"
        f"Resolved today: {resolved_today}\n"
        f"Total open complaints: {total_open}\n"
        f"Complaints at risk of SLA breach (next 12 hours): {sla_at_risk}\n"
        f"Escalations raised today: {escalations_today}\n"
        f"Open complaints by category: {category_counts}\n"
    )

    narrative = await _generate_narrative(stats_text)

    briefing = DailyBriefing(
        brief_date=now,
        new_complaints=new_complaints,
        resolved_today=resolved_today,
        sla_at_risk=sla_at_risk,
        escalations_today=escalations_today,
        narrative=narrative,
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    print(f"[BriefingAgent] Daily brief generated for {now.strftime('%d %B %Y')}")
    return briefing


async def _generate_narrative(stats_text: str) -> str:
    try:
        from app.services.llm import llm_service
        if not llm_service._has_api_key():
            return _fallback_narrative(stats_text)

        import asyncio
        import google.generativeai as genai

        prompt = (
            "You are an AI assistant for a civic complaint management system. "
            "Write a concise, professional morning briefing for a village officer. "
            "Use plain, clear language. Include: a summary sentence, key action items, "
            "and any risks they should be aware of. Keep it under 200 words. "
            "Do NOT add headings or bold. Just flowing paragraphs.\n\n"
            f"Today's statistics:\n{stats_text}"
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[BriefingAgent] Gemini failed, using fallback: {e}")
        return _fallback_narrative(stats_text)


def _fallback_narrative(stats_text: str) -> str:
    lines = {}
    for line in stats_text.strip().split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            lines[k.strip()] = v.strip()

    new = lines.get("New complaints today", "0")
    resolved = lines.get("Resolved today", "0")
    at_risk = lines.get("Complaints at risk of SLA breach (next 12 hours)", "0")
    escalations = lines.get("Escalations raised today", "0")
    total_open = lines.get("Total open complaints", "0")

    parts = [
        f"Good morning. As of today, {new} new complaints have been submitted and {resolved} have been resolved.",
        f"There are currently {total_open} open complaints in the system.",
    ]
    if int(at_risk or 0) > 0:
        parts.append(f"ATTENTION: {at_risk} complaint(s) are at risk of SLA breach within the next 12 hours and require immediate action.")
    if int(escalations or 0) > 0:
        parts.append(f"{escalations} escalation(s) were raised today due to SLA breaches.")
    parts.append("The AI system has automatically reassigned overdue complaints and created grouped work orders for clustered issues. No manual intervention required unless flagged above.")
    return " ".join(parts)
