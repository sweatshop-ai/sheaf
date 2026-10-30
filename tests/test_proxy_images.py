"""Local images in proxy mode (SPEC 9.9 "Local images", 6.2): a local image is embedded only when the
root 8.2 finds for its file is the document's own root. Any other is left out of the page and of
the share copy, element and all, and the render log says so, whether or not the file is there. In
loopback mode nothing changes."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from helpers import GIT_FAILS, git_fails
from PIL import Image

DOC = "work/plan.md"


def png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), (200, 30, 30)).save(path)
    return path


@pytest.fixture
def outside():
    """A PNG outside every root."""
    d = Path(tempfile.mkdtemp(dir="/tmp", prefix="si-"))
    yield png(d / "secret.png")
    shutil.rmtree(d, ignore_errors=True)


def page(front, plan, src):
    plan.write_text(f"# Plan\n\nSee ![the figure]({src}).\n", encoding="utf-8")
    r = front.get("/work/plan.md")
    assert r.status == 200
    share = front.post("/_/export", {"doc": DOC, "kind": "html"})
    assert share.status == 200
    return r.text, share.text, front.hub.entries[DOC].log


def test_an_image_outside_every_root_is_left_out_of_the_page_and_the_share_copy(front, plan, outside):
    html, share, log = page(front, plan, outside)
    for out in (html, share):
        assert "data:image/png" not in out and "the figure" not in out and "missing image" not in out
    assert any("left out" in line and str(outside) in line for line in log)


def test_one_that_is_not_there_is_left_out_the_same_so_nothing_says_whether_it_exists(front, plan, outside):
    html, _, log = page(front, plan, outside.parent / "nothing.png")
    assert "missing image" not in html and any("left out" in line for line in log)


def test_an_image_of_another_root_is_left_out(front, plan, other):
    (other / "notes.md").write_text("# Notes\n", encoding="utf-8")
    front.hub.roots.for_document(other / "notes.md")
    html, share, _ = page(front, plan, png(other / "fig.png"))
    assert "data:image/png" not in html and "data:image/png" not in share


def test_an_image_of_a_root_nested_inside_the_documents_is_left_out(front, plan, work):
    sub = work / "sub"
    png(sub / "fig.png")
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    html, _, _ = page(front, plan, "sub/fig.png")
    assert "data:image/png" not in html


@pytest.fixture
def nested(work):
    """A git repo inside the member's root, `work/sub`, which holds one folder, `real`."""
    sub = work / "sub"
    (sub / "real").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    return sub


@pytest.fixture
def locked(nested):
    """A folder of the nested repo that the hub's account cannot enter, `sub/locked`."""
    if os.geteuid() == 0:
        pytest.skip("root enters any folder")
    f = nested / "locked"
    f.mkdir(mode=0)
    yield f
    f.chmod(0o700)


def says_missing(src, *outs):
    """Each output says `[missing image: <src>]`."""
    return all(f"[missing image: {src}]" in out for out in outs)


def left_out(html, share, log):
    """The image is left out of the page and the share copy, element and all, and the log says so."""
    gone = all("missing image" not in out and "the figure" not in out for out in (html, share))
    return gone and any("left out" in line for line in log)


NOT_THERE = ["sub/guess/fig.png", "sub/real/guess/fig.png"]


@pytest.mark.parametrize("src", NOT_THERE)
def test_a_folder_that_is_not_there_in_a_nested_repo_is_left_out_like_one_that_is(front, plan, nested, src):
    assert left_out(*page(front, plan, "sub/real/fig.png"))
    assert left_out(*page(front, plan, src))


def test_a_folder_of_a_nested_repo_that_git_cannot_enter_is_left_out_like_one_it_can(front, plan, locked):
    assert left_out(*page(front, plan, "sub/locked/fig.png"))


@pytest.fixture
def git_dirs(nested):
    """The nested repo's git directories: a PNG in `sub/.git`, and a bare repo `sub/keep.git` holding one."""
    png(nested / ".git" / "fig.png")
    subprocess.run(["git", "init", "-q", "--bare", str(nested / "keep.git")], check=True)
    png(nested / "keep.git" / "fig.png")
    return nested


# Images in the nested repo's git directories, there or not, and under a bare repo that is not there
# (`gone.git`), which is a folder of its work tree.
GIT_DIR_PATHS = ["sub/.git/fig.png", "sub/.git/nope/fig.png", "sub/keep.git/fig.png", "sub/keep.git/nope.png",
                 "sub/gone.git/fig.png"]


