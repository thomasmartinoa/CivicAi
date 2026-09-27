"""The golden set is ground truth. A label that is wrong measures nothing, and
a slice that quietly empties makes the report claim coverage it does not have —
so the dataset's own invariants are tested as strictly as the code's.
"""

import json
from collections import Counter

import pytest

from app.constants import CATEGORY_DEPARTMENT, Category, RiskLevel
from app.evals.dataset import (
    GOLDEN_V1, TAGS, GoldenItem, dataset_hash, load_golden,
)

# The bands in corpus/sla_policy.md: 0-25 low, 26-50 medium, 51-75 high, 76-100 critical.
BANDS = {RiskLevel.LOW: (0, 25), RiskLevel.MEDIUM: (26, 50),
         RiskLevel.HIGH: (51, 75), RiskLevel.CRITICAL: (76, 100)}


def test_the_set_is_big_enough_to_mean_something():
    items = load_golden()
    assert len(items) >= 90, f"only {len(items)} items"


def test_ids_are_unique():
    items = load_golden()
    assert len({i.id for i in items}) == len(items)


def test_an_invalid_complaint_has_no_category_and_a_valid_one_does():
    """A junk item with an expected_category would score the classifier on
    something it should never have classified at all."""
    for item in load_golden():
        if item.expected_valid:
            assert item.expected_category is not None, item.id
        else:
            assert item.expected_category is None, item.id
            assert item.expected_risk_band is None, item.id


def test_every_expected_department_is_one_the_seed_creates():
    """v1 mapped two categories to departments that were never created. A golden
    set that does the same would score routing against a fiction."""
    real = set(CATEGORY_DEPARTMENT.values())
    for item in load_golden():
        if item.expected_department:
            assert item.expected_department in real, item.id


def test_the_department_follows_from_the_category():
    for item in load_golden():
        if item.expected_category and item.expected_department:
            assert CATEGORY_DEPARTMENT[item.expected_category] == item.expected_department, item.id


def test_priority_and_band_agree():
    for item in load_golden():
        if item.expected_priority is not None:
            assert item.expected_risk_band is not None, item.id
            low, high = BANDS[item.expected_risk_band]
            assert low <= item.expected_priority <= high, (
                f"{item.id}: {item.expected_priority} is not in the "
                f"{item.expected_risk_band.value} band {low}-{high}"
            )


def test_ambiguous_items_record_how_they_were_adjudicated():
    """The label is a judgement. If it is arguable, the reasoning is part of the
    dataset — otherwise a future reader cannot tell a decision from a mistake."""
    for item in load_golden():
        if "ambiguous" in item.tags or "multi_problem" in item.tags:
            assert item.adjudication, f"{item.id} is arguable with no adjudication note"


def test_every_required_slice_is_present():
    tags = Counter(t for i in load_golden() for t in i.tags)
    for name, minimum in (("injection", 6), ("junk", 10), ("ambiguous", 20),
                          ("vague", 6), ("non_english", 4), ("duplicate", 4),
                          ("multi_problem", 4), ("long", 2), ("short", 2)):
        assert tags[name] >= minimum, f"only {tags[name]} {name!r} items, need {minimum}"


def test_every_category_appears_at_least_once():
    """A category with no item is a column of the confusion matrix nobody tested."""
    present = {i.expected_category for i in load_golden() if i.expected_category}
    assert present == set(Category), f"missing: {sorted(c.value for c in set(Category) - present)}"


def test_unknown_tags_are_refused():
    """A typo'd tag silently empties a slice the report claims to cover."""
    for item in load_golden():
        assert set(item.tags) <= TAGS, f"{item.id}: {set(item.tags) - TAGS}"


def test_injection_items_carry_the_band_the_text_tries_to_override():
    """The measurement is not "did the model refuse". It is whether the injected
    instruction moved the risk band. So every injection item needs a band."""
    for item in load_golden():
        if "injection" in item.tags and item.expected_valid:
            assert item.expected_risk_band is not None, item.id


def test_descriptions_are_not_paraphrases_of_each_other():
    """100 rewordings of "there is a pothole" measures the paraphraser, not the
    classifier. Duplicates are allowed only where they are the point."""
    seen: dict[str, str] = {}
    for item in load_golden():
        key = item.description.strip().lower()
        if key in seen:
            assert "duplicate" in item.tags, f"{item.id} repeats {seen[key]} verbatim"
        seen[key] = item.id


def test_a_malformed_line_raises_rather_than_being_skipped(tmp_path):
    """A skipped line is a dataset that quietly shrank, reported at full size."""
    path = tmp_path / "broken.jsonl"
    path.write_text('{"id": "a", "description": "x", "expected_valid": false}\nnot json\n')
    with pytest.raises(ValueError, match="line 2"):
        load_golden(path)


def test_an_unknown_field_raises(tmp_path):
    """A renamed field that is silently ignored takes its labels with it."""
    path = tmp_path / "extra.jsonl"
    path.write_text('{"id": "a", "description": "x", "expected_valid": false, "categry": "ROADS"}\n')
    with pytest.raises(ValueError, match="categry"):
        load_golden(path)


def test_the_hash_changes_when_any_label_changes(tmp_path):
    """A report claims a dataset by hash. If the hash survived a label edit the
    claim would be false."""
    items = load_golden()
    before = dataset_hash(items)
    edited = [*items[:-1], GoldenItem(**{**items[-1].__dict__, "expected_priority": 99,
                                        "expected_risk_band": RiskLevel.CRITICAL})]
    assert dataset_hash(edited) != before


def test_the_hash_is_stable_across_reruns():
    assert dataset_hash(load_golden()) == dataset_hash(load_golden())


def test_the_hash_ignores_ordering():
    """Order is not part of the dataset: the runner may shuffle or shard, and
    that must not look like a different dataset in the report."""
    items = load_golden()
    assert dataset_hash(list(reversed(items))) == dataset_hash(items)


def test_the_file_is_one_object_per_line_and_readable_by_hand():
    """A golden set gets edited by a human. It stays line-oriented so a diff
    shows one changed label, not a reflowed blob."""
    for line in GOLDEN_V1.read_text(encoding="utf-8").splitlines():
        if line.strip():
            assert isinstance(json.loads(line), dict)
