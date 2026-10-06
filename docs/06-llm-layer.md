# 06 — The LLM layer

`app/ai/llm.py` is the only module in this project that builds a chat model. Everything
else receives one. This document is what you need when a provider misbehaves, a rate
limit bites, or a cost looks wrong.

---

## 1. One module, one reason

Nodes, services and agents all take their chain as an argument. The single construction
point means model choice, rate limiting, timeouts and fallbacks are configured once and
cannot drift between call sites — and it means a test can substitute a chain without
touching a provider.

```python
def build_structured(task, schema, prompt_name, prompt_version=None, *,
                     cache=None, retries=3) -> Runnable:
    model = build_chat_model(task)
    chain = get_prompt(prompt_name, prompt_version) | model.with_structured_output(
        schema).with_retry(stop_after_attempt=retries)
```

---

## 2. Tiering: tasks, not callers, choose the model

```python
TASK_MODEL: dict[Task, str] = {
    Task.VALIDATE: settings.gemini_model,            # flash-lite
    Task.CLASSIFY: settings.gemini_model,
    Task.INVESTIGATE: settings.gemini_model_strong,
    Task.ASSESS_RISK: settings.gemini_model_strong,  # sets the SLA — high stakes
    Task.VISION: settings.gemini_model,
    Task.NARRATE: settings.gemini_model_strong,      # prose a human reads
    Task.EMAIL_DRAFT: settings.gemini_model_strong,  # an officer signs this
    Task.WORK_ORDER: settings.gemini_model,
    Task.OFFICER_CHAT: settings.gemini_model,        # see below
}
```

Cheap models do the high-volume mechanical steps; the strong tier does the ones whose
output a human reads or whose judgement is high-stakes.

**`OFFICER_CHAT` is on the flash tier despite being conversational prose**, which looks
inconsistent until you count: a ReAct turn is three to four model calls, and the strong
tier's free quota is **20 a day**. An officer asking four questions would exhaust it
before lunch. Choosing among six tools is a mechanical decision, which is what flash is
good at.

### An import-time trap, documented in the source

`TASK_MODEL` reads `settings` **once, at import**. `monkeypatch.setattr(settings,
"gemini_model", …)` silently does nothing to it, even though the same pattern works
against `available_providers()`, which reads fresh every call. An eval sweep that wants
to vary a tier must mutate `TASK_MODEL` directly.

---

## 3. Rate limiting, and the bug that made a 429 storm self-amplifying

The free tier allows **15 generate requests per minute per model** and 500 a day for
flash-lite; the strong tier is 20 a day; embeddings are 100 a minute. These were
measured, not read off a page.

```python
SHARED_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_second=settings.llm_requests_per_second,   # 0.2
    check_every_n_seconds=0.1,
    max_bucket_size=_RETRY_SAFE_BUCKET,                     # 1
)
```

Both constants are the result of a real failure. A validator A/B run spent most of its
budget being rejected for being too frequent, and there were **two** causes:

- **The Gemini client's own `max_retries` retried beneath LangChain.** The limiter
  gates `invoke`; the SDK's retries are real HTTP requests it never sees. One gated
  call could fire four ungated ones, so every 429 produced *more* traffic rather than
  less. `LLM_MAX_RETRIES` now defaults to **0**, and the gated retry lives on the chain
  (`.with_retry`), which re-invokes the whole runnable and therefore queues.
- **`max_bucket_size` was 5.** Five requests went instantly and then throttled, which
  put the first minute over quota with no retries at all. The sustained rate was never
  the problem; the burst was.

After the fix the same sweep made 80 calls with zero rejections.

A note already in the source said to re-check the limiter against the real free-tier
RPM before a live demo. That was the check, and the answer was that two separate
mechanisms were each exceeding it.

---

## 4. Timeouts

`LLM_TIMEOUT_SECONDS=60`. Without it a stalled connection hangs the caller
indefinitely: a node waits for ever, so the complaint neither completes nor fails. This
was found in the first live run, not by a test.

---

## 5. Fallbacks

`build_chat_model` chains every configured provider after the first. With Ollama
enabled and a local model running, a Gemini outage falls through to it.

The sharp edge is in §6 of `docs/03`: the result is a `RunnableWithFallbacks`, not a
`BaseChatModel`, and it proxies `with_structured_output` to the primary through
`__getattr__`.

---

## 6. Model ids expire

Every call 404'd once because the configured Gemini model ids had been retired. The
fix was to check the live `/v1beta/models` list rather than guess a successor.

**A 404 on every node means check these first.** `GEMINI_MODEL` and
`GEMINI_MODEL_STRONG` are in `.env.example` with that note attached.

---

## 7. Content shapes change under you

Gemini 3 returns an AI message's `content` as a **list of content blocks** —
`[{"type": "text", "text": "…", "extras": {…}}]` — not a string. The officer agent
tested `isinstance(message.content, str)`, so it discarded real answers and told
officers "I ran the tools but did not produce an answer."

Every test passed, because every test used `AIMessage(content="a plain string")`. The
fix is LangChain's own `.text` accessor, behind a helper so there is one place to change
if a provider invents a third shape.

Together with the retriever-signature bug in `docs/04` §6, that is the same lesson
twice in one phase: **copy the real payload shape and the real signature, even when the
loose version is easier to write.**

---

## 8. Configuration that matters

```
GEMINI_API_KEY=                        # required for anything live
GEMINI_MODEL=gemini-3.5-flash-lite     # a 404 on every node means check this
GEMINI_MODEL_STRONG=gemini-3.5-flash
LLM_REQUESTS_PER_SECOND=0.2            # the free tier allows 15/minute/model
LLM_MAX_RETRIES=0                      # provider retries bypass the rate limiter
LLM_TIMEOUT_SECONDS=60                 # without it a stall hangs a run for ever
```

`.env.example` documents every setting and `tests/test_config.py` fails if one is
missing from it.

Without a key the API still boots, the suite still passes, and complaint submission
still works — the graph fails at its first model call and the complaint is retried on
the next restart.
