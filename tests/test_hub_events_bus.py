"""`Bus.publish` hands an event to every stream of the document (SPEC 8.8): a stream whose `on_put` is cleared by
another thread, or whose `on_put` raises, costs that stream alone (ticket 185 BD)."""
from sheafmd import diagnostics
from sheafmd.hub import events


class ClearedAfterFirstRead(events.Subscription):
    """A stream whose `on_put` a `Shared.leave` on another thread clears just after it is first read: the first read
    gives the callback, every later one None."""

    def __init__(self, bus):
        super().__init__(bus)
        self.reads, self.calls = 0, 0

    @property
    def on_put(self):
        self.reads += 1
        return self._count if self.reads == 1 else None

    @on_put.setter
    def on_put(self, value):     # Subscription.__init__ sets None; the reads above stand for the other thread
        pass

    def _count(self):
        self.calls += 1


def test_an_on_put_cleared_while_the_event_is_queued_is_called_once_as_first_read():
    bus = events.Bus()
    sub = ClearedAfterFirstRead(bus)
    bus._subs.add(sub)
    bus.publish("changed", {"n": 1})
    assert sub.get(0) == ("changed", {"n": 1})
    assert (sub.reads, sub.calls) == (1, 1)


def test_an_on_put_that_raises_costs_only_its_own_stream(monkeypatch):
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