@pytest.mark.parametrize("src", GIT_DIR_PATHS)
def test_an_image_in_a_git_directory_of_a_nested_repo_is_left_out_like_its_work_tree(front, plan, git_dirs, src):
    assert left_out(*page(front, plan, "sub/real/fig.png"))
    assert left_out(*page(front, plan, src))


def test_beside_a_nested_repos_git_directories_the_members_images_and_its_work_tree_answer_as_before(
        front, plan, work, git_dirs):
    png(work / "img" / "fig.png")
    png(git_dirs / "real" / "fig.png")
    html, share, _ = page(front, plan, "img/fig.png")
    assert "data:image/png" in html and "data:image/png" in share
    for src in ("img/nothing.png", "nope/nothing.png"):
        assert says_missing(src, *page(front, plan, src)[:2])
    for src in ("sub/real/fig.png", "sub/real/nothing.png", "sub/nope/fig.png"):
        assert left_out(*page(front, plan, src))


def test_in_a_git_root_its_own_git_directory_is_left_out_as_before(front, git_plan, work):
    png(work / ".git" / "fig.png")
    for src in (".git/fig.png", ".git/nope/fig.png"):
        assert left_out(*page(front, git_plan, src))


# Where git names neither a work tree nor a git directory (8.2) the path tells a git directory: images in
# the nested repo's, there or not.
IN_A_GIT_DIR = [p for p in GIT_DIR_PATHS if not p.startswith("sub/gone.git")]


@pytest.mark.parametrize("how", GIT_FAILS)
@pytest.mark.parametrize("src", IN_A_GIT_DIR)
def test_where_git_fails_an_image_in_a_nested_repos_git_directory_is_left_out(front, plan, git_dirs, monkeypatch,
                                                                           tmp_path, how, src):
    git_fails(how, monkeypatch, tmp_path)
    assert left_out(*page(front, plan, src))


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_the_members_images_and_a_nested_repos_work_tree_answer_as_before(front, plan, work,
                                                                                       git_dirs, monkeypatch,
                                                                                       tmp_path, how):
    png(git_dirs / "real" / "fig.png")
    png(work / "img" / "fig.png")
    git_fails(how, monkeypatch, tmp_path)
    for src in ("sub/real/fig.png", "img/fig.png"):
        html, share, _ = page(front, plan, src)
        assert "data:image/png" in html and "data:image/png" in share, src
    for src in ("sub/real/nothing.png", "img/nothing.png"):
        assert says_missing(src, *page(front, plan, src)[:2])


@pytest.fixture
def own_repo(plan, work):
    """The member's root `work`, registered as no git repo, made one with a PNG in its `.git` and one in
    `img`: what git refuses on a server where the member's folder is not the hub's account's."""
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    png(work / ".git" / "fig.png")
    png(work / "img" / "fig.png")
    return plan


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_the_members_own_repo_its_images_answer_as_before(front, own_repo, monkeypatch, tmp_path,
                                                                       how):
    git_fails(how, monkeypatch, tmp_path)
    html, share, _ = page(front, own_repo, "img/fig.png")
    assert "data:image/png" in html and "data:image/png" in share
    assert says_missing("img/nothing.png", *page(front, own_repo, "img/nothing.png")[:2])


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_the_members_own_repo_its_git_directory_is_left_out(front, own_repo, monkeypatch, tmp_path,
                                                                         how):
    git_fails(how, monkeypatch, tmp_path)
    for src in (".git/fig.png", ".git/nope/fig.png"):
        assert left_out(*page(front, own_repo, src))


