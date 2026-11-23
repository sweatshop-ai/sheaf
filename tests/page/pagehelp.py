"""What the page tests do with a page: select text the way a person's mouse does, and wait; and what a run says when its browser will not start."""
import contextlib
import datetime
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from sheafmd.atomic import write_text_atomic

DOC = "work/plan.md"
P1 = "main p:nth-of-type(2)"
P2 = "main p:nth-of-type(3)"
T0 = 1_800_000_000_000          # a fixed "now" for the page, in ms
PAGE_TIMEOUT_MS = 20_000        # how long a click, a fill or a wait for a selector may take (Playwright's own is 30 s)

# The colours the loader writes on the host from the front's theme (#164), one light set and one dark, as rgb() reads.
HOST = {"light": {"--bg": "rgb(250, 250, 250)", "--fg": "rgb(10, 20, 30)", "--muted": "rgb(90, 90, 100)",
                  "--rule": "rgb(200, 210, 220)", "--accent": "rgb(0, 100, 200)", "color-scheme": "light"},
        "dark": {"--bg": "rgb(20, 22, 24)", "--fg": "rgb(230, 231, 232)", "--muted": "rgb(150, 151, 152)",
                 "--rule": "rgb(50, 51, 52)", "--accent": "rgb(120, 170, 250)", "color-scheme": "dark"}}
# The one-off's red and the toggle's blue of the list and of #rd-actions, light and dark (#169).
RED = {"light": "rgb(198, 40, 40)", "dark": "rgb(255, 107, 107)"}
BLUE = {"light": "rgb(31, 95, 214)", "dark": "rgb(110, 162, 255)"}


def rewrite(path, text):
    """Replace the file at `path` with `text` whole (a temporary sibling, then a rename): a page open on it, and the hub's watcher, never read it
    truncated, as they can after `Path.write_text` (ticket 94). The file takes the umask's default mode, and a missing
    folder above it is created."""
    write_text_atomic(Path(path), text)


def contrast(a, b):
    """WCAG's contrast ratio of two colours read as `rgb(r, g, b)`."""
    def lum(c):
        ch = [int(v) / 255 for v in c[c.index("(") + 1:c.index(")")].split(",")[:3]]
        ch = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def assert_readable(colour, bg):
    """WCAG AA for the 13 px text of the action buttons: 4.5:1."""
    assert contrast(colour, bg) >= 4.5, (colour, bg, contrast(colour, bg))


def wear_host(page, scheme):
    """Set on the host (`#pane`) what the loader sets from the front's theme: HOST's colours and scheme."""
    for name, value in HOST[scheme].items():
        page.evaluate("([n, v]) => document.getElementById('pane').style.setProperty(n, v)", [name, value])


def drop_host(page, scheme):
    for name in HOST[scheme]:
        page.evaluate("(n) => document.getElementById('pane').style.removeProperty(n)", name)


def at(css, text, k=0):
    """A point in the page: `k` characters into the first text node under `css` that holds `text`
    (k = None puts it at the end of that text)."""
    return {"css": css, "text": text, "k": k}


# Puts a range from one `at()` point to another in the page's selection. `select` and `select_by_touch`
# both end it with what the gesture sends.
_RANGE_JS = """
      const find = ({css, text, k}) => {
        const w = document.createTreeWalker(document.querySelector(css), NodeFilter.SHOW_TEXT);
        for (let n; (n = w.nextNode());) {
          const i = n.nodeValue.indexOf(text);
          if (i >= 0) return [n, i + (k === null ? text.length : k)];
        }
        throw new Error('no text ' + text + ' under ' + css);
      };
      const [n1, o1] = find(a), [n2, o2] = find(b);
      const r = document.createRange();
      r.setStart(n1, o1);
      r.setEnd(n2, o2);
      const s = getSelection();
      s.removeAllRanges();
      s.addRange(r);
"""


def select(page, start, end):
    """Select from one point to another and let go of the mouse on the end point's element."""
    page.evaluate("([a, b]) => {" + _RANGE_JS +
                  "n2.parentElement.dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); }", [start, end])


