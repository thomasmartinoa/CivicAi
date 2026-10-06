"""The corpus status endpoint.

The case that matters is the missing index. Every node treats retrieval as a soft
dependency and carries on without it, so a missing index does not stop the pipeline —
it silently strips the citations from everything processed while it is gone. This
endpoint is how anybody would notice.
"""

import json

import pytest

from app.db.models.core import User
from app.services.auth import create_access_token, hash_password


@pytest.fixture
def officer(db_session, client):
    user = db_session.query(User).filter(User.role.in_(("officer", "admin"))).first()
    user.password_hash = hash_password("pw")
    db_session.commit()
    return user


@pytest.fixture
def auth(officer):
    return {"Authorization": f"Bearer {create_access_token(user_id=officer.id, role=officer.role)}"}


@pytest.fixture
def index_dir(tmp_path, monkeypatch):
    """Point the app at an empty index directory, so these tests never read the real
    one and never depend on whether someone has run the ingest."""
    from app.config import settings

    monkeypatch.setattr(type(settings), "rag_index_path",
                        property(lambda self: tmp_path))
    return tmp_path / "policy"


def _write_index(index_dir, chunks, manifest=None):
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "chunks.json").write_text(json.dumps(chunks))
    (index_dir / "manifest.json").write_text(json.dumps(
        manifest or {"model_tag": "gemini-embedding-001@768", "dim": 768, "count": len(chunks)}))
    (index_dir / "index.faiss").write_bytes(b"not a real index")


def _chunk(source, text="some policy text", title="A SOP", section="Ownership"):
    return {"text": text, "source": source, "chunk_id": f"{source}:{section}",
            "metadata": {"title": title, "collection": "policy", "doc_type": "sop",
                         "headers": [title, section]}}


# ── the case that matters ───────────────────────────────────────────────────


def test_a_missing_index_is_reported_loudly_rather_than_as_an_empty_list(
        client, auth, index_dir):
    """Retrieval is a soft dependency, so a missing index does not stop anything —
    it quietly removes the citations from every decision made while it is gone. An
    empty document list would look like a corpus with no documents in it."""
    body = client.get("/admin/corpus", headers=auth).json()
    assert body["available"] is False
    assert body["documents"] == []
    assert "no citations" in body["error"].lower()
    assert "ingest" in body["error"], "the message should say how to fix it"


def test_an_unreadable_index_reports_the_error_rather_than_raising(client, auth, index_dir):
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "chunks.json").write_text("{ this is not json")

    body = client.get("/admin/corpus", headers=auth).json()
    assert body["available"] is False
    assert "could not be read" in body["error"]


# ── the normal case ─────────────────────────────────────────────────────────


def test_documents_are_grouped_with_their_chunk_and_character_counts(client, auth, index_dir):
    _write_index(index_dir, [
        _chunk("sop_roads.md", text="a" * 100, title="Roads SOP", section="Ownership"),
        _chunk("sop_roads.md", text="b" * 50, title="Roads SOP", section="Escalation"),
        _chunk("rate_card.md", text="c" * 30, title="Rate Card", section="Purpose"),
    ])

    body = client.get("/admin/corpus", headers=auth).json()
    assert body["available"] is True
    assert body["chunk_count"] == 3
    assert body["document_count"] == 2

    roads = next(d for d in body["documents"] if d["source"] == "sop_roads.md")
    assert roads["chunks"] == 2
    assert roads["characters"] == 150
    assert roads["sections"] == ["Ownership", "Escalation"]
    assert roads["title"] == "Roads SOP"


def test_the_embedding_model_is_reported(client, auth, index_dir):
    """An index built with a different embedder than the one configured retrieves
    nonsense, so which model built it is not a detail."""
    _write_index(index_dir, [_chunk("sop_roads.md")])
    body = client.get("/admin/corpus", headers=auth).json()
    assert body["embedding_model"] == "gemini-embedding-001@768"
    assert body["dimensions"] == 768


def test_documents_are_in_a_stable_order(client, auth, index_dir):
    """A list that reorders between refreshes is one nobody can scan."""
    _write_index(index_dir, [_chunk("sop_water.md"), _chunk("category_taxonomy.md"),
                             _chunk("rate_card.md")])
    sources = [d["source"] for d in client.get("/admin/corpus", headers=auth).json()["documents"]]
    assert sources == sorted(sources)


def test_a_missing_manifest_does_not_hide_the_chunks(client, auth, index_dir):
    """The chunk store is what the retriever loads; the manifest is metadata about
    it. Losing the second should not make the first invisible."""
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "chunks.json").write_text(json.dumps([_chunk("sop_roads.md")]))

    body = client.get("/admin/corpus", headers=auth).json()
    assert body["available"] is True
    assert body["chunk_count"] == 1
    assert body["embedding_model"] is None


# ── access ──────────────────────────────────────────────────────────────────


def test_the_corpus_needs_an_officer(client, db_session, index_dir):
    assert client.get("/admin/corpus").status_code == 401
    citizen = User(email="c@example.com", name="C", role="citizen",
                   password_hash=hash_password("pw"))
    db_session.add(citizen)
    db_session.commit()
    token = create_access_token(user_id=citizen.id, role="citizen")
    assert client.get("/admin/corpus",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_there_is_no_way_to_rebuild_the_index_through_the_api(client, auth):
    """Rebuilding is destructive to the thing every grounded decision depends on, and
    this codebase has no confirmation mechanism — the same argument that kept
    mutation tools out of the officer agent."""
    from app.main import app

    corpus_routes = {
        (r.path, m) for r in app.routes
        for m in getattr(r, "methods", ()) or ()
        if "corpus" in r.path
    }
    assert corpus_routes == {("/admin/corpus", "GET")}
