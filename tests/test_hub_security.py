"""The hub's security model, through the handler, in memory (SPEC 9, 18 Security).

Wrong Host, cookie POST without a matching Origin, no cookie, /_/open with a wrong key,
next=//evil, a key in the page, the CSP on every HTML response, hostile document content,
a path out of the root, the proof of the health answer."""
import re

import pytest

from helpers import active_content, page_meta
from sheafmd import paths
from sheafmd.hub import auth
from sheafmd.source import md_hash

DOC = "work/plan.md"
URL = "/work/plan.md"

# Every route the hub has, as (method, path). Paths that name a document name the fixture's.
COOKIE_ROUTES = [
    ("GET", URL), ("GET", "/"), ("GET", "/work/"), ("GET", f"/_/live?doc={DOC}"),
    ("GET", f"/_/doc?doc={DOC}"), ("POST", "/_/save"), ("POST", "/_/comment"),
    ("POST", "/_/ask"), ("POST", "/_/tell"), ("POST", "/_/cancel"), ("POST", "/_/seen"),
    ("POST", "/_/export"), ("POST", "/_/diag"), ("POST", "/_/pin")]
KEY_ROUTES = [("GET", "/_/jobs"), ("POST", "/_/render"), ("POST", "/_/stop"), ("POST", "/_/signin"),
              ("POST", "/_/restarting"), ("DELETE", "/_/restarting")]
OPEN_ROUTES = [("GET", "/_/health"), ("GET", "/_/open?key=x&next=/")]
UNKNOWN = [("GET", "/_/nothing"), ("POST", "/_/nothing"), ("GET", "/favicon.ico"),
           ("GET", "/nothing/at/all.md"), ("PUT", "/_/save"), ("DELETE", URL), ("OPTIONS", URL),
           ("GET", "/_/mcp"), ("POST", "/_/mcp"), ("GET", "/_/index.json"), ("POST", "/_/rotate")]


# ── Host (9.2) ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", COOKIE_ROUTES + KEY_ROUTES + OPEN_ROUTES + UNKNOWN)
@pytest.mark.parametrize("host", ["evil.example", "evil.example:27419", "127.0.0.1",
                                  "127.0.0.1:27419.evil.example", ""])
def test_a_wrong_host_is_403_on_every_route_whatever_it_carries(browser, plan, method, path, host):
    r = browser.request(method, path, host=host, key=True, body={} if method == "POST" else None,
                        headers={"Host": host} if host == "" else None)
    assert r.status == 403 and r.json()["ok"] is False


def test_a_host_on_another_port_passes_so_a_forwarded_hub_works(browser, plan):
    host = "localhost:41234"
    assert browser.get(URL, host=host).status == 200
    assert browser.post("/_/seen", {"doc": DOC, "id": "c1", "count": 1}, host=host).status == 200


# ── Origin (9.2) ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [r for r in COOKIE_ROUTES if r[0] == "POST"])
@pytest.mark.parametrize("origin", [False, "http://evil.example", "null", "http://127.0.0.1:3000",
                                    "https://127.0.0.1:27419", "http://localhost:27419",
                                    "http://127.0.0.1:27419/"])
def test_a_cookie_post_without_an_origin_equal_to_its_host_is_403(browser, plan, method, path, origin):
    r = browser.post(path, {"doc": DOC}, origin=origin)
    assert r.status == 403 and r.json()["ok"] is False
    assert not (plan.parent / "plan.md.sheaf-tmp").exists()


def test_a_post_that_a_page_on_another_port_makes_with_the_cookie_cannot_write(browser, plan):
    before = plan.read_text(encoding="utf-8")
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(before),
                                 "edits": [{"i": 1, "html": "<p>defaced</p>"}]},
                     origin="http://127.0.0.1:3000")
    assert r.status == 403 and plan.read_text(encoding="utf-8") == before
    r = browser.post("/_/comment", {"doc": DOC, "op": "delete", "id": "c1", "hash": md_hash(before)},
                     origin="http://127.0.0.1:3000")
    assert r.status == 403


