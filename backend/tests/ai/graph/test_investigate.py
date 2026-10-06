"""The investigate loop: retrieve the taxonomy, re-classify, repeat at most
MAX_INVESTIGATE_TURNS times. Every path must terminate."""

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END

from app.ai.graph.edges import CONFIDENCE_THRESHOLD, MAX_INVESTIGATE_TURNS, after_classify, after_investigate
from app.ai.graph.nodes.investigate import investigate_node
from app.ai.schemas import ClassificationResult
from app.constants import Category
from tests.ai.graph.conftest import raises, returns
from tests.ai.graph.test_retrieval import FakeRetriever, _hit


def _taxonomy():
    return FakeRetriever([
        _hit("ROADS covers surface damage. A trench left by a utility is CONSTRUCTION.", "category_taxonomy.md", ["Category Taxonomy", "ROADS"]),
        _hit("CONSTRUCTION covers excavation left unrepaired.", "category_taxonomy.md", ["Category Taxonomy", "CONSTRUCTION"]),
        _hit("Roads scope: potholes and cracks.", "sop_roads.md", ["Roads SOP", "Scope"]),
    ])


def _unsure(base_state, turns=0):
    return {**base_state, "investigate_turns": turns,
            "classification": ClassificationResult(category=Category.ROADS, confidence=0.4, reasoning="could be a trench")}


def test_low_confidence_goes_to_investigate(base_state):
    assert after_classify(_unsure(base_state)) == "investigate"


def test_confident_classifications_skip_investigation(base_state):
    state = {**base_state, "classification": ClassificationResult(category=Category.ROADS, confidence=CONFIDENCE_THRESHOLD)}
    assert after_classify(state) == "assess_risk"


def test_investigate_reclassifies_with_taxonomy_evidence(make_config, base_state):
    seen = {}
    def capture(payload):
        seen.update(payload)
        return ClassificationResult(category=Category.CONSTRUCTION, confidence=0.85, reasoning="an unfilled utility trench [1]")
    config = make_config(investigate_chain=RunnableLambda(capture), policy_retriever=_taxonomy())
    update = investigate_node(_unsure(base_state), config)

    assert update["classification"].category == Category.CONSTRUCTION
    assert update["investigate_turns"] == 1
    assert seen["previous_category"] == "ROADS"
    assert seen["previous_confidence"] == 0.4
    assert "[1] category_taxonomy.md › Category Taxonomy › ROADS" in seen["evidence"]
    assert all(c.node == "investigate" for c in update["evidence"])
    assert update["decision_log"][-1].node == "investigate"


def test_each_turn_widens_the_taxonomy_search(make_config, base_state):
    retriever = _taxonomy()
    config = make_config(investigate_chain=returns(ClassificationResult(category=Category.ROADS, confidence=0.5)),
                         policy_retriever=retriever)
    investigate_node(_unsure(base_state, turns=0), config)
    investigate_node(_unsure(base_state, turns=1), config)
    taxonomy_calls = [c for c in retriever.calls if c["filters"] == {"doc_type": "taxonomy"}]
    assert taxonomy_calls[0]["k"] < taxonomy_calls[1]["k"]
    assert any(c["filters"] == {"doc_type": "sop"} for c in retriever.calls)


def test_a_failed_turn_keeps_the_previous_answer_and_still_counts(make_config, base_state):
    config = make_config(investigate_chain=raises(RuntimeError("quota")), policy_retriever=_taxonomy())
    update = investigate_node(_unsure(base_state, turns=1), config)
    assert update["investigate_turns"] == 2
    assert update["classification"].category == Category.ROADS
    assert update["errors"] == ["investigate: quota"]


def test_the_loop_exits_when_confident(base_state):
    state = {**base_state, "investigate_turns": 1,
             "classification": ClassificationResult(category=Category.CONSTRUCTION, confidence=0.9)}
    assert after_investigate(state) == "assess_risk"


def test_the_loop_repeats_while_unsure_and_turns_remain(base_state):
    assert after_investigate(_unsure(base_state, turns=1)) == "investigate"


def test_the_loop_gives_up_after_max_turns(base_state):
    assert after_investigate(_unsure(base_state, turns=MAX_INVESTIGATE_TURNS)) == "assess_risk"


def test_a_missing_classification_ends_the_run(base_state):
    assert after_investigate({**base_state, "classification": None, "investigate_turns": 1}) == END
