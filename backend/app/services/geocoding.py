import httpx


class GeocodingService:
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

    async def reverse_geocode(self, lat: float, lon: float) -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    self.NOMINATIM_URL,
                    params={"lat": lat, "lon": lon, "format": "json", "addressdetails": 1},
                    headers={"User-Agent": "CivicAI/1.0"},
                )
                data = response.json()

            address_parts = data.get("address", {})
            return {
                "address": data.get("display_name", ""),
                "ward": address_parts.get("suburb", address_parts.get("neighbourhood", "")),
                "block": address_parts.get("city_block", address_parts.get("quarter", "")),
                "district": address_parts.get("city_district", address_parts.get("county", "")),
                "city": address_parts.get("city", address_parts.get("town", "")),
                "state": address_parts.get("state", ""),
            }
        except Exception:
            return {"address": f"Lat: {lat}, Lon: {lon}", "ward": "", "block": "", "district": "", "city": "", "state": ""}

    def determine_jurisdiction_level(self, ward: str, block: str, district: str) -> str:
        if ward: return "ward"
        if block: return "block"
        if district: return "district"
        return "city"


geocoding_service = GeocodingService()
