"""`projects.toml` grants (SPEC 8.12, #44): in proxy mode a member opens the shared rectoversos of a `<client>/<project>`
folder only when that project's `members` hold their `short`; an owner always opens their own rectoverso. A project the
file does not name, and every project of a root whose file the hub cannot read, is open to its owners alone."""
import os
import pwd

import pytest
from helpers import FRONT, Front
from test_hub_place import BOB, MISSING, NAME, OPEN, SHARED, ALICE, absent, put, the_list_on, tokens  # noqa: F401

from sheafmd.hub import proxy
from sheafmd.mcp import NOT_IN_A_ROOT

CAROL = "7c4e2a90-1b3d-4f5e-8a6c-2d9e0f1b3c5a"
GRANTS = '[projects."acme/tiroir"]\nmembers = ["alice", "carol"]\nstatus = "live"\n'
BOB_OWN = OPEN.replace("owner: alice", "owner: bob").replace("sources: [issue:acme/agency-tiroir#9]",
                                                                 "sources: [library:doc-9]")


def members(work):
    team = {ALICE: {"name": "Alice", "short": "alice", "github": "tiroir", "roots": [str(work)],
                      "tokens": ["james-alice"]},
            BOB: {"name": "Bob", "short": "bob", "github": "bobsmith", "roots": [str(work)],
                   "tokens": ["james-bob"]},
            CAROL: {"name": "Carol", "short": "carol", "github": "carol01", "roots": [str(work)]}}
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": team}, "the test")


@pytest.fixture
def team(hub, browser, work, plan, tmp_path):
    hub.proxy = members(work)
    (work / "projects.toml").write_text(GRANTS, encoding="utf-8")
    (work / "acme" / "tiroir").mkdir(parents=True)
    the_list_on(hub, work, tmp_path)
    return Front(hub, browser.handler)


def test_a_member_the_project_does_not_name_cannot_open_its_shared_sheaf(team, work):
    put(team, work, SHARED, OPEN)
    assert team.get(f"/work/{SHARED}", member=ALICE).status == 200
    assert team.get(f"/work/{SHARED}", member=CAROL).status == 200
    assert team.get(f"/work/{SHARED}", member=BOB).status == 404


def test_an_owner_the_project_does_not_name_still_opens_their_own_sheaf(team, work):
    put(team, work, f"acme/tiroir/private/bob/{NAME}", BOB_OWN)
    assert team.get(f"/work/{SHARED}", member=BOB).status == 200
    assert team.get(f"/work/{SHARED}", member=CAROL).status == 404


def index_of(team, member):
    return [d["doc"] for r in team.get("/_/index.json", member=member).json()["roots"] for d in r["docs"]]


def test_the_index_leaves_out_a_project_that_does_not_name_the_member(team, work):
    put(team, work, SHARED, OPEN)
    put(team, work, "acme/README.md", "# Acme\n")
    assert f"work/{SHARED}" in index_of(team, CAROL)
    bob = index_of(team, BOB)
    assert "work/acme/README.md" in bob and f"work/{SHARED}" not in bob, bob


def test_a_door_token_bound_to_a_member_the_project_does_not_name_gets_no_such_document(team, work, browser,
                                                                                        tokens):
    put(team, work, SHARED, OPEN)
    assert absent(browser, tokens["bob"], SHARED) == absent(browser, tokens["bob"], MISSING)
    assert absent(browser, tokens["alice"], SHARED) != absent(browser, tokens["alice"], MISSING)


@pytest.mark.parametrize("grants", ['[projects."acme/other"]\nmembers = ["alice", "carol"]\nstatus = "live"\n',
                                    'not toml at all ['])
def test_a_project_the_file_does_not_name_and_a_file_the_hub_cannot_read_are_open_to_owners_alone(team, work,
                                                                                                  grants):
    put(team, work, SHARED, OPEN)
    put(team, work, "acme/README.md", "# Acme\n")
    (work / "projects.toml").write_text(grants, encoding="utf-8")
    assert team.get(f"/work/{SHARED}", member=CAROL).status == 404
    assert team.get("/work/acme/README.md", member=CAROL).status == 200       # above project depth: the roots
    put(team, work, f"acme/tiroir/private/bob/2026-10-29-own.md", BOB_OWN)
    assert team.get("/work/acme/tiroir/2026-10-29-own.md", member=BOB).status == 200


