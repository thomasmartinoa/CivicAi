"""The v1 keyword classifier, preserved as the naive baseline for evaluation.

This is the only code carried forward from CivicAI v1. It exists so every
accuracy number the eval harness reports in Phase 3 has a "before" column to be
measured against. It is NOT used in the production path.

Original: backend/app/services/llm.py :: _keyword_classify (v1).
"""

from dataclasses import dataclass

from app.constants import Category


@dataclass(frozen=True)
class BaselineResult:
    category: Category
    confidence: float


_KEYWORD_MAP: list[tuple[Category, list[str]]] = [
    (Category.ROADS, ["road", "pothole", "street", "highway", "pavement",
                      "footpath", "divider", "crack", "tar", "asphalt", "traffic"]),
    (Category.ELECTRICITY, ["electricity", "electric", "power", "light", "streetlight",
                            "wire", "transformer", "outage", "voltage", "bulb", "pole"]),
    (Category.WATER, ["water", "pipe", "supply", "leakage", "leak", "contamination",
                      "drinking", "tap", "borewell", "drainage"]),
    (Category.SEWAGE, ["sewage", "sewer", "manhole", "drain overflow", "septic",
                       "gutter", "blockage", "overflow"]),
    (Category.SANITATION, ["garbage", "waste", "trash", "dustbin", "bin", "litter",
                           "sanitation", "cleaning", "sweep"]),
    (Category.FLOODING, ["flood", "waterlog", "waterlogging", "inundation", "drain",
                         "stagnant water", "rain water"]),
    (Category.FIRE_HAZARD, ["fire", "gas leak", "smoke", "burning", "spark", "hazard",
                            "flammable", "explosion"]),
    (Category.HEALTH, ["hospital", "ambulance", "clinic", "health", "medical",
                       "medicine", "patient", "doctor"]),
    (Category.PUBLIC_SPACES, ["park", "tree", "garden", "bench", "playground",
                              "footpath", "public", "fallen tree"]),
    (Category.EDUCATION, ["school", "college", "education", "classroom", "student",
                          "toilet", "restroom", "building"]),
    (Category.CONSTRUCTION, ["construction", "illegal", "excavation", "digging",
                             "building", "demolish", "encroach"]),
    (Category.STRAY_ANIMALS, ["dog", "stray", "animal", "cattle", "cow", "buffalo",
                              "horse", "bite", "aggressive"]),
]


def keyword_classify(text: str) -> BaselineResult:
    """Count keyword hits per category and take the argmax.

    Confidence is fabricated from the hit count, exactly as v1 did. That is the
    point: this is the weak baseline the LLM pipeline has to beat.
    """
    lowered = (text or "").lower()
    best_category, best_score = Category.ROADS, 0

    for category, keywords in _KEYWORD_MAP:
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score > best_score:
            best_score, best_category = score, category

    confidence = min(0.5 + best_score * 0.1, 0.9) if best_score > 0 else 0.4
    return BaselineResult(category=best_category, confidence=float(confidence))
