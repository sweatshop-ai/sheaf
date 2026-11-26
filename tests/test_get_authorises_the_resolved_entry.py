"""A request authorises the entry it resolved, by that entry's root, never an address it resolves afterwards: a root
name given to another folder between the check and the resolve must not hand a member the replacement's document."""
import pytest
from helpers import Front
from test_hub_visibility import BOB, OPEN, members

DOC = "acme/tiroir/2026-10-28-contract.md"
MINE = OPEN
THEIRS = OPEN.replace("A quote from the contract.", "The replacement root's own text.")


@pytest.fixture
def team(hub, browser, work, plan):
    hub.proxy = members(work)
    (work / DOC).parent.mkdir(parents=True)
    (work / DOC).write_text(MINE, encoding="utf-8")
    return Front(hub, browser.handler)


def reassign_in_the_gap(hub, work, tmp_path, when, theirs=None):
    """The root name `work` is let go and given to another folder holding a document of the same address, once, at the
    moment `Hub.entry` (the resolve) is called, so after the handler's first check and before anything is served."""
    other = tmp_path / "other"
    (other / DOC).parent.mkdir(parents=True)
    (other / "plan.md").write_text("# plan\n", encoding="utf-8")
    (other / DOC).write_bytes(THEIRS.encode() if theirs is None else theirs)
    real, done = hub.entry, []

    def entry(address, *a, **k):
        if when == "before" and not done:
            done.append(1)
            hub.roots.forget("work")
            hub.roots._add(other, False, name="work")
        return real(address, *a, **k)
    hub.entry = entry
    return done


@pytest.mark.parametrize("path", ["/work/" + DOC, "/_/doc?doc=work/" + DOC])
def test_a_root_name_given_to_another_folder_between_the_check_and_the_resolve_serves_nothing(team, work, tmp_path, path):
    done = reassign_in_the_gap(team.hub, work, tmp_path, "before")
    got = team.get(path, member=BOB)
    assert done, "the gap was not reached"
    missing = team.get(path.replace(DOC, "acme/tiroir/nothing.md"), member=BOB)
    assert got.status == 404 and "replacement root" not in got.text
    assert got.body == missing.body


def test_a_replacement_that_is_not_utf8_answers_as_a_missing_document_and_is_never_read(team, work, tmp_path):
    done = reassign_in_the_gap(team.hub, work, tmp_path, "before", theirs=b"\xff\xfe not text")
    got = team.get("/work/" + DOC, member=BOB)
    missing = team.get("/work/acme/tiroir/nothing.md", member=BOB)
    assert done and got.status == missing.status == 404 and got.body == missing.body
    assert "work/" + DOC not in team.hub.entries


def test_a_root_registered_or_forgotten_during_the_check_does_not_fail_the_request(team, work, tmp_path):
    hub, done, real = team.hub, [], team.hub.visible

    def visible(*a, **k):
        if not done:
            done.append(1)
            side = tmp_path / "side"
            side.mkdir()
            (side / "x.md").write_text("# x\n", encoding="utf-8")
            hub.roots.for_document(side / "x.md")      # the registry is reloaded, every Root made again
            hub.roots.forget("side")
        return real(*a, **k)
    hub.visible = visible
    assert team.get("/work/" + DOC, member=BOB).status == 200 and done