def test_a_root_with_no_projects_toml_opens_as_before(team, work):
    put(team, work, SHARED, OPEN)
    (work / "projects.toml").unlink()
    assert team.get(f"/work/{SHARED}", member=BOB).status == 200


def test_a_member_added_to_the_file_opens_the_project_at_the_next_request(team, work):
    put(team, work, SHARED, OPEN)
    assert team.get(f"/work/{SHARED}", member=BOB).status == 404
    (work / "projects.toml").write_text(GRANTS.replace('"carol"]', '"carol", "Bob"]'), encoding="utf-8")
    assert team.get(f"/work/{SHARED}", member=BOB).status == 200


def test_an_open_stream_of_a_member_taken_off_the_project_is_told_gone(team, work):
    put(team, work, SHARED, OPEN)
    carol = team.get(f"/_/live?doc=work/{SHARED}", member=CAROL).stream
    alice = team.get(f"/_/live?doc=work/{SHARED}", member=ALICE).stream
    carol.drain(), alice.drain()
    (work / "projects.toml").write_text(GRANTS.replace(', "carol"', ""), encoding="utf-8")
    team.hub.tick()
    team.hub.tick()                 # told once the new file has held for two passes
    assert carol.drain() == [("gone", {"doc": f"work/{SHARED}", "why": "access"})]
    assert alice.drain() == []


def test_a_door_token_bound_to_a_member_the_project_does_not_name_makes_nothing_in_it(team, work, browser, tokens):
    from helpers import call
    is_error, got = call(browser, "create", token=tokens["bob"], doc="work/acme/tiroir/2026-10-29-new.md",
                         text="---\nvisibility: project\n---\n# New\n")
    assert is_error and "not in the project acme/tiroir" in got and not (work / "acme/tiroir/2026-10-29-new.md").exists(), got
    is_error, got = call(browser, "create", token=tokens["alice"], doc="work/acme/tiroir/2026-10-29-new.md",
                         text="---\nvisibility: project\n---\n# New\n")
    assert not is_error, got


