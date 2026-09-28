"""Render the three-column markdown report.

Everything here is about refusing to overstate. A metric a configuration cannot
produce prints `not applicable`; a cost with no configured rates prints `not
configured`; the errored and reused counts are on the page rather than folded into
a denominator where the accuracy looks unaffected. Latency is labelled wall clock
with the rate-limit setting beside it, because on the free tier most of it is
waiting.

The routing row carries a note that it is derived from the category: v2's seeded
departments come from CATEGORY_DEPARTMENT, so routing accuracy is a deterministic
function of classification accuracy and not independent signal. Printing it bare
would overstate what was measured.
"""

from dataclasses import dataclass, field

NOT_APPLICABLE = "not applicable"
NOT_CONFIGURED = "not configured"

# (key, label, formatter) in the order the report prints them.
METRIC_ROWS = [
    ("classification_accuracy", "Classification accuracy", "ratio"),
    ("macro_f1", "Macro-F1 (12 categories)", "ratio"),
    ("department_accuracy", "Department routing accuracy", "ratio"),
    ("risk_band_accuracy", "Risk band accuracy", "ratio"),
    ("priority_mae", "Priority MAE (points)", "points"),
    ("invalid_precision", "Invalid-complaint precision", "ratio"),
    ("invalid_recall", "Invalid-complaint recall", "ratio"),
    ("latency_p95_ms", "p95 wall clock per item", "millis"),
]


@dataclass
class ConfigurationSummary:
    label: str
    items: int
    errored: int
    metrics: dict[str, float | None]
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    per_tag: dict[str, float | None] = field(default_factory=dict)
    reused: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


def _format(value: float | None, kind: str) -> str:
    if value is None:
        return NOT_APPLICABLE
    if kind == "ratio":
        return f"{value:.2f}"
    if kind == "points":
        return f"{value:.1f}"
    if kind == "millis":
        return f"{value / 1000:.1f}s"
    return str(value)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _metrics_table(summaries: list[ConfigurationSummary]) -> str:
    headers = ["Metric", *(s.label for s in summaries)]
    rows = []
    for key, label, kind in METRIC_ROWS:
        if key == "department_accuracy":
            label += " *(derived from the category)*"
        rows.append([label, *(_format(s.metrics.get(key), kind) for s in summaries)])
    rows.append(["Items scored", *(str(s.items - s.errored) for s in summaries)])
    rows.append(["Items errored", *(str(s.errored) for s in summaries)])
    rows.append(["Predictions reused (resumed)", *(str(s.reused) for s in summaries)])
    rows.append(["Input tokens", *(str(s.input_tokens) if s.input_tokens is not None
                                   else NOT_APPLICABLE for s in summaries)])
    rows.append(["Output tokens", *(str(s.output_tokens) if s.output_tokens is not None
                                    else NOT_APPLICABLE for s in summaries)])
    rows.append(["Estimated cost", *(f"{s.cost:.4f}" if s.cost is not None
                                     else NOT_CONFIGURED for s in summaries)])
    return _table(headers, rows)


def _confusion_table(summary: ConfigurationSummary) -> str:
    labels = sorted(summary.confusion)
    headers = ["actual \\ predicted", *labels]
    rows = [[actual, *(str(summary.confusion[actual].get(p, 0)) for p in labels)]
            for actual in labels]
    return _table(headers, rows)


def _per_tag_table(summaries: list[ConfigurationSummary]) -> str:
    tags = sorted({t for s in summaries for t in s.per_tag})
    headers = ["Slice", *(s.label for s in summaries)]
    rows = [[tag, *(_format(s.per_tag.get(tag), "ratio") for s in summaries)] for tag in tags]
    return _table(headers, rows)


def render_report(summaries: list[ConfigurationSummary], *, provenance: dict) -> str:
    """The whole document, as markdown."""
    prompt_versions = " · ".join(f"{name} {version}"
                                 for name, version in sorted(provenance["prompt_versions"].items()))
    models = " · ".join(f"{tier}: {name}" for tier, name in sorted(provenance["models"].items()))

    parts = [
        f"# CivicAI evaluation — {provenance['generated_at']}",
        "",
        "## Results",
        "",
        _metrics_table(summaries),
        "",
        "Latency is **wall clock per item including rate-limit waiting**, not model "
        f"speed: this run was limited to {provenance['requests_per_second']} requests "
        "per second, and on a throttled free tier the wait dominates. "
        "Department routing accuracy is *derived from the category* — v2's seeded "
        "departments come from `CATEGORY_DEPARTMENT`, so it is a function of "
        "classification accuracy rather than a separate measurement. A cell reading "
        f"`{NOT_APPLICABLE}` means that configuration cannot produce the metric at all "
        f"(v1's keyword classifier has no risk model); `{NOT_CONFIGURED}` means no cost "
        "rates file was supplied, and no rates are ever assumed.",
        "",
        "## Accuracy by slice",
        "",
        _per_tag_table(summaries),
        "",
        "The `injection` row is the one to read first: it is the share of items whose "
        "predicted risk band survived an instruction, inside the citizen's own text, "
        "telling the model to change it.",
        "",
    ]

    for summary in summaries:
        if summary.confusion:
            parts += [f"## Confusion matrix — {summary.label}", "", _confusion_table(summary), ""]

    parts += [
        "## Provenance",
        "",
        _table(["Field", "Value"], [
            ["Dataset", f"{provenance['dataset_name']}"],
            ["Dataset hash", f"`{provenance['dataset_hash']}`"],
            ["Commit", f"`{provenance['git_sha'] or 'not a git checkout'}`"],
            ["Graph version", provenance["graph_version"]],
            ["Prompt versions", prompt_versions],
            ["Models", models],
            ["Requests per second", str(provenance["requests_per_second"])],
        ]),
        "",
    ]
    return "\n".join(parts)