@pytest.fixture(params=["bare-and-gitfile", "core-bare"])
def bare_layout(request, work, tmp_path):
    """The member's root holds a repo's git directory but is no work tree of it: a bare clone `.bare` that a
    `.git` file names (the bare repo plus worktrees layout), or a `.git` folder with `core.bare = true`."""
    if request.param == "bare-and-gitfile":
        src = tmp_path / "srcrepo"
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q",
                        "--allow-empty", "-m", "i"], check=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(work / ".bare")], check=True)
        (work / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")
    else:
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        subprocess.run(["git", "-C", str(work), "config", "core.bare", "true"], check=True)


def test_a_root_beside_its_repos_git_directory_keeps_its_images_as_before(front, bare_layout, work):
    plan = work / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    front.hub.roots.for_document(plan)
    png(work / "img" / "fig.png")
    html, share, _ = page(front, plan, "img/fig.png")
    assert "data:image/png" in html and "data:image/png" in share
    assert says_missing("img/nothing.png", *page(front, plan, "img/nothing.png")[:2])


def test_a_bare_repo_in_the_members_own_root_is_left_out_like_their_git_roots_git_directory(front, plan, work):
    subprocess.run(["git", "init", "-q", "--bare", str(work / "keep.git")], check=True)
    png(work / "keep.git" / "fig.png")
    assert left_out(*page(front, plan, "keep.git/fig.png"))


def test_an_image_of_the_documents_own_root_is_embedded(front, plan, work):
    png(work / "img" / "fig.png")
    html, share, _ = page(front, plan, "img/fig.png")
    assert "data:image/png" in html and "data:image/png" in share


@pytest.mark.parametrize("src", ["img/nothing.png", "nope/nothing.png"])
def test_a_missing_image_of_the_documents_own_root_says_so(front, plan, work, nested, src):
    (work / "img").mkdir()
    html, share, _ = page(front, plan, src)
    assert f"[missing image: {src}]" in html and f"[missing image: {src}]" in share


@pytest.fixture
def git_plan(front, work):
    """The member's root is a git repo: `work` itself, registered as one. Address `work/plan.md`."""
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    f = work / "plan.md"
    f.write_text("# Plan\n", encoding="utf-8")
    front.hub.roots.for_document(f)
    return f


def test_in_a_git_root_an_image_is_embedded_and_a_missing_one_says_so(front, git_plan, work):
    png(work / "img" / "fig.png")
    html, share, _ = page(front, git_plan, "img/fig.png")
    assert "data:image/png" in html and "data:image/png" in share
    html, share, _ = page(front, git_plan, "img/nothing.png")
    assert "[missing image: img/nothing.png]" in html and "[missing image: img/nothing.png]" in share


def test_in_a_git_root_an_image_under_a_folder_that_is_not_there_says_so_too(front, git_plan):
    html, share, _ = page(front, git_plan, "nope/fig.png")
    assert "[missing image: nope/fig.png]" in html and "[missing image: nope/fig.png]" in share


@pytest.fixture
def closed(work):
    """`work/closed`, a folder of the member's root that the hub's account cannot enter, holding `fig.png`."""
    if os.geteuid() == 0:
        pytest.skip("root enters any folder")
    f = work / "closed"
    png(f / "fig.png")
    f.chmod(0)
    yield f
    f.chmod(0o700)


@pytest.mark.parametrize("own", ["plan", "git_plan"])
def test_an_image_the_hub_cannot_reach_in_the_documents_own_root_says_missing(front, closed, own, request):
    html, share, _ = page(front, request.getfixturevalue(own), "closed/fig.png")
    assert "[missing image: closed/fig.png]" in html and "[missing image: closed/fig.png]" in share


def test_an_image_file_the_hub_cannot_read_says_missing(front, plan, work):
    if os.geteuid() == 0:
        pytest.skip("root reads any file")
    fig = png(work / "img" / "fig.png")
    fig.chmod(0)
    try:
        html, share, _ = page(front, plan, "img/fig.png")
    finally:
        fig.chmod(0o600)
    assert "[missing image: img/fig.png]" in html and "[missing image: img/fig.png]" in share


def test_in_loopback_mode_an_image_the_hub_cannot_reach_says_missing_too(browser, plan, closed):
    plan.write_text("# Plan\n\nSee ![the figure](closed/fig.png).\n", encoding="utf-8")
    r = browser.get("/work/plan.md")
    assert r.status == 200 and "[missing image: closed/fig.png]" in r.text


@pytest.fixture
def loops(nested):
    """Symlink loops: `work/loop.png` and `work/d` point at themselves, and so does `sub/loop.png` in
    the nested repo."""
    for link in (nested.parent / "loop.png", nested.parent / "d", nested / "loop.png"):
        link.symlink_to(link.name)


NOT_A_FILE = ["loop.png", "d/fig.png", "a%00b.png"]


@pytest.mark.parametrize("src", NOT_A_FILE)
def test_a_symlink_loop_or_a_nul_in_the_documents_own_root_is_a_missing_image(front, plan, loops, src):
    html, share, _ = page(front, plan, src)
    assert says_missing(src, html, share)


@pytest.mark.parametrize("src", ["sub/loop.png", "sub/a%00b.png"])
def test_a_symlink_loop_or_a_nul_at_a_path_of_another_root_is_left_out_like_a_file(front, plan, loops, src):
    assert left_out(*page(front, plan, "sub/real/fig.png"))
    assert left_out(*page(front, plan, src))


@pytest.mark.parametrize("src", ["a\0b.png", "sub/a\0b.png"])
def test_a_nul_written_in_the_source_names_no_file_and_says_missing_wherever_it_points(front, plan, nested, src):
    html, share, _ = page(front, plan, src)
    assert says_missing(src, html, share)


def test_a_file_named_with_a_percent_00_is_still_embedded_as_written(front, plan, work):
    png(work / "a%00b.png")
    html, share, _ = page(front, plan, "a%00b.png")
    assert "data:image/png" in html and "data:image/png" in share


@pytest.mark.parametrize("src", NOT_A_FILE)
def test_in_loopback_mode_a_symlink_loop_or_a_nul_is_a_missing_image(browser, plan, loops, src):
    plan.write_text(f"# Plan\n\nSee ![the figure]({src}).\n", encoding="utf-8")
    r, share = browser.get("/work/plan.md"), browser.post("/_/export", {"doc": DOC, "kind": "html"})
    assert r.status == share.status == 200 and says_missing(src, r.text, share.text)


def test_in_loopback_mode_an_image_outside_every_root_is_embedded_as_before(browser, plan, outside):
    plan.write_text(f"# Plan\n\nSee ![the figure]({outside}).\n", encoding="utf-8")
    assert "data:image/png" in browser.get("/work/plan.md").text
    assert "data:image/png" in browser.post("/_/export", {"doc": DOC, "kind": "html"}).text


# ── sheaf share, which renders without the hub (9.9 "Local images") ──────────

@pytest.fixture
def proxied():
    """config.toml with a `[proxy]` table: the share copy then holds the image rule too."""
    from helpers import BEA, proxy_table, write

    from sheafmd import paths
    write(paths.config_file(), proxy_table("/run/sheaf-proxy/hub.sock", {BEA: ("Bea", ["/srv/pages"])}))


def share(sheaf, work, src):
    doc = work / "doc.md"
    doc.write_text(f"# Doc\n\nSee ![the figure]({src}).\n", encoding="utf-8")
    r = sheaf(doc, "--share")
    assert r.code == 0, r.err
    return (work / "doc-share.html").read_text(encoding="utf-8"), r.err


def test_share_leaves_out_an_image_outside_every_root(proxied, sheaf, work, outside):
    copy, err = share(sheaf, work, outside)
    assert "data:image/png" not in copy and "the figure" not in copy and "missing image" not in copy
    assert "left out" in err and str(outside) in err


def test_share_leaves_out_one_that_is_not_there_the_same_so_nothing_says_whether_it_exists(proxied, sheaf, work,
                                                                                          outside):
    copy, err = share(sheaf, work, outside.parent / "nothing.png")
    assert "missing image" not in copy and "left out" in err


def test_share_leaves_out_an_image_of_another_root(proxied, sheaf, work, other):
    from sheafmd.hub.roots import Roots
    (other / "notes.md").write_text("# Notes\n", encoding="utf-8")
    Roots().for_document(other / "notes.md")
    copy, _ = share(sheaf, work, png(other / "fig.png"))
    assert "data:image/png" not in copy


def test_share_leaves_out_an_image_of_a_root_nested_inside_the_documents(proxied, sheaf, work):
    png(work / "sub" / "fig.png")
    subprocess.run(["git", "init", "-q", str(work / "sub")], check=True)
    copy, _ = share(sheaf, work, "sub/fig.png")
    assert "data:image/png" not in copy


def shared_left_out(copy, err):
    return "missing image" not in copy and "the figure" not in copy and "left out" in err


@pytest.mark.parametrize("src", NOT_THERE)
def test_share_leaves_out_a_folder_that_is_not_there_in_a_nested_repo_like_one_that_is(proxied, sheaf, work,
                                                                                      nested, src):
    assert shared_left_out(*share(sheaf, work, "sub/real/fig.png"))
    assert shared_left_out(*share(sheaf, work, src))


def test_share_leaves_out_a_folder_of_a_nested_repo_that_git_cannot_enter(proxied, sheaf, work, locked):
    assert shared_left_out(*share(sheaf, work, "sub/locked/fig.png"))


@pytest.mark.parametrize("src", GIT_DIR_PATHS)
def test_share_leaves_out_an_image_in_a_git_directory_of_a_nested_repo_like_its_work_tree(proxied, sheaf, work,
                                                                                         git_dirs, src):
    assert shared_left_out(*share(sheaf, work, "sub/real/fig.png"))
    assert shared_left_out(*share(sheaf, work, src))


@pytest.mark.parametrize("how", GIT_FAILS)
@pytest.mark.parametrize("src", IN_A_GIT_DIR)
def test_share_leaves_out_an_image_in_a_nested_repos_git_directory_where_git_fails(proxied, sheaf, work, git_dirs,
                                                                                  monkeypatch, tmp_path, how, src):
    git_fails(how, monkeypatch, tmp_path)
    assert shared_left_out(*share(sheaf, work, src))


@pytest.mark.parametrize("src", NOT_A_FILE)
def test_share_says_missing_for_a_symlink_loop_or_a_nul(proxied, sheaf, work, loops, src):
    assert says_missing(src, share(sheaf, work, src)[0])


def test_share_embeds_an_image_of_the_documents_own_root_and_registers_nothing(proxied, sheaf, work):
    from sheafmd import paths
    png(work / "img" / "fig.png")
    copy, _ = share(sheaf, work, "img/fig.png")
    assert "data:image/png" in copy
    assert not (paths.state_dir() / "roots.json").exists()


def test_share_says_missing_for_an_image_the_hub_cannot_reach(sheaf, work, closed):
    copy, _ = share(sheaf, work, "closed/fig.png")
    assert "[missing image: closed/fig.png]" in copy


def test_share_in_loopback_mode_embeds_an_image_outside_every_root_as_before(sheaf, work, outside):
    copy, _ = share(sheaf, work, outside)
    assert "data:image/png" in copy


def test_share_holds_the_rule_under_a_proxy_table_the_hub_would_refuse(sheaf, work, outside):
    from helpers import write

    from sheafmd import paths
    write(paths.config_file(), '[proxy]\norigin = "http://chat.example.com"\n')
    copy, _ = share(sheaf, work, outside)
    assert "data:image/png" not in copy


def test_share_leaves_a_registry_it_cannot_read_where_it_is(proxied, sheaf, work, outside):
    from sheafmd import paths
    reg = paths.state_dir() / "roots.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("{not json", encoding="utf-8")
    copy, _ = share(sheaf, work, outside)
    assert "data:image/png" not in copy
    assert reg.read_text(encoding="utf-8") == "{not json" and not list(reg.parent.glob("*.corrupt"))


PROJECTS = '[projects."acme/blog"]\nmembers = ["bea"]\nstatus = "live"\n' \
           '[projects."thinkingtoo/tiroir"]\nmembers = ["bea"]\nstatus = "live"\n'


@pytest.fixture
def granted(front, work):
    """`work` with a `projects.toml` (8.12) that names Bea, now `bea`, in both its projects: its projects' images
    are judged by project, and none of what Bea opens is shut by the grant itself."""
    import pwd
    from helpers import BEA, FRONT
    from sheafmd.hub import proxy
    front.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                   "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                                   "members": {BEA: {"name": "Bea", "short": "bea", "roots": [str(work)]}}}, "the test")
    (work / "projects.toml").write_text(PROJECTS, encoding="utf-8")
    return work


def project_page(front, work, rel, src):
    """The page and the share copy of the document `rel` in `work`, which names the image `src`, and its log."""
    doc = work / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f"# Plan\n\nSee ![the figure]({src}).\n", encoding="utf-8")
    front.hub.roots.for_document(doc)
    r = front.get(f"/work/{rel}")
    assert r.status == 200
    share = front.post("/_/export", {"doc": f"work/{rel}", "kind": "html"})
    assert share.status == 200
    return r.text, share.text, front.hub.entries[f"work/{rel}"].log


def test_an_image_of_another_project_is_left_out_like_one_of_another_root(front, plan, granted, work):
    """A member opens a page of a project they are in; an image of a project they may not be in is no part of it
    (#53): judged by its `<client>/<project>` as a document is (8.12), the same for every reader of the page."""
    png(work / "thinkingtoo" / "tiroir" / "secret.png")
    html, share, log = project_page(front, work, "acme/blog/pic.md", "../../thinkingtoo/tiroir/secret.png")
    for out in (html, share):
        assert "data:image/png" not in out and "the figure" not in out and "missing image" not in out
    assert any("left out" in line and "secret.png" in line for line in log)


def test_an_image_of_the_documents_own_project_or_above_any_project_is_embedded(front, plan, granted, work):
    png(work / "acme" / "blog" / "fig.png")
    png(work / "logo.png")
    for src in ("fig.png", "../../logo.png"):
        html, share, _ = project_page(front, work, "acme/blog/pic.md", src)
        assert "data:image/png" in html and "data:image/png" in share, src


def test_a_document_above_every_project_leaves_out_a_projects_image(front, plan, granted, work):
    """A document above project depth opens to every member of the root (8.12), so it embeds no project's image."""
    png(work / "acme" / "blog" / "fig.png")
    html, share, _ = page(front, plan, "acme/blog/fig.png")
    assert "data:image/png" not in html and "data:image/png" not in share


@pytest.mark.parametrize("rel", ["acme/blog/pic.md", "acme/blog/private/hans/pic.md"])
def test_an_image_in_a_private_folder_is_embedded_only_in_a_sheaf_of_that_folder(front, plan, granted, work, rel):
    """`private/<short>/` holds what is its owner's alone (9.11): its image is no part of a page of the project, nor
    of another owner's sheaf."""
    png(work / "acme" / "blog" / "private" / "thierry" / "seal.png")
    up = "../../" if "private" in rel else ""
    html, _, _ = project_page(front, work, rel, f"{up}private/thierry/seal.png")
    assert "data:image/png" not in html
    html, _, _ = project_page(front, work, "acme/blog/private/thierry/own.md", "seal.png")
    assert "data:image/png" in html


def test_a_root_without_projects_toml_embeds_another_projects_image_as_before(front, plan, work):
    """A root without the file grants as before (8.12): a folder at project depth is no project there."""
    png(work / "thinkingtoo" / "tiroir" / "fig.png")
    html, share, _ = project_page(front, work, "acme/blog/pic.md", "../../thinkingtoo/tiroir/fig.png")
    assert "data:image/png" in html and "data:image/png" in share


def test_a_page_built_before_projects_toml_came_is_built_again_at_its_next_load(front, plan, granted, work):
    (work / "projects.toml").unlink()
    png(work / "thinkingtoo" / "tiroir" / "secret.png")
    html, _, _ = project_page(front, work, "acme/blog/pic.md", "../../thinkingtoo/tiroir/secret.png")
    assert "data:image/png" in html
    (work / "projects.toml").write_text(PROJECTS, encoding="utf-8")
    assert "data:image/png" not in front.get("/work/acme/blog/pic.md").text
    (work / "projects.toml").unlink()
    assert "data:image/png" in front.get("/work/acme/blog/pic.md").text


def test_a_build_that_failed_after_projects_toml_came_is_tried_again_at_the_next_load(front, plan, granted, work,
                                                                                      monkeypatch):
    """The rule a page was built by is kept only once the build worked: one that raised leaves the page of the old
    rule marked as such, so the next request builds it again."""
    from sheafmd.hub import core
    (work / "projects.toml").unlink()
    png(work / "thinkingtoo" / "tiroir" / "secret.png")
    html, _, _ = project_page(front, work, "acme/blog/pic.md", "../../thinkingtoo/tiroir/secret.png")
    assert "data:image/png" in html
    (work / "projects.toml").write_text(PROJECTS, encoding="utf-8")
    real, calls = core.render_file, []

    def once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("the disk hiccuped")
        return real(*a, **k)
    monkeypatch.setattr(core, "render_file", once)
    front.get("/work/acme/blog/pic.md")
    assert "data:image/png" not in front.get("/work/acme/blog/pic.md").text


@pytest.fixture
def outsider(front, granted, work):
    """Cal, `cal`, holds `work` too and is in none of its projects (8.12): an owner of a sheaf there is no member."""
    import pwd
    from helpers import BEA, CAL, FRONT
    from sheafmd.hub import proxy
    front.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                   "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                                   "members": {BEA: {"name": "Bea", "short": "bea", "roots": [str(work)]},
                                               CAL: {"name": "Cal", "short": "cal", "roots": [str(work)]}}},
                                  "the test")
    png(work / "acme" / "blog" / "fig.png")
    return work


