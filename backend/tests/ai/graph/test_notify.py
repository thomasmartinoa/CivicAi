from app.ai.graph.nodes.notify import notify_node


def test_sends_one_notification(make_config, base_state):
    sent = []
    update = notify_node(base_state, make_config(notify=lambda **kw: sent.append(kw)))
    assert len(sent) == 1
    assert update["decision_log"][0].node == "notify"


def test_notifying_twice_sends_once(make_config, base_state):
    """Durability is bounded: a resumed run re-executes the node it died in, and
    the node before it may run again. Measured: an exception preserves progress,
    a SIGKILL does not. Either way this node must not email the citizen twice."""
    sent = []
    config = make_config(notify=lambda **kw: sent.append(kw))

    first = notify_node(base_state, config)
    state_after = {**base_state, **first}
    notify_node(state_after, config)

    assert len(sent) == 1


def test_a_notification_failure_does_not_end_the_run(make_config, base_state):
    def boom(**kw):
        raise ConnectionError("smtp down")

    update = notify_node(base_state, make_config(notify=boom))
    assert update["errors"]
    assert update.get("terminal_reason") is None


def test_a_retry_after_a_failed_send_still_notifies(make_config, base_state):
    """The guard must distinguish 'already succeeded' from 'already attempted'.
    A transient SMTP error must not permanently suppress the notification."""
    attempts = {"n": 0}
    sent = []

    def flaky(**kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("smtp down")
        sent.append(kw)

    config = make_config(notify=flaky)

    first = notify_node(base_state, config)
    assert first["errors"]

    state_after = {**base_state, "decision_log": first["decision_log"]}
    second = notify_node(state_after, config)

    assert len(sent) == 1, "the retry was suppressed by the idempotency guard"
    assert second["decision_log"][0].summary == "citizen notified"
