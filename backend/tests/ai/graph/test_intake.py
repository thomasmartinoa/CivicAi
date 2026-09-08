from langgraph.types import Send

from app.ai.graph.nodes.intake import fan_out_media, intake_node
from app.ai.schemas import Coords, LocationInfo, MediaRef
from tests.ai.graph.conftest import returns


def test_geocoding_populates_the_location(make_config, base_state):
    location = LocationInfo(address="MG Road", district="Bengaluru Urban", state="Karnataka")
    state = {**base_state, "coords": Coords(latitude=12.9, longitude=77.6)}
    update = intake_node(state, make_config(geocode=lambda lat, lon: location))

    assert update["location"].district == "Bengaluru Urban"


def test_no_coordinates_means_no_geocoding_call(make_config, base_state):
    called = {"n": 0}

    def counting(lat, lon):
        called["n"] += 1
        return LocationInfo()

    update = intake_node(base_state, make_config(geocode=counting))
    assert called["n"] == 0
    assert update["location"] is None


def test_a_geocoding_failure_does_not_end_the_run(make_config, base_state):
    def boom(lat, lon):
        raise TimeoutError("nominatim slow")

    state = {**base_state, "coords": Coords(latitude=1.0, longitude=2.0)}
    update = intake_node(state, make_config(geocode=boom))

    assert update["location"] is None
    assert update["errors"]


def test_fan_out_emits_one_send_per_media_file(base_state):
    state = {**base_state, "media": [
        MediaRef(file_path=f"uploads/{i}.jpg", media_type="image") for i in range(3)
    ]}
    sends = fan_out_media(state)

    assert len(sends) == 3
    assert all(isinstance(s, Send) for s in sends)
    assert {s.arg["file_path"] for s in sends} == {"uploads/0.jpg", "uploads/1.jpg", "uploads/2.jpg"}


def test_no_media_skips_straight_to_validate(base_state):
    """Returning a node name rather than an empty Send list; an empty list
    would leave the graph with nowhere to go."""
    assert fan_out_media(base_state) == "validate"