def test_the_key_header_needs_no_origin(browser, plan):
    r = browser.post("/_/render", {"path": str(plan)}, cookie=False, key=True, origin=False)
    assert r.status == 200


def test_a_get_with_the_cookie_needs_no_origin(browser, plan):
    assert browser.get(URL).status == 200


def test_no_response_carries_a_cors_header_and_options_gets_none(browser, plan):
    for method, path in COOKIE_ROUTES + KEY_ROUTES + OPEN_ROUTES + UNKNOWN:
        r = browser.request(method, path, key=True, body={} if method == "POST" else None,
                            headers={"Origin": "http://evil.example"})
        assert not [h for h in r.headers if h.lower().startswith("access-control")], (method, path)
    r = browser.request("OPTIONS", "/_/save", headers={"Access-Control-Request-Method": "POST",
                                                      "Origin": "http://evil.example"})
    assert r.status == 405 and not [h for h in r.headers if h.lower().startswith("access-control")]


# ── no cookie, no key (9.3) ──────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", COOKIE_ROUTES + KEY_ROUTES + UNKNOWN)
def test_no_credentials_is_401_on_every_route_but_health_and_open(browser, plan, method, path):
    r = browser.request(method, path, cookie=False, body={} if method == "POST" else None)
    assert r.status == 401
    assert "Set-Cookie" not in r.headers


def test_an_unsigned_page_gets_the_sign_in_page_and_an_api_call_gets_json(browser, plan):
    page = browser.get(URL, cookie=False)
    assert page.status == 401 and page.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "This browser is not signed in to your sheaf hub." in page.text
    import html
    assert "run `sheaf open <this url>`" in html.unescape(page.text).replace("<code>", "`").replace("</code>", "`")
    assert "sheaf signin-url" in page.text
    api = browser.get(f"/_/doc?doc={DOC}", cookie=False)
    assert api.status == 401 and api.json()["ok"] is False


def test_a_wrong_cookie_a_wrong_key_and_a_cookie_of_another_hub_are_not_credentials(browser, plan):
    name = browser.hub.auth.cookie_name
    for h in ({"Cookie": f"{name}=" + "0" * 64}, {"Cookie": f"{name}="}, {"Cookie": "sheaf_1=x"},
              {"X-Sheaf-Key": "x" * 43}, {"X-Sheaf-Key": ""}):
        assert browser.get(URL, cookie=False, headers=h).status == 401
    other = auth.Auth(paths.key_bytes and "A" * 43, 27419)          # a key this hub never had
    assert browser.get(URL, cookie=False, headers={
        "Cookie": f"{other.cookie_name}={other.cookie_value()}"}).status == 401


def test_the_key_header_opens_the_key_routes_and_the_cookie_does_not(browser, plan):
    assert browser.get("/_/jobs", cookie=False, key=True).status == 200
    r = browser.get("/_/jobs")                       # a signed-in browser is not the CLI
    assert r.status == 403
    assert browser.post("/_/stop", {"reason": "stop"}).status == 403
    assert browser.post("/_/render", {"path": str(plan)}).status == 403
    assert browser.hub.stop_requested is None


def test_the_key_header_does_not_open_a_cookie_route_that_writes(browser, plan):
    for path in ("/_/save", "/_/comment", "/_/seen", "/_/export", "/_/diag", "/_/ask", "/_/pin", "/_/jump"):
        r = browser.post(path, {"doc": DOC}, cookie=False, key=True)
        assert r.status == 403, path
    assert browser.get(URL, cookie=False, key=True).status == 403


# ── /_/open (9.3) ────────────────────────────────────────────────────────────

def sign_in_nonce(browser) -> str:
    """What `sheaf open` does first: the hub mints a one-time nonce for the key holder."""
    r = browser.post("/_/signin", cookie=False, key=True)
    assert r.status == 200 and r.json()["ok"] is True
    return r.json()["nonce"]


