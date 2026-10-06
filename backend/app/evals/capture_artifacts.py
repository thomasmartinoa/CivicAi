"""Collect the prose a judge is meant to score, out of the real database.

    python -m app.evals.capture_artifacts --artifact-type routing_justification

The rubric judges in `judges.py` score two things: the justification `route_node`
writes for its department and contractor choice, and the daily briefing. Both are
written by real runs, so both can be read back out rather than invented — and they
have to be, because a judge validated on prose nobody's system produced tells you
nothing about the prose it does produce.

Output is the JSONL `label_judges.py` reads: one `{id, text, evidence}` per line.
The evidence is included because two of the three routing criteria are about
grounding, and a human cannot score "does this cite something that supports it"
without seeing what was cited.
"""

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ARTIFACT_TYPES = ("routing_justification", "briefing")


@dataclass(frozen=True)
class CapturedArtifact:
    id: str
    text: str
    evidence: str


def _format_evidence(rows: list[dict]) -> str:
    """The numbered block the node showed the model, rebuilt from stored chunks.

    `citation` is a property on RetrievedChunk and so is not in the stored JSON, but
    source and headers are — see docs/07 §7 — so the reader sees the same
    "source › header › header" the prose cites by [n].
    """
    lines = []
    for index, row in enumerate(rows, start=1):
        path = " › ".join([row.get("source", "?"), *(row.get("headers") or [])])
        snippet = (row.get("snippet") or "").strip().replace("\n", " ")
        lines.append(f"[{index}] {path}\n    {snippet[:300]}")
    return "\n".join(lines) or "No supporting documents were retrieved."


def capture(artifact_type: str, *, session_factory: Callable,
            limit: int | None = None) -> list[CapturedArtifact]:
    """Read artefacts of one type out of the database, newest first."""
    from app.db.models.complaint import Complaint
    from app.db.models.workflow import DailyBriefing

    session = session_factory()
    try:
        if artifact_type == "routing_justification":
            query = (
                session.query(Complaint)
                .filter(Complaint.routing_justification.isnot(None))
                .order_by(Complaint.created_at.desc())
            )
            rows = query.limit(limit).all() if limit else query.all()
            return [
                CapturedArtifact(
                    id=complaint.tracking_id,
                    text=complaint.routing_justification,
                    # Only the chunks route actually retrieved: showing a labeller
                    # the work_order evidence too would invite scoring the wrong
                    # citations.
                    evidence=_format_evidence(
                        [c for c in (complaint.evidence or []) if c.get("node") == "route"]
                    ),
                )
                for complaint in rows
            ]

        query = session.query(DailyBriefing).order_by(DailyBriefing.brief_date.desc())
        rows = query.limit(limit).all() if limit else query.all()
        return [
            CapturedArtifact(
                id=f"briefing-{row.brief_date:%Y-%m-%d}-{(row.tenant_id or 'none')[:8]}",
                text=row.narrative,
                # The counts are the briefing's evidence: "accurate" means agreeing
                # with these, so a labeller needs them to score it at all.
                evidence=(f"new complaints: {row.new_complaints}\n"
                          f"resolved: {row.resolved_today}\n"
                          f"past half their window: {row.sla_at_risk}\n"
                          f"escalations: {row.escalations_today}\n"
                          f"grouped work orders: {row.clusters_detected}\n"
                          f"(is_fallback={row.is_fallback})"),
            )
            for row in rows
            if not row.is_fallback  # template text is not the model's prose
        ]
    finally:
        session.close()


def write_jsonl(artifacts: list[CapturedArtifact], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for artifact in artifacts:
            handle.write(json.dumps({"id": artifact.id, "text": artifact.text,
                                     "evidence": artifact.evidence},
                                    ensure_ascii=False) + "\n")
    return len(artifacts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture judge artefacts from the database.")
    parser.add_argument("--artifact-type", choices=ARTIFACT_TYPES, required=True)
    parser.add_argument("--out", type=Path, default=None,
                        help="default: data/judge-artifacts/<type>.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db.session import SessionLocal

    out = args.out or Path("data/judge-artifacts") / f"{args.artifact_type}.jsonl"
    artifacts = capture(args.artifact_type, session_factory=SessionLocal, limit=args.limit)
    if not artifacts:
        print(
            f"no {args.artifact_type} artefacts in the database yet.\n\n"
            "Routing justifications come from processed complaints; briefings come from "
            "a non-fallback run of generate_briefing. Run the pipeline against a real "
            "key first — there is deliberately no way to synthesise these, because a "
            "judge validated on invented prose says nothing about the real thing."
        )
        return 2

    written = write_jsonl(artifacts, out)
    print(f"wrote {written} {args.artifact_type} artefacts to {out}\n\n"
          f"next:\n  .venv/bin/python -m app.evals.label_judges "
          f"--artifact-type {args.artifact_type} --labeller YOUR_NAME --source {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