def select_by_touch(page, start, end):
    """Select as a long press and the handles do: the selection changes and the page is told by
    `selectionchange`; no mouse event follows."""
    page.evaluate("([a, b]) => {" + _RANGE_JS + "}", [start, end])


def selected(page):
    return page.evaluate("getSelection().toString()")


def box(page, css, text):
    """Where `text` is on screen (its first occurrence under `css`), for the mouse: x, y, width, height."""
    return page.evaluate("""([css, text]) => {
      const w = document.createTreeWalker(document.querySelector(css), NodeFilter.SHOW_TEXT);
      for (let n; (n = w.nextNode());) {
        const i = n.nodeValue.indexOf(text);
        if (i < 0) continue;
        const r = document.createRange();
        r.setStart(n, i);
        r.setEnd(n, i + text.length);
        const b = r.getBoundingClientRect();
        return {x: b.x, y: b.y, width: b.width, height: b.height};
      }
      throw new Error('no text ' + text + ' under ' + css);
    }""", [css, text])


# How `until` lets 50 ms pass (`_pump(seconds)`). Playwright's sync API hands the test a route, a request or
# any other event only while the test is inside a call into Playwright; `time.sleep` is not one, so a wait
# that sleeps never delivers the event it waits for and times out on a runner where the event comes late.
# The `chromium` fixture of conftest.py puts in a call that pumps; with no browser, a plain sleep does.
_pump = time.sleep


def use_pump(pump):
    """Set how `until` waits (`pump(seconds)`); returns what it was, for the fixture to put back."""
    global _pump
    was, _pump = _pump, pump
    return was


CLOSE_BOUND = 20.0       # seconds that taking the routes off a context, and closing it, may take each
STALL_GRACE = 5.0       # seconds past its deadline that one poll may take before the page counts as stalled


class PageStalled(BaseException):
    """A wait outlasted its bound because the page stopped answering. It is not an `Exception`, so the
    `except Exception` of a helper that treats a page going away as an answer (`gone`) cannot swallow it."""


@contextlib.contextmanager
def stalls_after(seconds, what):
    """Fail with PageStalled ("timed out waiting for `what`") if the block takes longer than `seconds`.
    `Page.evaluate` takes no timeout, so a page that stops answering blocks the test thread for ever (one
    run stood 11 minutes at 1.5% CPU); the alarm interrupts the wait the thread is in. It needs the main
    thread, where pytest runs a test; anywhere else the block runs unbounded, as before. A timer that
    was pending (pytest-timeout's) is put back, less the time the block took."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    import greenlet     # Playwright's dependency, so imported when a wait needs it: a run without Playwright still collects
    test = greenlet.getcurrent()

    def fire(signum, frame):
        # Playwright's sync API runs its event loop on a greenlet of its own, and the test's thread sits in
        # that loop while it waits: an exception raised here would end the loop for good. Throwing it into
        # the test's greenlet fails the wait and leaves the loop parked, to go on at its next call.
        error = PageStalled(f"timed out waiting for {what} (the page did not answer)")
        if greenlet.getcurrent() is test:
            raise error
        test.throw(error)
    left, every = signal.getitimer(signal.ITIMER_REAL)
    if left and left <= seconds:        # the pending timer (pytest-timeout's) ends the test sooner: leave it be
        yield
        return
    was = signal.signal(signal.SIGALRM, fire)
    began = time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, was)
        if left:
            signal.setitimer(signal.ITIMER_REAL, max(left - (time.monotonic() - began), 0.001), every)


def until(check, timeout=8.0, what="the condition"):
    """Poll `check` until it is truthy; its value is returned. The wait delivers Playwright's events.
    Each poll is bounded too: one that outlasts the deadline by STALL_GRACE seconds fails the wait."""
    end = time.monotonic() + timeout
    while True:
        with stalls_after(max(end - time.monotonic(), 0) + STALL_GRACE, what):
            got = check()
        if got:
            return got
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}")
        _pump(0.05)


def open_box(page):
    """After a selection: wait for the box of the new comment, and press the Comment bar only when the box did not open itself.
    A thread's box that stood before the selection has a field too and messages; it is not the box waited for (the mouseup offers the
    new one a task later, and on a slow runner the field of the old box was filled instead)."""
    until(lambda: (page.query_selector("#rd-popover textarea") and not page.query_selector("#rd-popover .rd-msg"))
          or page.query_selector("#rd-comment-btn"), what="the box or the Comment button")
    if not page.query_selector("#rd-popover textarea"):
        page.click("#rd-comment-btn")


def pasted(page):
    """What a real Ctrl+V brings into a plain input of the document: the clipboard as the browser holds it after a
    real Ctrl+C. The input is outside the page's own interface, off screen; it is focused by script, not clicked,
    so nothing of the page's is clicked away."""
    page.evaluate("""() => { let i = document.getElementById('probe-for-paste');
      if (!i) { i = document.createElement('input'); i.id = 'probe-for-paste'; i.style.cssText = 'position:fixed;left:-400px;top:0';
                document.body.appendChild(i); }
      i.value = ''; i.focus(); }""")
    page.keyboard.press("ControlOrMeta+v")
    return page.evaluate("document.getElementById('probe-for-paste').value")


