"""Fail the build when the pipeline gets worse.

`python -m app.evals.run --gate` exits nonzero when macro-F1 falls more than two
points below the stored baseline. Two points is roughly the drift a provider gives
you for free between model revisions; it is not a licence to regress.

Three rules, all of them about a gate being worth having:

- **Nothing to compare against is a failure, not a pass.** A missing baseline, or
  a macro-F1 that came back None because nothing was scored, raises. A gate that
  passes when it has no evidence is theatre.
- **An improvement does not move the baseline.** Auto-ratcheting would raise the
  bar on a lucky run and then fail every honest run after it. The baseline is
  updated by a human, in a commit, with the report that justifies it.
- **A baseline belongs to a dataset.** It stores the dataset hash it was measured
  on, and comparing across datasets raises rather than quietly passing.
"""

import json
from dataclasses import dataclass
from pathlib import Path

GATE_TOLERANCE = 0.02
DEFAULT_BASELINE = Path(__file__).parent / "baselines" / "core.json"


class NoBaseline(RuntimeError):
    """There was nothing to compare against, which is a failure and not a pass."""


@dataclass(frozen=True)
class Baseline:
    macro_f1: float
    dataset_hash: str
    git_sha: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class GateResult:
    passed: bool
    current: float
    baseline: float
    summary: str


def load_baseline(path: Path = DEFAULT_BASELINE) -> Baseline | None:
    """The stored baseline, or None when the file does not exist yet.

    Loading is allowed to find nothing — a fresh checkout has no baseline.
    *Checking* against nothing is what raises.
    """
    path = Path(path)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("dataset_hash"):
        raise ValueError(
            f"{path}: a baseline must record the dataset_hash it was measured on — "
            "comparing against a score from a different golden set is worse than "
            "not comparing at all"
        )
    return Baseline(
        macro_f1=float(payload["macro_f1"]),
        dataset_hash=payload["dataset_hash"],
        git_sha=payload.get("git_sha"),
        note=payload.get("note"),
    )


def write_baseline(path: Path, *, macro_f1: float, dataset_hash: str,
                   git_sha: str | None = None, note: str | None = None) -> None:
    """Write a baseline. Called by a human deciding to move the bar, never by the
    runner: see the module docstring."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "macro_f1": macro_f1,
        "dataset_hash": dataset_hash,
        "git_sha": git_sha,
        "note": note,
    }, indent=2) + "\n", encoding="utf-8")


def check_gate(*, current: float | None, baseline: float | None,
               current_dataset: str | None = None,
               baseline_dataset: str | None = None) -> GateResult:
    """Compare and explain. Raises rather than passing when it cannot compare."""
    if current is None:
        raise NoBaseline(
            "macro_f1 was not measured in this run, so the gate has nothing to check; "
            "an empty sweep must not pass by producing no evidence of regression"
        )
    if baseline is None:
        raise NoBaseline(
            "no baseline is stored, so this run cannot be compared; record one with "
            "write_baseline() once you have a report you are willing to defend"
        )
    if current_dataset and baseline_dataset and current_dataset != baseline_dataset:
        raise ValueError(
            f"the baseline was measured on dataset {baseline_dataset[:12]} but this run "
            f"used {current_dataset[:12]}; re-measure the baseline instead of comparing "
            "across datasets"
        )

    delta = current - baseline
    if delta >= 0:
        summary = (f"macro-F1 improved to {current:.2f} from {baseline:.2f} "
                   f"(+{delta:.2f}); the baseline stays at {baseline:.2f} until it is "
                   "moved deliberately")
        return GateResult(passed=True, current=current, baseline=baseline, summary=summary)

    drop = -delta
    passed = drop <= GATE_TOLERANCE
    verdict = "within" if passed else "beyond"
    summary = (f"macro-F1 {current:.2f} against a baseline of {baseline:.2f}: a drop of "
               f"{drop:.2f}, {verdict} the {GATE_TOLERANCE:.2f} tolerance")
    return GateResult(passed=passed, current=current, baseline=baseline, summary=summary)
