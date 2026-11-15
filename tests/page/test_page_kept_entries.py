"""The store of the kept comments, one localStorage key per entry (SPEC 10.8): what its keys may be taken for, and what
the move of an earlier build's list into keys does when pages and older tabs meet it (ticket 130, the c and d
leftovers of the review of ticket 121)."""
import json

import pytest

from pagehelp import P1, P2, at, comment_draft_key, kept_entries, select, set_kept, until

pytestmark = pytest.mark.page

FIELD = "#rd-popover textarea"
UNSENT = "#rd-unsent"
LIST = "#rd-popover[data-unsent]"


def message(body, born="2026-10-14T11:00:00.000Z"):
    """A new message kept for later, as an earlier build wrote it."""
    return {"quote": "apples", "body": body, "block": 0, "head": "x", "at": born, "min": True}


def reply(body, born="2026-10-14T11:00:00.000Z"):
    """A reply kept for later, as an earlier build wrote it (it names no passage: a message typed later replaces none)."""
    return {"thread": "c1", "kind": "reply", "body": body, "about": "apples", "born": "2026-10-14T10:00", "at": born}


def listed(page):
    """The texts of the not-sent list, as the page shows them."""
    page.click(UNSENT)
    page.wait_for_selector(LIST, timeout=3000)
    return sorted(f.locator("textarea").input_value() for f in page.locator(f"{LIST} .rd-form").all())


def in_order(page, among):
    """The texts of `among` as the not-sent list shows them, top to bottom (the list is closed again after)."""
    page.click(UNSENT)
    page.wait_for_selector(LIST, timeout=3000)
    got = [f.locator("textarea").input_value() for f in page.locator(f"{LIST} .rd-form").all()]
    page.click(UNSENT)
    return [t for t in got if t in among]


def loaded(page):
    page.reload()
    page.wait_for_selector("#rd-menu-btn", state="attached")


def unsent(page):
    """The text of the not-sent line, '' when there is none (a beat is given to a line still to be drawn)."""
    page.wait_for_timeout(400)
    return page.inner_text(UNSENT) if page.locator(UNSENT).count() else ""


def put(page, key, value):
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, value])


def keep_a_new_message(page, text):
    """A write of the store by the page: a message typed and put away."""
    select(page, at(P2, "pears"), at(P2, "pears", None))        # another passage: the kept messages are on "apples"
    page.fill(FIELD, text)
    page.keyboard.press("Escape")
    until(lambda: text in page.evaluate("JSON.stringify(Object.values(localStorage))"), what="the typed message in the store")


def discard(page, text):
    """Open the not-sent list and press Discard on the entry holding `text`."""
    page.click(UNSENT)
    page.wait_for_selector(LIST, timeout=3000)
    forms = page.locator(f"{LIST} .rd-form")
    mine = [i for i in range(forms.count()) if forms.nth(i).locator("textarea").input_value() == text]
    assert len(mine) == 1, f"{len(mine)} kept texts match {text!r}"
    forms.nth(mine[0]).locator("button[data-f=no]").click()


# c4: the key is `<doc>:e:<id>` and a document may be named `a.md:e:x.md`.
def test_a_document_named_with_e_colon_does_not_lend_its_entries_to_the_document_before_it(tab, site):
    tab.open()
    p, key = tab.page, comment_draft_key(site)
    put(p, key + ":e:0mwgzsy17-000-0000", json.dumps(message("mine")))
    put(p, key + ":e:x.md:e:0mwgzsy17-000-0001", json.dumps(message("the words of another document")))
    loaded(p)
    assert unsent(p) == "1 message not sent · Show", "another document's entry is listed as this one's"
    p.click(UNSENT)
    p.wait_for_selector(LIST, timeout=3000)
    assert [f.locator("textarea").input_value() for f in p.locator(f"{LIST} .rd-form").all()] == ["mine"]


