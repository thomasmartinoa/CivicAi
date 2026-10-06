import pytest

from app.services.streaming import ConnectionRegistry


class _FakeSocket:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, message: dict) -> None:
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(message)


async def test_a_published_message_reaches_a_subscriber():
    registry = ConnectionRegistry()
    socket = _FakeSocket()
    registry.connect("CIV-1", socket)
    await registry.publish("CIV-1", {"node": "classify"})
    assert socket.sent == [{"node": "classify"}]


async def test_publishing_to_nobody_is_not_an_error():
    await ConnectionRegistry().publish("CIV-NOBODY", {"node": "classify"})


async def test_every_subscriber_of_one_complaint_receives_it():
    registry = ConnectionRegistry()
    a, b = _FakeSocket(), _FakeSocket()
    registry.connect("CIV-1", a)
    registry.connect("CIV-1", b)
    await registry.publish("CIV-1", {"node": "route"})
    assert a.sent and b.sent


async def test_subscribers_of_other_complaints_do_not_receive_it():
    registry = ConnectionRegistry()
    mine, theirs = _FakeSocket(), _FakeSocket()
    registry.connect("CIV-1", mine)
    registry.connect("CIV-2", theirs)
    await registry.publish("CIV-1", {"node": "route"})
    assert mine.sent and not theirs.sent


async def test_a_dead_socket_is_dropped_and_does_not_break_the_others():
    """A closed browser tab must not stop the graph from streaming."""
    registry = ConnectionRegistry()
    dead, alive = _FakeSocket(fail=True), _FakeSocket()
    registry.connect("CIV-1", dead)
    registry.connect("CIV-1", alive)
    await registry.publish("CIV-1", {"node": "classify"})
    assert alive.sent
    assert registry.subscriber_count("CIV-1") == 1


async def test_disconnect_removes_the_last_subscriber_entirely():
    registry = ConnectionRegistry()
    socket = _FakeSocket()
    registry.connect("CIV-1", socket)
    registry.disconnect("CIV-1", socket)
    assert registry.subscriber_count("CIV-1") == 0