def typed(page):
    """The texts in the popover's fields that are not empty. The reply field is open from the start, so an
    empty field is the rest state; what a test must not find is text put into one."""
    return page.eval_on_selector_all("#rd-popover textarea", "els => els.map(e => e.value).filter(v => v)")


def open_form(page, form):
    """The form of a reply or an edit. A reply field is open from the start; Edit is in the thread's ⋯ menu."""
    if form == "edit":
        page.click("#rd-popover .rd-more summary")
        page.click("#rd-popover button[data-a=edit]")
    page.wait_for_selector("#rd-popover textarea")


def open_with_comment(tab, md, quote, text, author="Ada", when="2026-10-14T10:00"):
    """The page of any tab (phone or laptop), opened on `md` with one comment on `quote` already in the file. The comment
    is written before the page opens: a page open when its file changes reloads itself, which a second `open()` then races (tickets 78, 98).
    `md=None` keeps the file the site fixture wrote."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    if md is not None:
        rewrite(tab.site.file, md)
    update_file(tab.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, quote), quote, text, author, when)[0])
    return tab.open().page


def room_under_box(page):
    """(whether the empty room a moved comment box keeps under itself, `.rd-room`, lies right under it and is 8 px tall, what
    was measured). Ticket 183 BP."""
    got = page.evaluate("""(() => { const b = document.querySelector('#rd-popover'), r = document.querySelector('.rd-room');
        return r && { follows: r.previousSibling === b, top: parseFloat(r.style.top), foot: b.offsetTop + b.offsetHeight,
                      height: parseFloat(r.style.height) }; })()""")
    return bool(got) and got["follows"] and abs(got["top"] - got["foot"]) < 1 and got["height"] == 8, got


def comment_on(tab, start, end, body):
    """Select, type and send; returns the comment once it is in the file. A mouse selection opens the box by
    itself; a touch screen offers the Comment bar first."""
    from sheafmd import comments as rdc
    select(tab.page, start, end)
    open_box(tab.page)
    tab.page.fill("#rd-popover textarea", body)
    tab.page.click("#rd-popover button[data-f=ok], #rd-popover button[data-f=tell]")
    return until(lambda: (rdc.parse(tab.site.file.read_text()).comments or [None])[0],
                 what="the comment in the file")


def mark(page):
    """Tag this load of the page; the tag is gone once the page has reloaded."""
    page.evaluate("window.__same_load = true")


def gone(page):
    """The load that `mark` tagged has gone: the page reloaded, or is reloading."""
    try:
        return page.evaluate("window.__same_load !== true")
    except Exception:       # the page's context went away: it is reloading (a PageStalled is not an Exception)
        return True


def reloaded(page, timeout=8.0):
    until(lambda: gone(page), timeout, "the page to reload")


# What Playwright says when an evaluate falls on a page that is reloading: the new page has no #rd-toast yet, or
# the poll landed on the navigation itself (ticket 53). Any other error stays an error.
RELOADING = ("Cannot read properties of null (reading 'textContent')", "Execution context was destroyed")


def opened(context, site):
    """A new tab of `context` on the site's document, loaded, with the list its page errors go to."""
    p = context.new_page()
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(site.url)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    return p, errors


