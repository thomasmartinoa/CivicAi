"""Compare two versions of the validate prompt on the decision that matters.

    python -m app.evals.prompt_ab --a v1 --b v2 --limit 40

The prompt registry keeps old versions precisely so this is possible, and the
validity decision is the one worth A/B-ing first: the 2026-10-04 sweep measured
invalid-complaint precision at 0.40, meaning `validate` rejected 18 of 88 real
complaints to catch all 12 junk ones.

**The sample must contain junk, and this module refuses to run if it does not.**
The first attempt at this measurement was a throwaway script that walked the golden
set in id order; the free tier's daily budget ran out at item 29, and every `junk-*`
item sorts after that. The result looked encouraging — more real complaints accepted
— while saying nothing about the only thing that could make the change harmful,
which is a validator that accepts everything. That failure is the reason this is a
tested module with a stratified sample rather than a script, and the reason
`_require_both_classes` exists.
"""

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from app.evals.dataset import GoldenItem, load_golden
from app.evals.metrics import precision_recall
from app.evals.run import take_slice

logger = logging.getLogger(__name__)


class UnrepresentativeSample(RuntimeError):
    """The sample cannot answer the question being asked of it."""


@dataclass
class VersionResult:
    version: str
    scored: int
    errored: int
    invalid_precision: float | None
    invalid_recall: float | None
    wrongly_rejected: list[str] = field(default_factory=list)
    junk_accepted: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        precision = f"{self.invalid_precision:.2f}" if self.invalid_precision is not None else "n/a"
        recall = f"{self.invalid_recall:.2f}" if self.invalid_recall is not None else "n/a"
        return (f"{self.version}: precision {precision}, recall {recall} over n={self.scored}"
                f" — {len(self.wrongly_rejected)} real complaints rejected,"
                f" {len(self.junk_accepted)} junk accepted"
                + (f", {self.errored} errored" if self.errored else ""))


def _require_both_classes(items: list[GoldenItem]) -> None:
    """A validity comparison needs junk and real complaints in the sample.

    Without junk, "accepts more" cannot be told from "accepts everything"; without
    real complaints there is nothing for over-rejection to show up in.
    """
    junk = sum(1 for i in items if not i.expected_valid)
    real = sum(1 for i in items if i.expected_valid)
    if junk < 3 or real < 3:
        raise UnrepresentativeSample(
            f"the sample has {junk} junk and {real} real items; a validity comparison "
            "needs at least 3 of each, or 'accepts more' cannot be distinguished from "
            "'accepts everything'"
        )


def evaluate_version(version: str, items: list[GoldenItem], *,
                     decide: Callable[[str, GoldenItem], bool | None]) -> VersionResult:
    """Run one prompt version over the sample and score the validity decision.

    `decide(version, item) -> True | False | None` is injected so the tests never
    touch a model; None means the call failed and the item is excluded rather than
    counted as a rejection.
    """
    truth: list[bool] = []
    predicted: list[bool] = []
    wrongly_rejected: list[str] = []
    junk_accepted: list[str] = []
    errored = 0

    for item in items:
        verdict = decide(version, item)
        if verdict is None:
            errored += 1
            continue
        truth.append(item.expected_valid)
        predicted.append(verdict)
        if item.expected_valid and not verdict:
            wrongly_rejected.append(item.id)
        if not item.expected_valid and verdict:
            junk_accepted.append(item.id)

    precision, recall = precision_recall(truth, predicted, positive=False)
    return VersionResult(version=version, scored=len(truth), errored=errored,
                         invalid_precision=precision, invalid_recall=recall,
                         wrongly_rejected=sorted(wrongly_rejected),
                         junk_accepted=sorted(junk_accepted))


def compare(version_a: str, version_b: str, *, limit: int | None,
            decide: Callable[[str, GoldenItem], bool | None]) -> tuple[VersionResult, VersionResult]:
    """Both versions over the same stratified sample."""
    items = take_slice(load_golden(), limit)
    _require_both_classes(items)
    return (evaluate_version(version_a, items, decide=decide),
            evaluate_version(version_b, items, decide=decide))