def owned_page(front, work, rel, owner, src, member=None, visibility="project"):
    from helpers import BEA
    doc = work / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f"---\nowner: {owner}\nvisibility: {visibility}\n---\n# Plan\n\nSee ![the figure]({src}).\n",
                   encoding="utf-8")
    front.hub.roots.for_document(doc)
    r = front.get(f"/work/{rel}", member=member or BEA)
    assert r.status == 200, r.text
    share = front.post("/_/export", {"doc": f"work/{rel}", "kind": "html"}, member=member or BEA)
    assert share.status == 200
    return r.text, share.text


def test_a_sheaf_with_an_owner_outside_its_project_embeds_none_of_the_projects_images(front, plan, outsider):
    """`projects.toml` is the one source of who is in a project (8.12, #81): a non-member never receives a project's
    content, even as the owner of a sheaf in it. Its page is one render for every reader, so no reader gets them."""
    from helpers import CAL
    for member in (None, CAL):
        html, share = owned_page(front, outsider, "acme/blog/pic.md", "cal", "fig.png", member=member)
        assert "data:image/png" not in html and "data:image/png" not in share


def test_a_sheaf_whose_owners_are_all_members_keeps_the_projects_images(front, plan, outsider):
    html, share = owned_page(front, outsider, "acme/blog/pic.md", "bea", "fig.png")
    assert "data:image/png" in html and "data:image/png" in share


