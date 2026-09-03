from app.db.models.ai import AgentRun, AgentStep, Document, DocumentChunk, RetrievedChunk
from app.db.models.evaluation import EvalResult, EvalRun


def test_agent_run_records_cost_and_trace_url(db_session):
    run = AgentRun(
        thread_id="thread-1",
        status="completed",
        graph_version="v2.0",
        duration_ms=4200,
        total_tokens=1850,
        estimated_cost=0.0021,
        langsmith_url="https://smith.langchain.com/o/x/r/y",
    )
    db_session.add(run)
    db_session.commit()

    assert run.status == "completed"
    assert run.estimated_cost == 0.0021


def test_steps_are_ordered_by_seq_within_a_run(db_session):
    run = AgentRun(thread_id="thread-2", status="running")
    db_session.add(run)
    db_session.flush()

    for seq, node in enumerate(["intake", "validate", "classify"]):
        db_session.add(AgentStep(run_id=run.id, seq=seq, node=node, status="ok"))
    db_session.commit()
    db_session.expire_all()

    steps = db_session.query(AgentStep).order_by(AgentStep.seq).all()
    assert [s.node for s in steps] == ["intake", "validate", "classify"]


def test_retrieved_chunk_records_its_score(db_session):
    run = AgentRun(thread_id="thread-3", status="completed")
    db_session.add(run)
    db_session.flush()

    db_session.add(RetrievedChunk(
        run_id=run.id, node="route", source="sop_public_works.md",
        chunk_id="c-17", score=0.83, snippet="Potholes are repaired within...",
    ))
    db_session.commit()
    assert db_session.query(RetrievedChunk).one().score == 0.83


def test_document_tracks_its_embedding_model(db_session):
    """Querying an index built by a different embedding model must be detectable."""
    doc = Document(
        collection="policy",
        source_path="corpus/sla_policy.md",
        title="SLA Policy Handbook",
        content_hash="abc123",
        chunk_count=14,
        embedding_model="gemini-embedding-001@768",
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(DocumentChunk(document_id=doc.id, seq=0, text="Priority bands..."))
    db_session.commit()

    assert db_session.query(Document).one().embedding_model.endswith("@768")


def test_eval_results_attach_to_a_run(db_session):
    run = EvalRun(suite="core", dataset_name="golden_complaints",
                  dataset_hash="deadbeef", git_sha="abc1234", config_label="v2_full")
    db_session.add(run)
    db_session.flush()

    db_session.add(EvalResult(eval_run_id=run.id, metric="category_macro_f1", value=0.91))
    db_session.commit()

    assert db_session.query(EvalResult).one().metric == "category_macro_f1"