def open_with(browser, nonce, nxt="/work/plan.md"):
    return browser.get(f"/_/open?nonce={nonce}&next={nxt}", cookie=False)


def open_url(browser, key=None, nxt="/work/plan.md", **kw):
    k = browser.hub.auth.key if key is None else key
    q = f"key={k}" + (f"&next={nxt}" if nxt is not None else "")
    return browser.get("/_/open?" + q, cookie=False, **kw)


def test_the_right_key_swaps_for_a_cookie_and_sends_the_browser_on(browser, plan):
    r = open_url(browser)
    assert r.status == 303 and r.headers["Location"] == "/work/plan.md" and r.body == b""
    cookie = r.headers["Set-Cookie"]
    assert cookie == (f"sheaf_27419={browser.hub.auth.cookie_value()}; HttpOnly; SameSite=Strict; "
                      "Path=/; Max-Age=34560000")
    jar = cookie.split(";")[0]
    assert browser.get(URL, cookie=False, headers={"Cookie": jar}).status == 200


@pytest.mark.parametrize("name", ["a b.md", "a#b.md", "a?b.md", "a%23b.md", "a&b=c.md"])
def test_the_sign_in_url_the_cli_builds_lands_on_the_document_whatever_its_name(browser, plan, work, name):
    from sheafmd.hub.client import HubClient
    from sheafmd.hub.roots import url_path
    (work / name).write_text("# T\n\nHello.\n", encoding="utf-8")
    address = browser.hub.roots.address(work / name)
    next_path = url_path(address)
    url = HubClient(browser.hub.auth.key, 27419).sign_in_url(next_path)
    r = browser.get(url.split("27419", 1)[1], cookie=False)
    assert r.status == 303 and r.headers["Location"] == next_path
    assert browser.get(r.headers["Location"], cookie=True).status == 200


def test_the_cookie_does_not_hold_the_key(browser, plan):
    r = open_url(browser)
    assert browser.hub.auth.key not in r.headers["Set-Cookie"]
    assert browser.hub.auth.key not in r.headers["Location"]


@pytest.mark.parametrize("key", ["", "x", "A" * 43, None])
def test_a_wrong_key_sets_nothing(browser, plan, key):
    r = browser.get("/_/open" + (f"?key={key}&next=/work/plan.md" if key is not None else "?next=/"),
                    cookie=False)
    assert r.status == 401 and "Set-Cookie" not in r.headers and "Location" not in r.headers


@pytest.mark.parametrize("nxt", ["//evil.example", "/%5Cevil.example", "http://evil.example/x",
                                 "evil.example", "/a%5Cb", "//", "/x%0d%0aSet-Cookie:%20a=b",
                                 "javascript:alert(1)", "%2F%2Fevil.example"])
def test_a_next_that_leaves_the_hub_is_refused_and_sets_no_cookie(browser, plan, nxt):
    r = open_url(browser, nxt=nxt)
    assert r.status == 400 and "Set-Cookie" not in r.headers and "Location" not in r.headers


def test_a_next_with_a_raw_line_break_cannot_split_the_header(browser, plan):
    r = browser.get("/_/open?key=" + browser.hub.auth.key + "&next=/x\r\nSet-Cookie: a=b", cookie=False)
    assert r.status == 400 and "Set-Cookie" not in r.headers


def test_next_defaults_to_the_root_and_may_carry_a_query(browser, plan):
    assert open_url(browser, nxt=None).headers["Location"] == "/"
    assert open_url(browser, nxt="/work/plan.md%3Fa=1").headers["Location"].startswith("/work/plan.md")


def test_the_key_is_compared_not_looked_up(browser, plan):
    r = open_url(browser, key=browser.hub.auth.key + "x")
    assert r.status == 401


# ── /_/health and the impostor check (9.4) ───────────────────────────────────