def test_an_outside_owner_keeps_the_images_of_their_own_private_folder_and_above_every_project(front, plan,
                                                                                               outsider):
    """The owner's own `private/<short>/` is theirs in the Library too (`*/*/private/<short>/**`), and an image
    above project depth is every root member's."""
    from helpers import CAL
    png(outsider / "acme" / "blog" / "private" / "cal" / "seal.png")
    png(outsider / "logo.png")
    for src in ("seal.png", "../../../../logo.png"):
        html, _ = owned_page(front, outsider, "acme/blog/private/cal/own.md", "cal", src, member=CAL,
                             visibility="owner")
        assert "data:image/png" in html, src
    html, _ = owned_page(front, outsider, "acme/blog/private/cal/own.md", "cal", "../../fig.png", member=CAL,
                         visibility="owner")
    assert "data:image/png" not in html


def test_an_outside_owner_added_to_the_project_gets_its_images_at_the_next_load(front, plan, outsider):
    html, _ = owned_page(front, outsider, "acme/blog/pic.md", "cal", "fig.png")
    assert "data:image/png" not in html
    toml = outsider / "projects.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('members = ["bea"]', 'members = ["bea", "cal"]', 1),
                    encoding="utf-8")
    assert "data:image/png" in front.get("/work/acme/blog/pic.md").text
    toml.write_text(PROJECTS, encoding="utf-8")
    assert "data:image/png" not in front.get("/work/acme/blog/pic.md").text