def shows(p, text):
    """Whether the page shows `text`. A change from outside reloads the page, so a read can fall on the reload:
    that is not yet."""
    try:
        return text in p.evaluate("document.body.textContent")
    except Exception as e:
        if any(said in str(e) for said in RELOADING):
            return False
        raise


def toast(page):
    """The text of the toast; "" while the page reloads and has none yet."""
    try:
        return page.evaluate("document.querySelector('#rd-toast').textContent")
    except Exception as e:      # a PageStalled is not an Exception, so a driver that stopped answering still fails
        if any(said in str(e) for said in RELOADING):
            return ""
        raise


def toast_state(page):
    """(text, up): the text of the toast, and whether one is on the screen. Toasts queue (ticket 62): when one ends the
    next is shown in the same task, so `up` is False only when none is waiting. ("", None) while the page reloads: the
    page that comes may say a toast of its own, so it is not "none waiting"."""
    try:
        return tuple(page.evaluate("(t => t ? [t.textContent, t.classList.contains('show')] : ['', false])"
                                   "(document.querySelector('#rd-toast'))"))
    except Exception as e:      # a PageStalled is not an Exception, so a driver that stopped answering still fails
        if any(said in str(e) for said in RELOADING):
            return "", None
        raise


def run_clock(page, ms):
    """Run the page's clock `ms` on; nothing to run while the page reloads."""
    try:
        page.clock.run_for(ms)
    except Exception as e:
        if not any(said in str(e) for said in RELOADING):
            raise


# ms of the page's clock per look: shorter than any toast (2.6 s), so none goes by unseen. Measured on the organisation's runners (2026-11-14,
# test_page_actions.py, the three tests that queue behind a red toast, twice): 7.5 s at 250 ms, 7.0 s at 1000 and 2000. No gain, so not larger.
TOAST_STEP = 250


def toasted(page, text, timeout=8.0, *, on_clock=False):
    """Wait for a toast that says `text`. (Not wait_for_function: the page's policy forbids eval.)
    A toast waits behind the one on the screen (2.6 s, 7 s red). On a clock the test drives (`on_clock`) the clock is run on
    while another toast is up, so `text` comes when its turn does, however the runner is loaded; on the real clock
    only a longer `timeout` waits for it."""
    went_by = []

    def look():
        said, up = toast_state(page)
        if said and said not in went_by:
            went_by.append(said)
        if text in said:
            return True
        if on_clock and up:
            run_clock(page, TOAST_STEP)
        return False
    try:
        until(look, timeout, f"a toast saying {text!r}")
    except AssertionError as e:
        raise AssertionError(f"{e}; the toasts that went by: {went_by}") from None


def toasts_to_the_end(page, timeout=8.0, *, on_clock=False):
    """The texts the toasts say from now until the last one has gone: the one on the screen, and every one queued behind it,
    in order. An assertion that a toast is NOT said reads this, not `toast()`: a toast still in the queue is not on the
    screen yet. On a clock the test drives (`on_clock`) the clock is run on until the queue is empty. (A toast that
    follows another with the same text is one entry, and a toast said later than the queue's end is not here.)"""
    seen = []

    def look():
        said, up = toast_state(page)
        if up and said and (not seen or seen[-1] != said):       # the text stays in #rd-toast after the toast has gone
            seen.append(said)
        if up and on_clock:
            run_clock(page, TOAST_STEP)
        return up is False          # None: the page reloads, and the one that comes may say more
    until(look, timeout, "the toasts to end")
    return seen


def draft_key(site):
    """The localStorage key of the unsaved edits of the site's document."""
    return f"sheaf-draft:{site.port}:{DOC}"


def comment_draft_key(site):
    """The localStorage key of the new comments, replies and edits the hub has not taken yet."""
    return f"sheaf-comment-draft:{site.port}:{DOC}"


