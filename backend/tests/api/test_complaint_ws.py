from app.services.streaming import registry


def test_connecting_to_ws_registers_a_subscriber(client):
    """The citizen connects to the WebSocket and receives streaming updates.

    We test connection/disconnection here; actual message delivery is covered
    in test_streaming.py where we can drive it directly without TestClient's
    synchronous context constraints.
    """
    tracking_id = client.post(
        "/complaints/",
        data={"description": "A large pothole on the main road near the school",
              "citizen_email": "a@b.com"},
    ).json()["tracking_id"]

    # Initially no subscribers
    assert registry.subscriber_count(tracking_id) == 0

    with client.websocket_connect(f"/complaints/ws/{tracking_id}") as ws:
        # After connecting, we have one subscriber
        assert registry.subscriber_count(tracking_id) == 1

    # After disconnecting, subscribers are cleaned up
    assert registry.subscriber_count(tracking_id) == 0
