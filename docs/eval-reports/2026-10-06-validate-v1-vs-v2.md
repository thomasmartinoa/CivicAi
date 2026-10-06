# `validate` v1 vs v2 — 2026-10-06

**80 calls, n=40 stratified, `gemini-3.5-flash-lite`, zero rate-limit failures.**

The measurement Phase 3 deferred and Phase 4a's carried-forward section flagged as the
project's worst known defect.

## Result

| | precision | recall | real complaints wrongly rejected | junk wrongly accepted |
|---|---|---|---|---|
| **v1** (current `LATEST`) | 0.31 | 1.00 | **9** | **0** |
| **v2** (written, not promoted) | 0.50 | 0.75 | **3** | **1** |

The harness's own verdict, unedited:

> a trade, not an improvement: v2 rejects 6 fewer real complaints but accepts 1 more
> junk — someone has to decide which error is cheaper here

That wording is deliberate. `prompt_ab` refuses to call a change an improvement when
it moves both error types in opposite directions, because the alternative is a report
that launders a policy decision as a measurement.

- Still rejected by v2: `short-1`, `short-3`, `short-4` — all very short reports.
- Junk accepted by v2: `junk-10`.

## What the two errors actually cost

This is not a question the numbers answer.

**A wrongly rejected complaint** is a citizen told their report is not an
infrastructure problem. Phase 3's earlier run found a gas-cylinder fire hazard and a
child's dog bite among them. There is no appeal path in the system: a rejection is
terminal, and the citizen's only recourse is to file again and hope. The cost lands on
the person least able to do anything about it.

**A wrongly accepted junk item** reaches the officer queue, where it costs an officer
a few seconds to dismiss. It consumes a classification and a risk assessment of model
quota on the way.

On those terms the trade favours v2 and it is not close — six fewer ignored citizens
for one more junk row. But *it is a policy choice about a public service*, not a
technical one, so `LATEST` has not been moved. Promoting it is one line plus a
re-baseline.

## Caveats a reader should hold

- **n=40**, stratified. 9 versus 3 is a real difference at this size; 0 versus 1 junk
  is a single item and could flip on a rerun.
- v2 has **not** been measured for its effect downstream. A validator that admits more
  borderline reports changes what `classify` and `assess_risk` see, and the headline
  macro-F1 of 0.93 was measured with v1 in front of them.
- Both runs used flash-lite. The strong tier's 20/day makes a comparison there
  impractical.

## Reproducing

```bash
.venv/bin/python -m app.evals.prompt_ab --a v1 --b v2 --limit 40
```

Earlier the same command spent most of its budget on 429s. That was a real defect, not
a quota shortage: the Gemini client's own `max_retries` retried *beneath* the shared
rate limiter, so a 429 storm amplified itself. Fixed in `1026a15`; this run made 80
calls with zero rejections.