def kept_json(page, site):
    """What the comment store holds, as the one JSON list the page used to keep under the key (None when it holds
    nothing): its entries are one key each, `<key>:e:<id>`, and an older list under the key itself counts too."""
    return page.evaluate("""(key) => {
      const got = Object.keys(localStorage).filter(k => k.startsWith(key + ':e:')).sort()
        .map(k => JSON.parse(localStorage.getItem(k)));
      const old = localStorage.getItem(key);
      return got.length || old ? JSON.stringify(got.concat(old ? JSON.parse(old) : [])) : null;
    }""", comment_draft_key(site))


def kept_entries(page, site):
    """The entries of the comment store, in the order of the store: the entry keys by id, then those of an earlier build's
    list. (The page lists the list's entries first; no test reads this order for a store that holds both.)"""
    return json.loads(kept_json(page, site) or "[]")


def set_kept(page, site, entries):
    """Put exactly `entries` in the comment store, as a list under the key (an earlier build's, which the page moves into
    entry keys at its next write and reads as it is until then)."""
    page.evaluate("""([key, v]) => {
      Object.keys(localStorage).filter(k => k.startsWith(key + ':e:')).forEach(k => localStorage.removeItem(k));
      localStorage.setItem(key, v);
    }""", [comment_draft_key(site), json.dumps(entries)])


# What Playwright's Chromium does on macOS with these keys is what macOS does (its macEditingCommands): End and
# Home scroll the document, Control+End moves nothing, Control+v is page down. These are the keys a person there
# presses for the move the test means.
MAC_KEYS = {"End": "Meta+ArrowRight", "Home": "Meta+ArrowLeft", "Shift+End": "Shift+Meta+ArrowRight",
            "Control+End": "Meta+ArrowDown", "Control+Home": "Meta+ArrowUp", "Control+v": "Meta+v"}


def key(combo, platform=sys.platform):
    """The keys to press for `combo`, written as on Linux, on the system the browser runs on."""
    return MAC_KEYS.get(combo, combo) if platform == "darwin" else combo


def type_at_end(page, css, text):
    """Press e, click the paragraph `css`, go to its end and type `text`."""
    page.keyboard.press("e")
    page.click(css)
    page.keyboard.press(key("End"))
    page.keyboard.type(text)


def clock_at(ms):
    """A point for page.clock from epoch milliseconds. Not the bare number: Playwright for Python reads a number as
    seconds, so T0 (ms) put the page's Date.now() in the year 57000, and the ids the page makes from it were longer than
    any real one (ticket 130)."""
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)


def stand_still(page):
    """The installed clock runs at the real pace: from now on it moves only when the test runs it. Called before a
    press, so the half second it jumps is not the Undo's. A page that read the clock past that time meanwhile makes
    `pause_at` refuse ("fast-forward to the past"): the time is read again."""
    for _ in range(5):
        try:
            page.clock.pause_at((page.evaluate("Date.now()") + 500) / 1000)       # seconds, in Playwright's Python
            return
        except Exception as e:
            if "past" not in str(e):
                raise
    raise AssertionError("the page clock would not pause")


def reload_on_clock(page, start=T0, *, pause=False):
    """Put a clock the test drives under the open page, from `start` (ms), and reload it; with
    `pause` the clock stands still 5 s later."""
    page.clock.install(time=clock_at(start))
    page.reload()
    page.wait_for_selector("#rd-menu-btn", state="attached")
    if pause:
        page.clock.pause_at(clock_at(start + 5_000))


# ── a browser that will not start ────────────────────────────────────────────────────────────────────────
# A person's machine without Chromium skips the page tests with the reason; a CI run must fail, because a
# Page step that skipped everything has tested nothing. A Chromium has closed with no word on the runner,
# so the failure carries all that can be known.

def unavailable(reason, in_ci):
    (pytest.fail if in_ci else pytest.skip)(reason)


HANG_AFTER = 30      # seconds a second run of the browser may take before the report calls it hung


