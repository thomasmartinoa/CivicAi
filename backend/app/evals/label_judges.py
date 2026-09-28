"""Score judge artefacts by hand, one criterion at a time.

    python -m app.evals.label_judges --artifact-type briefing

The judges in `judges.py` score prose against anchored rubrics, and nothing in this
repository may decide whether those scores are any good — a judge validated against
labels produced by the same family of model is measuring its own reflection. So the
labels come from a person, and this exists to make that cheap: it prints the rubric,
prints one artefact, takes a digit, and appends a row.

It is resumable and additive. Work already in the file is skipped, so twenty labels
can be done in four sittings, and nothing is ever overwritten.
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.evals.judge_validation import DEFAULT_LABELS, load_judge_labels
from app.evals.judges import CRITERIA

logger = logging.getLogger(__name__)

TARGET_PER_CRITERION = 20
"""Below this, κ over a five-point scale is too noisy to mean much. It is a
convention rather than a law, and the report prints n so a reader can judge."""


@dataclass(frozen=True)
class Artifact:
    id: str
    text: str
    evidence: str = ""


def artifacts_for(artifact_type: str, source: Path | None) -> list[Artifact]:
    """The texts to score.

    Read from a JSONL file of `{"id", "text", "evidence"}` — normally produced by a
    real run, because a judge validated on invented prose tells you nothing about
    the prose the system actually writes.
    """
    if source is None or not Path(source).exists():
        return []
    items = []
    for line in Path(source).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            items.append(Artifact(id=row["id"], text=row["text"],
                                  evidence=row.get("evidence", "")))
    return items


def _already_labelled(path: Path, artifact_type: str) -> set[tuple[str, str]]:
    return {(label.artifact_id, label.criterion) for label in load_judge_labels(path)
            if label.artifact_type == artifact_type}


def _append(path: Path, *, artifact_type: str, artifact_id: str, criterion: str,
            score: int, labeller: str) -> None:
    """One row, flushed immediately, so quitting halfway loses nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "criterion": criterion,
            "score": score,
            "labeller": labeller,
            "labelled_at": date.today().isoformat(),
        }) + "\n")
        handle.flush()


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def label(*, artifact_type: str, artifacts: list[Artifact], path: Path,
          labeller: str) -> int:
    """Walk the artefacts. Returns how many labels were added."""
    criteria = CRITERIA[artifact_type]
    done = _already_labelled(path, artifact_type)
    added = 0

    for artifact in artifacts:
        pending = [c for c in criteria if (artifact.id, c.name) not in done]
        if not pending:
            continue
        print("\n" + "=" * 72)
        print(f"{artifact_type} · {artifact.id}")
        print("=" * 72)
        if artifact.evidence:
            print(f"\nEvidence it was given:\n{artifact.evidence}")
        print(f"\nText:\n{artifact.text}\n")

        for criterion in pending:
            print("-" * 72)
            print(f"{criterion.name}: {criterion.description}")
            for value, anchor in sorted(criterion.anchors.items()):
                print(f"   {value} = {anchor}")
            while True:
                answer = _ask("score 1-5 (s to skip this one, q to stop): ").lower()
                if answer == "q":
                    print(f"\nstopped. {added} labels added to {path}")
                    return added
                if answer == "s":
                    break
                if answer in {"1", "2", "3", "4", "5"}:
                    _append(path, artifact_type=artifact_type, artifact_id=artifact.id,
                            criterion=criterion.name, score=int(answer), labeller=labeller)
                    added += 1
                    break
                print("  a digit 1-5, or s, or q")

    print(f"\ndone. {added} labels added to {path}")
    return added


def progress(path: Path, artifact_type: str) -> dict[str, int]:
    """How many labels each criterion has, so it is obvious what is left."""
    labelled = [label for label in load_judge_labels(path)
                if label.artifact_type == artifact_type]
    counts = {c.name: 0 for c in CRITERIA[artifact_type]}
    for item in labelled:
        if item.criterion in counts:
            counts[item.criterion] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hand-label judge artefacts.")
    parser.add_argument("--artifact-type", choices=sorted(CRITERIA), required=True)
    parser.add_argument("--source", type=Path, default=None,
                        help="JSONL of {id, text, evidence} to score, normally captured "
                             "from a real run")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--labeller", default=None,
                        help="who is scoring; recorded on every row so the agreement "
                             "figures can be audited")
    parser.add_argument("--status", action="store_true", help="show progress and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    counts = progress(args.labels, args.artifact_type)
    print(f"{args.artifact_type}: " + ", ".join(
        f"{name} {n}/{TARGET_PER_CRITERION}" for name, n in sorted(counts.items())))
    if args.status:
        return 0

    if not args.labeller:
        print("\n--labeller is required: agreement reported without naming who scored "
              "it cannot be audited.", file=sys.stderr)
        return 2

    artifacts = artifacts_for(args.artifact_type, args.source)
    if not artifacts:
        print(f"\nno artefacts to score. Pass --source pointing at a JSONL of "
              f"{{id, text, evidence}} captured from a real run — judging invented "
              f"prose would not tell you anything about the prose the system writes.",
              file=sys.stderr)
        return 2

    label(artifact_type=args.artifact_type, artifacts=artifacts, path=args.labels,
          labeller=args.labeller)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
