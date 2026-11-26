"""The Source adapter contract (ADR 0004, 0006; block editor v1, ticket 21): one suite, run unchanged against the Markdown-file
adapter and against the remote adapter talking to the reference Source service, a process of its own.

The tests under "the contract" take the `kind` fixture and know nothing of which adapter they have. What only a service can do
(its authors, its bearer, its pages, its errors) is below them."""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from source_fakes import ReferenceService, Stand

from sheafmd import adapter as rda
from sheafmd import remote
from sheafmd import source as rds

DOC = "Para one.\n\nPara two.\n"
AUTHOR = "Ada"


class FileKind:
    """The Markdown-file adapter over a file of a folder."""
    name = "file"

    def __init__(self, tmp_path):
        self.folder = tmp_path / "docs"
        self.folder.mkdir()

    def adapter(self, name="d.md", text=DOC):
        (self.folder / name).write_text(text, encoding="utf-8")
        return rda.MarkdownFileAdapter(self.folder / name)

    def refusing(self):
        """An adapter that refuses any write, a tree to try it with, and the name of its file."""
        return self.adapter("d.txt"), rda.Tree("x\n"), "d.txt"

    def outside(self, name, text):
        (self.folder / name).write_text(text, encoding="utf-8")

    def text(self, name="d.md"):
        return (self.folder / name).read_text(encoding="utf-8")


class RemoteKind(FileKind):
    """The remote adapter, over the reference Source service started as a process, serving the same kind of folder."""
    name = "remote"

    def __init__(self, tmp_path, request):
        super().__init__(tmp_path)
        (tmp_path / "secrets").mkdir()
        self.service = ReferenceService(self.folder, tmp_path / "secrets")
        request.addfinalizer(self.service.stop)
        self.source = remote.RemoteSource("site", self.service.url, self.service.bearer)

    def adapter(self, name="d.md", text=DOC):
        (self.folder / name).write_text(text, encoding="utf-8")
        return self.source.adapter(name)

    def refusing(self):
        return self.adapter(), rda.Tree(""), "d.md"


@pytest.fixture(params=["file", "remote"])
def kind(request, tmp_path):
    return FileKind(tmp_path) if request.param == "file" else RemoteKind(tmp_path, request)


# ── the contract ─────────────────────────────────────────────────────────────

def test_the_adapter_declares_an_integer_interface_version(kind):
    a = kind.adapter()
    assert isinstance(a.interface, int) and not isinstance(a.interface, bool)
    assert a.interface == rda.INTERFACE_VERSION


def test_read_gives_the_tree_and_the_content_hash_as_base(kind):
    tree, base = kind.adapter().read()
    assert tree.text == DOC
    assert base == rds.md_hash(DOC)


def test_a_write_against_the_current_base_is_written(kind):
    a = kind.adapter()
    _, base = a.read()
    out = a.write(rda.Tree("Changed.\n"), base, author=AUTHOR, note="n")
    assert out["outcome"] == "written"
    assert out["base"] == rds.md_hash("Changed.\n")
    assert kind.text() == "Changed.\n"
    assert a.read()[1] == out["base"]


def test_a_stale_base_is_a_conflict_not_an_exception_and_writes_nothing(kind):
    a = kind.adapter()
    _, old = a.read()
    kind.outside("d.md", "Someone else.\n")
    out = a.write(rda.Tree("Mine.\n"), old, author=AUTHOR, note="")
    assert out["outcome"] == "conflict"
    assert out["base"] == rds.md_hash("Someone else.\n")
    assert out["blocks"] == []
    assert kind.text() == "Someone else.\n"


def test_a_write_the_adapter_will_not_make_is_refused_and_writes_nothing(kind):
    a, tree, name = kind.refusing()
    _, base = a.read()
    before = kind.text(name)
    out = a.write(tree, base, author=AUTHOR, note="")
    assert out["outcome"] == "refused"
    assert out["reason"]
    assert kind.text(name) == before


def test_the_base_a_write_gives_is_the_one_the_next_write_needs(kind):
    a = kind.adapter()
    _, base = a.read()
    first = a.write(rda.Tree("One.\n"), base, author=AUTHOR, note="")
    second = a.write(rda.Tree("Two.\n"), first["base"], author=AUTHOR, note="")
    assert (first["outcome"], second["outcome"]) == ("written", "written")
    assert kind.text() == "Two.\n"
    again = a.write(rda.Tree("Three.\n"), first["base"], author=AUTHOR, note="")      # the base of two writes ago
    assert again["outcome"] == "conflict" and again["base"] == second["base"]
    assert kind.text() == "Two.\n"


def test_a_write_of_the_text_already_there_is_written_with_the_same_base(kind):
    a = kind.adapter()
    tree, base = a.read()
    out = a.write(tree, base, author=AUTHOR, note="")
    assert out["outcome"] == "written" and out["base"] == base


def test_a_text_that_is_not_ascii_comes_back_as_written(kind):
    a = kind.adapter()
    _, base = a.read()
    text = "Café — 日本語\n"
    out = a.write(rda.Tree(text), base, author=AUTHOR, note="")
    assert out["outcome"] == "written"
    assert a.read()[0].text == text and kind.text() == text


# ── what only a service has ───────────────────────────────────────────────────

