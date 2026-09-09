"""Reverse geocoding.

Thin stub for Phase 1b: returns an empty LocationInfo unconditionally. Only
reached when the graph runner is not given an injected `deps.geocode`, which
no test does. Phase 1c wires this to Nominatim for real.
"""

from app.ai.schemas import LocationInfo


def reverse_geocode(lat: float, lon: float) -> LocationInfo:
    return LocationInfo()
