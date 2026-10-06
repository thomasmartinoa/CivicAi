from app.db.models.complaint import Complaint
from app.services.streaming import registry


def test_connecting_to_ws_registers_a_subscriber(client, db_session):
    """The citizen connects to the WebSocket and receives streaming updates.

    We test connection/disconnection here; actual message delivery is covered
    in test_streaming.py where we can drive it directly without TestClient's
    synchronous context constraints.

    The complaint is inserted directly rather than submitted through the API. Posting
    it schedules a real background pipeline run, and that run publishes node updates
    to `registry` for this very tracking id — so a publish landing mid-test could
    drop the socket under assertion, because `publish` disconnects any subscriber
    whose `send_json` raises. This test failed once that way in a full-suite run and
    could not be reproduced in twelve isolated runs, six api-suite runs or four
    further full-suite runs; the race is real whether or not it was the cause, and a
    test asserting on registry bookkeeping has no reason to start a pipeline.
    """
    complaint = Complaint(tracking_id="CIV-WSTEST01", citizen_email="a@b.com",
                          description="A large pothole near the school",
                          status="submitted")
    db_session.add(complaint)
    db_session.commit()
    tracking_id = complaint.tracking_id

    # Initially no subscribers
    assert registry.subscriber_count(tracking_id) == 0

    with client.websocket_connect(f"/complaints/ws/{tracking_id}") as ws:
        # After connecting, we have one subscriber
        assert registry.subscriber_count(tracking_id) == 1

    # After disconnecting, subscribers are cleaned up
    assert registry.subscriber_count(tracking_id) == 0


async def test_handler_deregisters_on_any_exception():
    """Handler cleanup is guaranteed on all exit paths, not only clean disconnect.

    A transport error, cancelled task at shutdown, or any other exception
    must not leave the subscriber in the registry forever — the registry
    only prunes dead sockets when it next publishes, and a finished
    complaint never publishes again.
    """
    from app.api.complaints import complaint_updates

    tracking_id = "TEST-123"

    class _MockWebSocket:
        def __init__(self, fail_on_receive=False):
            self.fail_on_receive = fail_on_receive
            self.accepted = False
            self.closed = False

        async def accept(self):
            self.accepted = True

        async def receive_text(self):
            if self.fail_on_receive:
                raise RuntimeError("transport error")
            await self._never_returns()

        async def _never_returns(self):
            # Simulate waiting forever (test will time out if not handled properly)
            import asyncio
            await asyncio.sleep(999)

        async def send_json(self, message: dict) -> None:
            # Required by the Sendable protocol, but not called in this test
            pass

    # Test: exception during receive_text cleanup
    ws = _MockWebSocket(fail_on_receive=True)
    assert registry.subscriber_count(tracking_id) == 0

    try:
        await complaint_updates(ws, tracking_id)
    except RuntimeError:
        pass  # Expected

    # Cleanup must have happened despite the exception
    assert registry.subscriber_count(tracking_id) == 0
