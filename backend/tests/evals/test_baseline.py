from app.constants import Category
from app.evals.baseline import keyword_classify


def test_classifies_an_obvious_pothole():
    result = keyword_classify("There is a huge pothole on the main road near the market")
    assert result.category == Category.ROADS
    assert result.confidence > 0.5


def test_classifies_a_streetlight_fault():
    result = keyword_classify("The streetlight pole has hanging wires, no power since Monday")
    assert result.category == Category.ELECTRICITY


def test_unmatched_text_gets_low_confidence():
    result = keyword_classify("zzzz qqqq wwww")
    assert result.confidence <= 0.4


def test_confidence_is_always_a_float_between_zero_and_one():
    """v1 compared confidence with `< 0.7` without guaranteeing it was numeric."""
    for text in ["pothole road street", "", "fire gas leak smoke burning spark"]:
        result = keyword_classify(text)
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0


def test_returns_a_real_category_enum_member():
    result = keyword_classify("garbage overflowing from the dustbin")
    assert isinstance(result.category, Category)


def test_building_only_text_matches_v1_education_not_construction():
    """v1 checks EDUCATION before CONSTRUCTION and first-to-score wins.

    Guards the keyword map against silent drift from the v1 behaviour this
    baseline exists to reproduce.
    """
    assert keyword_classify("the building is falling apart").category == Category.EDUCATION
