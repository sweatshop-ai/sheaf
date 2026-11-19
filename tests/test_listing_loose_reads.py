"""A member's Sheaf listing reads `loose.json` a bounded number of times (SPEC 8.6): the registry of loose roots is read once per
listing, not once per page and question. Each page asked it about five times, and every ask read the file and resolved each
folder in it; on a hub with 1067 pages the listing cost 12 to 20 s of CPU, and a second one asked beside it doubled that."""
from helpers import BEA
from test_archive import made, clock  # noqa: F401  (fixture)
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd.hub import loose

PAGES = 40


def test_the_sheaf_listing_reads_the_loose_registry_per_listing_not_per_page(agents, clock, monkeypatch):
    for n in range(PAGES):
        made(agents, "bea-claude", doc=f"n{n}.md")
    asked = []
    real = loose.Loose._read

    def spy(self):
        asked.append(1)
        return real(self)
    monkeypatch.setattr(loose.Loose, "_read", spy)
    got = agents.get("/_/mount?sheaf=1", member=BEA)
    assert got.status == 200 and len(got.json()["sheaf"]["rows"]) >= PAGES
    assert len(asked) <= 6, f"{len(asked)} reads of loose.json for {PAGES} pages"          # a bound that does not grow with the pages


def test_what_loose_json_says_is_read_again_by_the_next_listing(agents, clock, monkeypatch):
    made(agents, "bea-claude", doc="a.md")
    asked = []
    real = loose.Loose._read
    monkeypatch.setattr(loose.Loose, "_read", lambda self: (asked.append(1), real(self))[1])
    agents.get("/_/mount?sheaf=1", member=BEA)
    first = len(asked)
    agents.get("/_/mount?sheaf=1", member=BEA)
    assert first > 0 and len(asked) >= 2 * first          # nothing is kept past the listing: a root made since is seen at once
