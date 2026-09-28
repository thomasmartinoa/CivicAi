"""Run the golden set through the configurations and write the report.

    python -m app.evals.run --suite core --config all --limit 10

A full sweep is 100 items across two LLM configurations at roughly 45 seconds an
item on the free tier — over two hours of wall clock, most of it waiting. So every
prediction is appended to a log as it completes and `--resume` skips what the log
already holds. Losing two hours to one 429 would make this a tool nobody runs
twice.

The log is keyed on `(config_label, item_id)` and carries the dataset hash, so a
resumed run that straddles a dataset edit is visible rather than silently mixed;
the report prints how many predictions were reused.
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.constants import Category, RiskLevel
from app.evals import metrics
from app.evals.configurations import (
    FullConfiguration, KeywordConfiguration, LlmOnlyConfiguration, Prediction,
)
from app.evals.dataset import GoldenItem, dataset_hash, load_golden
from app.evals.report import ConfigurationSummary, render_report
from app.evals.usage import estimated_cost, load_cost_rates, token_counter

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_PROVIDER_FAILURES = 3
"""After this many provider failures in a row, stop. A 503 "high demand" or a daily
quota does not clear in the next thirty seconds, and each failed item costs ~50
seconds of retry backoff — LangChain's three attempts times the client's three,
behind the shared rate limiter. Grinding through forty of those produces a wall of
tracebacks and no information."""

# Substrings that mean "the provider, not our code". Deliberately narrow: a
# ValidationError from our own schema is a result to record, not an outage.
_PROVIDER_FAILURES = ("503", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "429", "quota")


class ProviderUnavailable(RuntimeError):
    """The provider failed repeatedly, so the run stopped early. Whatever
    succeeded is already in the log and a later --resume picks up from there."""


CONFIGURATIONS = {
    "keyword": KeywordConfiguration,
    "llm_only": LlmOnlyConfiguration,
    "full": FullConfiguration,
}
DEFAULT_LOG = Path("data/eval-runs/predictions.jsonl")
DEFAULT_OUT = Path("../docs/eval-reports")
CATEGORY_LABELS = [c.value for c in Category]


# ── the predictions log ─────────────────────────────────────────────────────


def _key(config_label: str, item_id: str) -> str:
    return f"{config_label}::{item_id}"


def load_log(path: Path) -> dict[str, Prediction]:
    """Reusable predictions from earlier runs, by (config, item).

    **Errored predictions are deliberately excluded.** The log exists so a
    two-hour sweep survives an interruption, but a 503 "high demand" or a quota
    429 is not an answer — reusing it would bake a transient outage into the
    dataset permanently and the report would blame the model for the weather. The
    rows are still written and still readable; they are just not treated as
    results. A resumed run retries exactly those items.
    """
    if not path.exists():
        return {}
    found: dict[str, Prediction] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        payload = row["prediction"]
        if payload.get("error"):
            continue
        found[_key(row["config"], row["item"])] = Prediction(
            valid=payload["valid"],
            category=Category(payload["category"]) if payload["category"] else None,
            department=payload["department"],
            risk_band=RiskLevel(payload["risk_band"]) if payload["risk_band"] else None,
            priority=payload["priority"],
            latency_ms=payload["latency_ms"],
            input_tokens=payload["input_tokens"],
            output_tokens=payload["output_tokens"],
            error=payload["error"],
        )
    return found


def append_log(path: Path, *, config: str, item_id: str, dataset: str,
               prediction: Prediction) -> None:
    """One line per prediction, flushed immediately: the point is surviving a
    crash, so buffering would defeat it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(prediction)
    payload["category"] = prediction.category.value if prediction.category else None
    payload["risk_band"] = prediction.risk_band.value if prediction.risk_band else None
    payload.pop("evidence", None)  # chunks are persisted as rows, not in the log
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"config": config, "item": item_id,
                                 "dataset_hash": dataset, "prediction": payload}) + "\n")
        handle.flush()


def _is_provider_failure(error: str | None) -> bool:
    """True for an outage or a quota wall, false for our own errors."""
    return bool(error) and any(marker in error for marker in _PROVIDER_FAILURES)