def test_health_names_the_hub_and_proves_it_holds_the_key(browser, plan):
    nonce = "ab" * 16
    got = browser.get(f"/_/health?nonce={nonce}", cookie=False).json()
    assert got == {"ok": True, "app": "sheaf", "version": browser.hub.version,
                   "boot": browser.hub.boot, "service": False,
                   "proof": browser.hub.auth.proof(nonce)}
    assert got["proof"] != browser.hub.auth.proof("cd" * 16)


def test_health_without_a_nonce_gives_no_proof_and_never_a_path_or_a_document(browser, plan):
    browser.get(URL)
    r = browser.get("/_/health", cookie=False)
    assert set(r.json()) == {"ok", "app", "version", "boot", "service"}
    assert str(plan.parent) not in r.text and "plan" not in r.text


@pytest.mark.parametrize("nonce", ["zz", "", "AB" * 16, "ab" * 3, "ab" * 100, "../../x"])
def test_health_with_a_nonce_that_is_not_one_is_400(browser, plan, nonce):
    assert browser.get(f"/_/health?nonce={nonce}", cookie=False).status == 400


def test_a_proof_from_another_key_does_not_match(browser, plan):
    nonce = "ab" * 16
    impostor = auth.Auth("A" * 43, 27419)
    assert impostor.proof(nonce) != browser.get(f"/_/health?nonce={nonce}", cookie=False).json()["proof"]


# ── the key never reaches a page (9.3) ───────────────────────────────────────

def test_no_page_and_no_answer_holds_the_key_or_the_cookie_value(browser, plan):
    secrets = [browser.hub.auth.key, browser.hub.auth.cookie_value()]
    answers = [browser.get(URL), browser.get(URL, cookie=False), browser.get(f"/_/doc?doc={DOC}"),
               browser.get("/_/health", cookie=False), browser.get("/_/jobs", key=True, cookie=False),
               browser.post("/_/export", {"doc": DOC, "kind": "html"}),
               browser.get("/_/nothing"), browser.get(f"/_/live?doc={DOC}")]
    for r in answers:
        for s in secrets:
            assert s not in r.text and s not in "".join(f"{k}{v}" for k, v in r.headers.items())
    assert "token" not in page_meta(browser.get(URL).text)


# ── the CSP on every HTML response (9.5) ─────────────────────────────────────

def test_every_html_response_carries_the_csp_with_its_own_nonce(browser, plan):
    html = [browser.get(URL), browser.get(URL, cookie=False), browser.get("/work/", cookie=False),
            browser.post("/_/export", {"doc": DOC, "kind": "html"})]
    nonces = set()
    for r in html:
        assert r.headers["Content-Type"].startswith("text/html")
        policy = r.headers["Content-Security-Policy"]
        m = re.fullmatch(r"default-src 'none'; script-src 'nonce-([A-Za-z0-9+/_=-]+)'; "
                         r"style-src 'unsafe-inline'; img-src data:; font-src data:; "
                         r"connect-src 'self'; base-uri 'none'; form-action 'none'; "
                         r"frame-ancestors 'none'", policy)
        assert m, policy
        nonces.add(m.group(1))
    assert len(nonces) == len(html)


def test_the_sign_in_page_has_no_script_at_all(browser, plan):
    assert "<script" not in browser.get(URL, cookie=False).text


def test_json_answers_need_no_csp_but_say_what_they_are(browser, plan):
    r = browser.get(f"/_/doc?doc={DOC}")
    assert r.headers["Content-Type"] == "application/json" and "Content-Security-Policy" not in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"


# ── hostile content in a document (9.5) ──────────────────────────────────────

HOSTILE = '''# Hostile

Plain text.

<script>document.title = "pwned"</script>

<img src="x" onerror="alert(1)">

<iframe src="http://evil.example"></iframe>

[click](javascript:alert(1))

<a href="javascript:alert(2)" onclick="alert(3)">second</a>

<form action="http://evil.example"><button>go</button></form>

<style>body { background: url(http://evil.example/x) }</style>

<meta http-equiv="refresh" content="0;url=http://evil.example">

- [x] done
- [ ] not done

<!-- a foreign comment -->
'''


