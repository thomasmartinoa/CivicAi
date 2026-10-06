# ADR 0007 — Provider-side retries are disabled

**Status:** accepted, 2026-10
**Context:** The Gemini free tier allows 15 generate requests per minute per model. A
validator A/B run spent most of its budget being rejected for exceeding it, while the
application's rate limiter believed it was pacing at 12 a minute.

## Decision

`LLM_MAX_RETRIES=0`. Retries live on the chain (`.with_retry`), which re-invokes the
whole gated runnable. `max_bucket_size = 1`.

## Why

- **The shared `InMemoryRateLimiter` gates LangChain's `invoke`. The provider client's
  own `max_retries` retries beneath it**, so those attempts are real HTTP requests the
  limiter never sees. One gated call could fire four ungated ones, which made a 429
  storm self-amplifying: every rejection for being too frequent produced *more*
  traffic.
- A bucket of 5 let five requests go instantly and then throttled, putting the first
  minute over quota with no retries at all. The sustained rate was never the problem.
- After the change the same sweep made 80 calls with **zero** rejections.

## What it costs

- A transient network blip now costs a chain-level retry, which is slower than an
  SDK-level one because it queues behind the limiter.
- On a paid tier this is unnecessarily conservative, and the setting exists so it can
  be raised — with a comment in `.env.example` saying what raising it reintroduces.
- `max_bucket_size = 1` removes burst capacity, so a batch of independent calls is
  strictly serialised at the configured rate.
