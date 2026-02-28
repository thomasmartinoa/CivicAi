"""One-time backfill: re-run AI pipeline on complaints with missing category/risk."""
import sys
import asyncio
sys.path.insert(0, ".")

from app.database import SessionLocal
from app.models.complaint import Complaint
from app.agents import create_pipeline, PipelineContext


async def backfill():
    db = SessionLocal()
    try:
        complaints = db.query(Complaint).filter(
            (Complaint.category == None) | (Complaint.risk_level == None)
        ).all()
        print(f"Found {len(complaints)} complaints to backfill")

        for c in complaints:
            desc = (c.description or "")[:60]
            print(f"  Processing {c.tracking_id}: {desc}")

            pipeline = create_pipeline()
            context = PipelineContext(
                complaint_id=str(c.id),
                tenant_id=str(c.tenant_id) if c.tenant_id else None,
            )
            context.raw_input = {
                "description": c.description,
                "citizen_email": c.citizen_email,
                "citizen_phone": c.citizen_phone,
                "citizen_name": c.citizen_name,
                "latitude": float(c.latitude) if c.latitude else None,
                "longitude": float(c.longitude) if c.longitude else None,
                "address": c.address,
                "media_files": [],
            }
            context.data["tracking_id"] = c.tracking_id

            result = await pipeline.run(context, db)

            cat = result.data.get("category")
            risk = result.data.get("risk_level")
            print(f"    Errors: {result.errors}")
            print(f"    Category: {cat} | Risk: {risk}")

            if cat:
                c.category = cat
                c.subcategory = result.data.get("subcategory")
                c.priority_score = result.data.get("priority_score")
                c.risk_level = risk
                c.classification_confidence = result.data.get("classification_confidence")
                c.ai_analysis = {
                    "structured": result.structured_complaint,
                    "classification": result.classification,
                    "risk": result.risk_assessment,
                    "routing": result.routing,
                }
                if not result.errors:
                    c.status = result.status
                db.commit()
                print("    Updated successfully")
            else:
                print("    Skipped (no category returned)")

        print("Backfill complete!")
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(backfill())
