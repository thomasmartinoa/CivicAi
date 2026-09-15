"""Build the policy index from the corpus, and record what was indexed.

Idempotent on content: a file whose hash matches its Document row is skipped, a
changed file is re-chunked and its old DocumentChunk rows replaced. The whole
FAISS index is rebuilt each run — with a few hundred chunks that costs seconds,
and it keeps the sidecar and the DB rows trivially consistent.

Run with: python -m app.ai.rag.ingest
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


@dataclass
class IngestReport:
    documents: int
    chunks: int
    skipped_unchanged: int
    index_dir: Path


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_policy_corpus(
    *,
    embedder: Embedder,
    index_dir: Path,
    session_factory: Callable,
    corpus_dir: Path = CORPUS_DIR,
) -> IngestReport:
    from app.db.models.ai import Document, DocumentChunk

    session = session_factory()
    try:
        all_chunks: list[Chunk] = []
        skipped = 0

        for path, text in load_corpus(corpus_dir):
            digest = _content_hash(text)
            doc = session.query(Document).filter_by(
                collection=COLLECTION, source_path=path.name
            ).one_or_none()

            chunks = chunk_markdown(text, path.name)
            if doc is not None and doc.content_hash == digest and doc.embedding_model == embedder.model_tag:
                skipped += 1
                # still needs to be in the rebuilt index
                all_chunks.extend(chunks)
                continue

            if doc is None:
                doc = Document(collection=COLLECTION, source_path=path.name)
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

        session.commit()

        store = FaissStore(embedder)
        store.add(all_chunks)
        store.save(index_dir)

        documents = session.query(Document).filter_by(collection=COLLECTION).count()
        logger.info("indexed %d documents, %d chunks (%d unchanged) into %s",
                    documents, len(all_chunks), skipped, index_dir)
        return IngestReport(documents=documents, chunks=len(all_chunks),
                            skipped_unchanged=skipped, index_dir=index_dir)
    finally:
        session.close()


def load_policy_retriever(*, embedder: Embedder, index_dir: Path) -> HybridRetriever:
    store = FaissStore.load(index_dir, embedder)
    return HybridRetriever(DenseRetriever(store), BM25Retriever(store.chunks))


def main() -> None:
    from app.ai.rag.embeddings import build_embedder
    from app.config import settings
    from app.db.session import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = ingest_policy_corpus(
        embedder=build_embedder(),
        index_dir=Path(settings.rag_index_dir),
        session_factory=SessionLocal,
    )
    print(f"{report.documents} documents, {report.chunks} chunks -> {report.index_dir}")


if __name__ == "__main__":
    main()