def _tail(stderr):
    return "\n".join((stderr or b"").decode("utf-8", "replace").strip().splitlines()[-15:])


def how_it_ended(code):
    """A subprocess return code, said as a person reads it."""
    if code >= 0:
        return f"exit code {code}"
    try:
        return f"killed by signal {-code} ({signal.Signals(-code).name})"
    except ValueError:
        return f"killed by signal {-code}"


def died_report(exe):
    """Run the browser binary once, headless, and say how it ended: its exit code or the signal that
    killed it, and the last lines it wrote. Playwright's own error says only that the browser closed."""
    try:
        done = subprocess.run([exe, "--headless", "--no-sandbox", "--disable-gpu", "--dump-dom", "about:blank"],
                              capture_output=True, timeout=HANG_AFTER)
    except subprocess.TimeoutExpired as e:
        return (f"a second run of {exe} was still going after {HANG_AFTER} s and was killed; "
                f"its stderr ends:\n{_tail(e.stderr)}")
    except OSError as e:
        return f"the binary {exe} cannot be run for a report: {e!r}"
    return f"a second run of {exe} ended with {how_it_ended(done.returncode)}; its stderr ends:\n{_tail(done.stderr)}"


def launched_binary(exe):
    """What `launch()` runs: Playwright's headless shell of the same revision as the Chromium that
    `executable_path` names (on Linux `<cache>/chromium-1208/chrome-linux64/chrome`, in an app bundle on macOS)."""
    for d in Path(exe).parents:
        if d.name.startswith("chromium-"):
            where = d.parent / f"chromium_headless_shell-{d.name.split('-', 1)[1]}"
            shells = sorted([*where.glob("*/chrome-headless-shell"), *where.glob("*/headless_shell")])    # Linux ARM: the latter
            return str(shells[-1]) if shells else exe
    return exe


def launch_chromium(chromium, error, in_ci, **options):
    """The browser, or a skip (a machine of a person) or a failure (CI) that says why it did not start. `options` go to
    `launch()` (the DevTools port of stall_evidence)."""
    try:
        return chromium.launch(**options)
    except error as e:
        if not in_ci:
            pytest.skip(f"no Chromium for Playwright (run `playwright install chromium`): "
                        f"{str(e).splitlines()[0]}")
        unavailable(f"Chromium did not start:\n{e}\n{died_report(launched_binary(chromium.executable_path))}", in_ci)


def launch_engine(browser_type, name, error=None, in_ci=None, **options):
    """A browser a test launches for itself (`pw.<engine>.launch()`): the browser, a skip off CI when the engine is not
    here, or a failure on CI that carries the whole error (Playwright puts the browser's log after the first line)
    and, for Chromium, how a second run of the binary ends. A skip on CI only turns the job red with one line
    (ticket 138: four runs, 12-15 November). `options` go to `launch()`: `channel="chromium"` is the full Chromium.
    """
    if error is None:
        from playwright.sync_api import Error as error
    if in_ci is None:
        in_ci = os.environ.get("CI", "").lower() in ("1", "true")
    try:
        return browser_type.launch(**options)
    except error as e:
        if not in_ci:
            pytest.skip(f"{name} cannot start here: {str(e).splitlines()[0]}")
        report = died_report(launched_binary(browser_type.executable_path)) if name == "chromium" else ""
        pytest.fail(f"{name} did not start:\n{e}\n{report}".rstrip())