def groups(capsys, *argv):
    from sheafmd import cli
    code = cli.main(["projects", "groups", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_projects_groups_gives_the_library_the_hubs_own_judgement(team, work, capsys):
    import json
    (work / "projects.toml").write_text(GRANTS + '\n[projects."acme/blog"]\nmembers = ["Carol"]\nstatus = "closed"\n',
                                        encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    assert code == 0
    got = json.loads(out)
    assert got["projects"] == [
        {"project": "acme/blog", "group": "group:proj-acme-blog", "glob": "acme/blog/*.md", "status": "closed",
         "members": ["carol"], "assistants": []},
        {"project": "acme/tiroir", "group": "group:proj-acme-tiroir", "glob": "acme/tiroir/*.md",
         "status": "live", "members": ["alice", "carol"], "assistants": []}]
    assert got["members"] == {"carol": ["group:proj-acme-blog", "group:proj-acme-tiroir"],
                              "alice": ["group:proj-acme-tiroir"]}
    for member in team.hub.proxy.members.values():
        assert ("group:proj-acme-tiroir" in got["members"].get(member.short, [])) \
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
    bob, carol = (team.get("/_/live", member=m).stream for m in (BOB, CAROL))
    for m in (BOB, CAROL):
        team.get("/_/index.json", member=m)
    now[0] += SWEEP_SECONDS
    team.hub.tick()
    bob.drain(), carol.drain()
    (work / SHARED).write_text(OPEN + "\nMore.\n", encoding="utf-8")
    now[0] += SWEEP_SECONDS
    team.hub.tick()
    assert [d for name, d in bob.drain() if name == "status"] == []
    assert [d["doc"] for name, d in carol.drain() if name == "status"] == [f"work/{SHARED}"]



def test_a_link_in_a_granted_project_reaches_no_sheaf_of_a_project_that_is_not(team, work):
    """Opus P1 (PR 51): in a root the hub does not place, a link is followed, so the project is judged on where
    the file is as well as on the address: both must name the member."""
    team.hub.the_list = None
    (work / "projects.toml").write_text(GRANTS + '\n[projects."acme/blog"]\nmembers = ["bob"]\nstatus = "live"\n',
                                        encoding="utf-8")
    put(team, work, SHARED, OPEN.replace("A quote from the contract.", "SECRET"))
    (work / "acme/blog").mkdir(parents=True)
    os.symlink(f"../../{SHARED}", work / "acme/blog/link.md")
    got = team.get("/work/acme/blog/link.md", member=BOB)
    assert got.status == 404 and "SECRET" not in got.text


def test_a_sheaf_its_owner_keeps_outside_their_projects_is_never_told_gone_for_a_bad_moment(team, work):
    """Opus P2 (PR 51): `gone` ends the page for good; it is the answer to a change of `projects.toml` alone, never
    to a file of the rectoverso that cannot be read for a moment."""
    rel = f"acme/tiroir/private/bob/{NAME}"
    put(team, work, rel, BOB_OWN)
    stream = team.get(f"/_/live?doc=work/{SHARED}", member=BOB).stream
    stream.drain()
    (work / rel).write_text("", encoding="utf-8")
    team.hub.tick()
    assert [name for name, _ in stream.drain() if name == "gone"] == []


@pytest.mark.parametrize("name", ["acme/*", "acme/blog?", "acme/[x]", "acme/blog post"])
def test_a_project_name_the_librarys_glob_would_read_otherwise_is_refused(work, capsys, name):
    (work / "projects.toml").write_text(f'[projects."{name}"]\nmembers = ["bob"]\nstatus = "live"\n',
                                        encoding="utf-8")
    code, out, err = groups(capsys, "--root", str(work))
    assert code == 1 and out == "" and name in err


def test_two_projects_that_would_share_a_library_group_are_refused(work, capsys):
    (work / "projects.toml").write_text('[projects."a-b/c"]\nmembers = ["bob"]\nstatus = "live"\n\n'
                                        '[projects."a/b-c"]\nmembers = ["carol"]\nstatus = "live"\n', encoding="utf-8")
    code, out, err = groups(capsys, "--root", str(work))
    assert code == 1 and out == "" and "group:proj-a-b-c" in err



@pytest.mark.parametrize("cut", [GRANTS[:40], "", GRANTS.replace(', "carol"', "")])
def test_a_projects_toml_caught_mid_write_ends_no_page(team, work, cut):
    """Opus P2 (PR 51, round 2): a file written in place is met empty or cut off for a moment, and `gone` ends a
    page for good. A change is told once the watcher has seen it hold for two passes."""
    put(team, work, SHARED, OPEN)
    carol = team.get(f"/_/live?doc=work/{SHARED}", member=CAROL).stream
    carol.drain()
    (work / "projects.toml").write_text(cut, encoding="utf-8")
    team.hub.tick()
    got = carol.drain()                                                      # a stream reads at once
    (work / "projects.toml").write_text(GRANTS + "\n", encoding="utf-8")       # the write ends
    team.hub.tick()
    team.hub.tick()
    assert [name for name, _ in got + carol.drain() if name == "gone"] == []


def test_projects_groups_prints_each_projects_assistants_and_their_groups(work, capsys):
    """An entry's `assistants` names the agents that work on the project for its members (8.12): the Library
    gives each its groups, as `members` does for a member. An entry without it has none."""
    import json
    (work / "projects.toml").write_text(GRANTS.replace("members =", 'assistants = ["James"]\nmembers =')
                                        + '\n[projects."acme/inbox"]\nmembers = ["alice"]\nstatus = "live"\n'
                                        + 'assistants = ["james", "mistral"]\n'
                                        + '\n[projects."acme/blog"]\nmembers = ["carol"]\nstatus = "live"\n',
                                        encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    assert code == 0
    got = json.loads(out)
    assert {p["project"]: p["assistants"] for p in got["projects"]} == {
        "acme/blog": [], "acme/inbox": ["james", "mistral"], "acme/tiroir": ["james"]}
    assert got["assistants"] == {"james": ["group:proj-acme-inbox", "group:proj-acme-tiroir"],
                                 "mistral": ["group:proj-acme-inbox"]}
    assert got["members"] == {"carol": ["group:proj-acme-blog", "group:proj-acme-tiroir"],
                              "alice": ["group:proj-acme-inbox", "group:proj-acme-tiroir"]}


def test_a_file_without_assistants_prints_none(work, capsys):
    import json
    (work / "projects.toml").write_text(GRANTS, encoding="utf-8")
    code, out, _ = groups(capsys, "--root", str(work))
    got = json.loads(out)
    assert code == 0 and got["assistants"] == {} and got["projects"][0]["assistants"] == []


def test_an_assistant_is_granted_nothing_in_the_hub(team, work):
    """`assistants` is for the Library alone: an agent reaches the hub through its member's token (9.7), so a
    member's short in `assistants` opens nothing that `members` does not."""
    (work / "projects.toml").write_text(GRANTS.replace("members =", 'assistants = ["bob"]\nmembers ='),
                                        encoding="utf-8")
    put(team, work, SHARED, OPEN)
    assert team.get(f"/work/{SHARED}", member=BOB).status == 404
    assert team.get(f"/work/{SHARED}", member=CAROL).status == 200


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


NEW = "# New\n"
THE_PAGE = "acme/tiroir/2026-10-29-new.md"


def made(browser, token, doc=f"work/{THE_PAGE}"):
    from helpers import call
    return call(browser, "create", token=token, doc=doc, text=NEW)


def test_a_create_by_a_non_member_names_the_project_and_never_a_root(team, work, browser, tokens):
    is_error, got = made(browser, tokens["bob"])
    assert is_error and not (work / THE_PAGE).exists()
    assert got == (f"work/{THE_PAGE} cannot be made: the token's member is not in the project acme/tiroir."), got
    assert "root" not in got and "alice" not in got.lower() and "carol" not in got.lower()


@pytest.mark.parametrize("grants", ['[projects."acme/other"]\nmembers = ["alice"]\nstatus = "live"\n',
                                    'not toml at all ['])
def test_a_project_the_file_does_not_name_and_a_file_that_cannot_be_read_answer_as_a_non_member(
        team, work, browser, tokens, grants):
    is_error, got = made(browser, tokens["bob"])
    _, absent_project = made(browser, tokens["bob"], doc=f"work/{THE_PAGE}".replace("tiroir", "ghost"))
    (work / "projects.toml").write_text(grants, encoding="utf-8")
    is_error, unnamed = made(browser, tokens["alice"])
    assert is_error and unnamed == got, unnamed
    assert absent_project == got.replace("acme/tiroir", "acme/ghost")


def test_a_refusal_of_the_real_path_alone_keeps_the_old_sentence(team, work, browser, tokens):
    (work / "projects.toml").write_text(GRANTS + '\n[projects."acme/other"]\nmembers = ["carol"]\nstatus = "live"\n',
                                        encoding="utf-8")
    (work / "acme" / "other").mkdir()
    (work / "acme" / "tiroir" / "link").symlink_to(work / "acme" / "other")
    is_error, got = made(browser, tokens["alice"], doc="work/acme/tiroir/link/2026-10-29-new.md")
    assert is_error and NOT_IN_A_ROOT in got and "member" not in got, got


def test_the_key_and_an_unbound_token_are_never_told_of_a_member(team, work, browser):
    from sheafmd.hub.state import Tokens
    for n, token in enumerate([None, Tokens().add("plain", write=True)]):
        _, got = made(browser, token, doc=f"work/acme/tiroir/2026-10-29-new{n}.md")
        assert "member" not in str(got), got


def test_a_path_in_no_root_and_a_root_of_another_member_keep_the_old_sentence(team, work, browser, tokens, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    for doc in (str(outside / "new.md"), "nowhere/acme/tiroir/new.md"):
        is_error, got = made(browser, tokens["bob"], doc=doc)
        assert is_error and got == f"{doc} {NOT_IN_A_ROOT}", got
