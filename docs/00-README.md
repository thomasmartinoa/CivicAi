# 00 — How to read these

Eleven documents about one codebase, written for an intermediate Python programmer
who has not seen it before. They are not a tutorial series: each one explains a
concept, shows **the actual code from this repository**, and says why it is built that
way and what was rejected.

## Order

| # | Document | Read it when |
|---|---|---|
| 01 | [Legacy system explained](01-legacy-system-explained.md) | You want to know what v1 was and why it was deleted. Written *before* the deletion, so it is a record rather than a reconstruction. |
| 02 | [Architecture overview](02-architecture-overview.md) | First, if you only read one. The shape of the system and what happens to a complaint. |
| 03 | [LangChain fundamentals](03-langchain-fundamentals.md) | You are new to LCEL, structured output, or tools. |
| 04 | [LangGraph deep dive](04-langgraph-deep-dive.md) | You want to understand the pipeline itself — state, reducers, `Send`, checkpoints. |
| 05 | [RAG explained](05-rag-explained.md) | You want to know how a decision gets a citation. |
| 06 | [The LLM layer](06-llm-layer.md) | You are debugging a provider, a rate limit or a cost. |
| 07 | [Evaluation and observability](07-evaluation-and-observability.md) | You want to know whether any of it actually works. **Start here if you are sceptical.** |
| 08 | [Code walkthrough](08-code-walkthrough.md) | You are about to change something and want to know where it lives. |
| 09 | [Interview prep](09-interview-prep.md) | You have to explain this to someone. |
| 10 | [Resume lines](10-resume-lines.md) | You need the claims and the numbers behind them. |

## Three conventions

**Every number is real.** Measurements come from runs against live Gemini, with the
date attached. Where something has not been measured, the document says so rather
than estimating. `docs/07` §5 is a list of what is *not* known.

**Every code reference is real.** Paths and symbols can be opened. If a snippet is
abridged, it says so.

**The defects are written down.** Each phase plan under `docs/superpowers/plans/`
ends with a **Carried forward** section listing what was deferred and what is known to
be wrong. That is the first thing to read before changing anything, and it is more
useful than this index.

## Where the decisions live

- `docs/adr/` — one file per decision that was genuinely contested, with what it cost.
- `docs/superpowers/plans/` — one plan per phase, each ending in *Carried forward*.
- `docs/eval-reports/` — measured results, dated.
- Commit messages — this repository's commit bodies explain *why*, not what. `git log`
  is a design document.
