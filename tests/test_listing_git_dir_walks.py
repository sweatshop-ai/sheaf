"""A member's Sheaf listing looks for git directories once per folder, not once per page (SPEC 8.2, 8.6): `in_git_dir` walked a
page's folder and every folder above it, four `lstat` calls each, for every page and twice. On a hub with 150 pages one listing
made about 24,000 `lstat` calls."""
import os

from helpers import BEA
from test_archive import made, clock  # noqa: F401  (fixture)
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)

SHAPE = {"HEAD", "commondir", "objects", "refs"}          # what `_shaped_like_a_git_dir` looks for in a folder


def shape_lstats(agents, monkeypatch) -> int:
    asked = []
    real = os.lstat

    def spy(path, *a, **k):
        if os.path.basename(os.fspath(path)) in SHAPE:
            asked.append(path)
        return real(path, *a, **k)
    monkeypatch.setattr(os, "lstat", spy)
    got = agents.get("/_/mount?sheaf=1", member=BEA)
    monkeypatch.setattr(os, "lstat", real)
    assert got.status == 200
    return len(asked)


def test_the_sheaf_listing_looks_for_git_directories_per_folder_not_per_page(agents, clock, monkeypatch):
    for n in range(10):
        made(agents, "bea-claude", doc=f"n{n}.md")
    few = shape_lstats(agents, monkeypatch)
    for n in range(10, 60):
        made(agents, "bea-claude", doc=f"n{n}.md")
    many = shape_lstats(agents, monkeypatch)
    assert few > 0 and many <= few, f"{few} lstat calls for 10 pages, {many} for 60"          # the folders are the same: it does not grow with the pages
