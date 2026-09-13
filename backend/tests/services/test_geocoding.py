import httpx
import pytest

from app.ai.schemas import LocationInfo
from app.services.geocoding import reverse_geocode


def _transport(payload, status_code=200):
    return httpx.MockTransport(lambda request: httpx.Response(status_code, json=payload))


def test_a_nominatim_response_maps_onto_location_info():
    payload = {"display_name": "MG Road, Bengaluru",
               "address": {"suburb": "Shivajinagar", "city_district": "Bengaluru East",
                           "state": "Karnataka"}}
    location = reverse_geocode(12.97, 77.59, transport=_transport(payload))
    assert location.address == "MG Road, Bengaluru"
    assert location.ward == "Shivajinagar"
    assert location.district == "Bengaluru East"
    assert location.state == "Karnataka"


def test_a_missing_field_becomes_an_empty_string_not_none():
    """LocationInfo's falsy checks drive jurisdiction level; None would still be
    falsy but the type says str."""
    location = reverse_geocode(0, 0, transport=_transport({"address": {}}))
    assert location.ward == ""
    assert isinstance(location.address, str)


def test_an_http_error_raises_so_intake_can_degrade():
    """intake catches this and records an error without terminating the run."""
    with pytest.raises(Exception):
        reverse_geocode(0, 0, transport=_transport({}, status_code=500))


def test_a_timeout_raises_rather_than_hanging():
    def timeout(request):
        raise httpx.ConnectTimeout("too slow")

    with pytest.raises(httpx.ConnectTimeout):
        reverse_geocode(0, 0, transport=httpx.MockTransport(timeout))
