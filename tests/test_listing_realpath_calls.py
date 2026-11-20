"""A member listing resolves each path once (SPEC 8.12): the same few paths (the roots, their folders, the pages' addresses) were
resolved 32 times each, 53,867 `realpath` calls for 1,685 distinct paths, about a third of the time of a listing of 1067 pages."""
import os
from collections import Counter

import pytest
from helpers import in_beneath_walk
from test_listing_git_calls import FOLDERS, PAGES, make_pages
from two_roots import A, TwoRoots, two_roots


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def counted_resolutions(monkeypatch) -> Counter:
    asked = Counter()
    real = os.path.realpath

    def spy(path, *a, **kw):
        if not in_beneath_walk():
            asked[os.fspath(path)] += 1
        return real(path, *a, **kw)
    monkeypatch.setattr(os.path, "realpath", spy)
    return asked


def listing(hub, member) -> list:
    return [d for r in hub.index.data(member=member)["roots"] for d in r["docs"]]


def test_a_member_listing_resolves_each_path_once(two, monkeypatch):
    hub = two.hub()
    make_pages(two, hub)
    member = hub.proxy.members[A]
    asked = counted_resolutions(monkeypatch)
    docs = listing(hub, member)
    assert len(docs) >= FOLDERS * PAGES
    twice = {p: n for p, n in asked.items() if n > 1}
    assert not twice, f"{sum(asked.values())} resolutions of {len(asked)} paths; asked again: {dict(list(twice.items())[:3])}"


def test_the_next_listing_resolves_its_paths_again(two, monkeypatch):
    hub = two.hub()
    make_pages(two, hub)
    member = hub.proxy.members[A]
    listing(hub, member)
    asked = counted_resolutions(monkeypatch)
    listing(hub, member)                        # nothing of the first is kept: a path that became a link is seen
    assert asked and max(asked.values()) == 1, dict(asked)