# The page's side of the stream journal (conftest.py `stream_journal`): it wraps EventSource and notes, in real
# time (taken before a test's fake clock replaces the page's), each open, error and event into window.__sseJournal.
STREAM_JOURNAL_JS = """(() => {
  const now = performance.now.bind(performance), origin = performance.timeOrigin;
  // Kept in sessionStorage: a reload of the page, which is what a lost event or a lost toast often is, would
  // otherwise take the journal of the page that heard it (ticket 137).
  const setItem = Storage.prototype.setItem;      // the native one: a test that watches the page's own setItem does not see the journal's
  let log = [];
  try { log = JSON.parse(sessionStorage.getItem('__sseJournal') || '[]'); } catch (e) {}
  window.__sseJournal = log;
  const note = (what, data) => {
    log.push([origin + now(), what, data === undefined ? '' : String(data).slice(0, 120)]);
    try { setItem.call(sessionStorage, '__sseJournal', JSON.stringify(log.slice(-400))); } catch (e) {}
  };
  note('document', 'starts');
  window.addEventListener('pagehide', () => note('pagehide'));
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (url, init) => {
    const what = String(url) + ' ' + ((init && init.method) || 'GET');
    note('fetch', what);
    return nativeFetch(url, init).then(r => { note('fetched', what + ' ' + r.status); return r; },
                                       e => { note('fetch failed', what + ' ' + e); throw e; });
  };
  const Native = window.EventSource;
  if (!Native) return;
  // A subclass, not a function that returns a native one: a test's own script may `class extends window.EventSource`.
  window.EventSource = class extends Native {
    constructor(url, init) {
      super(url, init);
      note('new', url);
      super.addEventListener('open', () => note('open', url));
      super.addEventListener('error', () => note('error', 'readyState ' + this.readyState));
    }
    addEventListener(name, fn, o) {
      if (name !== 'open' && name !== 'error') super.addEventListener(name, ev => note('event ' + name, ev.data), o);
      return super.addEventListener(name, fn, o);
    }
  };
})()"""


# The page's side of the guard of close_context: a document that has begun to leave (a reload, a goto) says so in
# `__leaving`. A navigation that has not committed leaves the old document in place, so the flag is readable until the
# new one comes; the new document starts without it.
# A page that asks before it is left cancels the navigation (a handler's preventDefault): once every handler has run, such a leave is no longer pending.
# Only a trusted event counts (a test's own dispatchEvent leaves nothing), and the reset runs on the timer the page had
# at the start: a test's `page.clock` replaces the page's setTimeout with one that stands still.
LEAVING_JS = """(() => {
  const later = window.setTimeout.bind(window);
  window.addEventListener('beforeunload', e => {
    if (!e.isTrusted) return;
    window.__leaving = true;
    later(() => { if (e.defaultPrevented || e.returnValue) window.__leaving = false; }, 0);
  });
})()"""


def leaving(page):
    """Whether the page is leaving for a navigation that has not committed (or its document went away while we asked).
    `Page.evaluate` takes no timeout: a page that stops answering is a PageStalled, not a wait for ever."""
    try:
        with stalls_after(CLOSE_BOUND, "the page to say whether it is leaving"):
            return page.evaluate("window.__leaving === true")
    except Exception as e:      # a PageStalled is not an Exception
        return any(said in str(e) for said in RELOADING)


def pending_navigations(context):
    """The URLs of the pages of the context that are leaving (see `leaving`)."""
    return [page.url for page in context.pages if leaving(page)]


def landed_page(page, timeout=8.0):
    """A reload that has begun is waited for, and the document it brings until it has loaded (any page: it need not be
    a sheaf page, so no selector of ours is waited for)."""
    until(lambda: not leaving(page), timeout, "a reload in flight to land")
    page.wait_for_load_state("load")


def settled(page, timeout=8.0):
    """End of a test whose last step may leave a reload of the page in flight (a save the hub answered, a file it
    wrote): a reload that has begun is waited for, and the page it brings, until its menu is there. close_context fails
    a test whose navigation does not land."""
    landed_page(page, timeout)
    page.wait_for_selector("#rd-menu-btn", state="attached")


def landed(page, timeout=8.0):
    """A reload that has begun is waited for, and the page it brings until its menu is there; nothing to wait for when
    the page is not leaving. The teardown of a tab: a test that ends on a reload in flight is not told apart from one
    that does not by its last line, and closing the context under the reload hangs the driver (flake e2)."""
    if leaving(page):
        settled(page, timeout)


# The page's stream as each tab held it before ticket 160: an EventSource of its own. The tests that watch the stream
# wrap window.EventSource, which the browser's one shared stream (page/live.js) would take out of their tab; only
# test_page_shared_live.py runs the shared one (new_context's `shared`).
PLAIN_LIVE_JS = """window.SheafLive = {shared: false, source: d =>
  new EventSource(d ? '/_/live?doc=' + encodeURIComponent(d) : '/_/live')};"""