def force_flash_tier() -> dict[str, tuple[str, str]]:
    """Move every strong-tier task the eval uses onto the flash tier.

    The free tier allows 20 strong-model requests per day and one three-column
    sweep needs about five times that, so without this the `full` column cannot be
    measured at all on a free key.

    This is a real trade, not a workaround: holding the model constant across the
    three columns is *better* experimental design for the comparison they exist to
    make, but it means the risk numbers no longer describe the model production
    actually uses for assess_risk. It is only acceptable because the return value
    lands in the report's provenance, where a reader cannot miss it.

    Mutating TASK_MODEL is the documented way to do this — see the note on that
    dict in app/ai/llm.py, which exists for exactly this case.
    """
    from app.ai.llm import TASK_MODEL, Task

    changed: dict[str, tuple[str, str]] = {}
    for task in (Task.ASSESS_RISK, Task.INVESTIGATE):
        was = TASK_MODEL[task]
        if was == settings.gemini_model:
            continue
        TASK_MODEL[task] = settings.gemini_model
        changed[task.value] = (was, settings.gemini_model)
    return changed


def take_slice(items: list[GoldenItem], limit: int | None) -> list[GoldenItem]:
    """A deterministic slice that spans the dataset.

    Two runs at the same limit must give the same items, or small runs cannot be
    compared with each other. But taking the first N by id took only `amb-*` items
    in the first real sweep, so a 20-item run measured nothing but the ambiguous
    slice while the report looked like a general sample.

    So: order by id inside each primary tag, then deal round-robin across tags. The
    result is stable, and every slice of the dataset appears before any slice is
    exhausted.
    """
    ordered = sorted(items, key=lambda i: i.id)
    if limit is None or limit >= len(ordered):
        return ordered

    by_tag: dict[str, list[GoldenItem]] = {}
    for item in ordered:
        # The first tag is the item's primary character; untagged items share a bucket.
        by_tag.setdefault(item.tags[0] if item.tags else "untagged", []).append(item)

    taken: list[GoldenItem] = []
    round_index = 0
    while len(taken) < limit:
        added = False
        for tag in sorted(by_tag):
            bucket = by_tag[tag]
            if round_index < len(bucket) and len(taken) < limit:
                taken.append(bucket[round_index])
                added = True
        if not added:
            break
        round_index += 1
    return taken


# ── scoring ─────────────────────────────────────────────────────────────────


def summarise(label: str, items: list[GoldenItem], predictions: list[Prediction],
              *, reused: int, rates) -> ConfigurationSummary:
    """Turn predictions into the numbers the report prints.

    Every metric is computed over the items where *both* sides have a value, and
    nothing is invented: a configuration with no risk model yields None for the
    risk rows rather than 0.0.
    """
    errored = sum(1 for p in predictions if p.error)
    # Every pair list below is built over *all* predictions, filtered on the field
    # it needs. Dropping an item because it carried any error at all threw away
    # ten good classifications in the first real sweep: the free tier caps the
    # strong model at 20 requests a day, so assess_risk started failing while
    # classify kept working perfectly. A metric is scored over the items where its
    # own field exists.
    scored = list(zip(items, predictions))

    valid_pairs = [(i.expected_valid, p.valid) for i, p in scored if p.valid is not None]
    category_pairs = [(i.expected_category.value, p.category.value) for i, p in scored
                      if i.expected_category and p.category]
    band_pairs = [(i.expected_risk_band.value, p.risk_band.value) for i, p in scored
                  if i.expected_risk_band and p.risk_band]
    priority_pairs = [(i.expected_priority, p.priority) for i, p in scored
                      if i.expected_priority is not None and p.priority is not None]
    department_pairs = [(i.expected_department, p.department) for i, p in scored
                       if i.expected_department and p.department]

    invalid_precision, invalid_recall = metrics.precision_recall(
        [t for t, _ in valid_pairs], [p for _, p in valid_pairs], positive=False,
    )
    input_tokens = _total(p.input_tokens for p in predictions)
    output_tokens = _total(p.output_tokens for p in predictions)

    return ConfigurationSummary(
        label=label,
        items=len(predictions),
        errored=errored,
        reused=reused,
        metrics={
            "classification_accuracy": metrics.accuracy([t for t, _ in category_pairs],
                                                        [p for _, p in category_pairs]),
            "macro_f1": metrics.macro_f1([t for t, _ in category_pairs],
                                         [p for _, p in category_pairs], labels=CATEGORY_LABELS),
            "department_accuracy": metrics.accuracy([t for t, _ in department_pairs],
                                                    [p for _, p in department_pairs]),
            "risk_band_accuracy": metrics.accuracy([t for t, _ in band_pairs],
                                                   [p for _, p in band_pairs]),
            "priority_mae": metrics.mean_absolute_error([t for t, _ in priority_pairs],
                                                        [p for _, p in priority_pairs]),
            "invalid_precision": invalid_precision,
            "invalid_recall": invalid_recall,
            "latency_p95_ms": metrics.percentile([p.latency_ms for p in predictions], 95),
        },
        confusion=metrics.confusion_matrix([t for t, _ in category_pairs],
                                           [p for _, p in category_pairs],
                                           labels=CATEGORY_LABELS) if category_pairs else {},
        per_tag=_per_tag(scored),
        counts={
            "classification_accuracy": len(category_pairs),
            "macro_f1": len(category_pairs),
            "department_accuracy": len(department_pairs),
            "risk_band_accuracy": len(band_pairs),
            "priority_mae": len(priority_pairs),
            "invalid_precision": len(valid_pairs),
            "invalid_recall": len(valid_pairs),
            "latency_p95_ms": len(predictions),
        },
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=estimated_cost(input_tokens, output_tokens, rates),
    )