@pytest.fixture
def remote_kind(tmp_path, request):
    return RemoteKind(tmp_path, request)


def git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(folder):
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.name", "Seed")
    git(folder, "config", "user.email", "seed@example.org")
    (folder / "d.md").write_text(DOC, encoding="utf-8")
    git(folder, "add", ".")
    git(folder, "commit", "-q", "-m", "seed")


def test_an_unmapped_member_is_refused_with_unknown_author_and_nothing_is_written(remote_kind):
    a = remote_kind.adapter()
    _, base = a.read()
    out = a.write(rda.Tree("Changed.\n"), base, author="Mallory", note="")
    assert out["outcome"] == "refused" and out["code"] == "unknown_author"
    assert remote_kind.text() == DOC


def test_an_empty_author_is_unmapped_too(remote_kind):
    a = remote_kind.adapter()
    _, base = a.read()
    assert a.write(rda.Tree("Changed.\n"), base, author="", note="")["code"] == "unknown_author"
    assert remote_kind.text() == DOC


def test_the_member_is_mapped_before_the_base_is_looked_at(remote_kind):
    a = remote_kind.adapter()
    out = a.write(rda.Tree("Changed.\n"), "not-the-base", author="Mallory", note="")
    assert out["outcome"] == "refused" and out["code"] == "unknown_author"


def test_a_mapped_members_write_is_committed_as_the_mapped_author(tmp_path, request):
    kind = RemoteKind(tmp_path, request)
    make_repo(kind.folder)
    kind.service.stop()                         # restart where the folder is a work tree: the service looks once, at its start
    kind.service = ReferenceService(kind.folder, tmp_path / "secrets")
    request.addfinalizer(kind.service.stop)
    a = remote.RemoteSource("site", kind.service.url, kind.service.bearer).adapter("d.md")
    _, base = a.read()
    note = "Shorten the second paragraph, via agent-one"
    assert a.write(rda.Tree("Para one.\n"), base, author="Grace", note=note)["outcome"] == "written"
    assert git(kind.folder, "log", "-1", "--format=%an <%ae>|%cn <%ce>|%s") == \
        f"Grace Editor <grace@example.org>|Grace Editor <grace@example.org>|{note}"
    assert git(kind.folder, "status", "--porcelain") == ""


def test_a_refused_member_leaves_no_commit(tmp_path, request):
    kind = RemoteKind(tmp_path, request)
    make_repo(kind.folder)
    kind.service.stop()
    kind.service = ReferenceService(kind.folder, tmp_path / "secrets")
    request.addfinalizer(kind.service.stop)
    a = remote.RemoteSource("site", kind.service.url, kind.service.bearer).adapter("d.md")
    _, base = a.read()
    a.write(rda.Tree("Para one.\n"), base, author="Mallory", note="x")
    assert git(kind.folder, "rev-list", "--count", "HEAD") == "1"


def test_a_missing_or_wrong_bearer_is_unauthorized_for_every_call(remote_kind):
    remote_kind.adapter()
    for bearer in ("wrong-bearer-0123456789", "", "x" * 600):
        source = remote.RemoteSource("site", remote_kind.service.url, bearer)
        for verb, body in (("info", {}), ("documents", {}), ("read", {"document": "d.md"}),
                           ("write", {"document": "d.md", "tree": {"text": "z\n"}, "base": "b", "author": AUTHOR, "note": ""})):
            with pytest.raises(remote.SourceError) as e:
                source.ask(verb, body)
            assert e.value.code == "unauthorized", (bearer, verb)
            assert bearer not in str(e.value) or bearer == ""
    assert remote_kind.text() == DOC


def test_a_bearer_that_is_not_ascii_is_unauthorized_not_a_crash(remote_kind):
    stand_free = remote.RemoteSource("site", remote_kind.service.url, "x")
    for raw in (b"Bearer p\xc3\xa4ss-0123456789", b"Bearer \xff\xfe", b"Bearer", b"Basic abc", b"bearer " + remote_kind.service.bearer.encode()):
        conn = stand_free._connection()
        conn.connect()
        conn.request("POST", "/read", json.dumps({"document": "d.md"}), {"Content-Type": "application/json", "Authorization": raw})
        res = conn.getresponse()
        body = json.loads(res.read())
        conn.close()
        assert res.status == 401 and body["error"]["code"] == "unauthorized", raw


def test_a_bearer_with_a_character_the_wire_cannot_carry_is_refused_by_the_client_without_naming_it():
    with pytest.raises(ValueError) as e:
        remote.RemoteSource("site", "unix:///x.sock", "p\u00e4ss-\u2603-0123456789")
    assert "p\u00e4ss" not in str(e.value)


def test_a_request_with_no_authorization_header_is_unauthorized(remote_kind):
    stand_free = remote.RemoteSource("site", remote_kind.service.url, "x")
    stand_free._bearer = None
    conn = stand_free._connection()
    conn.connect()
    conn.request("POST", "/read", json.dumps({"document": "d.md"}), {"Content-Type": "application/json"})
    res = conn.getresponse()
    body = json.loads(res.read())
    conn.close()
    assert res.status == 401 and body["error"]["code"] == "unauthorized"
    assert DOC not in json.dumps(body)