# c3, c6: the id an entry takes when the list moves into keys is the same wherever the entry stands in the list.
def test_an_entry_the_page_moved_is_not_listed_twice_when_an_older_tab_writes_the_list_again(tab, site):
    tab.open()
    p = tab.page
    first, second = message("first words"), message("second words", "2026-10-14T11:01:00.000Z")
    set_kept(p, site, [first, second])
    loaded(p)
    assert unsent(p) == "2 messages not sent · Show"
    discard(p, "first words")                      # a write: the list moves into keys, the first is removed
    until(lambda: p.evaluate("localStorage.getItem(%s)" % json.dumps(comment_draft_key(site))) is None, what="the list to be moved")
    # An older tab, which saw the first entry removed, writes the list with the second one at the place the first had.
    put(p, comment_draft_key(site), json.dumps([second]))
    loaded(p)
    assert unsent(p) == "1 message not sent · Show", "the entry the page moved is listed again from the list"


# d2: a list is not the only form an earlier build wrote: the one-slot form is an object under the key.
def test_a_comment_kept_in_the_one_slot_of_an_older_store_is_listed_and_moved_by_the_next_write(tab, site):
    tab.open()
    p, key = tab.page, comment_draft_key(site)
    put(p, key, json.dumps(message("from the one slot")))
    loaded(p)
    assert unsent(p) == "1 message not sent · Show"
    keep_a_new_message(p, "typed after")
    assert p.evaluate("localStorage.getItem(%s)" % json.dumps(key)) is None, "the one slot was left where it was"
    assert sorted(d["body"] for d in kept_entries(p, site)) == ["from the one slot", "typed after"]


# d3: the list and entry keys together (an older tab writes the list after a page moved it).
def test_a_list_beside_entry_keys_that_hold_the_same_entries_lists_each_once(tab, site):
    tab.open()
    p = tab.page
    both = [reply("first words"), reply("second words", "2026-10-14T11:01:00.000Z")]
    set_kept(p, site, both)
    loaded(p)
    keep_a_new_message(p, "third words")
    until(lambda: p.evaluate("localStorage.getItem(%s)" % json.dumps(comment_draft_key(site))) is None, what="the list to be moved")
    put(p, comment_draft_key(site), json.dumps(both))
    loaded(p)
    assert listed(p) == ["first words", "second words", "third words"]


# d3: two pages that write while the list is still in the store of both.
def test_two_pages_that_move_the_same_list_leave_each_entry_once(tab, site, context):
    tab.open()
    a = tab.page
    set_kept(a, site, [reply("first words"), reply("second words", "2026-10-14T11:01:00.000Z")])
    loaded(a)
    b = context.new_page()
    b.goto(site.url)
    b.wait_for_selector("#rd-menu-btn", state="attached")
    # Page b's view of the list is out of date (another page's write reaches it late): it still sees the list that a moves.
    b.evaluate("""([key, list]) => { const get = Storage.prototype.getItem;
      Storage.prototype.getItem = function (k) { return k === key ? list : get.call(this, k); }; }""",
               [comment_draft_key(site), a.evaluate("(k) => localStorage.getItem(k)", comment_draft_key(site))])
    keep_a_new_message(a, "from page a")
    select(b, at(P1, "apples"), at(P1, "apples", None))
    b.fill(FIELD, "from page b")
    b.keyboard.press("Escape")
    until(lambda: len(kept_entries(a, site)) == 4, what="the four entries")
    assert sorted(d["body"] for d in kept_entries(a, site)) == ["first words", "from page a", "from page b", "second words"]
    assert a.evaluate("localStorage.getItem(%s)" % json.dumps(comment_draft_key(site))) is None


# d3: a store that holds one entry only. The write that replaces an entry is refused at first and made once the entry it
# replaces is gone (every other full-store test refuses every write).
def test_a_store_with_room_for_one_entry_takes_the_entry_that_replaces_it(tab, site):
    tab.open()
    p = tab.page
    p.evaluate("""(key) => { const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function (k, v) {
        if (String(k).startsWith(key + ':e:') && Object.keys(localStorage).filter(x => x.startsWith(key + ':e:')).length >= 1) throw new Error('quota');
        return set.call(this, k, v); }; }""", comment_draft_key(site))
    select(p, at(P2, "pears"), at(P2, "pears", None))
    p.fill(FIELD, "first words")
    p.evaluate("document.querySelector('#rd-popover .rd-form').stash()")
    p.fill(FIELD, "first words, more")
    p.evaluate("document.querySelector('#rd-popover .rd-form').stash()")
    p.wait_for_timeout(400)
    assert [d["body"] for d in kept_entries(p, site)] == ["first words, more"]
    assert "could not be kept" not in p.inner_text("#rd-toast")


