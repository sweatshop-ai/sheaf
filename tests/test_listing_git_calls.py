"""A member's listing asks git a bounded number of times (SPEC 8.2, 8.6): the answer for a folder is asked once per
listing, not once per page and rule. On a hub with 1067 pages, one listing made 10,462 `git rev-parse` runs and `/_/mount?sheaf=1` took 48-51 s."""
import pytest
from two_roots import A, TwoRoots, git, two_roots

from sheafmd import config

FOLDERS, PAGES = 4, 12          # 48 pages in four folders


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def counted_runs(monkeypatch) -> list:
    asked = []
    real = config._rev_parse

    def spy(folder, *a):
        asked.append((folder, a))
        return real(folder, *a)
    monkeypatch.setattr(config, "_rev_parse", spy)
    return asked


def make_pages(two: TwoRoots, hub) -> None:
    root = two.list_repo / hub.the_list.root().name
    for f in range(FOLDERS):
        (root / f"c{f}" / "inbox").mkdir(parents=True)
        for p in range(PAGES):
            (root / f"c{f}" / "inbox" / f"p{p}.md").write_text(f"# Page {f}-{p}\n\nWords.\n", encoding="utf-8")
    git(two.list_repo, "add", "-A")
    git(two.list_repo, "commit", "-q", "-m", "pages")


def listing_runs(two, monkeypatch) -> tuple[int, int]:
    hub = two.hub()
    make_pages(two, hub)
    member = hub.proxy.members[A]
    asked = counted_runs(monkeypatch)
    docs = [d for r in hub.index.data(member=member)["roots"] for d in r["docs"]]
    return len(docs), len(asked)


def test_a_member_listing_asks_git_per_folder_not_per_page(two, monkeypatch):
    docs, asked = listing_runs(two, monkeypatch)
    assert docs >= FOLDERS * PAGES
    assert asked <= 8 * FOLDERS, f"{asked} git runs for {docs} pages"          # a bound by folders: it does not grow with the pages


def test_what_git_says_is_asked_again_by_the_next_listing(two, monkeypatch):
    hub = two.hub()
    make_pages(two, hub)
    member = hub.proxy.members[A]
    asked = counted_runs(monkeypatch)
    hub.index.data(member=member)
    first = len(asked)
    hub.index.data(member=member)
    assert len(asked) >= 2 * first - 1 and first > 0         # nothing is kept past the listing: a folder that turned into a repo is seen at once
