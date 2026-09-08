import operator
from typing import Annotated, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from app.ai import schemas as schemas_module
from app.ai.graph.state import (
    CHECKPOINT_ALLOWLIST, ComplaintState, build_serializer, initial_state,
)
from app.ai.schemas import Coords, MediaRef


ACCUMULATING = ["media_insights", "evidence", "decision_log", "errors"]


def test_accumulating_fields_have_reducers():
    """Without a reducer, two parallel nodes writing the same field raise
    InvalidUpdateError. The media subgraph fans out, so these must merge."""
    hints = get_type_hints(ComplaintState, include_extras=True)
    for field in ACCUMULATING:
        annotation = hints[field]
        assert get_origin(annotation) is Annotated, f"{field} has no reducer"
        assert operator.add in get_args(annotation), f"{field}'s reducer is not operator.add"


def test_scalar_fields_do_not_have_reducers():
    """A reducer on a scalar would concatenate instead of replace."""
    hints = get_type_hints(ComplaintState, include_extras=True)
    for field in ("description", "classification", "risk", "terminal_reason"):
        assert get_origin(hints[field]) is not Annotated, f"{field} should not have a reducer"


def test_initial_state_populates_every_declared_key():
    """A missing key surfaces as a KeyError inside a node, far from its cause."""
    state = initial_state(
        complaint_id="c1",
        tracking_id="CIV-TEST0001",
        tenant_id="t1",
        raw_description="pothole on the main road",
        media=[MediaRef(file_path="uploads/x.jpg", media_type="image")],
        coords=Coords(latitude=12.9, longitude=77.6),
    )
    assert set(state) == set(get_type_hints(ComplaintState))


def test_initial_state_starts_accumulators_empty():
    state = initial_state(complaint_id="c1", tracking_id="CIV-T", raw_description="x")
    for field in ACCUMULATING:
        assert state[field] == []


def test_checkpoint_allowlist_covers_every_pydantic_model_in_schemas():
    """A class missing from the allowlist is deserialized back as a plain dict,
    NOT an error — so `state["classification"].category` fails later with
    AttributeError, far from the cause. This test is the guard."""
    defined = {
        obj for obj in vars(schemas_module).values()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel
    }
    missing = defined - set(CHECKPOINT_ALLOWLIST)
    assert not missing, f"not in CHECKPOINT_ALLOWLIST: {sorted(c.__name__ for c in missing)}"


def test_allowlist_entries_are_classes_not_module_tuples():
    """Passing ("app","ai","schemas") silently allows nothing. Pass the classes."""
    for entry in CHECKPOINT_ALLOWLIST:
        assert isinstance(entry, type), f"{entry!r} is not a class"


def test_build_serializer_round_trips_a_pydantic_model():
    from app.ai.schemas import ClassificationResult

    serde = build_serializer()
    original = ClassificationResult(category="ROADS", confidence=0.9)
    restored = serde.loads_typed(serde.dumps_typed(original))
    assert isinstance(restored, ClassificationResult), (
        f"round-tripped to {type(restored).__name__}, not ClassificationResult — "
        "the allowlist is not being applied"
    )
    assert restored.confidence == 0.9


def test_parallel_writes_merge_instead_of_colliding():
    """The property the reducer exists for: two branches writing the same key."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    from app.ai.schemas import MediaInsight

    def start(state: ComplaintState) -> dict:
        return {}

    def fan_out(state: ComplaintState):
        return [Send("analyse", {"item": m.file_path}) for m in state["media"]]

    def analyse(payload: dict) -> dict:
        return {"media_insights": [
            MediaInsight(file_path=payload["item"], media_type="image", text="seen")
        ]}

    builder = StateGraph(ComplaintState)
    builder.add_node("start", start)
    builder.add_node("analyse", analyse)
    builder.add_edge(START, "start")
    builder.add_conditional_edges("start", fan_out, ["analyse"])
    builder.add_edge("analyse", END)
    graph = builder.compile()

    state = initial_state(
        complaint_id="c1", tracking_id="CIV-T", raw_description="x",
        media=[MediaRef(file_path=f"uploads/{i}.jpg", media_type="image") for i in range(3)],
    )
    result = graph.invoke(state)

    assert len(result["media_insights"]) == 3
    assert {i.file_path for i in result["media_insights"]} == {
        "uploads/0.jpg", "uploads/1.jpg", "uploads/2.jpg"
    }
