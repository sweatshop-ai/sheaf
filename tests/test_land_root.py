"""The receiving end of a root's move, first stage (ticket 21): which pages this tiroir can take. The clone through the
same report as a laptop's, each page's owner by e-mail, the page's blob against this tiroir's own clone. A fake hub: no
server, no network."""
import subprocess
from types import SimpleNamespace

import pytest

from sheafmd.hub import incoming, proxy
from sheafmd.hub import repos as repos_mod

HERE = "https://here.example"


def member(id, email, short="", private_root=""):
    return proxy.Member(id=id, name=id, roots=(), email=email, short=short, private_root=private_root)


class FakeRepos:
    def __init__(self, clone, dest):
        self.answer, self.dest, self.calls = {"clone": clone, "commit_known": True}, dest, []

    def report(self, member, repo, path, commit, privates=(), declared=None):
        self.calls.append((member, repo, path, commit, list(privates)))
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"repo": repo, "path": path, **self.answer}

    def clone_dir(self, repo):
        return self.dest


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path):
    """A clone on `dev` whose `origin/dev` holds a.md."""
    bare = tmp_path / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(bare)], check=True)
    c = tmp_path / "c"
    subprocess.run(["git", "clone", "-q", str(bare), str(c)], check=True, capture_output=True)
    git(c, "checkout", "-q", "-b", "dev")
    (c / "a.md").write_text("# A\n")
    git(c, "add", "a.md")
    git(c, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qm", "a")
    git(c, "push", "-q", "-u", "origin", "dev")
    return c


def hub(clone, state=repos_mod.OK, members=None):
    members = members if members is not None else [member("alice", "alice@example.com", short="al"), member("bob", "bob@example.com")]
    return SimpleNamespace(proxy=SimpleNamespace(origin=HERE, members={m.id: m for m in members}), repos=FakeRepos(state, clone))


def body(clone, *pages, **over):
    return {"id": "m1", "repo": "o/r", "branch": "dev", "tip": git(clone, "rev-parse", "dev"),
            "from": {"origin": "https://there.example", "by": "alice"},
            "pages": [{"path": p, "owner_email": e, "blob": git(clone, "hash-object", "a.md") if b is None else b}
                      for p, e, b in pages], **over}


def test_a_page_whose_owner_and_blob_match_is_ready(clone):
    status, answer = incoming.check_root(hub(clone), body(clone, ("a.md", "ALICE@example.com", None)))
    assert (status, answer) == (200, {"pages": {"a.md": {"ready": True}}})


def test_the_report_is_the_laptops_own_with_the_owner_the_tip_and_the_private_roots(clone):
    h = hub(clone, members=[member("alice", "alice@example.com", short="al"), member("bob", "bob@example.com", private_root="/x")])
    incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)))
    (who, repo, path, commit, privates), = h.repos.calls
    assert (who, repo, path, commit) == ("al", "o/r", "a.md", git(clone, "rev-parse", "dev"))
    assert privates == [("bob", "/x")]


def test_one_report_is_made_for_the_whole_root(clone):
    h = hub(clone)
    incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None), ("b.md", "bob@example.com", None)))
    assert len(h.repos.calls) == 1


def test_a_clone_being_made_answers_cloning(clone):
    assert incoming.check_root(hub(clone, repos_mod.CLONING), body(clone, ("a.md", "alice@example.com", None))) == (202, {"state": "cloning"})


def test_a_clone_that_does_not_know_the_tip_yet_answers_cloning(clone):
    h = hub(clone)
    h.repos.answer["commit_known"] = False
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (202, {"state": "cloning"})


def test_no_app_for_the_repo_is_refused_whole_with_the_install_link(clone):
    h = hub(clone, repos_mod.NO_APP)
    h.repos.answer["install"] = "https://install.example/o/r"
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == \
        (409, {"why": "no_app", "install": "https://install.example/o/r"})


@pytest.mark.parametrize("state,why", [(repos_mod.PRIVATE_ROOT, "private_root"), (repos_mod.NOT_CLONED, "not_cloned")])
def test_a_private_root_or_a_repo_not_cloned_is_refused_whole(clone, state, why):
    assert incoming.check_root(hub(clone, state), body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": why})


def test_a_refused_report_is_refused_whole(clone):
    h = hub(clone)
    h.repos.answer = repos_mod.Refused("the clone failed")
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "refused"})


def test_each_page_is_judged_alone_none_ambiguous_and_made_up_refused(clone):
    members = [member("alice", "alice@example.com"), member("c1", "twin@example.com"), member("c2", "TWIN@example.com"), member("dan", "")]
    made_up = proxy.default_email("dan", HERE)
    pages = [("a.md", "alice@example.com", None), ("b.md", "nobody@example.com", None), ("c.md", "twin@example.com", None),
             ("d.md", made_up, None), ("e.md", "", None)]
    status, answer = incoming.check_root(hub(clone, members=members), body(clone, *pages))
    assert status == 200
    assert answer["pages"] == {"a.md": {"ready": True}, "b.md": {"ok": False, "why": "no_owner"},
                               "c.md": {"ok": False, "why": "ambiguous_owner"}, "d.md": {"ok": False, "why": "no_email"},
                               "e.md": {"ok": False, "why": "no_email"}}


def test_a_page_this_tiroirs_clone_does_not_hold_with_that_blob_is_text_differs(clone):
    status, answer = incoming.check_root(hub(clone), body(clone, ("a.md", "alice@example.com", "0" * 40), ("gone.md", "alice@example.com", None)))
    assert answer["pages"] == {"a.md": {"ok": False, "why": "text_differs"}, "gone.md": {"ok": False, "why": "text_differs"}}


def test_no_page_with_an_owner_makes_no_report_and_no_clone(clone):
    h = hub(clone)
    status, answer = incoming.check_root(h, body(clone, ("a.md", "nobody@example.com", None)))
    assert h.repos.calls == [] and answer["pages"]["a.md"]["why"] == "no_owner"


def test_a_hub_with_no_clones_refuses_the_root(clone):
    h = hub(clone)
    h.repos = None
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "no_clones"})


@pytest.mark.parametrize("bad", [{"id": ""}, {"repo": 3}, {"branch": None}, {"tip": ""}, {"pages": "x"}, {"pages": [{"path": "../x.md", "owner_email": "a", "blob": "b"}]},
                                 {"pages": [{"path": "a.md", "blob": "b"}]}])
def test_a_body_that_is_not_a_root_is_refused_with_the_reason(clone, bad):
    with pytest.raises(ValueError):
        incoming.check_root(hub(clone), body(clone, ("a.md", "alice@example.com", None), **bad))


def test_a_repo_that_moved_away_is_refused_whole_and_never_answers_cloning(clone):
    assert incoming.check_root(hub(clone, repos_mod.MOVED), body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "moved"})


def test_a_hub_with_no_origin_of_its_own_refuses_the_root_whole(clone):
    h = hub(clone)
    del h.proxy
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "no_origin"})
