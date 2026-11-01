"""The page meets a hub that was upgraded under it (SPEC 14.4, 10.7), or whose key was rotated
(9.3): `hello` is the first event of every connect and carries the hub's version; `signed-out` is
the last event a rotation sends. A static pin of the script, as the other page tests are; the
browser behaviour was checked by hand against a real hub when it was written."""
import re
from importlib.resources import files

JS = (files("sheafmd") / "page" / "page.js").read_text(encoding="utf-8")


def body_of(opener):
    """The text of the function or handler that starts at `opener`, to its closing brace."""
    start = JS.index(opener)
    i = JS.index("{", start)
    depth = 0
    for j in range(i, len(JS)):
        depth += JS[j] == "{"
        depth -= JS[j] == "}"
        if depth == 0:
            return JS[start:j + 1]
    raise AssertionError(opener)


def test_hello_hands_the_hubs_version_to_the_version_check():
    hello = body_of("live.addEventListener('hello'")
    assert re.search(r"meetVersion\(\s*data\(ev\)\.version\s*\)", hello)


def test_a_page_on_the_old_version_reloads_when_nothing_is_only_on_screen():
    f = body_of("var meetVersion = function")
    assert "CFG.version" in f and "reloadKeep(" in f
    assert "dirty().length" in f and "writingNow({ page: true })" in f


def test_unsaved_edits_and_a_comment_being_written_are_never_reloaded_over():
    f = body_of("var meetVersion = function")
    guard = f.index("dirty().length")
    assert guard < f.index("reloadKeep(")              # the guard is checked first
    assert "showNoticeOverOffer(" in f[guard:f.index("reloadKeep(")]
    assert "location.reload" not in f and "reloadPage" not in f      # only reloadKeep, which keeps scroll and caret


def test_a_comment_being_written_is_a_form_with_text_in_it_and_not_a_kept_comment():
    f = body_of("function formsWithText")
    assert ".rd-form:not([data-kept])" in f and ".value.trim()" in f
    assert "writingNow({ page: true })" in body_of("var meetVersion = function")


def test_signed_out_is_handled_by_the_sign_out_check():
    h = body_of("live.addEventListener('signed-out'")
    assert "meetSignOut(" in h


def test_a_tab_with_nothing_only_on_screen_reloads_into_the_sign_in_page():
    f = body_of("var meetSignOut = function")
    guard = f.index("dirty().length")
    assert "writingNow({ page: true })" in f[:f.index("reloadPage()")]
    assert guard < f.index("reloadPage()")        # the guard comes first
    assert "stopped = true" in f                       # the "hub unreachable" toast stays quiet


def test_a_tab_with_unsaved_work_keeps_it_and_says_how_to_sign_in_again():
    f = body_of("var meetSignOut = function")
    notice = f[f.index("showNoticeOverOffer("):f.index("reloadPage()")]
    assert "sheaf open" in notice and "on screen" in notice


# A comment is sent from a form that removes itself the moment it is sent, so while its POST is in
# flight nothing is on screen to show that it is being written. The reload waits for the answer.

def test_a_write_in_flight_is_counted_whatever_its_outcome():
    post = body_of("async function post(")
    assert "writes++" in post
    assert "finally" in post and post.index("finally") < post.index("writes--")


def test_the_reload_waits_for_a_write_in_flight_before_it_looks_at_the_screen():
    for opener in ("var meetVersion = function", "var meetSignOut = function"):
        f = body_of(opener)
        wait = f.index("writes")
        assert "afterWrites" in f[wait:f.index("dirty().length")], opener      # parked, not dropped
        assert wait < f.index("dirty().length"), opener
        assert "return" in f[wait:f.index("dirty().length")], opener


def test_what_was_parked_runs_again_when_the_last_write_is_answered():
    post = body_of("async function post(")
    assert "afterWrites" in post[post.index("finally"):] and "!writes" in post[post.index("finally"):]
