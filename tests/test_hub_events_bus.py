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


def test_a_stream_hears_nothing_after_its_last_event_whoever_publishes():
    """Ticket 212 A: `gone`, `hub-stopping` and `signed-out` end a stream (8.8). A publisher that held the document's entry
    from before (`_tell_grants`, a waiting Tell, a session's Tell) and publishes after it reaches that stream no more,
    while a stream opened after it hears what comes."""
    for end in ("gone", "hub-stopping", "signed-out"):
        bus = events.Bus()
        sub = bus.subscribe()
        bus.publish("changed", {"n": 1})
        bus.publish(end, {})
        bus.publish("grants", {})
        assert sub.drain() == [("changed", {"n": 1}), (end, {})], end
        later = bus.subscribe()
        bus.publish("grants", {})
        assert later.drain() == [("grants", {})], end


def test_an_event_handed_out_before_the_last_one_is_not_queued_after_it():
    """Ticket 212 A: two publishers at once. One took the list of streams, then the other published `gone` to them: the
    first one's event, queued after `gone`, is not sent."""
    bus = events.Bus()
    sub = bus.subscribe()
    real_put, once = sub.put, []

    def gone_first(name, data):
        if name == "grants" and not once:
            once.append(1)
            bus.publish("gone", {"doc": "a.md"})
        real_put(name, data)
    sub.put = gone_first
    bus.publish("grants", {})
    assert sub.drain() == [("gone", {"doc": "a.md"})]


def test_an_end_event_a_stream_refuses_does_not_end_it():
    """Ticket 212 A, round 1: a member's stream refuses `signed-out` (a key rotation does not touch a member) and a `gone`
    of a page it may not open. The stream ends on the end event it is sent, never on one it refuses: what comes after
    still reaches it."""
    bus = events.Bus()
    sub = bus.subscribe(accept=lambda name, data: None if name in ("signed-out", "gone") else data)
    bus.publish("signed-out", {})
    bus.publish("gone", {"doc": "a.md"})
    bus.publish("changed", {"n": 1})
    assert sub.drain() == [("changed", {"n": 1})]
    assert not sub.ended


def test_an_end_event_a_stream_is_sent_in_place_of_another_ends_it():
    """Ticket 212 A: `accept` sends `gone` in place of `grants` (8.12): that `gone` is the stream's last event."""
    bus = events.Bus()
    sub = bus.subscribe(accept=lambda name, data: events.Renamed("gone", {"doc": "a.md"}) if name == "grants" else data)
    bus.publish("grants", {})
    bus.publish("changed", {"n": 1})
    assert sub.drain() == [("gone", {"doc": "a.md"})]
    bus.publish("changed", {"n": 2})
    assert sub.drain() == []
