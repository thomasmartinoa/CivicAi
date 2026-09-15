from app.ai.rag.chunking import Chunk, chunk_markdown, chunk_record

SAMPLE = """---
title: Sample SOP
collection: policy
category: ROADS
---

# Sample SOP

## Scope

Roads covers surface damage. A trench left by a utility is CONSTRUCTION.

## Ownership

Public Works Department owns this category.

## Response norms

Critical within 4 hours. High within 24 hours.
"""


def test_front_matter_becomes_metadata_not_text():
    chunks = chunk_markdown(SAMPLE, "sample.md")
    assert all(c.metadata["category"] == "ROADS" for c in chunks)
    assert all(c.metadata["collection"] == "policy" for c in chunks)
    assert not any("collection: policy" in c.text for c in chunks)


def test_every_chunk_records_its_header_path():
    chunks = chunk_markdown(SAMPLE, "sample.md")
    scope = next(c for c in chunks if "trench" in c.text)
    assert scope.metadata["headers"] == ["Sample SOP", "Scope"]


def test_chunks_respect_max_chars_with_overlap():
    long_section = "## Long\n\n" + ("A sentence about roads. " * 300)
    chunks = chunk_markdown("# Doc\n\n" + long_section, "long.md", max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    # overlap: the tail of one chunk appears at the head of the next
    assert chunks[0].text[-30:] in chunks[1].text


def test_chunk_ids_are_stable_and_unique():
    a = chunk_markdown(SAMPLE, "sample.md")
    b = chunk_markdown(SAMPLE, "sample.md")
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)


def test_a_record_is_exactly_one_chunk():
    chunks = chunk_record("Pothole near school, fixed in 2 days for 8000", "case:abc",
                          {"category": "ROADS", "district": "East"})
    assert len(chunks) == 1
    assert chunks[0].metadata["district"] == "East"
    assert chunks[0].source == "case:abc"


def test_chunk_is_frozen():
    import dataclasses
    c = chunk_record("x", "s", {})[0]
    assert dataclasses.is_dataclass(c) and c.__dataclass_params__.frozen


def test_table_rows_are_not_split_mid_row():
    # Rows of varying length, like a real rate card, so a naive "cut at the
    # last space" strategy lands mid-row instead of on a row boundary.
    names = [
        "Hot-mix asphalt patching", "Cold-mix asphalt (emergency)",
        "Aggregate base material", "Precast concrete kerb stone",
        "Thermoplastic road marking paint", "Excavation and trench reinstatement",
        "Barricading and warning signage", "LED street luminaire (with fitting)",
        "Concrete street lighting pole", "Armoured underground cable",
    ]
    rows = [
        f"| {names[i % len(names)]} {i} | CATEGORY | per unit | ₹{100 + i * 7} |"
        for i in range(60)
    ]
    text = "# Doc\n\n## Table\n\n" + "\n".join(rows) + "\n"
    chunks = chunk_markdown(text, "table.md", max_chars=500, overlap=50)
    assert len(chunks) > 1
    for c in chunks:
        for line in c.text.split("\n"):
            if line.strip():
                assert line.startswith("|") and line.endswith("|"), (
                    f"truncated row: {line!r}"
                )


def test_crlf_front_matter_parses_the_same_as_lf():
    crlf_sample = SAMPLE.replace("\n", "\r\n")
    chunks = chunk_markdown(crlf_sample, "sample.md")
    assert all(c.metadata["category"] == "ROADS" for c in chunks)
    assert all(c.metadata["collection"] == "policy" for c in chunks)
    assert not any("collection: policy" in c.text for c in chunks)
