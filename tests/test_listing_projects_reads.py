"""A member listing reads each root's `projects.toml` once, not once per page checked (SPEC 8.12): on a hub with 1067 pages
one listing opened and parsed it 801 times, 3.1 s of a mount that took 33-36 s."""
import pytest
from test_listing_git_calls import FOLDERS, PAGES, make_pages
from two_roots import A, TwoRoots, git, two_roots

from sheafmd.hub import projects


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def write_projects(two: TwoRoots, members: str) -> None:
    (two.list_repo / projects.FILE).write_text(
        "".join(f'[projects."list/c{f}"]\nmembers = [{members}]\nstatus = "live"\n' for f in range(FOLDERS)),
        encoding="utf-8")
    git(two.list_repo, "add", "-A")
    git(two.list_repo, "commit", "-q", "-m", "projects")


def counted(monkeypatch) -> dict:
    n = {"load": 0, "parse": 0}
    for name in n:
        real = getattr(projects, name)

        def spy(*a, _real=real, _name=name, **kw):
            n[_name] += 1
            return _real(*a, **kw)
        monkeypatch.setattr(projects, name, spy)
    return n


def listing(two, hub, member) -> list:
    return [d for r in hub.index.data(member=member)["roots"] for d in r["docs"]]


def test_a_member_listing_reads_projects_toml_per_root_not_per_page(two, monkeypatch):
    hub = two.hub()
    make_pages(two, hub)
    write_projects(two, '"a"')
    n = counted(monkeypatch)
    docs = listing(two, hub, hub.proxy.members[A])
    assert len(docs) >= FOLDERS * PAGES
    roots = len(hub.proxy.members[A].roots)
    assert 0 < n["load"] <= roots and n["parse"] <= roots, f"{n} for {len(docs)} pages"


def test_an_edit_of_projects_toml_is_seen_by_the_next_listing(two, monkeypatch):
    hub = two.hub()
    make_pages(two, hub)
    member = hub.proxy.members[A]
    write_projects(two, '"a"')
    n = counted(monkeypatch)
    before = len(listing(two, hub, member))
    write_projects(two, '"b"')                  # member A is no longer named
    after = len(listing(two, hub, member))
    assert n["load"] >= 2
    assert after < before
