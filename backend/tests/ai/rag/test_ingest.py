from pathlib import Path

from app.ai.rag.chunking import CORPUS_DIR
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.ingest import IngestReport, ingest_policy_corpus, load_policy_retriever
from app.db.models.ai import Document, DocumentChunk


def _mini_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "sop_roads.md").write_text(
        "---\ntitle: Roads SOP\ncollection: policy\ncategory: ROADS\n---\n\n# Roads SOP\n\n"
        "## Scope\n\nPotholes and surface cracks on existing roads.\n\n"
        "## Response norms\n\nCritical within 4 hours.\n", encoding="utf-8")
    (corpus / "sla_policy.md").write_text(
        "---\ntitle: SLA\ncollection: policy\n---\n\n# SLA policy\n\n## Windows\n\n"
        "Critical 4 hours, high 24 hours, medium 72 hours, low 168 hours.\n", encoding="utf-8")
    return corpus


def test_ingest_indexes_every_file_and_records_it(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    report = ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                                  session_factory=lambda: db_session, corpus_dir=corpus)
    assert isinstance(report, IngestReport)
    assert report.documents == 2
    assert report.chunks >= 2
    assert (tmp_path / "idx" / "manifest.json").exists()

    docs = db_session.query(Document).all()
    assert {d.source_path for d in docs} == {"sop_roads.md", "sla_policy.md"}
    assert all(d.embedding_model == "fake@768" for d in docs)
    assert all(d.collection == "policy" for d in docs)
    assert db_session.query(DocumentChunk).count() == report.chunks


def test_ingest_is_idempotent_on_content(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    kwargs = dict(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                  session_factory=lambda: db_session, corpus_dir=corpus)
    ingest_policy_corpus(**kwargs)
    second = ingest_policy_corpus(**kwargs)
    assert second.skipped_unchanged == 2
    assert db_session.query(Document).count() == 2, "unchanged files must not duplicate rows"


def test_a_changed_file_is_reindexed_and_old_chunks_replaced(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    kwargs = dict(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                  session_factory=lambda: db_session, corpus_dir=corpus)
    first = ingest_policy_corpus(**kwargs)
    (corpus / "sop_roads.md").write_text(
        (corpus / "sop_roads.md").read_text() + "\n## Escalation\n\nWard then block then district.\n",
        encoding="utf-8")
    second = ingest_policy_corpus(**kwargs)

    assert second.skipped_unchanged == 1
    roads = db_session.query(Document).filter_by(source_path="sop_roads.md").one()
    assert db_session.query(DocumentChunk).filter_by(document_id=roads.id).count() > 0
    assert db_session.query(Document).count() == 2
    assert db_session.query(DocumentChunk).count() == second.chunks


def test_the_loaded_retriever_finds_a_policy_chunk_with_a_citation(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                         session_factory=lambda: db_session, corpus_dir=corpus)
    retriever = load_policy_retriever(embedder=FakeEmbedder(), index_dir=tmp_path / "idx")
    hits = retriever.search("critical response window hours", k=2)
    assert hits
    top = hits[0].chunk
    assert top.source in {"sop_roads.md", "sla_policy.md"}
    assert top.metadata["headers"], "a policy hit must be citable by section"


def test_the_real_corpus_ingests_end_to_end(db_session, tmp_path):
    """The authored corpus, the chunker, the store and the DB rows all agree."""
    report = ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                                  session_factory=lambda: db_session, corpus_dir=CORPUS_DIR)
    assert report.documents == 16
    assert report.chunks >= 16
