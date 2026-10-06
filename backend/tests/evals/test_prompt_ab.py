"""A/B-ing the validate prompt, offline.

The point of these tests is the sample guard. The first attempt at this
measurement walked the golden set in id order, ran out of daily quota at item 29,
and reached zero junk items — so it reported that the new prompt accepted more real
complaints while being structurally unable to notice that it might accept
everything.
"""

import pytest

from app.evals.dataset import load_golden
from app.evals.prompt_ab import (
    UnrepresentativeSample, compare, evaluate_version, verdict,
)


def _accept_all(version, item):
    return True


def _perfect(version, item):
    return item.expected_valid


def test_scoring_one_version_does_not_need_both_classes():
    """Scoring a single version on real complaints only is legitimate — it just
    cannot answer whether the validator still rejects junk."""
    real_only = [i for i in load_golden() if i.expected_valid][:20]
    result = evaluate_version("v2", real_only, decide=_perfect)
    assert result.scored == 20
    assert result.invalid_recall is None, "no junk in the sample, so recall is undefined"


def test_compare_refuses_a_sample_that_cannot_answer_the_question(monkeypatch):
    import app.evals.prompt_ab as module

    monkeypatch.setattr(module, "load_golden",
                        lambda: [i for i in load_golden() if i.expected_valid][:10])
    with pytest.raises(UnrepresentativeSample, match="3 of each"):
        compare("v1", "v2", limit=10, decide=_perfect)


def test_the_default_sample_contains_both_classes():
    """take_slice is stratified, so this holds — but it is the assumption the whole
    comparison rests on, so it is asserted rather than trusted."""
    a, b = compare("v1", "v2", limit=40, decide=_perfect)
    assert a.scored == 40
    assert a.invalid_precision == 1.0 and a.invalid_recall == 1.0


def test_a_validator_that_accepts_everything_is_caught():
    a, b = compare("v1", "v2", limit=40, decide=_accept_all)
    assert a.invalid_precision is None, "nothing was predicted invalid"
    assert a.invalid_recall == 0.0, "no junk was caught"
    assert a.junk_accepted, "and the accepted junk is named"
    assert "nothing to compare" in verdict(a, b), (
        "both versions accept everything here, so there is genuinely nothing to say"
    )


def test_errored_items_are_excluded_rather_than_counted_as_rejections():
    """A 429 is not a verdict."""
    def flaky(version, item):
        return None if item.id.startswith("junk") else item.expected_valid

    result = evaluate_version("v2", load_golden(), decide=flaky)
    assert result.errored > 0
    assert result.scored == len(load_golden()) - result.errored
    assert result.junk_accepted == [], "the junk items were not scored at all"


def test_fewer_wrong_rejections_with_no_extra_junk_is_an_improvement():
    items = load_golden()

    def strict(version, item):
        # v1 rejects three real complaints; v2 rejects one.
        rejects = {"vague-1", "vague-2", "vague-3"} if version == "v1" else {"vague-1"}
        return item.expected_valid and item.id not in rejects

    a = evaluate_version("v1", items, decide=lambda v, i: strict("v1", i))
    b = evaluate_version("v2", items, decide=lambda v, i: strict("v2", i))
    assert "v2 is better" in verdict(a, b)


def test_fewer_rejections_bought_with_more_junk_is_called_a_trade_not_a_win():
    """The honest answer when a looser threshold moves both numbers: someone has to
    decide which error is cheaper, and the tool must not decide it for them."""
    items = load_golden()

    def decide(version, item):
        if version == "v1":
            return item.expected_valid and item.id != "vague-1"
        return True  # accepts everything: no wrong rejections, all the junk

    a = evaluate_version("v1", items, decide=lambda v, i: decide("v1", i))
    b = evaluate_version("v2", items, decide=lambda v, i: decide("v2", i))
    assert "a trade, not an improvement" in verdict(a, b)


def test_no_difference_is_reported_as_no_difference():
    items = load_golden()
    a = evaluate_version("v1", items, decide=_perfect)
    b = evaluate_version("v2", items, decide=_perfect)
    assert "no measurable difference" in verdict(a, b)


def test_the_length_guard_is_part_of_the_comparison(monkeypatch):
    """The node rejects anything under MIN_DESCRIPTION_CHARS before calling a model,
    so a comparison that skipped it would not describe the pipeline."""
    from app.ai.graph.nodes.validate import MIN_DESCRIPTION_CHARS
    from app.evals.prompt_ab import _real_decider

    calls = []
    decide = _real_decider()
    short = next(i for i in load_golden() if len(i.description) < MIN_DESCRIPTION_CHARS)
    assert decide("v2", short) is False, "the guard decides, with no model call"
    assert calls == []


def test_a_quota_wall_mid_run_makes_the_comparison_inconclusive():
    """The guard checked the sample and not the survivors, which is half a guard.

    A run that starts with a representative sample and then loses most of it to a
    daily quota can end up scoring a handful of items with no junk among them — the
    very situation the sample guard exists to prevent, arriving by a different door.
    The verdict has to notice.
    """
    items = load_golden()
    junk_ids = {i.id for i in items if not i.expected_valid}

    def dies_after_five(version, item):
        # Only the first few real complaints get through; every junk item 429s.
        if item.id in junk_ids:
            return None
        return item.expected_valid

    a = evaluate_version("v1", items, decide=lambda v, i: dies_after_five("v1", i))
    b = evaluate_version("v2", items, decide=lambda v, i: dies_after_five("v2", i))
    assert a.errored == len(junk_ids)
    assert "inconclusive" in verdict(a, b)
    assert "junk" in verdict(a, b)


def test_a_version_result_knows_whether_it_saw_both_classes():
    items = load_golden()
    real_only = [i for i in items if i.expected_valid][:10]
    assert evaluate_version("v2", real_only, decide=_perfect).conclusive is False
    assert evaluate_version("v2", items, decide=_perfect).conclusive is True
