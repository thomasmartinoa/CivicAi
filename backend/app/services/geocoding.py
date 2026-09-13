"""Reverse geocoding via OpenStreetMap Nominatim.

Raises on failure rather than returning an empty result: `intake_node` catches it,
records the error and continues, so a complaint without a ward is still a
complaint. Swallowing the failure here would make it invisible.
"""

import httpx

from app.ai.schemas import LocationInfo

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
TIMEOUT_SECONDS = 3.0
USER_AGENT = "CivicAI/2.0 (infrastructure complaint routing)"


def reverse_geocode(lat: float, lon: float, *, transport: httpx.BaseTransport | None = None) -> LocationInfo:
    with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
        response = client.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "json", "addressdetails": 1},
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()

    address = payload.get("address", {}) or {}
    return LocationInfo(
        address=payload.get("display_name", "") or "",
        ward=address.get("suburb") or address.get("neighbourhood") or "",
        block=address.get("city_block") or address.get("quarter") or "",
        district=address.get("city_district") or address.get("county") or "",
        state=address.get("state") or "",
    )
