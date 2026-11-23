"""`Bus.publish` hands an event to every stream of the document (SPEC 8.8): a stream whose waker is cleared
by another thread, or whose waker raises, costs that stream alone (ticket 185 BD)."""
from sheafmd import diagnostics
from sheafmd.hub import events


class ClearedBetweenReads(events.Subscription):
    """A stream whose `on_put` a `Shared.leave` on another thread clears just after it is first read."""
    reads = 0

    @property
    def on_put(self):
        type(self).reads += 1
        return (lambda: None) if type(self).reads == 1 else None

    @on_put.setter
    def on_put(self, value):
        pass


def test_a_waker_cleared_while_the_event_is_queued_is_not_called():
    bus = events.Bus()
    sub = bus.subscribe()
    sub.__class__ = ClearedBetweenReads
    bus.publish("changed", {"n": 1})
    assert sub.get(0) == ("changed", {"n": 1})


def test_a_waker_that_raises_costs_only_its_own_stream(monkeypatch):
    rows = []
    monkeypatch.setattr(diagnostics, "record", lambda *a, **k: rows.append((a, k)) or True)
    bus = events.Bus()
    subs = [bus.subscribe() for _ in range(4)]

    def broken():
        raise RuntimeError("gone")
    subs[1].on_put = broken
    bus.publish("changed", {"n": 1})                        # the thread that publishes is not handed the error
    assert [s.get(0) for s in subs] == [("changed", {"n": 1})] * 4
    assert [a[:2] for a, _ in rows] == [("hub", "publish-failed")]
