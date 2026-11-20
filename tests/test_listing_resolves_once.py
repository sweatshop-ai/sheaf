"""A member's Sheaf listing resolves each folder once, not once per page (SPEC 8.2, 8.6): `Loose.owner_of`, the `mine` of each row,
`shown` and the row's own `realpath` each walked the path of a page and of the registry's folders, an `lstat` per component, for every
page. After the git walks went (test_listing_git_dir_walks) they were most of the 15,790 `lstat` calls of 150 pages."""
import os
import stat

from helpers import BEA, in_beneath_walk
from test_archive import made, clock  # noqa: F401  (fixture)
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)


def folder_lstats(agents, monkeypatch) -> int:
    asked = []
    real = os.lstat

    def spy(path, *a, **k):
        got = real(path, *a, **k)
        if stat.S_ISDIR(got.st_mode) and not in_beneath_walk():
            asked.append(path)
        return got
    monkeypatch.setattr(os, "lstat", spy)
    got = agents.get("/_/mount?sheaf=1", member=BEA)
    monkeypatch.setattr(os, "lstat", real)
    assert got.status == 200
    return len(asked)


def test_the_sheaf_listing_resolves_folders_once_per_listing_not_per_page(agents, clock, monkeypatch):
    for n in range(10):
        made(agents, "bea-claude", doc=f"n{n}.md")
    few = folder_lstats(agents, monkeypatch)
    for n in range(10, 60):
        made(agents, "bea-claude", doc=f"n{n}.md")
    many = folder_lstats(agents, monkeypatch)
    assert few > 0 and many <= few, f"{few} folder lstat calls for 10 pages, {many} for 60"
