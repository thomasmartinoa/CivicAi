# 04 — LangGraph deep dive

The pipeline itself: how state flows, how branches merge, how a run resumes, and the
four mistakes this repository made and fixed. `GRAPH_VERSION = "2b.0"`.

---

## 1. State is a TypedDict with reducers

`app/ai/graph/state.py`:

```python
class ComplaintState(TypedDict):
    # ── immutable input ──────────────────────────────────────
    complaint_id: str
    tracking_id: str
    tenant_id: str | None
    raw_description: str
    media: list[MediaRef]
    coords: Coords | None

    # ── written in parallel: reducers required ───────────────
    media_insights: Annotated[list[MediaInsight], operator.add]
    evidence: Annotated[list[RetrievedChunk], operator.add]
    decision_log: Annotated[list[NodeDecision], operator.add]
    errors: Annotated[list[str], operator.add]
    ...
```

A node returns a **partial** dict and LangGraph merges it. For a scalar the last write
wins. For a list written by more than one branch at once, that is not good enough:
without `Annotated[list[X], operator.add]`, LangGraph raises `InvalidUpdateError` when
two fan-out branches write the same key.

Four fields need reducers here, and three of them are append-only logs rather than
results — evidence, decisions and errors accumulate across every node.

### The reducer has a consequence that caused a bug

`errors` accumulates and **is never cleared**. So an edge predicate that checked
`state["errors"]` would end a run because of an unrelated upstream soft error — a
failed geocode, an unreadable image — even though the node in front of it had
everything it needed. `after_classify` documents exactly this and deliberately checks
only for a missing classification.

---

## 2. Conditional edges are pure functions

`app/ai/graph/edges.py` keeps routing out of the nodes, so the rules are unit-testable
without building a graph:

```python
CONFIDENCE_THRESHOLD = 0.7
MAX_INVESTIGATE_TURNS = 3

def after_classify(state: ComplaintState) -> str:
    classification = state["classification"]
    if classification is None:
        return END
    if classification.confidence < CONFIDENCE_THRESHOLD:
        return "investigate"
    return "assess_risk"
```

**Every edge fails closed.** If the evidence a decision needs is absent, the run ends
rather than proceeding on nothing. A pipeline that routes a complaint it could not
classify is worse than one that stops.

---

## 3. The loop

`investigate` is a cycle: `classify → investigate → classify`, bounded by a counter in
state. Each turn widens the taxonomy search (`k = 2 + turn`), and **a turn that fails
still counts** — otherwise a persistently failing retrieval would loop until the
recursion limit instead of giving up after three.

After `MAX_INVESTIGATE_TURNS` the best available answer proceeds anyway. A stuck loop
is worse than a low-confidence category an officer can see and correct.

---

## 4. Fan-out with `Send`

`intake` emits one `Send("analyse_media", …)` per uploaded file. Each branch runs the
vision chain on one image and appends to `media_insights`, which is why that field
needs its reducer.

The branches have no ordering guarantee, and that leaked into the frontend: the live
pipeline view takes `Math.max` of the stage reported so far rather than assigning,
because a media branch can report after a later node and a progress bar that goes
backwards looks broken.

---

## 5. Checkpointing, and the two bugs it hid

Every node's output is checkpointed. `run_complaint` re-invokes rather than replays, so
an interrupted run continues where it stopped.

### 5.1 The allowlist

```python
CHECKPOINT_ALLOWLIST = (...)   # every Pydantic class reachable from state
```

A class missing from it does **not** raise. It deserialises back from the checkpoint as
a plain dict, and the failure surfaces much later as an `AttributeError` on a field
access. Pass the classes themselves — a `("module",)` tuple silently allows nothing.

### 5.2 A failed node is checkpointed as complete

This is the subtle one, and it took two commits.

A node that fails does not raise. It returns `{"errors": [...]}`, deliberately, because
retrieval is a soft dependency and a node should still produce its output. LangGraph
cannot distinguish that update from a successful one, so the failed node is
checkpointed as **complete**. Re-invoking the same thread replays the stored error
without ever calling the model again.

A live run proved it. A gas-cylinder leak was validated, classified `FIRE_HAZARD` at
0.99 confidence, and lost `assess_risk` to a transient 503. Three `AgentRun` rows:

```
failed     57575ms  thread=…4b92db         assess_risk: 503 UNAVAILABLE
failed        20ms  thread=…4b92db         assess_risk: 503 UNAVAILABLE   ← the bug
completed  28034ms  thread=…4b92db:retry2  no error
```

Twenty milliseconds and a byte-identical error, because it made no request at all.

**The fix is two parts.** `UNFINISHED` now includes `failed`, bounded by
`MAX_RESUME_ATTEMPTS` so a permanently broken complaint is not re-driven on every
restart for ever. And a retry runs on a **fresh thread** (`_thread_for`), so the nodes
actually re-execute. An interrupted run — one with no failed `AgentRun` — still keeps
the complaint id and resumes exactly as before.

The eval harness had the same bug and the same fix a phase and a half earlier:
`load_log` excludes errored rows so `--resume` cannot bake in an outage. The shape of
a bug recurs across layers that look nothing alike.

---

## 6. Dependency injection is what makes it testable

Nodes never construct a model, a retriever or a session. Everything arrives through
`config["configurable"]`, typed by `GraphDeps` in `ai/graph/deps.py`. A test injects a
`RunnableLambda` returning a fixture.

This is not a style preference. LangChain's fake chat models **raise** on
`with_structured_output`, so a node that built its own model could not be tested at
all.

The retriever protocol is `.search(query, *, k, fetch_k, filters)` — keyword-only in
all three. Phase 4b shipped a tool calling it with only `k`, which would have raised
`TypeError` on every call in production. Eighteen tests passed because the test fake
was declared `search(self, query, k=5)` and accepted a call the real retriever
rejects. **A fake looser than the thing it stands in for converts a crash into a green
suite.**

---

## 7. Streaming

`run_complaint` can `astream` with `stream_mode="updates"` and call back per node.
`app/services/execution.py` publishes each update to a `ConnectionRegistry`, which
fans it out to any WebSocket watching that tracking id. The citizen's tracking screen
lights up a stage per node and shows the node's own decision summary.

`publish` is best-effort and drops a subscriber whose send raises: a closed tab must
not stop the graph from streaming.