def test_an_entry_whose_root_was_forgotten_is_built_again_once_not_at_every_catch_up(front, plan, granted, work,
                                                                                     monkeypatch):
    """Its image scope goes from the root's to none: one build takes that in, and the next catch-ups find nothing
    moved (a gate P3 on 4272c2f)."""
    from sheafmd.hub import live
    project_page(front, work, "acme/blog/pic.md", "fig.png")
    e = front.hub.entries["work/acme/blog/pic.md"]
    builds, real = [], live.LiveDocument.rebuild
    monkeypatch.setattr(live.LiveDocument, "rebuild", lambda self: builds.append(1) or real(self))
    front.hub.roots.forget("work")
    for _ in range(3):
        front.hub.catch_up(e)
    assert len(builds) <= 1 and e.images_scope is None


def test_a_link_sheaf_judges_its_owners_by_the_project_of_its_file_too(front, plan, outsider):
    """A link in a project Cal is in, to a sheaf of one he is not, that he owns: he opens it (8.12), and its images
    are judged by where its file is, so its owners are judged there as well, as `granted` judges both (#81)."""
    from helpers import CAL
    (outsider / "projects.toml").write_text(
        '[projects."acme/blog"]\nmembers = ["bea", "cal"]\nstatus = "live"\n'
        '[projects."acme/secret"]\nmembers = ["bea"]\nstatus = "live"\n', encoding="utf-8")
    png(outsider / "acme" / "secret" / "img.png")
    doc = outsider / "acme" / "secret" / "doc.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("---\nowner: cal\nvisibility: project\n---\n# Doc\n\nSee ![x](img.png).\n", encoding="utf-8")
    (outsider / "acme" / "blog" / "link.md").symlink_to(doc)
    front.hub.roots.for_document(outsider / "acme" / "blog" / "link.md")
    r = front.get("/work/acme/blog/link.md", member=CAL)
    assert r.status == 200, r.text
    assert "data:image/png" not in r.text


