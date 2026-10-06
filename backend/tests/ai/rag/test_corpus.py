import re

from app.ai.rag.chunking import CORPUS_DIR, chunk_markdown, load_corpus
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.retrievers import BM25Retriever, DenseRetriever, HybridRetriever
from app.ai.rag.store import FaissStore
from app.constants import CATEGORY_DEPARTMENT, DEFAULT_SLA_HOURS, Category
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


def test_response_norms_agree_with_the_default_sla_hours():
    """The corpus and the code must not disagree about the SLA.

    Checking the level name and the hour count occur *anywhere* in the
    document isn't load-bearing: swapping which level gets which window
    still passes as long as all four numbers appear somewhere. Requiring
    them in the same sentence catches that.
    """
    text = next(t for p, t in load_corpus() if p.name == "sla_policy.md")
    for level, hours in DEFAULT_SLA_HOURS.items():
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


def test_every_corpus_file_declares_a_doc_type():
    """A category filter can't reach rate_card.md or contractor_scoring.md,
    which carry no category. doc_type covers every file instead."""
    specific = {
        "rate_card.md": "rate_card",
        "sla_policy.md": "sla_policy",
        "category_taxonomy.md": "taxonomy",
        "contractor_scoring.md": "contractor_scoring",
    }
    for path, text in load_corpus():
        front_matter = text.split("---")[1]
        assert "doc_type:" in front_matter, f"{path.name} missing doc_type"
        if path.name.startswith("sop_"):
            assert "doc_type: sop" in text, path.name
        elif path.name in specific:
            assert f"doc_type: {specific[path.name]}" in text, path.name


def test_a_doc_type_filter_reaches_the_rate_card():
    embedder = FakeEmbedder()
    store = FaissStore(embedder)
    all_chunks = []
    for path, text in load_corpus():
        all_chunks.extend(chunk_markdown(text, path.name))
    store.add(all_chunks)
    retriever = HybridRetriever(DenseRetriever(store), BM25Retriever(store.chunks))

    hits = retriever.search("asphalt per square metre", k=3, fetch_k=200,
                            filters={"doc_type": "rate_card"})

    assert hits
    assert all(h.chunk.source == "rate_card.md" for h in hits)


def test_the_rate_card_states_a_rule_for_grouped_work():
    """v1 priced a cluster at `base * count * 0.7` in Python. The discount is a
    municipal rule, so the prompt must be able to cite it — if the section is
    missing, the model is asked for a rule that does not exist and invents one.
    """
    text = next(t for p, t in load_corpus() if p.name == "rate_card.md")
    assert "## Grouped work at multiple sites" in text
    section = text.split("## Grouped work at multiple sites", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"\b\d{1,3}\s?%", section), "the grouped-work rule states no percentage"
    assert "mobilis" in section.lower(), "the rule must explain what the saving is"


def test_the_rate_card_table_is_split_by_category():
    """The fix for a measured retrieval miss lives in this document's shape, so it
    needs guarding here.

    One table spanning twelve categories chunked into a single 1,780-character
    block, so a CONSTRUCTION rate query met a chunk where "CONSTRUCTION" was two
    rows out of twenty-five and lost to the card's prose sections, which discuss
    rates in the query's own words. recall@3 for that query was 0.00 — see
    docs/07 §4.4. A subsection per category gives each one its own chunk, and the
    header-aware chunker needed no changes.
    """
    from app.ai.rag.chunking import chunk_markdown

    text = next(t for p, t in load_corpus() if p.name == "rate_card.md")
    chunks = chunk_markdown(text, "rate_card.md")

    for category in Category:
        owning = [c for c in chunks
                  if any(category.value in h for h in c.metadata.get("headers", []))]
        assert owning, f"{category.value} has no rate-card chunk of its own"
        assert len(owning) == 1, f"{category.value} rates are split across chunks"
        others = [o.value for o in Category if o is not category and o.value in owning[0].text]
        assert not others, (
            f"the {category.value} chunk also contains {others}, which is the dilution "
            "this structure exists to avoid"
        )


def test_every_rate_card_line_survived_the_restructuring():
    """Splitting the table must not have dropped or changed a rate."""
    text = next(t for p, t in load_corpus() if p.name == "rate_card.md")
    for item, rate in (("Excavation and trench reinstatement", "₹900"),
                       ("Hot-mix asphalt patching", "₹450"),
                       ("Distribution transformer (25 kVA)", "₹65,000"),
                       ("Animal capture and transport", "₹1,000"),
                       ("Larvicide treatment", "₹800")):
        line = next((l for l in text.splitlines() if item in l), None)
        assert line is not None, f"{item} is missing from the rate card"
        assert rate in line, f"{item} no longer costs {rate}: {line}"
