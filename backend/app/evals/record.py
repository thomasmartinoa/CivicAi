"""Persist what an eval run was, and what it measured.

A report is written from these rows. A number nobody can trace back to a dataset
hash and a commit is a screenshot, so `EvalRun` carries both and the report prints
them.

One rule with teeth: a metric that could not be computed is **not written**. An
unmeasured value stored as 0.0 would make the regression gate compare against a
failure that never happened, and would read in the report as though the model
scored nothing.
"""

import logging
import subprocess
from pathlib import Path

from app.db.base import utcnow

logger = logging.getLogger(__name__)

BACKEND = Path(__file__).resolve().parents[2]


def git_sha(*, cwd: Path | None = None) -> str | None:
    """The current commit, or None.

    None rather than an exception: the harness must run from a tarball or a
    container with no git. The argument list is fixed — nothing is interpolated
    into a shell — and `check=False` means a non-repository is a None, not a
    traceback.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd or BACKEND), capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        logger.info("git is not available; the run will record no commit")
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha if len(sha) == 40 else None


def start_run(session, *, suite: str, config_label: str, dataset_name: str, dataset_hash: str):
    """Open a run row. `finished_at` stays null until the run completes, so a
    crashed run is distinguishable from a clean one rather than looking like a
    run with no metrics."""
    from app.db.models.evaluation import EvalRun

    run = EvalRun(
        suite=suite,
        config_label=config_label,
        dataset_name=dataset_name,
        dataset_hash=dataset_hash,
        git_sha=git_sha(),
        started_at=utcnow(),
    )
    session.add(run)
    session.flush()
    return run


def record_metrics(session, run, metrics: dict[str, tuple[float | None, dict | None]],
                   *, finished: bool = False) -> int:
    """Write one row per measured metric. Returns how many were written.

    `{"macro_f1": (0.79, {"n": 88})}` — a None value is skipped, deliberately:
    see the module docstring.
    """
    from app.db.models.evaluation import EvalResult

    written = 0
    for metric, (value, detail) in metrics.items():
        if value is None:
            logger.info("%s was not measured for %s; recording no row", metric, run.config_label)
            continue
        session.add(EvalResult(eval_run_id=run.id, metric=metric, value=float(value),
                               detail_json=detail or {}))
        written += 1
    if finished:
        run.finished_at = utcnow()
    session.flush()
    return written