def test_an_error_names_the_source_and_never_the_bearer(remote_kind):
    bearer = remote_kind.service.bearer
    source = remote.RemoteSource("site", remote_kind.service.url, bearer)
    with pytest.raises(remote.SourceError) as e:
        source.adapter("missing.md").read()
    assert e.value.code == "not_found"
    assert bearer not in str(e.value) and bearer not in repr(source) and bearer not in e.value.message
    down = remote.RemoteSource("site", "unix:///nonexistent/s.sock", bearer)
    with pytest.raises(remote.Unreachable) as e:
        down.info()
    assert bearer not in str(e.value) and "site" in str(e.value)


def test_a_document_that_is_not_there_is_not_found_and_a_bad_name_is_bad_request(remote_kind):
    source = remote_kind.source
    for name, code in (("missing.md", "not_found"), ("../up.md", "bad_request"), ("/abs.md", "bad_request"),
                       ("a//b.md", "bad_request"), ("d.txt", "bad_request"), (".git/x.md", "bad_request"), ("", "bad_request"),
                       ("a\0b.md", "bad_request")):
        with pytest.raises(remote.SourceError) as e:
            source.adapter(name).read()
        assert e.value.code == code, name


def test_a_link_that_leaves_the_folder_is_not_read(remote_kind, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    (remote_kind.folder / "link.md").symlink_to(outside)
    with pytest.raises(remote.SourceError) as e:
        remote_kind.source.adapter("link.md").read()
    assert e.value.code == "not_found"


def test_info_names_the_interface_the_source_and_whether_it_publishes(remote_kind):
    got = remote_kind.source.info()
    assert got == {"interface": rda.INTERFACE_VERSION, "name": remote_kind.folder.name, "publish": False}
    assert remote_kind.source.display == remote_kind.folder.name and remote_kind.source.publishes is False


def test_documents_pages_past_500(remote_kind):
    names = sorted(f"s{i % 7}/d{i:04d}.md" for i in range(1203))
    for n in names:
        p = remote_kind.folder / n
        p.parent.mkdir(exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    first = remote_kind.source.ask("documents", {})
    assert len(first["documents"]) == 500 and first["next"]
    second = remote_kind.source.ask("documents", {"cursor": first["next"]})
    assert len(second["documents"]) == 500 and second["next"]
    third = remote_kind.source.ask("documents", {"cursor": second["next"]})
    assert len(third["documents"]) == 203 and third["next"] is None
    assert list(remote_kind.source.documents()) == names


def test_documents_lists_only_markdown_files_below_the_folder_and_none_a_link_leads_out_of(remote_kind, tmp_path):
    f = remote_kind.folder
    (f / "keep.md").write_text("x\n", encoding="utf-8")
    (f / "sub").mkdir()
    (f / "sub" / "deep.md").write_text("x\n", encoding="utf-8")
    (f / "note.txt").write_text("x\n", encoding="utf-8")
    (f / ".hidden").mkdir()
    (f / ".hidden" / "no.md").write_text("x\n", encoding="utf-8")
    (f / ".dot.md").write_text("x\n", encoding="utf-8")
    outside = tmp_path / "out.md"
    outside.write_text("x\n", encoding="utf-8")
    (f / "link.md").symlink_to(outside)
    assert list(remote_kind.source.documents()) == ["keep.md", "sub/deep.md"]


def test_a_cursor_the_service_did_not_give_is_bad_request(remote_kind):
    with pytest.raises(remote.SourceError) as e:
        remote_kind.source.ask("documents", {"cursor": "%%%"})
    assert e.value.code == "bad_request"
    with pytest.raises(remote.SourceError) as e:
        remote_kind.source.ask("documents", {"cursor": 7})
    assert e.value.code == "bad_request"


def test_an_unknown_call_and_a_get_are_bad_request(remote_kind):
    with pytest.raises(remote.SourceError) as e:
        remote_kind.source.ask("frobnicate", {})
    assert e.value.code == "bad_request"
    with pytest.raises(remote.SourceError) as e:
        remote_kind.source.ask("publish", {"document": "d.md"})        # the reference service declares none
    assert e.value.code == "bad_request"


# ── the client, against a service of the test's own ───────────────────────────

def stand(request, handler):
    s = Stand(handler)
    request.addfinalizer(s.stop)
    return s


def test_a_service_that_closes_its_connection_after_each_answer_is_served(request):
    """`http.client` lets go of the socket once it has read a `Connection: close` answer: the client must not touch it again."""
    s = Stand(lambda verb, body, h: (200, {"interface": rda.INTERFACE_VERSION, "name": "x", "publish": False}), close=True)
    request.addfinalizer(s.stop)
    src = remote.RemoteSource("shop", s.url, "b" * 20)
    assert src.info()["interface"] == rda.INTERFACE_VERSION
    assert src.info()["interface"] == rda.INTERFACE_VERSION


def test_another_interface_version_is_a_mismatch_that_names_both(request):
    s = stand(request, lambda verb, body, h: (200, {"interface": 2, "name": "x", "publish": False}))
    with pytest.raises(remote.VersionMismatch) as e:
        remote.RemoteSource("shop", s.url, "b" * 20).info()
    assert e.value.code == "version" and "2" in str(e.value) and str(rda.INTERFACE_VERSION) in str(e.value) and "shop" in str(e.value)
    assert (e.value.theirs, e.value.ours) == (2, rda.INTERFACE_VERSION)


@pytest.mark.parametrize("reported", [None, "1", True, 1.5, [1]])
def test_a_version_that_is_not_the_integer_is_a_mismatch(request, reported):
    s = stand(request, lambda verb, body, h: (200, {"interface": reported, "name": "x"}))
    with pytest.raises(remote.VersionMismatch):
        remote.RemoteSource("shop", s.url, "b" * 20).info()


def test_every_request_is_a_post_with_the_bearer_and_a_json_body(request):
    s = stand(request, lambda verb, body, h: (200, {"interface": 1, "name": "x", "publish": True}))
    source = remote.RemoteSource("shop", s.url, "the-bearer-0123456789")
    source.info()
    verb, body, headers = s.seen[0]
    assert verb == "info"
    assert headers["Authorization"] == "Bearer the-bearer-0123456789"
    assert headers["Content-Type"] == "application/json"
    assert source.publishes is True


@pytest.mark.parametrize("code,status", [("unauthorized", 401), ("not_found", 404), ("bad_request", 400),
                                         ("unknown_author", 403), ("version", 409)])
def test_each_error_body_raises_its_code(request, code, status):
    s = stand(request, lambda verb, body, h: (status, {"error": {"code": code, "message": "words"}}))
    with pytest.raises(remote.SourceError) as e:
        remote.RemoteSource("shop", s.url, "b" * 20).ask("read", {"document": "a.md"})
    assert e.value.code == code and not isinstance(e.value, remote.Unreachable)


@pytest.mark.parametrize("status,payload", [(503, {"error": {"code": "unavailable", "message": "down"}}), (500, {}), (502, {"x": 1}),
                                            (200, {"error": {"code": "unavailable", "message": "down"}})])
def test_unavailable_and_a_5xx_count_as_unreachable(request, status, payload):
    s = stand(request, lambda verb, body, h: (status, payload))
    with pytest.raises(remote.Unreachable):
        remote.RemoteSource("shop", s.url, "b" * 20).ask("read", {"document": "a.md"})


def test_an_answer_that_is_not_json_is_a_protocol_error_naming_no_content(request):
    s = stand(request, lambda verb, body, h: (200, ["not", "an", "object"]))
    with pytest.raises(remote.SourceError) as e:
        remote.RemoteSource("shop", s.url, "b" * 20).ask("info")
    assert e.value.code == "protocol"


def test_a_service_that_never_answers_is_unreachable_after_the_request_timeout(request):
    s = stand(request, lambda verb, body, h: None)
    source = remote.RemoteSource("shop", s.url, "b" * 20, timeout=0.6)
    import time
    t = time.monotonic()
    with pytest.raises(remote.Unreachable):
        source.info()
    assert time.monotonic() - t < 5


def test_a_service_that_drips_its_answer_is_cut_off_at_the_request_deadline(tmp_path):
    import socket
    import threading
    import time
    from source_fakes import short_dir
    run = short_dir()
    path = str(run / "d.sock")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(path)
    srv.listen(1)

    def drip():
        c, _ = srv.accept()
        c.recv(65536)
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n")
        for _ in range(40):
            try:
                c.sendall(b" ")
            except OSError:
                break
            time.sleep(0.1)
        c.close()
    threading.Thread(target=drip, daemon=True).start()
    t = time.monotonic()
    with pytest.raises(remote.Unreachable):
        remote.RemoteSource("shop", f"unix://{path}", "b" * 20, timeout=0.8).info()
    assert time.monotonic() - t < 3
    srv.close()


def test_the_defaults_are_5_seconds_to_connect_and_30_for_a_request():
    assert (remote.CONNECT_TIMEOUT, remote.REQUEST_TIMEOUT) == (5.0, 30.0)
    s = remote.RemoteSource("shop", "unix:///x.sock", "b" * 20)
    assert (s._connect, s._timeout) == (5.0, 30.0)


def test_a_service_that_lists_more_than_500_in_a_page_is_not_believed(request):
    rows = [{"name": f"d{i}.md"} for i in range(501)]
    s = stand(request, lambda verb, body, h: (200, {"documents": rows, "next": None}))
    with pytest.raises(remote.SourceError):
        list(remote.RemoteSource("shop", s.url, "b" * 20).documents())


def test_a_cursor_that_does_not_move_ends_the_listing_with_an_error(request):
    s = stand(request, lambda verb, body, h: (200, {"documents": [{"name": "a.md"}], "next": "same"}))
    with pytest.raises(remote.SourceError):
        list(remote.RemoteSource("shop", s.url, "b" * 20).documents())


@pytest.mark.parametrize("url,ok", [("https://site.example/sheaf", True), ("unix:///run/site/s.sock", True),
                                    ("http://127.0.0.1:9000", True), ("http://localhost:9000/x", True),
                                    ("http://site.example", False), ("https://user:pw@site.example", False),
                                    ("https://user@site.example", False), ("ftp://site.example", False),
                                    ("unix://host/run/s.sock", False), ("unix:relative.sock", False), ("https://", False),
                                    ("https://site.example/?key=1", False), ("", False), ("site.example", False)])
def test_a_url_is_https_a_unix_socket_or_loopback_and_carries_no_credential(url, ok):
    if ok:
        assert remote.check_url(url) == url
    else:
        with pytest.raises(remote.BadUrl) as e:
            remote.check_url(url)
        assert "pw" not in str(e.value)


def test_a_write_through_an_agent_token_carries_via_the_token_name_in_its_note(tmp_path, request):
    kind = RemoteKind(tmp_path, request)
    make_repo(kind.folder)
    kind.service.stop()
    kind.service = ReferenceService(kind.folder, tmp_path / "secrets")
    request.addfinalizer(kind.service.stop)
    a = remote.RemoteSource("site", kind.service.url, kind.service.bearer).adapter("d.md")
    _, base = a.read()
    assert a.write(rda.Tree("Para one.\n"), base, author="Ada", note="Shorten it", via="grace-claude")["outcome"] == "written"
    assert git(kind.folder, "log", "-1", "--format=%s") == "Shorten it via grace-claude"


def test_via_is_one_line_and_absent_when_no_token_wrote():
    assert remote.with_via("Edit", "") == "Edit"
    assert remote.with_via("", "tok") == "via tok"
    assert remote.with_via("Edit\n", "a\nb  c") == "Edit via a b c"


# ── the reference service's git commits ───────────────────────────────────────

def _git_service(tmp_path):
    import subprocess
    from sheafmd import sourceservice
    folder = tmp_path / "repo"
    folder.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}

    def git(*a):
        return subprocess.run(["git", "-C", str(folder), *a], capture_output=True, text=True, check=True, env={**os.environ, **env}).stdout
    git("init", "-q")
    (folder / "*.md").write_text("star\n")
    (folder / "b.md").write_text("bee\n")
    git("add", "."), git("commit", "-q", "-m", "start")
    return sourceservice.Service(folder, "b" * 20, {"Ada": ("Ada Writer", "ada@example.org")}), folder, git


def test_a_document_named_like_a_glob_commits_that_file_only(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    (folder / "b.md").write_text("bee, edited by someone else\n")
    base = svc.read("*.md")["base"]
    out = svc.write({"document": "*.md", "author": "Ada", "note": "n", "base": base, "tree": {"text": "star two\n"}})
    assert out["outcome"] == "written"
    assert git("show", "--name-only", "--format=", "HEAD").split() == ["*.md"]
    assert "b.md" in git("status", "--porcelain")                   # the other file is still the other person's change


def test_a_write_that_changes_nothing_commits_nothing(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    (folder / "b.md").write_text("bee, uncommitted\n")
    before = git("rev-list", "--count", "HEAD")
    base = svc.read("b.md")["base"]
    out = svc.write({"document": "b.md", "author": "Ada", "note": "n", "base": base, "tree": {"text": "bee, uncommitted\n"}})
    assert out["outcome"] == "written" and git("rev-list", "--count", "HEAD") == before


# ── round 9: a failed git step, a link inside the folder, the fixture's start-up failure ───────────────────────

def _signing_fails(git):
    """The repository is set to sign each commit with a program that fails: every commit is refused."""
    git("config", "commit.gpgsign", "true")
    git("config", "gpg.program", "false")


def test_a_git_step_that_fails_restores_the_file_and_refuses_and_a_retry_then_commits(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    _signing_fails(git)
    before = (folder / "b.md").read_bytes()
    head = git("rev-parse", "HEAD")
    base = svc.read("b.md")["base"]
    body = {"document": "b.md", "author": "Ada", "note": "n", "base": base, "tree": {"text": "bee two\n"}}
    out = svc.write(body)
    assert out["outcome"] == "refused" and "written" not in json.dumps(out)
    assert (folder / "b.md").read_bytes() == before and git("rev-parse", "HEAD") == head
    assert git("status", "--porcelain") == ""                           # nothing is left staged either
    git("config", "commit.gpgsign", "false")
    out = svc.write(body)                                               # the same text, the same base
    assert out["outcome"] == "written" and git("rev-parse", "HEAD") != head
    assert git("show", "--name-only", "--format=", "HEAD").split() == ["b.md"]
    assert (folder / "b.md").read_text() == "bee two\n"


def test_a_git_step_that_fails_is_a_refusal_over_the_wire_too(tmp_path, request):
    kind = RemoteKind(tmp_path, request)
    make_repo(kind.folder)
    git(kind.folder, "config", "commit.gpgsign", "true")
    git(kind.folder, "config", "gpg.program", "false")
    kind.service.stop()
    kind.service = ReferenceService(kind.folder, tmp_path / "secrets")
    request.addfinalizer(kind.service.stop)
    a = remote.RemoteSource("site", kind.service.url, kind.service.bearer).adapter("d.md")
    _, base = a.read()
    assert a.write(rda.Tree("Para one.\n"), base, author="Grace", note="x")["outcome"] == "refused"
    assert (kind.folder / "d.md").read_text() == DOC


def _svc_plain(tmp_path):
    from sheafmd import sourceservice
    folder = tmp_path / "plain"
    (folder / "sub").mkdir(parents=True)
    (folder / "real.md").write_text("real\n")
    (folder / "sub" / "deep.md").write_text("deep\n")
    (folder / ".hidden.md").write_text("hidden\n")
    (folder / "notes.txt").write_text("not markdown\n")
    return sourceservice.Service(folder, "b" * 20, {"Ada": ("Ada Writer", "ada@example.org")}), folder


@pytest.mark.parametrize("link,target", [("link.md", "real.md"), ("hid.md", ".hidden.md"), ("txt.md", "notes.txt"), ("viasub/deep.md", None)])
def test_a_link_inside_the_folder_is_neither_read_nor_written(tmp_path, link, target):
    svc, folder = _svc_plain(tmp_path)
    if target is None:
        (folder / "viasub").symlink_to(folder / "sub")
        target = "sub/deep.md"
    else:
        (folder / link).symlink_to(folder / target)
    before = (folder / target).read_bytes()
    with pytest.raises(sourceservice_fault()) as e:
        svc.read(link)
    assert e.value.code == "not_found"
    base = rds.md_hash(before.decode())
    with pytest.raises(sourceservice_fault()) as e:
        svc.write({"document": link, "author": "Ada", "note": "n", "base": base, "tree": {"text": "changed\n"}})
    assert e.value.code in ("not_found", "bad_request")
    assert (folder / target).read_bytes() == before


def sourceservice_fault():
    from sheafmd import sourceservice
    return sourceservice.Fault


def test_a_write_to_a_plain_file_still_commits_that_same_path(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    (folder / "sub").mkdir()
    (folder / "sub" / "c.md").write_text("see\n")
    git("add", "."), git("commit", "-q", "-m", "sub")
    base = svc.read("sub/c.md")["base"]
    assert svc.write({"document": "sub/c.md", "author": "Ada", "note": "n", "base": base, "tree": {"text": "see two\n"}})["outcome"] == "written"
    assert git("show", "--name-only", "--format=", "HEAD").split() == ["sub/c.md"]


def test_a_service_that_fails_to_start_says_why_in_the_failure_of_the_fixture(tmp_path):
    (tmp_path / "secrets").mkdir()
    folder = tmp_path / "docs"
    folder.mkdir()
    with pytest.raises(AssertionError) as e:
        ReferenceService(folder, tmp_path / "secrets", authors='[authors]\n"Ada" = "no address"\n')
    assert "must be written" in str(e.value) and "closed file" not in str(e.value)


# ── round 10: nothing to roll back (the commit is made first, off the real index; the file is replaced last), no link at any step ───

def _write_body(svc, rel, text, note="n"):
    return {"document": rel, "author": "Ada", "note": note, "base": svc.read(rel)["base"], "tree": {"text": text}}


def _no_leftovers(folder):
    assert [p.name for p in folder.iterdir() if p.name.startswith(".sheaf-")] == []


def test_a_git_timeout_stops_the_service_with_unavailable_and_it_says_where_things_stand(tmp_path, monkeypatch, capsys):
    svc, folder, git = _git_service(tmp_path)
    real = svc._git

    def slow(*args, **kw):
        if "commit" in args:
            raise subprocess.TimeoutExpired("git", 30)
        return real(*args, **kw)
    monkeypatch.setattr(svc, "_git", slow)
    with pytest.raises(sourceservice_fault()) as e:
        svc.write(_write_body(svc, "b.md", "bee two\n"))
    assert e.value.code == "unavailable"
    said = capsys.readouterr().err
    assert "HEAD" in said and "b.md" in said
    for verb, body in (("read", {"document": "b.md"}), ("documents", {}), ("write", _write_body(svc, "b.md", "x\n"))):
        with pytest.raises(sourceservice_fault()) as again:
            svc.handle(verb, body)
        assert again.value.code == "unavailable"


def test_a_write_is_unavailable_while_the_index_holds_staged_changes_and_nothing_is_touched(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    (folder / "other.md").write_text("other\n")
    git("add", "other.md")
    with pytest.raises(sourceservice_fault()) as e:
        svc.write(_write_body(svc, "b.md", "bee two\n"))
    assert e.value.code == "unavailable" and (folder / "b.md").read_text() == "bee\n" and git("diff", "--cached", "--name-only").strip() == "other.md"


@pytest.mark.parametrize("marker", ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "sequencer"])
def test_a_write_is_unavailable_while_a_merge_rebase_or_cherry_pick_is_in_progress(tmp_path, marker):
    svc, folder, git = _git_service(tmp_path)
    gd = Path(git("rev-parse", "--absolute-git-dir").strip())
    (gd / marker).mkdir() if marker in ("rebase-merge", "sequencer") else (gd / marker).write_text(git("rev-parse", "HEAD").strip() + "\n")
    with pytest.raises(sourceservice_fault()) as e:
        svc.write(_write_body(svc, "b.md", "bee two\n"))
    assert e.value.code == "unavailable" and (folder / "b.md").read_text() == "bee\n"


def test_the_service_refuses_to_start_while_the_repository_is_busy(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    (folder / "other.md").write_text("other\n")
    git("add", "other.md")
    from sheafmd import sourceservice
    with pytest.raises(SystemExit):
        sourceservice.Service(folder, "b" * 20, {})


def test_a_failed_commit_puts_the_bytes_back_even_when_the_cleanup_step_raises(tmp_path, monkeypatch):
    svc, folder, git = _git_service(tmp_path)
    _signing_fails(git)
    real = svc._git

    def broken_reset(*args, **kw):
        if args[:1] == ("reset",):
            raise OSError("reset failed")
        return real(*args, **kw)
    monkeypatch.setattr(svc, "_git", broken_reset)
    with pytest.raises(sourceservice_fault()) as e:
        svc.write(_write_body(svc, "b.md", "bee two\n"))
    assert e.value.code == "unavailable" and (folder / "b.md").read_text() == "bee\n"


def test_a_failed_sync_of_the_folder_after_a_commit_still_counts_as_written(tmp_path, monkeypatch):
    svc, folder, git = _git_service(tmp_path)
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("sync")) if stat.S_ISDIR(os.fstat(fd).st_mode) else real(fd))
    assert svc.write(_write_body(svc, "b.md", "bee two\n"))["outcome"] == "written"
    assert git("show", "HEAD:b.md") == "bee two\n"


def test_a_clean_write_leaves_the_index_and_the_tree_clean_and_the_other_files_of_head_in_the_commit(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    assert svc.write(_write_body(svc, "b.md", "bee two\n"))["outcome"] == "written"
    assert git("status", "--porcelain") == "" and git("show", "--name-only", "--format=", "HEAD").split() == ["b.md"]
    _no_leftovers(folder)


def test_a_stale_base_is_a_conflict_in_a_repository_too(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    body = _write_body(svc, "b.md", "bee two\n")
    (folder / "b.md").write_text("changed under the member\n")
    assert svc.write(body)["outcome"] == "conflict" and (folder / "b.md").read_text() == "changed under the member\n"


def test_a_write_keeps_the_mode_of_the_file(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    (folder / "b.md").chmod(0o640)
    svc.write(_write_body(svc, "b.md", "bee two\n"))
    assert (folder / "b.md").stat().st_mode & 0o777 == 0o640


def _swap_when_opened(monkeypatch, name, make_link):
    """The first `os.open` of `name` below a folder finds a link there: the check, if there was one, was made a moment before."""
    from sheafmd import sourceservice
    real, done = os.open, []

    def opener(path, flags, mode=0o777, *, dir_fd=None):
        if not done and dir_fd is not None and path == name:
            done.append(1)
            make_link()
        return real(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(sourceservice.os, "open", opener)
    return done


def test_a_file_that_becomes_a_link_between_the_check_and_the_open_is_not_followed(tmp_path, monkeypatch):
    svc, folder = _svc_plain(tmp_path)
    body = {"document": "real.md", "author": "Ada", "note": "n", "base": rds.md_hash("real\n"), "tree": {"text": "changed\n"}}

    def link():
        (folder / "real.md").unlink()
        (folder / "real.md").symlink_to(folder / ".hidden.md")
    done = _swap_when_opened(monkeypatch, "real.md", link)
    with pytest.raises(sourceservice_fault()) as e:
        svc.write(body)
    assert done and e.value.code == "not_found" and (folder / ".hidden.md").read_text() == "hidden\n"


def test_a_folder_that_becomes_a_link_between_the_check_and_the_open_is_not_followed(tmp_path, monkeypatch):
    svc, folder = _svc_plain(tmp_path)
    (folder / "other").mkdir()
    (folder / "other" / "deep.md").write_text("other deep\n")

    def link():
        import shutil
        shutil.rmtree(folder / "sub")
        (folder / "sub").symlink_to(folder / "other")
    done = _swap_when_opened(monkeypatch, "sub", link)
    with pytest.raises(sourceservice_fault()) as e:
        svc.read("sub/deep.md")
    assert done and e.value.code == "not_found"


def test_a_hard_link_is_not_a_document(tmp_path):
    svc, folder = _svc_plain(tmp_path)
    os.link(folder / "notes.txt", folder / "twin.md")
    with pytest.raises(sourceservice_fault()) as e:
        svc.read("twin.md")
    assert e.value.code == "not_found"


def test_the_root_is_held_by_descriptor_from_the_start_so_a_link_put_in_its_place_is_not_followed(tmp_path):
    svc, folder = _svc_plain(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "real.md").write_text("elsewhere\n")
    moved = tmp_path / "moved"
    folder.rename(moved)
    folder.symlink_to(elsewhere)
    assert svc.read("real.md")["tree"]["text"] == "real\n"


# ── round 12: the edges ───────────────────────────────────────────────────────

def test_a_document_with_a_very_long_name_is_written(tmp_path):
    svc, folder, git = _git_service(tmp_path)
    name = "n" * 237 + ".md"
    (folder / name).write_text("long\n")
    git("add", name), git("commit", "-q", "-m", "long")
    out = svc.write(_write_body(svc, name, "longer\n"))
    assert out["outcome"] == "written" and (folder / name).read_text() == "longer\n"
    _no_leftovers(folder)


def test_a_read_during_a_write_waits_and_never_sees_a_text_that_git_then_refuses(tmp_path, monkeypatch):
    import threading
    svc, folder, git = _git_service(tmp_path)
    _signing_fails(git)
    real, seen = svc._git, {}

    def reading_meanwhile(*args, **kw):
        if "commit" in args and "t" not in seen:
            seen["t"] = t = threading.Thread(target=lambda: seen.update(got=svc.read("b.md")["tree"]["text"]))
            t.start()
            t.join(0.4)
            seen["blocked"] = t.is_alive()
        return real(*args, **kw)
    monkeypatch.setattr(svc, "_git", reading_meanwhile)
    assert svc.write(_write_body(svc, "b.md", "bee two\n"))["outcome"] == "refused"
    seen["t"].join(5)
    assert seen["blocked"] and seen["got"] == "bee\n"


def test_a_git_timeout_after_the_commit_moved_head_is_not_guessed_at_it_is_unavailable(tmp_path, monkeypatch):
    svc, folder, git = _git_service(tmp_path)
    real = svc._git

    def late(*args, **kw):
        got = real(*args, **kw)
        if "commit" in args:
            raise subprocess.TimeoutExpired("git", 30)
        return got
    monkeypatch.setattr(svc, "_git", late)
    with pytest.raises(sourceservice_fault()) as e:
        svc.write(_write_body(svc, "b.md", "bee two\n"))
    assert e.value.code == "unavailable"


def test_the_start_refusal_names_the_manual_repair(tmp_path):
    from sheafmd import sourceservice
    svc, folder, git = _git_service(tmp_path)
    (folder / "o.md").write_text("o\n")
    git("add", "o.md")
    with pytest.raises(SystemExit) as e:
        sourceservice.Service(folder, "b" * 20, {})
    assert "docs/source-service.md" in str(e.value) and "Failure" in str(e.value)


def test_a_document_that_is_a_fifo_is_not_found_and_blocks_nothing(tmp_path):
    import threading
    svc, folder = _svc_plain(tmp_path)
    os.mkfifo(folder / "pipe.md")
    got = {}

    def go():
        try:
            svc.read("pipe.md")
        except sourceservice_fault() as e:
            got["code"] = e.code
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(3)
    assert not t.is_alive() and got == {"code": "not_found"}
    assert svc.read("real.md")["tree"]["text"] == "real\n"


def test_a_replacement_that_fails_before_the_rename_is_a_clean_refusal_and_leaves_nothing(tmp_path, monkeypatch):
    svc, folder, git = _git_service(tmp_path)
    monkeypatch.setattr(os, "rename", lambda *a, **k: (_ for _ in ()).throw(OSError("rename")))
    assert svc.write(_write_body(svc, "b.md", "bee two\n"))["outcome"] == "refused"
    assert (folder / "b.md").read_text() == "bee\n" and git("status", "--porcelain") == ""
    _no_leftovers(folder)

def test_a_failed_reset_after_a_failed_commit_makes_the_service_unavailable_and_is_never_a_clean_refusal(tmp_path, monkeypatch):
    svc, folder, git = _git_service(tmp_path)
    _signing_fails(git)
    real = svc._git

    def reset_fails(*args, **kw):
        if args[:1] == ("reset",):
            return subprocess.CompletedProcess(args, 1, "", "no")
        return real(*args, **kw)
    monkeypatch.setattr(svc, "_git", reset_fails)
    with pytest.raises(sourceservice_fault()) as e:
        svc.write(_write_body(svc, "b.md", "bee two\n"))
    assert e.value.code == "unavailable" and (folder / "b.md").read_text() == "bee\n"
    git("config", "commit.gpgsign", "false")
    monkeypatch.setattr(svc, "_git", real)
    with pytest.raises(sourceservice_fault()) as again:
        svc.write(_write_body(svc, "b.md", "bee three\n"))
    assert again.value.code == "unavailable"


def test_staged_changes_outside_the_folder_are_seen_whatever_diff_relative_says(tmp_path):
    import subprocess as sp
    from sheafmd import sourceservice
    top = tmp_path / "top"
    (top / "docs").mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}

    def g(*a):
        return sp.run(["git", "-C", str(top), *a], capture_output=True, text=True, check=True, env=env).stdout
    g("init", "-q")
    (top / "docs" / "a.md").write_text("a\n")
    (top / "x.txt").write_text("x\n")
    g("add", "."), g("commit", "-q", "-m", "s")
    g("config", "diff.relative", "true")
    (top / "x.txt").write_text("changed\n")
    g("add", "x.txt")
    with pytest.raises(SystemExit):
        sourceservice.Service(top / "docs", "b" * 20, {})


def test_an_unauthorized_caller_that_trickles_its_body_is_cut_within_a_couple_of_seconds(tmp_path):
    import socket
    import time
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "d.md").write_text("d\n")
    (tmp_path / "secrets").mkdir()
    svc = ReferenceService(folder, tmp_path / "secrets")
    try:
        c = socket.socket(socket.AF_UNIX)
        c.connect(svc.sock)
        c.sendall(b"POST /read HTTP/1.1\r\nHost: x\r\nContent-Length: 60000\r\n\r\n")
        started, gone = time.monotonic(), False
        c.settimeout(0.2)
        while time.monotonic() - started < 6:
            try:
                c.sendall(b"x")
            except OSError:
                gone = True
                break
            time.sleep(0.2)
        assert gone and time.monotonic() - started < 4
    finally:
        svc.stop()


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="counts descriptors through /proc")
def test_a_refused_start_and_close_release_the_root_descriptor(tmp_path):
    from sheafmd import sourceservice
    svc, folder, git = _git_service(tmp_path)
    (folder / "o.md").write_text("o\n")
    git("add", "o.md")
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(5):
        with pytest.raises(SystemExit):
            sourceservice.Service(folder, "b" * 20, {})
    assert len(os.listdir("/proc/self/fd")) == before
    svc.close()
    with pytest.raises(OSError):
        os.fstat(svc._root)
