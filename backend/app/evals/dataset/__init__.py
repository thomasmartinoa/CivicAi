"""The golden set: labelled complaints, and the loader that refuses to guess.

This is ground truth. Every number the eval harness reports is relative to these
labels, so the loader is strict on purpose — a malformed line raises rather than
being skipped, and an unknown field raises rather than being ignored. A dataset
that quietly shrank or quietly dropped a renamed column would be reported at full
size, and the report would be wrong in a way nobody could see.

`dataset_hash` is what a report cites. It covers the labels and the text but not
the order, because the runner may shard or shuffle and that is not a different
dataset.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from app.constants import Category, RiskLevel

GOLDEN_V1 = Path(__file__).parent / "golden_v1.jsonl"

# Every tag a slice of the report is built from. Closed set: a typo would empty a
# slice the report still claims to cover.
TAGS = frozenset({
    "straightforward",   # one clear problem, one obvious category
    "ambiguous",         # two categories defensible; adjudication explains the call
    "junk",              # not an infrastructure complaint at all
    "injection",         # tries to instruct the model from inside the report
    "vague",             # real but underspecified; low confidence is correct
    "multi_problem",     # more than one fault in one report
    "non_english",       # Hindi/Kannada words, transliteration, code-switching
    "long",              # several hundred words
    "short",             # a handful of words
    "duplicate",         # near-identical to another item, for the clustering eval
})


@dataclass(frozen=True)
class GoldenItem:
    id: str
    description: str
    expected_valid: bool
    expected_category: Category | None = None
    expected_department: str | None = None
    expected_risk_band: RiskLevel | None = None
    expected_priority: int | None = None
    tags: tuple[str, ...] = ()
    adjudication: str | None = None
    cluster_group: str | None = None
    """Items sharing a group describe the same problem in the same place, and the
    clustering eval expects exactly those to be grouped together. Explicit rather
    than derived from the id, so the expectation cannot drift from the data."""

    @property
    def canonical(self) -> str:
        """The form the hash is taken over: every field, in a fixed key order."""
        payload = asdict(self)
        payload["expected_category"] = self.expected_category.value if self.expected_category else None
        payload["expected_risk_band"] = self.expected_risk_band.value if self.expected_risk_band else None
        payload["tags"] = sorted(self.tags)
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _item_from(row: dict, *, where: str) -> GoldenItem:
    known = {f.name for f in fields(GoldenItem)}
    unknown = set(row) - known
    if unknown:
        raise ValueError(f"{where}: unknown field(s) {sorted(unknown)}")
    category = row.get("expected_category")
    band = row.get("expected_risk_band")
    return GoldenItem(
        id=row["id"],
        description=row["description"],
        expected_valid=row["expected_valid"],
        expected_category=Category(category) if category else None,
        expected_department=row.get("expected_department"),
        expected_risk_band=RiskLevel(band) if band else None,
        expected_priority=row.get("expected_priority"),
        tags=tuple(row.get("tags", ())),
        adjudication=row.get("adjudication"),
        cluster_group=row.get("cluster_group"),
    )


def load_golden(path: Path = GOLDEN_V1) -> list[GoldenItem]:
    """Every item, or an error naming the line that could not be read."""
    items: list[GoldenItem] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name} line {number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{where}: not valid JSON ({exc.msg})") from exc
        try:
            items.append(_item_from(row, where=where))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{where}: {exc}") from exc
    return items


def dataset_hash(items: list[GoldenItem]) -> str:
    """sha256 over the canonical form of every item, order-independent."""
    digest = hashlib.sha256()
    for canonical in sorted(item.canonical for item in items):
        digest.update(canonical.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


__all__ = ["GOLDEN_V1", "TAGS", "GoldenItem", "dataset_hash", "load_golden"]
