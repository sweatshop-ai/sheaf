"""The index page: `GET /` for every root and `GET /<root>/` for one (SPEC 8.5, 8.6). In memory,
no browser: what the server writes is what the page shows; the script only refreshes it."""
import html as htmllib
import os
import re
import time

import pytest

from helpers import CREDIT, NOW, active_content, thread, with_threads
from sheafmd.hub import index as index_mod
from sheafmd.hub.handler import SIGN_IN

ROW = re.compile(r'<li class="doc" data-doc="([^"]*)" data-dot="(\w+)">(.*?)</li>', re.S)


def rows(page: str) -> dict:
    """{doc: (dot, row html)} of the rows on the page, in page order."""
    return {htmllib.unescape(m.group(1)): (m.group(2), m.group(3)) for m in ROW.finditer(page)}


def text_of(fragment: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def index(browser, path="/", **kw):
    r = browser.get(path, **kw)
    assert r.status == 200, (r.status, r.text[:300])
    return r


# ── the page ─────────────────────────────────────────────────────────────────

def test_the_index_is_an_html_page_with_a_header_and_a_footer(world):
    r = index(world)
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "<title>sheaf</title>" in r.text
    assert f"{world.hub.version} · port {world.hub.port}" in text_of(r.text)
    assert "<h1>sheaf</h1>" in r.text


def test_the_footer_has_the_credit_and_no_link(world):
    footer = re.search(r"<footer>(.*?)</footer>", index(world).text, re.S).group(1)
    assert footer == CREDIT


def test_the_page_script_carries_the_nonce_of_its_own_csp(world):
    r = index(world)
    nonce = r.headers["Content-Security-Policy"].split("script-src 'nonce-")[1].split("'")[0]
    assert r.text.count("<script") == 1 and f'<script nonce="{nonce}">' in r.text
    assert "new EventSource('/_/live')" in r.text and ".dot.green" in r.text
    assert index(world).headers["Content-Security-Policy"] != r.headers["Content-Security-Policy"]


def test_the_page_never_holds_the_key(world):
    assert world.hub.auth.key not in index(world).text
    assert "rd-edit-meta" not in index(world).text


def test_the_index_is_not_cached(world):
    assert index(world).headers["Cache-Control"] == "no-store"


def test_the_index_needs_the_cookie(world):
    r = world.get("/", cookie=False)
    assert r.status == 401 and SIGN_IN.split("<code>")[0] in r.text
    assert world.get("/work/", cookie=False).status == 401
    assert world.get("/", cookie=False, key=True).status == 403


# ── the rows (8.6) ───────────────────────────────────────────────────────────

def test_a_row_is_its_dot_its_path_as_a_link_its_count_and_its_last_change(world, put):
    put("sub/plan.md", with_threads(thread("c1", "Ada"), thread("c2", "Ada")), age=240)
    got = rows(index(world).text)["work/sub/plan.md"]
    assert got[0] == "blue"
    assert '<a href="/work/sub/plan.md">sub/plan.md</a>' in got[1]
    assert re.search(r'<span class="dot blue"[^>]*>2</span>', got[1])
    assert text_of(got[1]).endswith("2 open 4 min ago")


def test_a_row_without_comments_shows_a_green_check_and_no_count(world, put):
    put("quiet.md", age=7200)
    got = rows(index(world).text)["work/quiet.md"]
    assert got[0] == "green" and re.search(r'<span class="dot green"[^>]*>✓</span>', got[1])
    assert text_of(got[1]) == "✓ quiet.md 2 h ago"


def test_the_four_dots_are_red_orange_blue_and_green(world, put):
    put("r.md", with_threads(thread("c1", "Bob")), age=1)
    put("o.md", with_threads(thread("c1", "Ada")), age=2)
    world.hub.entry("work/o.md").live.await_reply("c1")
    put("b.md", with_threads(thread("c1", "Ada")), age=3)
    put("g.md", age=4)
    got = {d: v[0] for d, v in rows(index(world).text).items()}
    assert got == {"work/r.md": "red", "work/o.md": "orange", "work/b.md": "blue",
                   "work/g.md": "green", "work/start.md": "green"}


def test_a_red_row_says_how_many_threads_are_unread(world, put):
    put("r.md", with_threads(thread("c1", "Bob"), thread("c2", "Cy")))
    got = rows(index(world).text)["work/r.md"][1]
    assert "2 open" in text_of(got) and "2 unread" in text_of(got)


def test_every_dot_says_in_words_what_it_means(world, put):
    put("r.md", with_threads(thread("c1", "Bob")))
    put("b.md", with_threads(thread("c1", "Ada")))
    got = index(world).text
    assert 'aria-label="1 thread with a message you have not read"' in got
    assert 'aria-label="1 open comment"' in got
    assert 'aria-label="no open comments"' in got


def test_rows_are_in_the_order_the_data_gives(world, put):
    put("start.md", age=5000)
    put("g.md", age=10)
    put("b.md", with_threads(thread("c1", "Ada")), age=50)
    put("r.md", with_threads(thread("c1", "Bob")), age=900)
    assert list(rows(index(world).text)) == ["work/r.md", "work/b.md", "work/g.md", "work/start.md"]


def test_a_root_header_has_its_name_its_folder_and_its_worst_dot(world, work, put):
    put("b.md", with_threads(thread("c1", "Ada")))
    head = re.search(r"<h2>(.*?)</h2>", index(world).text, re.S).group(1)
    assert '<a href="/work/">work</a>' in head and f'<span class="path">{work.resolve()}</span>' in head
    assert 'class="dot blue"' in head and "dot red" not in head
    put("r.md", with_threads(thread("c1", "Bob")))
    assert 'class="dot red"' in re.search(r"<h2>(.*?)</h2>", index(world).text, re.S).group(1)


def test_roots_follow_the_data_order(world, put, tmp_path):
    put("start.md", age=500)
    for name, age in (("older", 9000), ("newer", 1)):
        d = tmp_path / name
        d.mkdir()
        f = d / "a.md"
        f.write_text("# A\n")
        os.utime(f, (NOW - age, NOW - age))
        world.hub.roots.for_document(f)
    assert re.findall(r'<section class="root" data-root="([^"]+)"', index(world).text) == [
        "newer", "work", "older"]


def test_the_link_of_a_row_is_percent_encoded(world, put):
    put("a b/ünï #1.md")
    assert 'href="/work/a%20b/%C3%BCn%C3%AF%20%231.md"' in index(world).text


def test_a_link_of_the_page_opens_the_document(world, put):
    put("a b/plan.md")
    assert index(world, "/work/a%20b/plan.md").status == 200


# ── what is not a document ───────────────────────────────────────────────────

def test_a_root_whose_folder_is_gone_says_how_to_forget_it(world, work):
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    got = index(world).text
    assert "folder missing: <code>sheaf roots forget work</code>" in got
    assert rows(got) == {}


def test_a_root_behind_a_folder_the_hub_may_not_enter_says_so_and_not_how_to_forget_it(
        world, tmp_path, closed):
    notes = tmp_path / "srv" / "notes"
    notes.mkdir(parents=True)
    (notes / "a.md").write_text("# a\n", encoding="utf-8")
    world.hub.roots.for_document(notes / "a.md")
    closed(tmp_path / "srv")
    got = index(world).text
    section = re.search(r'<section class="root" data-root="notes">(.*?)</section>', got, re.S).group(1)
    assert str(notes) in text_of(section)
    assert "folder cannot be entered: Permission denied" in text_of(section)
    assert "folder missing" not in got and "sheaf roots forget" not in got


def test_a_root_over_the_cap_says_and_n_more(world, put, monkeypatch):
    from sheafmd.hub import roots
    monkeypatch.setattr(roots, "LIST_CAP", 2)
    for i in range(5):
        put(f"d{i}.md")
    got = index(world).text
    assert len(rows(got)) == 2 and "and 4 more" in text_of(got)


@pytest.mark.parametrize("docs, says", [(7, "and 3+ more"), (4, "and 2 more")])
def test_a_count_that_stopped_at_its_limit_says_so(world, put, monkeypatch, docs, says):
    """The listing stops counting at roots.COUNT_LIMIT (100,000): the page then says "100000+", that
    many or more, not a number it did not count to. Under the limit the number is exact."""
    from sheafmd.hub import roots
    monkeypatch.setattr(roots, "LIST_CAP", 2)
    monkeypatch.setattr(roots, "COUNT_LIMIT", 3)
    (world.hub.roots.get("work").path / "start.md").unlink()
    for i in range(docs):
        put(f"d{i}.md")
    got = text_of(index(world).text)
    assert says in got


def test_a_root_with_no_markdown_says_so(world, work):
    (work / "start.md").unlink()
    assert "No markdown files in this folder." in index(world).text


def test_a_hub_with_no_root_says_how_to_add_one(browser):
    got = index(browser).text
    assert "No documents yet." in got and "<code>sheaf open FILE.md</code>" in got


# ── one root ─────────────────────────────────────────────────────────────────

@pytest.fixture
def two(world, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.md").write_text("# X\n")
    world.hub.roots.for_document(other / "x.md")
    return world


def test_a_root_page_lists_only_that_root(two):
    got = index(two, "/other/").text
    assert list(rows(got)) == ["other/x.md"] and 'data-root="work"' not in got
    assert '<a class="back" href="/">all roots</a>' in got
    assert 'data-only="other"' in got


def test_the_index_of_every_root_has_no_back_link(two):
    got = index(two).text
    assert 'class="back"' not in got and 'data-only=""' in got
    assert set(re.findall(r'data-root="([^"]+)"', got)) == {"work", "other"}


def test_a_root_that_is_not_registered_is_404(two):
    assert two.get("/nothere/").status == 404
    assert two.get("/_/").status == 404


def test_a_root_name_without_its_slash_is_sent_to_its_page(two):
    r = two.get("/other")
    assert r.status == 301 and r.headers["Location"] == "/other/"
    assert two.get("/o%74her").headers["Location"] == "/o%74her/"
    assert two.get("/nothere").status == 404          # no root by that name: nowhere to send it


# ── names a person chose cannot reach the page's markup ──────────────────────

def test_hostile_file_and_folder_names_are_text(world, tmp_path):
    folder = tmp_path / 'ev<il>"&\'x'
    f = folder / '<img src=x onerror=alert(1)>"&.md'
    f.parent.mkdir()
    f.write_text("# E\n")
    world.hub.roots.for_document(f)
    page = index(world).text
    assert active_content(page) == ["<script>"]          # ours, and nothing a name added
    assert "<img" not in page and "<il>" not in page
    assert world.hub.roots.address(f) in rows(page)
    assert str(folder.resolve()) not in page and htmllib.escape(str(folder.resolve())) in page


# ── "4 min ago" ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sec,text", [
    (-30, "just now"), (0, "just now"), (44, "just now"), (45, "1 min ago"), (89, "1 min ago"),
    (240, "4 min ago"), (3599, "59 min ago"), (3600, "1 h ago"), (7300, "2 h ago"),
    (86399, "23 h ago"), (86400, "1 day ago"), (3 * 86400, "3 days ago"),
    (29 * 86400 + 5, "29 days ago")])
def test_the_last_change_reads_as_a_span(sec, text):
    assert index_mod.ago(sec) == text


def test_a_change_older_than_a_month_is_a_date():
    t = time.mktime((2026, 7, 1, 12, 0, 0, 0, 0, -1))
    assert index_mod.when(t, t + 40 * 86400) == "2026-07-01"
    assert index_mod.when(t, t + 5 * 86400) == "5 days ago"


def test_the_page_reads_its_times_against_the_hubs_clock(world, put):
    put("a.md", age=240)
    world.hub.clock = lambda: NOW + 3600
    assert text_of(rows(index(world).text)["work/a.md"][1]).endswith("1 h ago")


def test_the_index_page_reloads_into_the_sign_in_page_when_its_stream_says_signed_out(world):
    script = world.get("/").text
    assert re.search(r"addEventListener\('signed-out',\s*function \(\) \{[^}]*location\.reload\(\)", script)