def test_a_hostile_document_is_served_without_anything_that_runs(browser, plan, work):
    f = work / "hostile.md"
    f.write_text(HOSTILE, encoding="utf-8")
    r = browser.get("/work/hostile.md")
    assert r.status == 200
    found = active_content(r.text)
    # Only the page's own two scripts: the meta block (data) and the page script (nonce).
    assert found == ["<script>", "<script>"], found
    assert r.text.count("<script") == 2
    doc = r.text.split('<script id="rd-edit-meta"')[0]       # the document, before the page's own scripts
    assert "pwned" not in doc and "evil.example" not in doc and "javascript:" not in doc
    assert 'type="checkbox"' in doc                          # task boxes stay
    assert "a foreign comment" in doc                        # comments stay


def test_the_page_carries_no_inline_handler_and_no_script_but_its_own(browser, plan, work):
    f = work / "hostile.md"
    f.write_text(HOSTILE, encoding="utf-8")
    html = browser.get("/work/hostile.md").text
    assert not re.search(r"\son[a-z]+\s*=", html, re.I)
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert len(scripts) == 2 and 'type="application/json"' in scripts[0] and re.fullmatch(r'<script nonce="[^"]+">', scripts[1])


def test_a_comment_holding_a_closing_script_tag_cannot_end_the_meta_block(browser, plan):
    import sheafmd.comments as rdc
    from sheafmd.source import update_file
    update_file(plan, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"),
                                                "Second paragraph", "</script><script>alert(1)</script>",
                                                "Eve", "2026-10-14T10:00")[0])
    html = browser.get(URL).text
    assert html.count("<script") == 2
    assert page_meta(html)["comments"][0]["body"] == "</script><script>alert(1)</script>"


def test_the_export_of_a_hostile_document_runs_nothing_either(browser, plan, work):
    f = work / "hostile.md"
    f.write_text(HOSTILE, encoding="utf-8")
    r = browser.post("/_/export", {"doc": "work/hostile.md", "kind": "html"})
    assert active_content(r.text) == [] and "<script" not in r.text


# ── paths out of the root (8.3) ──────────────────────────────────────────────

SECRET = "TOP SECRET\n"


@pytest.fixture
def outside(tmp_path, work, plan):
    secret = tmp_path / "secret.md"
    secret.write_text(SECRET, encoding="utf-8")
    (work / "link.md").symlink_to(secret)
    (work / "dir").symlink_to(tmp_path)
    (tmp_path / "secret.txt").write_text(SECRET)
    return secret


@pytest.mark.parametrize("url", [
    "/work/../secret.md", "/work/%2e%2e/secret.md", "/work/%2E%2E/secret.md", "/work/./plan.md",
    "/work/..%2fsecret.md", "/work//plan.md", "/work/link.md", "/work/dir/secret.md",
    "/work/dir/secret.txt", "/work/plan.md/", "/work/plan.md/../secret.md", "/%2e%2e/secret.md",
    "/work/%00.md", "/work/plan.MD", "/work/plan.md%00", "/nowhere/plan.md",
    "/_/plan.md"])
def test_a_url_that_leaves_the_root_is_404_and_serves_nothing(browser, outside, url):
    r = browser.get(url)
    assert r.status in (404, 400) and SECRET.strip() not in r.text


@pytest.mark.parametrize("doc", ["work/../secret.md", "work/link.md", "work/dir/secret.md",
                                 "../secret.md", "/etc/passwd", "work/dir/secret.txt"])
def test_a_doc_field_that_leaves_the_root_is_404_on_every_route(browser, outside, doc):
    assert browser.get(f"/_/doc?doc={doc}").status == 404
    assert browser.get(f"/_/live?doc={doc}").status == 404
    for route, body in (("/_/save", {"hash": "x", "edits": []}), ("/_/comment", {"op": "delete", "id": "c1"}),
                        ("/_/seen", {"id": "c1", "count": 1}), ("/_/export", {"kind": "html"}),
                        ("/_/ask", {"id": "c1"})):
        assert browser.post(route, {"doc": doc, **body}).status == 404, route
    assert outside.read_text() == SECRET


