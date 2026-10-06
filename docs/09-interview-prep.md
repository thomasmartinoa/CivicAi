# 09 — Interview prep

Questions this project invites, answered with what it actually did. Where the honest
answer is "we did not measure that", it says so — a claim you cannot defend is worse
than one you never made.

---

## The system

**Q. What is it?**

An AI pipeline for municipal infrastructure complaints. A citizen submits a report; a
LangGraph graph validates it, classifies it into one of twelve categories, scores its
risk, routes it to a department and contractor, drafts a work order with an SLA
deadline, and notifies them. Every AI decision cites the municipal documents it was
grounded in. 904 tests, no network, ~20 seconds.

**Q. Why a graph and not a chain, or just a loop?**

v1 was a `for` loop over seven classes it called agents. A graph buys three things the
loop could not have: conditional branching (`classify` re-reads the taxonomy when it is
unsure), fan-out (`Send` per uploaded image), and checkpointing — an interrupted run
resumes instead of restarting.

**Q. Where is the agent, then?**

Only in the officer chat. The architecture is "deterministic spine plus scoped agentic
loops": SLA decisions must be reproducible and auditable, so LLM-driven control flow is
confined to `app/ai/agents/`.

---

## The decisions worth defending

**Q. Why FAISS and not pgvector?**

Zero infrastructure for a few thousand chunks, exact search with no tuning knobs. The
cost is real and documented in `docs/adr/0002`: FAISS cannot filter by metadata, so
every retriever over-fetches and filters in Python. Below ~10k chunks that is
negligible; at 100k it would not be.

**Q. Why is retrieval a soft dependency?**

Because the alternative is worse. If a missing index stopped the pipeline, an index
problem would become a service outage for citizens. Instead the node records an error
and still produces a department, an SLA and a tracking id.

The cost is that a complaint processed during an outage is ungrounded and nothing in
the system would say so — which is why `/admin/corpus` exists and why the evidence
panel announces missing citations in amber rather than hiding the section.

**Q. Your officer agent can read the whole department's data. Why is that safe?**

It is not safe because the prompt asks it to behave. It is safe because **no tool has a
parameter that could name another tenant** — the department is bound in a closure at
construction. The agent's context contains complaint text written by members of the
public, and this project measured that such text moves a risk band in 1 of 6 injection
items. A signature that cannot express the wrong tenant beats a prompt that asks
nicely.

The agent is also read-only. Human-in-the-loop approval is deferred, so until that
mechanism exists an LLM does not get to move a municipal work order.

**Q. How do you know retrieval is worth it?**

Three columns on a 100-item golden set: keyword 0.54, model without retrieval 0.81,
model with retrieval 0.93. The gap between the last two is the evidence. The
interesting part is that accuracy rose ~5 points while macro-F1 rose 12 — retrieval
helps most on the rare categories.

I kept the ungrounded prompts registered specifically so that comparison stays
repeatable.

---

## The uncomfortable questions

**Q. What is the worst thing about this system?**

It was `validate` rejecting 18 of 88 real complaints — including a gas-cylinder fire
hazard and a child's dog bite — to catch all 12 junk ones. It is now better and still
not good: v2 rejects 3 in 40 instead of 9, at the cost of admitting 1 junk item.

The harness called that **"a trade, not an improvement"**, in those words, because it
refuses to call a change an improvement when it moves both error types in opposite
directions. Promoting it was a judgement that a terminal rejection with no appeal path
costs a citizen far more than a junk row costs an officer — not a conclusion the
numbers reached on their own.

**Q. What is not measured?**

Faithfulness. Citations are checked for shape, never for whether the cited passage
supports the sentence. A node can cite a real document and still say something it does
not support, and nothing here would catch it. Also: the headline macro-F1 is currently
**stale**, because it was measured under the old validator.

**Q. Did your tests catch your bugs?**

No. All six production bugs came from running the system: retired model ids, a missing
request timeout, `finished_at` landing before `started_at`, a rate limiter bypassed by
the provider client's own retries, a transient 503 permanently abandoning a complaint,
and two cases where a test fake was looser than the thing it stood in for.

That last pair is the one I would want to be asked about. A fake that accepts a call
the real object rejects converts a crash into a green suite — one of them made a tool
that could never have worked in production pass eighteen tests.

**Q. So what are the tests for?**

Regressions and contracts. They encode decisions — that a rejection is not a failure,
that a null median is not zero hours, that no tool may name a tenant. Two of those are
enforced by reading the source rather than exercising behaviour, and both were verified
by breaking the code deliberately and watching them fail.

---

## "Why not X?"

| X | Why not |
|---|---|
| **Ragas** | It is LLM-judge based, which is the worst possible spend on a free tier. A deterministic harness measures the same comparisons for no model calls. |
| **A vector DB service** | See ADR 0002. The whole system starts with one command. |
| **Celery/Redis for background work** | APScheduler in-process is enough for four jobs, and the startup resume sweep covers the failure case a queue would. |
| **Server-side chat sessions** | Deferred until a screen needed one. Holding no conversation state is the simplest thing that cannot leak one officer's conversation into another's. |
| **A reindex button** | Rebuilding replaces the index every grounded decision depends on, and there is no confirmation mechanism. A test asserts the only corpus route is a GET. |
| **Mutation tools on the agent** | Same argument. Approval is deferred to a later phase. |
| **passlib** | Broken on Python 3.14. Direct bcrypt. |

---

## If you had more time

1. **Re-baseline the evals** under validator v2 — the current headline figure is stale
   and the dashboard says so.
2. **Measure faithfulness**, which is the biggest unmeasured risk.
3. **Cache repeated policy searches within an agent turn** — the model rephrases rather
   than accepting its first result set, so one question costs three or four calls.
4. **Frontend tests.** Rendering and looking caught five real bugs but will not survive
   a refactor.
5. **A retention policy.** `agent_steps` now stores officer questions and tool results,
   and a tool result can contain a complaint description written by a member of the
   public.