def new_context(browser, error=None, shared=False, **options):
    """A context of the browser (its clicks, fills and waits for a selector give up after PAGE_TIMEOUT_MS),
    or a failure that says whether the browser is still there. `error` is
    Playwright's own (the default); any other exception is a bug of the test and passes through. `shared`: the
    tabs share one stream, as in a browser (page/live.js); otherwise each holds its own."""
    if error is None:
        from playwright.sync_api import Error as error
    try:
        context = browser.new_context(**options)
        context.set_default_timeout(PAGE_TIMEOUT_MS)
        context.add_init_script(STREAM_JOURNAL_JS)
        context.add_init_script(LEAVING_JS)
        if not shared:
            context.add_init_script(PLAIN_LIVE_JS)
        return context
    except error as e:
        pytest.fail(f"Chromium went away under a new context (connected={browser.is_connected()}):\n{e}")


# Every route the test's handlers were given this test, with its context: (context, route). The route wrapper of
# conftest.py's `hub_journal` adds to it.
_ROUTED = []


def note_route(context, route):
    _ROUTED.append((context, route))


def settle_routes(context=None):
    """Hand on every route of `context` (of every context: None) that a handler of the test kept and never answered.
    Playwright's task for such a route waits for the answer for ever. Once nothing holds it, the garbage collector
    ends it wherever the test then is: outside the event loop, where the task's `finally` fails ("Exception ignored
    in: <coroutine object Page._on_route>", a PytestUnraisableExceptionWarning on a later test), or as "Task was
    destroyed but it is pending!". `fallback` answers the route on this side alone, so the task ends in the loop;
    what it then sends to a page that is gone, or whose routes are off, Playwright drops. An abort would not do:
    once the routes are off, the driver takes the route as handled and refuses it, and the task still waits."""
    mine = [(c, route) for c, route in _ROUTED if context is None or c is context]
    _ROUTED[:] = [(c, route) for c, route in _ROUTED if not (context is None or c is context)]
    for c, route in mine:   # taken off the list first: an error here is this test's, not every later test's
        try:
            route.fallback()
        except Exception as e:  # the test answered it: the one error fallback() raises (Playwright 1.58)
            if "Route is already handled!" not in str(e):
                raise


def close_context(context):
    """Close a context of new_context. A route of its pages still in `route.fetch` would otherwise fail
    there, and Playwright raises that failure in the next call into the browser: another test's new_context.
    A page that is still navigating when the test ends (a reload that begins in the teardown of the test's other
    fixtures) is waited for first, with the page it brings: closing the context under it hung the driver (flake e2,
    4 of 85 CI runs). A navigation that does not land fails the test, after the context is closed."""
    stuck = []
    raising = False
    try:
        for page in context.pages:
            if leaving(page):
                try:
                    landed_page(page)
                except Exception:       # the wait ran out; a PageStalled is not an Exception and passes
                    stuck.append(page.url)
    except BaseException:
        raising = True
        raise
    finally:        # a page that stopped answering (PageStalled) still has its context closed
        try:
            _close_context(context)
        except PageStalled:
            if not stuck and not raising:       # a close that hangs fails the test; one already failing keeps its own failure
                raise
    if stuck:
        pytest.fail(f"the test ended with a navigation that did not land on {stuck}: wait for the page to load "
                    f"(reloaded(page), then a selector of the new page) before the test ends")


def _close_context(context):
    try:
        with stalls_after(CLOSE_BOUND, "the routes to come off"):
            for page in context.pages:
                page.unroute_all(behavior="ignoreErrors")
            context.unroute_all(behavior="ignoreErrors")
    except PageStalled:     # a handler that does not end (CI, PR 227: 360 s): closing the context ends it
        pass
    settle_routes(context)  # also after a stall: fallback() asks nothing of the driver
    with stalls_after(CLOSE_BOUND, "the context to close"):
        context.close()
