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
    team.hub.tick()                 # told once the new file has held for two passes
    assert sven.drain() == [("gone", {"doc": f"work/{SHARED}", "why": "access"})]
    assert thierry.drain() == []


def test_a_door_token_bound_to_a_member_the_project_does_not_name_makes_nothing_in_it(team, work, browser, tokens):
    from helpers import call
    is_error, got = call(browser, "create", token=tokens["hans"], doc="work/thinkingtoo/tiroir/2026-10-29-new.md",
                         text="---\nvisibility: project\n---\n# New\n")
    assert is_error and NOT_IN_A_ROOT in got and not (work / "thinkingtoo/tiroir/2026-10-29-new.md").exists(), got
    is_error, got = call(browser, "create", token=tokens["thierry"], doc="work/thinkingtoo/tiroir/2026-10-29-new.md",
                         text="---\nvisibility: project\n---\n# New\n")
    assert not is_error, got


def groups(capsys, *argv):
    from sheafmd import cli
    code = cli.main(["projects", "groups", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_projects_groups_gives_the_library_the_hubs_own_judgement(team, work, capsys):
    import json
    (work / "projects.toml").write_text(GRANTS + '\n[projects."acme/blog"]\nmembers = ["Sven"]\nstatus = "closed"\n',
                                        encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    assert code == 0
    got = json.loads(out)
    assert got["projects"] == [
        {"project": "acme/blog", "group": "group:proj-acme-blog", "glob": "acme/blog/*.md", "status": "closed",
         "members": ["sven"], "assistants": []},
        {"project": "thinkingtoo/tiroir", "group": "group:proj-thinkingtoo-tiroir", "glob": "thinkingtoo/tiroir/*.md",
         "status": "live", "members": ["sven", "thierry"], "assistants": []}]
    assert got["members"] == {"sven": ["group:proj-acme-blog", "group:proj-thinkingtoo-tiroir"],
                              "thierry": ["group:proj-thinkingtoo-tiroir"]}
    for member in team.hub.proxy.members.values():
        assert ("group:proj-thinkingtoo-tiroir" in got["members"].get(member.short, [])) \
            == team.hub.granted(member, f"work/{SHARED}")


@pytest.mark.parametrize("text", [None, "not toml ["])
def test_projects_groups_fails_on_a_file_that_is_not_there_or_cannot_be_read(work, capsys, text):
    if text is not None:
        (work / "projects.toml").write_text(text, encoding="utf-8")
    code, out, err = groups(capsys, "--root", str(work))
    assert code == 1 and out == "" and "projects.toml" in err


def test_the_index_stream_tells_a_change_in_a_project_to_its_members_alone(team, work, monkeypatch):
    import time
    from sheafmd.hub.index import SWEEP_SECONDS
    now = [time.time()]
    team.hub.clock = lambda: now[0]
    monkeypatch.setattr(team.hub.index, "_start_sweep", lambda run: run())     # a sweep inside the tick
    put(team, work, SHARED, OPEN)
    hans, sven = (team.get("/_/live", member=m).stream for m in (HANS, SVEN))
    for m in (HANS, SVEN):
        team.get("/_/index.json", member=m)
    now[0] += SWEEP_SECONDS
    team.hub.tick()
    hans.drain(), sven.drain()
    (work / SHARED).write_text(OPEN + "\nMore.\n", encoding="utf-8")
    now[0] += SWEEP_SECONDS
    team.hub.tick()
    assert [d for name, d in hans.drain() if name == "status"] == []
    assert [d["doc"] for name, d in sven.drain() if name == "status"] == [f"work/{SHARED}"]



def test_a_link_in_a_granted_project_reaches_no_sheaf_of_a_project_that_is_not(team, work):
    """Opus P1 (PR 51): in a root the hub does not place, a link is followed, so the project is judged on where
    the file is as well as on the address: both must name the member."""
    team.hub.the_list = None
    (work / "projects.toml").write_text(GRANTS + '\n[projects."acme/blog"]\nmembers = ["hans"]\nstatus = "live"\n',
                                        encoding="utf-8")
    put(team, work, SHARED, OPEN.replace("A quote from the contract.", "SECRET"))
    (work / "acme/blog").mkdir(parents=True)
    os.symlink(f"../../{SHARED}", work / "acme/blog/link.md")
    got = team.get("/work/acme/blog/link.md", member=HANS)
    assert got.status == 404 and "SECRET" not in got.text


def test_a_sheaf_its_owner_keeps_outside_their_projects_is_never_told_gone_for_a_bad_moment(team, work):
    """Opus P2 (PR 51): `gone` ends the page for good; it is the answer to a change of `projects.toml` alone, never
    to a file of the sheaf that cannot be read for a moment."""
    rel = f"thinkingtoo/tiroir/private/hans/{NAME}"
    put(team, work, rel, HANS_OWN)
    stream = team.get(f"/_/live?doc=work/{SHARED}", member=HANS).stream
    stream.drain()
    (work / rel).write_text("", encoding="utf-8")
    team.hub.tick()
    assert [name for name, _ in stream.drain() if name == "gone"] == []


@pytest.mark.parametrize("name", ["acme/*", "acme/blog?", "acme/[x]", "acme/blog post"])
def test_a_project_name_the_librarys_glob_would_read_otherwise_is_refused(work, capsys, name):
    (work / "projects.toml").write_text(f'[projects."{name}"]\nmembers = ["hans"]\nstatus = "live"\n',
                                        encoding="utf-8")
    code, out, err = groups(capsys, "--root", str(work))
    assert code == 1 and out == "" and name in err


def test_two_projects_that_would_share_a_library_group_are_refused(work, capsys):
    (work / "projects.toml").write_text('[projects."a-b/c"]\nmembers = ["hans"]\nstatus = "live"\n\n'
                                        '[projects."a/b-c"]\nmembers = ["sven"]\nstatus = "live"\n', encoding="utf-8")
    code, out, err = groups(capsys, "--root", str(work))
    assert code == 1 and out == "" and "group:proj-a-b-c" in err



@pytest.mark.parametrize("cut", [GRANTS[:40], "", GRANTS.replace(', "sven"', "")])
def test_a_projects_toml_caught_mid_write_ends_no_page(team, work, cut):
    """Opus P2 (PR 51, round 2): a file written in place is met empty or cut off for a moment, and `gone` ends a
    page for good. A change is told once the watcher has seen it hold for two passes."""
    put(team, work, SHARED, OPEN)
    sven = team.get(f"/_/live?doc=work/{SHARED}", member=SVEN).stream
    sven.drain()
    (work / "projects.toml").write_text(cut, encoding="utf-8")
    team.hub.tick()
    got = sven.drain()                                                      # a stream reads at once
    (work / "projects.toml").write_text(GRANTS + "\n", encoding="utf-8")       # the write ends
    team.hub.tick()
    team.hub.tick()
    assert [name for name, _ in got + sven.drain() if name == "gone"] == []


def test_projects_groups_prints_each_projects_assistants_and_their_groups(work, capsys):
    """An entry's `assistants` names the agents that work on the project for its members (8.12): the Library
    gives each its groups, as `members` does for a member. An entry without it has none."""
    import json
    (work / "projects.toml").write_text(GRANTS.replace("members =", 'assistants = ["James"]\nmembers =')
                                        + '\n[projects."thinkingtoo/inbox"]\nmembers = ["thierry"]\nstatus = "live"\n'
                                        + 'assistants = ["james", "mistral"]\n'
                                        + '\n[projects."acme/blog"]\nmembers = ["sven"]\nstatus = "live"\n',
                                        encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    assert code == 0
    got = json.loads(out)
    assert {p["project"]: p["assistants"] for p in got["projects"]} == {
        "acme/blog": [], "thinkingtoo/inbox": ["james", "mistral"], "thinkingtoo/tiroir": ["james"]}
    assert got["assistants"] == {"james": ["group:proj-thinkingtoo-inbox", "group:proj-thinkingtoo-tiroir"],
                                 "mistral": ["group:proj-thinkingtoo-inbox"]}
    assert got["members"] == {"sven": ["group:proj-acme-blog", "group:proj-thinkingtoo-tiroir"],
                              "thierry": ["group:proj-thinkingtoo-inbox", "group:proj-thinkingtoo-tiroir"]}


def test_a_file_without_assistants_prints_none(work, capsys):
    import json
    (work / "projects.toml").write_text(GRANTS, encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    got = json.loads(out)
    assert code == 0 and got["assistants"] == {} and got["projects"][0]["assistants"] == []


def test_an_assistant_is_granted_nothing_in_the_hub(team, work):
    """`assistants` is for the Library alone: an agent reaches the hub through its member's token (9.7), so a
    member's short in `assistants` opens nothing that `members` does not."""
    (work / "projects.toml").write_text(GRANTS.replace("members =", 'assistants = ["hans"]\nmembers ='),
                                        encoding="utf-8")
    put(team, work, SHARED, OPEN)
    assert team.get(f"/work/{SHARED}", member=HANS).status == 404
    assert team.get(f"/work/{SHARED}", member=SVEN).status == 200


@pytest.mark.parametrize("value", ['"james"', "[1]", '[""]', "true"])
def test_assistants_that_are_not_a_list_of_names_are_refused(work, capsys, value):
    (work / "projects.toml").write_text(GRANTS + f"assistants = {value}\n", encoding="utf-8")
    code, out, err = groups(capsys, "--root", str(work))
    assert code == 1 and out == "" and "'assistants' in" in err and "list of names" in err


def test_projects_groups_prints_a_name_in_lower_case_not_casefolded(work, capsys):
    """The Library compares principal ids as given (#58): `Straße` is printed `straße`, as `str.lower()` gives it,
    not `strasse`, which would name no principal."""
    import json
    (work / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["Straße"]\nstatus = "live"\n'
                                        'assistants = ["Weiß"]\n', encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    got = json.loads(out)
    assert code == 0
    assert got["members"] == {"straße": ["group:proj-acme-blog"]}
    assert got["assistants"] == {"weiß": ["group:proj-acme-blog"]}
    assert got["projects"][0]["members"] == ["straße"] and got["projects"][0]["assistants"] == ["weiß"]


@pytest.mark.parametrize("short, granted", [("straße", True), ("STRASSE", False), ("strasse", False)])
def test_the_hub_grants_by_the_same_lower_case_it_prints(work, short, granted):
    """`grants` and `sheaf projects groups` give the same judgement (8.12): a short is held by `members` when the
    two are equal in lower case, so a member the Library is told of is the member the hub opens the project to."""
    from sheafmd.hub import projects
    entries = {"acme/blog": {"members": ["Straße"], "status": "live"}}
    assert projects.grants(entries, "acme/blog/a.md", short) is granted
    assert (short.lower() in projects.groups(entries)["members"]) is granted


def test_a_name_in_both_members_and_assistants_is_in_both_maps_and_the_library_unions_them(work, capsys):
    """A name may be a member of one project and an assistant of another (#58). It is printed under `members` with
    the groups that name it a member and under `assistants` with the groups that name it an assistant; its
    principal's groups in the Library are the union of the two (13)."""
    import json
    (work / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["james"]\nstatus = "live"\n'
                                        '\n[projects."acme/shop"]\nmembers = ["ada"]\nstatus = "live"\n'
                                        'assistants = ["James"]\n', encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    got = json.loads(out)
    assert code == 0
    assert got["members"]["james"] == ["group:proj-acme-blog"]
    assert got["assistants"]["james"] == ["group:proj-acme-shop"]
    assert sorted(set(got["members"]["james"]) | set(got["assistants"]["james"])) == [
        "group:proj-acme-blog", "group:proj-acme-shop"]