def verdict(a: VersionResult, b: VersionResult) -> str:
    """Say which is better, or that the comparison does not support a change.

    Deliberately conservative: a version that accepts more real complaints *and*
    more junk is not an improvement, it is a looser threshold, and the honest
    answer is that the trade needs a decision rather than a default change.
    """
    fewer_wrong = len(b.wrongly_rejected) < len(a.wrongly_rejected)
    more_junk = len(b.junk_accepted) > len(a.junk_accepted)

    # The junk comparison comes first, before any check on precision. A version
    # that accepts *everything* has undefined precision, and reporting that as
    # "inconclusive" would bury the most important thing about it — that it has
    # stopped rejecting anything at all.
    if more_junk and not fewer_wrong:
        return (f"{b.version} is worse: it accepts "
                f"{len(b.junk_accepted) - len(a.junk_accepted)} more junk complaints "
                f"without rejecting fewer real ones")
    if a.invalid_precision is None and b.invalid_precision is None:
        return ("inconclusive: neither version predicted anything invalid, so there is "
                "nothing to compare")
    if fewer_wrong and not more_junk:
        return (f"{b.version} is better: {len(a.wrongly_rejected)} real complaints rejected "
                f"-> {len(b.wrongly_rejected)}, with no extra junk accepted")
    if fewer_wrong and more_junk:
        return (f"a trade, not an improvement: {b.version} rejects "
                f"{len(a.wrongly_rejected) - len(b.wrongly_rejected)} fewer real complaints "
                f"but accepts {len(b.junk_accepted) - len(a.junk_accepted)} more junk — "
                "someone has to decide which error is cheaper here")
    if len(b.wrongly_rejected) == len(a.wrongly_rejected) and not more_junk:
        return f"no measurable difference between {a.version} and {b.version}"
    if b.invalid_precision is None:
        return (f"{b.version} predicted nothing invalid at all: it rejects no real "
                f"complaints and catches no junk, which is not a validator")
    return f"{a.version} is better or equal; do not switch"


def _real_decider() -> Callable[[str, GoldenItem], bool | None]:
    """The live decider: one validate call per item, per version."""
    from app.ai.graph.nodes.validate import MIN_DESCRIPTION_CHARS
    from app.ai.llm import Task, build_structured
    from app.ai.schemas import ValidationResult

    chains: dict[str, object] = {}

    def decide(version: str, item: GoldenItem) -> bool | None:
        # The node's own cheap guard runs before any model call, so a comparison
        # that skipped it would not describe the pipeline.
        if len(item.description.strip()) < MIN_DESCRIPTION_CHARS:
            return False
        if version not in chains:
            chains[version] = build_structured(Task.VALIDATE, ValidationResult, "validate",
                                               version, cache=None, retries=1)
        try:
            return bool(chains[version].invoke({"description": item.description}).is_valid)
        except Exception as exc:
            logger.warning("validate %s failed on %s: %s", version, item.id, exc)
            return None

    return decide


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A/B two validate prompt versions.")
    parser.add_argument("--a", default="v1")
    parser.add_argument("--b", default="v2")
    parser.add_argument("--limit", type=int, default=40,
                        help="stratified sample size; 40 items is 80 calls, well inside "
                             "the free tier's 500 a day")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        a, b = compare(args.a, args.b, limit=args.limit, decide=_real_decider())
    except UnrepresentativeSample as exc:
        print(f"refused: {exc}")
        return 2

    print(f"\n{a.summary}\n{b.summary}\n\n{verdict(a, b)}")
    if b.wrongly_rejected:
        print(f"\nstill rejected by {b.version}: {', '.join(b.wrongly_rejected)}")
    if b.junk_accepted:
        print(f"junk accepted by {b.version}: {', '.join(b.junk_accepted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
