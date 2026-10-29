"""`projects.toml` grants (SPEC 8.12, #44): in proxy mode a member opens the shared sheaves of a `<client>/<project>`
folder only when that project's `members` hold their `short`; an owner always opens their own sheaf. A project the
file does not name, and every project of a root whose file the hub cannot read, is open to its owners alone."""
import os
import pwd

import pytest
from helpers import FRONT, Front
from test_hub_place import HANS, MISSING, NAME, OPEN, SHARED, THIERRY, absent, put, the_list_on, tokens  # noqa: F401

from sheafmd.hub import proxy
from sheafmd.mcp import NOT_IN_A_ROOT

SVEN = "7c4e2a90-1b3d-4f5e-8a6c-2d9e0f1b3c5a"
GRANTS = '[projects."thinkingtoo/tiroir"]\nmembers = ["thierry", "sven"]\nstatus = "live"\n'
HANS_OWN = OPEN.replace("owner: thierry", "owner: hans").replace("sources: [issue:thinkingtoo/tt-tiroir#9]",
                                                                 "sources: [library:doc-9]")


def members(work):
    team = {THIERRY: {"name": "Thierry", "short": "thierry", "github": "tiroir", "roots": [str(work)],
                      "tokens": ["james-thierry"]},
            HANS: {"name": "Hans", "short": "hans", "github": "hanshermans", "roots": [str(work)],
                   "tokens": ["james-hans"]},
            SVEN: {"name": "Sven", "short": "sven", "github": "sven01", "roots": [str(work)]}}
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": team}, "the test")


@pytest.fixture
def team(hub, browser, work, plan, tmp_path):
    hub.proxy = members(work)
    (work / "projects.toml").write_text(GRANTS, encoding="utf-8")
    (work / "thinkingtoo" / "tiroir").mkdir(parents=True)
    the_list_on(hub, work, tmp_path)
    return Front(hub, browser.handler)


def test_a_member_the_project_does_not_name_cannot_open_its_shared_sheaf(team, work):
    put(team, work, SHARED, OPEN)
    assert team.get(f"/work/{SHARED}", member=THIERRY).status == 200
    assert team.get(f"/work/{SHARED}", member=SVEN).status == 200
    assert team.get(f"/work/{SHARED}", member=HANS).status == 404


def test_an_owner_the_project_does_not_name_still_opens_their_own_sheaf(team, work):
    put(team, work, f"thinkingtoo/tiroir/private/hans/{NAME}", HANS_OWN)
    assert team.get(f"/work/{SHARED}", member=HANS).status == 200
    assert team.get(f"/work/{SHARED}", member=SVEN).status == 404


def index_of(team, member):
    return [d["doc"] for r in team.get("/_/index.json", member=member).json()["roots"] for d in r["docs"]]


def test_the_index_leaves_out_a_project_that_does_not_name_the_member(team, work):
    put(team, work, SHARED, OPEN)
    put(team, work, "thinkingtoo/README.md", "# ThinkingToo\n")
    assert f"work/{SHARED}" in index_of(team, SVEN)
    hans = index_of(team, HANS)
    assert "work/thinkingtoo/README.md" in hans and f"work/{SHARED}" not in hans, hans


def test_a_door_token_bound_to_a_member_the_project_does_not_name_gets_no_such_document(team, work, browser,
                                                                                        tokens):
    put(team, work, SHARED, OPEN)
    assert absent(browser, tokens["hans"], SHARED) == absent(browser, tokens["hans"], MISSING)
    assert absent(browser, tokens["thierry"], SHARED) != absent(browser, tokens["thierry"], MISSING)


@pytest.mark.parametrize("grants", ['[projects."thinkingtoo/other"]\nmembers = ["thierry", "sven"]\nstatus = "live"\n',
                                    'not toml at all ['])
def test_a_project_the_file_does_not_name_and_a_file_the_hub_cannot_read_are_open_to_owners_alone(team, work,
                                                                                                  grants):
    put(team, work, SHARED, OPEN)
    put(team, work, "thinkingtoo/README.md", "# ThinkingToo\n")
    (work / "projects.toml").write_text(grants, encoding="utf-8")
    assert team.get(f"/work/{SHARED}", member=SVEN).status == 404
    assert team.get("/work/thinkingtoo/README.md", member=SVEN).status == 200       # above project depth: the roots
    put(team, work, f"thinkingtoo/tiroir/private/hans/2026-10-29-own.md", HANS_OWN)
    assert team.get("/work/thinkingtoo/tiroir/2026-10-29-own.md", member=HANS).status == 200


def test_a_root_with_no_projects_toml_opens_as_before(team, work):
    put(team, work, SHARED, OPEN)
    (work / "projects.toml").unlink()
    assert team.get(f"/work/{SHARED}", member=HANS).status == 200


def test_a_member_added_to_the_file_opens_the_project_at_the_next_request(team, work):
    put(team, work, SHARED, OPEN)
    assert team.get(f"/work/{SHARED}", member=HANS).status == 404
    (work / "projects.toml").write_text(GRANTS.replace('"sven"]', '"sven", "Hans"]'), encoding="utf-8")
    assert team.get(f"/work/{SHARED}", member=HANS).status == 200


def test_an_open_stream_of_a_member_taken_off_the_project_is_told_gone(team, work):
    put(team, work, SHARED, OPEN)
    sven = team.get(f"/_/live?doc=work/{SHARED}", member=SVEN).stream
    thierry = team.get(f"/_/live?doc=work/{SHARED}", member=THIERRY).stream
    sven.drain(), thierry.drain()
    (work / "projects.toml").write_text(GRANTS.replace(', "sven"', ""), encoding="utf-8")
    team.hub.tick()
    assert sven.drain() == [("gone", {"doc": f"work/{SHARED}"})]
    assert thierry.drain() == []


def test_a_door_token_bound_to_a_member_the_project_does_not_name_makes_nothing_in_it(team, work, browser, tokens):
    from helpers import call
    is_error, got = call(browser, "create", token=tokens["hans"], doc="work/thinkingtoo/tiroir/2026-10-29-new.md",
                         text="---\nvisibility: project\n---\n# New\n")
    assert is_error and NOT_IN_A_ROOT in got and not (work / "thinkingtoo/tiroir/2026-10-29-new.md").exists(), got
    is_error, got = call(browser, "create", token=tokens["thierry"], doc="work/thinkingtoo/tiroir/2026-10-29-new.md",
                         text="---\nvisibility: project\n---\n# New\n")
    assert not is_error, got