# d4 (a limit written in SPEC 10.8): an entry key whose text is not JSON is left where it is.
def test_an_entry_key_that_is_not_json_is_left_alone_and_does_not_stop_the_others(tab, site):
    tab.open()
    p, key = tab.page, comment_draft_key(site)
    put(p, key + ":e:0mwgzsy17-000-0000", "{not json")
    put(p, key + ":e:0mwgzsy17-000-0001", json.dumps(message("kept words")))
    loaded(p)
    assert unsent(p) == "1 message not sent · Show"
    keep_a_new_message(p, "typed after")
    assert p.evaluate("localStorage.getItem(%s)" % json.dumps(key + ":e:0mwgzsy17-000-0000")) == "{not json"


# An earlier build's list is in the order of its writes, and entries written in one millisecond share their `at`: the
# page lists them in the order of the list, not in the order of a hash of their text.
def test_entries_of_an_earlier_builds_list_with_the_same_time_keep_the_order_of_the_list(tab, site):
    tab.open()
    p = tab.page
    words = [f"words number {n}" for n in range(6)]
    set_kept(p, site, [reply(w) for w in words])               # one `at` for all six
    loaded(p)
    assert in_order(p, words) == words
    keep_a_new_message(p, "a write that moves the list into keys")
    until(lambda: p.evaluate("localStorage.getItem(%s)" % json.dumps(comment_draft_key(site))) is None, what="the list to be moved")
    loaded(p)
    assert in_order(p, words) == words


# Ticket 144 (355, round 2, F2/F3): a move of the list that stops half-way (the store has room for one key) while a clear is held (the store refused the read
# when the entry was discarded): the clear is played by the first read that works, and the list is written back without
# the entry it names, with no key of the move left and none of the entries listed twice.
def test_a_held_clear_is_played_when_the_move_of_the_list_stops_half_way(tab, site):
    tab.open()
    p, key = tab.page, comment_draft_key(site)
    entries = [message(t, f"2026-10-14T11:0{i}:00.000Z") for i, t in enumerate(["first words", "second words", "third words"])]
    set_kept(p, site, entries)
    loaded(p)
    p.click(UNSENT)
    p.wait_for_selector(LIST, timeout=3000)
    p.evaluate("""(key) => { const get = Storage.prototype.getItem;
      window.__refuse = true; window.__get = get;
      Storage.prototype.getItem = function (k) { if (window.__refuse && String(k).startsWith(key)) throw new Error('refused'); return get.call(this, k); }; }""", key)
    forms = p.locator(f"{LIST} .rd-form")
    forms.nth([f.locator("textarea").input_value() for f in forms.all()].index("second words")).locator("button[data-f=no]").click()
    # the read is refused: the clear is held, nothing is written
    assert [e["body"] for e in json.loads(p.evaluate("(k) => window.__get.call(localStorage, k)", key))] \
        == ["first words", "second words", "third words"]
    p.evaluate("""(key) => { window.__refuse = false; const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function (k, v) {
        if (String(k).startsWith(key + ':e:')) { if (window.__moved >= 1) throw new Error('quota'); window.__moved = (window.__moved || 0) + 1; }
        return set.call(this, k, v); }; }""", key)
    assert p.locator(UNSENT).count() == 1, "the line was not drawn again: the click below is not the read the test means"
    p.click(UNSENT)                                # a read that works: the held clear is played, and the move stops after one key
    until(lambda: sorted(e["body"] for e in kept_entries(p, site)) == ["first words", "third words"], what="the held clear to be played")
    assert p.evaluate("window.__moved") == 1, "the move did not stop half-way"
    loaded(p)
    assert listed(p) == ["first words", "third words"]
