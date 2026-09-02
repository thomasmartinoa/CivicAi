"""Domain vocabulary shared across the application.

v1 scattered these values across four modules and a seed script, which is how
two categories ended up mapped to departments that were never created. There is
one definition of each here, and `tests/test_config.py` asserts they agree.
"""

from enum import StrEnum


class Category(StrEnum):
    ROADS = "ROADS"
    ELECTRICITY = "ELECTRICITY"
    WATER = "WATER"
    SANITATION = "SANITATION"
    PUBLIC_SPACES = "PUBLIC_SPACES"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    FLOODING = "FLOODING"
    FIRE_HAZARD = "FIRE_HAZARD"
    CONSTRUCTION = "CONSTRUCTION"
    STRAY_ANIMALS = "STRAY_ANIMALS"
    SEWAGE = "SEWAGE"


class RiskLevel(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Every Category MUST appear here, and every department named here MUST be
# created by app/services/seed.py. Both invariants are tested.
CATEGORY_DEPARTMENT: dict[Category, str] = {
    Category.ROADS: "Public Works Department",
    Category.CONSTRUCTION: "Public Works Department",
    Category.ELECTRICITY: "Electricity Board",
    Category.WATER: "Water Supply Department",
    Category.SANITATION: "Sanitation Department",
    Category.SEWAGE: "Sanitation Department",
    Category.PUBLIC_SPACES: "Parks & Recreation",
    Category.EDUCATION: "Education Department",
    Category.HEALTH: "Health Department",
    Category.FLOODING: "Flood Control Authority",
    Category.FIRE_HAZARD: "Fire Department",
    Category.STRAY_ANIMALS: "Animal Control",
}