def test_an_owner_lookup_that_fails_leaves_the_projects_images_out(front, plan, outsider, monkeypatch):
    """Judged as a reader the project may not name, never as one it does: the page holds none of its images."""
    monkeypatch.setattr(front.hub, "owners", lambda address, members: (_ for _ in ()).throw(RuntimeError("boom")))
    html, share = owned_page(front, outsider, "acme/blog/pic.md", "bea", "fig.png")
    assert "data:image/png" not in html and "data:image/png" not in share


def test_a_page_built_with_its_images_drops_them_when_its_owners_can_no_longer_be_judged(front, plan, outsider,
                                                                                        monkeypatch):
    """`catch_up` serves no page built under an older answer: one whose owners the hub then cannot judge is built
    again without the project's images before it is served."""
    html, _ = owned_page(front, outsider, "acme/blog/pic.md", "bea", "fig.png")
    assert "data:image/png" in html
    monkeypatch.setattr(front.hub, "owners", lambda address, members: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "data:image/png" not in front.get("/work/acme/blog/pic.md").text


@pytest.mark.parametrize("bad", ["not toml at all [", '[projects."acme/blog"]\nmembers = "bea"\n'],
                         ids=["not-toml", "invalid"])
def test_an_invalid_projects_toml_leaves_out_the_projects_images_of_a_sheaf_with_an_owner(front, plan, outsider,
                                                                                          bad):
    """A file the hub cannot read names nobody, so every owner counts as one it does not name (#81, #91): a sheaf
    with an owner embeds none of the project's images. Above-project images and the sheaf's own `private/<short>/`
    ones stay."""
    png(outsider / "acme" / "blog" / "private" / "bea" / "seal.png")
    png(outsider / "logo.png")
    html, _ = owned_page(front, outsider, "acme/blog/pic.md", "bea", "fig.png")
    assert "data:image/png" in html
    (outsider / "projects.toml").write_text(bad, encoding="utf-8")
    from sheafmd.hub import projects
    assert isinstance(front.hub.projects_of(front.hub.roots.get("work")), projects.Invalid)
    html, share = owned_page(front, outsider, "acme/blog/pic.md", "bea", "fig.png")
    assert "data:image/png" not in html and "data:image/png" not in share
    for src in ("seal.png", "../../../../logo.png"):
        html, _ = owned_page(front, outsider, "acme/blog/private/bea/own.md", "bea", src, visibility="owner")
        assert "data:image/png" in html, src
    html, _ = owned_page(front, outsider, "acme/blog/private/bea/own.md", "bea", "../../fig.png", visibility="owner")
    assert "data:image/png" not in html


def test_an_open_tab_has_its_page_built_again_when_projects_toml_moves_its_images(front, plan, outsider):
    """The tick tells an open tab of a `projects.toml` change (`_tell_grants`) and builds its page again once the
    image rule moved (#53, #81, #91), before any request comes: the page the hub holds has the images the file now
    gives."""
    from helpers import BEA
    owned_page(front, outsider, "acme/blog/pic.md", "cal", "fig.png")
    e = front.hub.entries["work/acme/blog/pic.md"]
    assert "data:image/png" not in e.html
    stream = front.get("/_/live?doc=work/acme/blog/pic.md", member=BEA).stream
    stream.drain()
    assert e.bus.count()
    toml = outsider / "projects.toml"
    toml.write_text(PROJECTS.replace('members = ["bea"]', 'members = ["bea", "cal"]', 1), encoding="utf-8")
    front.hub.tick()
    front.hub.tick()                    # told once the new file has held for two passes
    assert "data:image/png" in e.html
    assert "changed" in [name for name, _ in stream.drain()]
    toml.write_text(PROJECTS, encoding="utf-8")
    front.hub.tick()
    front.hub.tick()
    assert "data:image/png" not in e.html