def test_render_of_a_file_through_a_symlink_that_leaves_its_root_serves_nothing(browser, outside, work):
    r = browser.post("/_/render", {"path": str(work / "link.md")}, cookie=False, key=True)
    assert r.status == 200                                   # the CLI named a real file of its own
    assert browser.get(r.json()["url"].split("27419")[1]).status == 200
    assert browser.get("/work/link.md").status == 404        # but the link is not reachable by URL


# ── the one-time sign-in nonce (9.3): what `sheaf open` hands the browser instead of the key ──

def test_a_nonce_swaps_for_the_cookie_the_key_would_have_given(browser, plan):
    nonce = sign_in_nonce(browser)
    r = open_with(browser, nonce)
    assert r.status == 303 and r.headers["Location"] == "/work/plan.md" and r.body == b""
    assert r.headers["Set-Cookie"] == open_url(browser).headers["Set-Cookie"]
    jar = r.headers["Set-Cookie"].split(";")[0]
    assert browser.get(URL, cookie=False, headers={"Cookie": jar}).status == 200


def test_the_nonce_is_not_the_key_and_the_answer_says_how_long_it_lives(browser, plan):
    r = browser.post("/_/signin", cookie=False, key=True)
    assert r.json()["nonce"] != browser.hub.auth.key and r.json()["expires"] == 30
    assert browser.hub.auth.key not in r.text.replace(f'"nonce": "{r.json()["nonce"]}"', "")
    assert sign_in_nonce(browser) != sign_in_nonce(browser)


def test_a_nonce_used_twice_is_refused_the_second_time_and_sets_nothing(browser, plan):
    nonce = sign_in_nonce(browser)
    assert open_with(browser, nonce).status == 303
    again = open_with(browser, nonce)
    assert again.status == 401 and "Set-Cookie" not in again.headers and "Location" not in again.headers


def refused_open(browser, how):
    """`/_/open` as a browser sends it (`Accept: text/html`) after a link that does not work."""
    now = [1000.0]
    browser.hub.auth.clock = lambda: now[0]
    nonce = sign_in_nonce(browser)
    if how == "spent":
        assert open_with(browser, nonce).status == 303
    elif how == "expired":
        now[0] += 31
    elif how == "never made":
        nonce = "x" * 43
    return browser.get(f"/_/open?nonce={nonce}&next=/work/plan.md", cookie=False,
                       headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}), nonce


@pytest.mark.parametrize("how", ["spent", "expired", "never made"])
def test_a_link_that_does_not_work_shows_a_browser_the_sign_in_page_not_json(browser, plan, how):
    r, nonce = refused_open(browser, how)
    assert r.status == 401 and r.headers["Content-Type"].startswith("text/html")
    assert "Set-Cookie" not in r.headers and "Location" not in r.headers
    assert "Content-Security-Policy" in r.headers
    assert not r.text.lstrip().startswith("{")
    # the way back in, and the rotate for a link that someone else used
    assert "sheaf open" in r.text and "sheaf rotate" in r.text
    assert nonce not in r.text and browser.hub.auth.key not in r.text   # nothing of the query comes back


def test_a_wrong_key_in_the_link_shows_a_browser_the_sign_in_page_too(browser, plan):
    r = browser.get("/_/open?key=nope&next=/work/plan.md", cookie=False,
                    headers={"Accept": "text/html"})
    assert r.status == 401 and r.headers["Content-Type"].startswith("text/html")
    assert "sheaf signin-url" in r.text and "nope" not in r.text and "Set-Cookie" not in r.headers


