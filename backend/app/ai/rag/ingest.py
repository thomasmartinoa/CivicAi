"""Build the retrieval indexes from their sources, and record what was indexed.

Idempotent on content: a file whose hash matches its Document row is skipped, a
changed file is re-chunked and its old DocumentChunk rows replaced. The whole
FAISS index is rebuilt each run — with a few hundred chunks that costs seconds,
and it keeps the sidecar and the DB rows trivially consistent.

Run with: python -m app.ai.rag.ingest [--collection policy|cases|all]
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.ai.rag.chunking import CORPUS_DIR, Chunk, chunk_markdown, load_corpus
from app.ai.rag.embeddings import Embedder
from app.ai.rag.retrievers import BM25Retriever, DenseRetriever, HybridRetriever
from app.ai.rag.store import FaissStore
from app.db.base import utcnow

logger = logging.getLogger(__name__)

COLLECTION = "policy"


def collection_index_dir(base: Path, collection: str) -> Path:
    """Each collection gets its own subdirectory, so rebuilding one never touches another."""
    return base / collection


@dataclass
class IngestReport:
    documents: int
    chunks: int
    skipped_unchanged: int
    index_dir: Path
    removed: int = 0


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sync_collection(
    session,
    *,
    collection: str,
    items: list[tuple[str, str, list[Chunk]]],
    embedder: Embedder,
    index_dir: Path,
) -> IngestReport:
    """Bring the Document/DocumentChunk rows for one collection in line with
    `items` (source, full text, chunks), then rebuild that collection's index.

    Idempotent on content hash and embedder tag; prunes rows whose source is
    no longer in `items`. Saves the index before committing, so a failed save
    leaves no row claiming its content was indexed.
    """
    from app.db.models.ai import Document, DocumentChunk

    all_chunks: list[Chunk] = []
    skipped = 0
    seen: set[str] = set()

    for source, text, chunks in items:
        seen.add(source)
        digest = _content_hash(text)
        doc = session.query(Document).filter_by(collection=collection, source_path=source).one_or_none()
        if doc is not None and doc.content_hash == digest and doc.embedding_model == embedder.model_tag:
            skipped += 1
            # still needs to be in the rebuilt index
            all_chunks.extend(chunks)
            continue

        if doc is None:
            doc = Document(collection=collection, source_path=source)
            session.add(doc)
            session.flush()
        else:
            session.query(DocumentChunk).filter_by(document_id=doc.id).delete()

        doc.title = chunks[0].metadata.get("title") if chunks else None
        doc.content_hash = digest
        doc.chunk_count = len(chunks)
        doc.embedding_model = embedder.model_tag
        doc.indexed_at = utcnow()
        for seq, chunk in enumerate(chunks):
            session.add(DocumentChunk(
                document_id=doc.id, seq=seq, text=chunk.text,
                metadata_json={**chunk.metadata, "chunk_id": chunk.chunk_id},
            ))
        all_chunks.extend(chunks)

    # Sources that left the collection since the last run -- a deleted corpus
    # file, a work order that is no longer completed. Their rows must not
    # outlive the index, or the registry silently drifts from reality.
    orphans_query = session.query(Document).filter_by(collection=collection)
    if seen:
        orphans_query = orphans_query.filter(~Document.source_path.in_(seen))
    orphans = orphans_query.all()
    for orphan in orphans:
        session.query(DocumentChunk).filter_by(document_id=orphan.id).delete()
        session.delete(orphan)

    # Save the index before committing the DB: a failed save must not leave
    # rows claiming their content was indexed.
    store = FaissStore(embedder)
    store.add(all_chunks)
    store.save(index_dir)

    session.commit()

    documents = session.query(Document).filter_by(collection=collection).count()
    logger.info("indexed %d %s documents, %d chunks (%d unchanged, %d removed) into %s",
                documents, collection, len(all_chunks), skipped, len(orphans), index_dir)
    return IngestReport(documents=documents, chunks=len(all_chunks),
                        skipped_unchanged=skipped, index_dir=index_dir, removed=len(orphans))


def ingest_policy_corpus(
    *,
    embedder: Embedder,
    index_dir: Path,
    session_factory: Callable,
    corpus_dir: Path = CORPUS_DIR,
) -> IngestReport:
    session = session_factory()
    try:
        items = [(path.name, text, chunk_markdown(text, path.name))
                 for path, text in load_corpus(corpus_dir)]
        return _sync_collection(session, collection=COLLECTION, items=items,
                                embedder=embedder, index_dir=index_dir)
    finally:
        session.close()


def load_policy_retriever(*, embedder: Embedder, index_dir: Path) -> HybridRetriever:
    store = FaissStore.load(index_dir, embedder)
    return HybridRetriever(DenseRetriever(store), BM25Retriever(store.chunks))


def main(argv: list[str] | None = None) -> None:
    import argparse

    from app.ai.rag.cases import CASES_COLLECTION, ingest_cases
    from app.ai.rag.embeddings import build_embedder
    from app.config import settings
    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser(description="Build the retrieval indexes.")
    parser.add_argument("--collection", choices=[COLLECTION, CASES_COLLECTION, "all"], default=COLLECTION)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    embedder = build_embedder()
    if args.collection in (COLLECTION, "all"):
        report = ingest_policy_corpus(
            embedder=embedder, session_factory=SessionLocal,
            index_dir=collection_index_dir(settings.rag_index_path, COLLECTION),
        )
        print(f"policy: {report.documents} documents, {report.chunks} chunks -> {report.index_dir}")
    if args.collection in (CASES_COLLECTION, "all"):
        report = ingest_cases(
            embedder=embedder, session_factory=SessionLocal,
            index_dir=collection_index_dir(settings.rag_index_path, CASES_COLLECTION),
        )
        print(f"cases: {report.documents} documents, {report.chunks} chunks -> {report.index_dir}")


if __name__ == "__main__":
    main()
