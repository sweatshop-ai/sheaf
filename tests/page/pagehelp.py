"""What the page tests do with a page: select text the way a person's mouse does, and wait; and what a run says when its browser will not start."""
import contextlib
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

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


def comment_on(tab, start, end, body):
    """Select, press Comment, type and send; returns the comment once it is in the file."""
    from sheafmd import comments as rdc
    select(tab.page, start, end)
    tab.page.click("#rd-comment-btn")
    tab.page.fill("#rd-popover textarea", body)
    tab.page.click("#rd-popover button[data-f=ok]")
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


def toast(page):
    return page.evaluate("document.querySelector('#rd-toast').textContent")


def toasted(page, text, timeout=8.0):
    """Wait for a toast that says `text`. (Not wait_for_function: the page's policy forbids eval.)"""
    until(lambda: text in toast(page), timeout, f"a toast saying {text!r}")


def draft_key(site):
    """The localStorage key of the unsaved edits of the site's document."""
    return f"sheaf-draft:{site.port}:{DOC}"


def comment_draft_key(site):
    """The localStorage key of the new comments, replies and edits the hub has not taken yet."""
    return f"sheaf-comment-draft:{site.port}:{DOC}"


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


def reload_on_clock(page, start=T0, *, pause=False):
    """Put a clock the test drives under the open page, from `start` (ms), and reload it; with
    `pause` the clock stands still 5 s later."""
    page.clock.install(time=start)
    page.reload()
    page.wait_for_selector("#rd-menu-btn", state="attached")
    if pause:
        page.clock.pause_at(start + 5_000)


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


def launch_chromium(chromium, error, in_ci):
    """The browser, or a skip (a machine of a person) or a failure (CI) that says why it did not start."""
    try:
        return chromium.launch()
    except error as e:
        if not in_ci:
            pytest.skip(f"no Chromium for Playwright (run `playwright install chromium`): "
                        f"{str(e).splitlines()[0]}")
        unavailable(f"Chromium did not start:\n{e}\n{died_report(launched_binary(chromium.executable_path))}", in_ci)


def new_context(browser, error=None, **options):
    """A context of the browser (its clicks, fills and waits for a selector give up after PAGE_TIMEOUT_MS),
    or a failure that says whether the browser is still there. `error` is
    Playwright's own (the default); any other exception is a bug of the test and passes through."""
    if error is None:
        from playwright.sync_api import Error as error
    try:
        context = browser.new_context(**options)
        context.set_default_timeout(PAGE_TIMEOUT_MS)
        return context
    except error as e:
        pytest.fail(f"Chromium went away under a new context (connected={browser.is_connected()}):\n{e}")


def close_context(context):
    """Close a context of new_context. A route of its pages still in `route.fetch` would otherwise fail
    there, and Playwright raises that failure in the next call into the browser: another test's new_context."""
    for page in context.pages:
        page.unroute_all(behavior="ignoreErrors")
    context.unroute_all(behavior="ignoreErrors")
    context.close()
