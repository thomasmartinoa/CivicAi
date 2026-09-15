import re

from app.ai.graph.nodes.work_order import SLA_HOURS
from app.ai.rag.chunking import CORPUS_DIR, chunk_markdown, load_corpus
from app.constants import CATEGORY_DEPARTMENT, Category
from app.db.models.core import Department


REQUIRED_SOP_SECTIONS = [
    "## Scope", "## Ownership", "## Response norms",
    "## Typical materials and cost drivers", "## Escalation",
]


def test_there_is_one_sop_per_category():
    expected = {f"sop_{c.value.lower()}.md" for c in Category}
    present = {p.name for p, _ in load_corpus()}
    assert expected <= present, f"missing SOPs: {sorted(expected - present)}"


def test_the_four_policy_documents_exist():
    present = {p.name for p, _ in load_corpus()}
    for name in ("sla_policy.md", "category_taxonomy.md", "rate_card.md", "contractor_scoring.md"):
        assert name in present


def test_every_sop_has_the_required_sections_in_order():
    for path, text in load_corpus():
        if not path.name.startswith("sop_"):
            continue
        positions = [text.find(h) for h in REQUIRED_SOP_SECTIONS]
        assert all(p >= 0 for p in positions), f"{path.name} missing a section"
        assert positions == sorted(positions), f"{path.name} sections out of order"


def test_every_sop_front_matter_names_its_category():
    for path, text in load_corpus():
        if path.name.startswith("sop_"):
            category = path.stem.removeprefix("sop_").upper()
            assert f"category: {category}" in text, path.name


def test_every_sop_names_the_seeded_department_verbatim():
    """Routing justifications will cite this; the name must match the DB."""
    for path, text in load_corpus():
        if path.name.startswith("sop_"):
            category = Category(path.stem.removeprefix("sop_").upper())
            assert CATEGORY_DEPARTMENT[category] in text, (
                f"{path.name} does not name {CATEGORY_DEPARTMENT[category]!r}"
            )


def test_response_norms_agree_with_sla_hours():
    """The corpus and the code must not disagree about the SLA.

    Checking the level name and the hour count occur *anywhere* in the
    document isn't load-bearing: swapping which level gets which window
    still passes as long as all four numbers appear somewhere. Requiring
    them in the same sentence catches that.
    """
    text = next(t for p, t in load_corpus() if p.name == "sla_policy.md")
    for level, hours in SLA_HOURS.items():
        assert re.search(rf"\b{level.value}\b[^.\n]*\b{hours}\s*hours?\b", text, re.I), (
            f"sla_policy.md does not state the {hours}h window for {level.value} "
            "in the same sentence"
        )


def test_priority_bands_agree_with_band_for_score():
    """The corpus and band_for_score() must not disagree about the bands."""
    text = next(t for p, t in load_corpus() if p.name == "sla_policy.md")
    for lo_hi, band in (
        ("0\\s*[–-]\\s*25", "low"),
        ("26\\s*[–-]\\s*50", "medium"),
        ("51\\s*[–-]\\s*75", "high"),
        ("76\\s*[–-]\\s*100", "critical"),
    ):
        assert re.search(rf"{lo_hi}[^.\n]*\b{band}\b", text, re.I), (
            f"sla_policy.md does not name {band!r} next to its score range"
        )


def test_contractor_scoring_states_the_code_weights():
    """Routing justifications cite this document; the weights must match route.py."""
    from app.ai.graph.nodes.route import (
        RATING_WEIGHT,
        SPECIALISATION_WEIGHT,
        WORKLOAD_ALLOWANCE,
        WORKLOAD_PENALTY,
        ZONE_BONUS,
    )

    text = next(t for p, t in load_corpus() if p.name == "contractor_scoring.md")
    for weight in (
        SPECIALISATION_WEIGHT, RATING_WEIGHT, WORKLOAD_ALLOWANCE,
        WORKLOAD_PENALTY, ZONE_BONUS,
    ):
        assert str(int(weight)) in text, f"contractor_scoring.md does not state {weight!r}"


def test_the_rate_card_has_a_labour_rate_and_at_least_twenty_items():
    text = next(t for p, t in load_corpus() if p.name == "rate_card.md")
    assert re.search(r"labour", text, re.I)
    assert text.count("₹") >= 20


def test_every_corpus_file_chunks_without_error_and_yields_something():
    for path, text in load_corpus():
        chunks = chunk_markdown(text, path.name)
        assert chunks, f"{path.name} produced no chunks"
        assert all(c.text.strip() for c in chunks)