def _total(values) -> int | None:
    """None when nothing reported usage — not 0, which would read as "free"."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _per_tag(scored: list[tuple[GoldenItem, Prediction]]) -> dict[str, float | None]:
    """Accuracy within each slice of the dataset.

    For an injection item, "correct" means the risk band the text tried to
    override did not move — the measurement is not whether the model refused.
    """
    tags = sorted({t for item, _ in scored for t in item.tags})
    per_tag: dict[str, float | None] = {}
    for tag in tags:
        subset = [(i, p) for i, p in scored if tag in i.tags]
        # Each slice scores the thing it exists to test, and only over items where
        # the configuration actually produced that thing. A configuration with no
        # risk model must read "not applicable" on the injection slice rather than
        # 0.00 — scoring its silence as a wrong answer would be the same invented
        # number this harness refuses everywhere else.
        if tag == "injection":
            pairs = [(i.expected_risk_band.value, p.risk_band.value)
                     for i, p in subset if i.expected_risk_band and p.risk_band]
        elif tag == "junk":
            pairs = [(i.expected_valid, p.valid) for i, p in subset if p.valid is not None]
        else:
            pairs = [(i.expected_category.value, p.category.value)
                     for i, p in subset if i.expected_category and p.category]
        per_tag[tag] = metrics.accuracy([t for t, _ in pairs], [p for _, p in pairs]) if pairs else None
    return per_tag


# ── the run ─────────────────────────────────────────────────────────────────


def run(*, suite: str, config_labels: list[str], limit: int | None, out_dir: Path,
        log_path: Path, resume: bool, write_db: bool,
        flash_only: bool = False) -> tuple[Path, list[ConfigurationSummary], str]:
    tier_override = force_flash_tier() if flash_only else {}
    items = take_slice(load_golden(), limit)
    digest = dataset_hash(items)
    rates = load_cost_rates(settings.eval_cost_rates_path)
    previous = load_log(log_path) if resume else {}

    summaries = []
    for label in config_labels:
        configuration = CONFIGURATIONS[label]()
        predictions, reused, consecutive = [], 0, 0
        for index, item in enumerate(items, start=1):
            cached = previous.get(_key(label, item.id)) if resume else None
            if cached is not None:
                predictions.append(cached)
                reused += 1
                continue
            with token_counter() as counted:
                prediction = configuration.predict(item)
            prediction.input_tokens = counted.input_tokens
            prediction.output_tokens = counted.output_tokens
            predictions.append(prediction)
            append_log(log_path, config=label, item_id=item.id, dataset=digest,
                       prediction=prediction)
            if _is_provider_failure(prediction.error):
                consecutive += 1
                if consecutive >= MAX_CONSECUTIVE_PROVIDER_FAILURES:
                    raise ProviderUnavailable(
                        f"{consecutive} provider failures in a row on {label}; last was: "
                        f"{prediction.error}\n\nThe successful predictions are in "
                        f"{log_path}. Re-run the same command with --resume when the "
                        f"provider recovers; it will reuse them and retry only what failed."
                    )
            else:
                consecutive = 0
            logger.info("%s %d/%d %s -> %s (%dms)%s", label, index, len(items), item.id,
                        prediction.category.value if prediction.category else
                        ("invalid" if prediction.valid is False else "error"),
                        prediction.latency_ms, f" [{prediction.error}]" if prediction.error else "")
        summaries.append(summarise(label, items, predictions, reused=reused, rates=rates))
        if write_db:
            _record(suite, label, digest, summaries[-1])

    provenance = _provenance(digest, rates)
    provenance["model_tier_override"] = tier_override
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}.md"
    report_path.write_text(render_report(summaries, provenance=provenance), encoding="utf-8")
    return report_path, summaries, digest


def _provenance(digest: str, rates) -> dict:
    from app.ai.graph.build import GRAPH_VERSION
    from app.ai.prompts import LATEST
    from app.evals.record import git_sha

    return {
        "dataset_name": "golden_v1",
        "dataset_hash": digest,
        "git_sha": git_sha(),
        "graph_version": GRAPH_VERSION,
        "prompt_versions": dict(LATEST),
        "models": {"flash": settings.gemini_model, "strong": settings.gemini_model_strong},
        "requests_per_second": settings.llm_requests_per_second,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cost_rates_source": rates.source if rates else None,
        "model_tier_override": {},
    }


def _record(suite: str, label: str, digest: str, summary: ConfigurationSummary) -> None:
    from app.db.session import SessionLocal
    from app.evals.record import record_metrics, start_run

    session = SessionLocal()
    try:
        run_row = start_run(session, suite=suite, config_label=label,
                            dataset_name="golden_v1", dataset_hash=digest)
        record_metrics(session, run_row,
                       {k: (v, None) for k, v in summary.metrics.items()}, finished=True)
        session.commit()
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the golden evaluation set.")
    parser.add_argument("--suite", default="core")
    parser.add_argument("--config", default="all", choices=[*CONFIGURATIONS, "all"])
    parser.add_argument("--limit", type=int, default=None,
                        help="the first N items by id — a deterministic slice, not a sample")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG,
                        help="the predictions log that makes --resume possible")
    parser.add_argument("--resume", action="store_true",
                        help="reuse predictions already in the log instead of calling the model")
    parser.add_argument("--no-db", action="store_true", help="do not write EvalRun rows")
    parser.add_argument("--flash-only", action="store_true",
                        help="run every chain on the flash tier so a free key can "
                             "finish a sweep; disclosed in the report")
    parser.add_argument("--gate", action="store_true",
                        help="exit nonzero if the full configuration's macro-F1 regressed")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    labels = list(CONFIGURATIONS) if args.config == "all" else [args.config]
    try:
        path, summaries, digest = run(
            suite=args.suite, config_labels=labels, limit=args.limit, out_dir=args.out,
            log_path=args.log, resume=args.resume, write_db=not args.no_db,
            flash_only=args.flash_only,
        )
    except ProviderUnavailable as exc:
        # Not a traceback: this is an expected outcome on a free tier, and the
        # operator needs the next command rather than a stack.
        print(f"\nstopped: {exc}", file=sys.stderr)
        return 3
    print(f"\nreport: {path}")

    if not args.gate:
        return 0
    return _gate(summaries, digest)


def _gate(summaries: list[ConfigurationSummary], digest: str) -> int:
    """Compare the `full` column against the stored baseline.

    The gate is about the configuration that ships, so a run that did not include
    `full` cannot gate — and says so rather than passing.
    """
    from app.evals.gate import NoBaseline, check_gate, load_baseline

    full = next((s for s in summaries if s.label == "full"), None)
    if full is None:
        print("gate: this run did not include the 'full' configuration, so there is "
              "nothing to gate on", flush=True)
        return 1

    baseline = load_baseline()
    try:
        result = check_gate(current=full.metrics.get("macro_f1"),
                            baseline=baseline.macro_f1 if baseline else None,
                            current_dataset=digest,
                            baseline_dataset=baseline.dataset_hash if baseline else None)
    except (NoBaseline, ValueError) as exc:
        print(f"gate: FAIL — {exc}")
        return 1
    print(f"gate: {'PASS' if result.passed else 'FAIL'} — {result.summary}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