@pytest.mark.parametrize("accept", [None, "application/json", "*/*"])
def test_a_caller_that_did_not_ask_for_html_still_gets_the_json_refusal(browser, plan, accept):
    nonce = sign_in_nonce(browser)
    assert open_with(browser, nonce).status == 303
    r = browser.get(f"/_/open?nonce={nonce}&next=/work/plan.md", cookie=False,
                    headers={"Accept": accept} if accept else None)
    assert r.status == 401 and r.json() == {"ok": False, "error": "that sign-in link was used already, "
                                            "has expired or is not this hub's"}


def test_a_nonce_works_for_about_thirty_seconds_and_not_after(browser, plan):
    now = [1000.0]
    browser.hub.auth.clock = lambda: now[0]
    fresh, stale = sign_in_nonce(browser), sign_in_nonce(browser)
    now[0] += 29.9
    assert open_with(browser, fresh).status == 303
    now[0] += 0.2                                   # 30.1 s after the mint
    late = open_with(browser, stale)
    assert late.status == 401 and "Set-Cookie" not in late.headers


def test_a_nonce_that_expired_is_gone_for_good_even_if_the_clock_goes_back(browser, plan):
    now = [1000.0]
    browser.hub.auth.clock = lambda: now[0]
    nonce = sign_in_nonce(browser)
    now[0] += 31
    assert open_with(browser, nonce).status == 401
    now[0] -= 31
    assert open_with(browser, nonce).status == 401


@pytest.mark.parametrize("nonce", ["", "x", "A" * 43, "0" * 64, "../etc", "a b"])
def test_a_nonce_the_hub_never_made_sets_nothing(browser, plan, nonce):
    sign_in_nonce(browser)
    r = open_with(browser, nonce)
    assert r.status == 401 and "Set-Cookie" not in r.headers and "Location" not in r.headers


def test_a_nonce_made_before_a_rotation_does_not_survive_it(browser, plan):
    nonce = sign_in_nonce(browser)
    browser.hub.rotate()
    r = open_with(browser, nonce)
    assert r.status == 401 and "Set-Cookie" not in r.headers


def test_the_key_comes_only_from_the_key_header_when_minting_a_nonce(browser, plan):
    assert browser.post("/_/signin", cookie=False).status == 401
    assert browser.post("/_/signin").status == 403            # a signed-in browser may not mint another
    assert browser.get("/_/signin", cookie=False, key=True).status == 405


def test_a_nonce_is_neither_a_key_nor_a_cookie(browser, plan):
    nonce = sign_in_nonce(browser)
    name = browser.hub.auth.cookie_name
    assert browser.get("/_/jobs", cookie=False, headers={"X-Sheaf-Key": nonce}).status == 401
    assert browser.get(URL, cookie=False, headers={"Cookie": f"{name}={nonce}"}).status == 401
    assert open_with(browser, nonce).status == 303               # and it was still unspent


def test_a_nonce_does_not_open_a_next_that_leaves_the_hub(browser, plan):
    r = open_with(browser, sign_in_nonce(browser), nxt="//evil.example")
    assert r.status == 400 and "Set-Cookie" not in r.headers and "Location" not in r.headers


def test_a_refused_nonce_leaves_a_row_in_the_diagnostics_log_without_the_nonce(browser, plan):
    from sheafmd import diagnostics
    nonce = sign_in_nonce(browser)
    open_with(browser, nonce)
    open_with(browser, nonce)
    got = [r for r in diagnostics.read() if r["kind"] == "open-401"]
    assert got and nonce not in str(diagnostics.read())


def test_the_row_of_a_refused_link_keeps_its_reason_when_the_answer_is_a_page(browser, plan):
    from sheafmd import diagnostics
    r, nonce = refused_open(browser, "spent")
    assert r.headers["Content-Type"].startswith("text/html")
    got = [x for x in diagnostics.read() if x["kind"] == "open-401"]
    assert got and "used already" in got[-1]["error"] and nonce not in str(diagnostics.read())


def test_the_key_still_opens_the_browser_for_signin_url(browser, plan):
    r = open_url(browser)                                       # D13: the key URL stays for another machine
    assert r.status == 303 and "Set-Cookie" in r.headers
