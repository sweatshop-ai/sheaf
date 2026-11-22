"""The microphone button of the chat box (ticket 06, SPEC 10.4): shown only when the hub says it can transcribe, records with
MediaRecorder, sends the sound to the hub's POST /_/transcribe, and puts the text in the field, where it stays editable.

No real microphone and no real speech-to-text server: an init script replaces getUserMedia and MediaRecorder, and the hub's two routes
are answered by the browser context (`route`), so these tests check the page's wiring (bytes, headers, the field), not
decoding."""
import json

import pytest

from pagehelp import P1, at, comment_on, open_with_comment, until
from sheafmd import comments as rdc
from sheafmd.source import update_file

pytestmark = pytest.mark.page

FIELD = "#rd-popover textarea"
MIC = "#rd-popover .rd-mic"
SAYS = "#rd-popover .rd-mic-says"

# A microphone that records four bytes of "RIFF" in the type it was asked for, and counts what the page does with it.
FAKE_MIC = """(() => {
  const mic = window.__mic = { stops: 0, asked: 0, denied: false, types: ['audio/webm;codecs=opus', 'audio/webm'], made: [], inputs: 0, held: [] };
  mic.answer = (i = 0) => mic.held[i].ok();                                               // the person allows the i-th held request
  mic.refuse = (i = 0) => mic.held[i].no(new DOMException('no', 'NotAllowedError'));      // ... or refuses it
  navigator.mediaDevices.getUserMedia = async (c) => {
    mic.asked++; mic.constraints = c;
    if (mic.denied) throw new DOMException('no', 'NotAllowedError');
    if (mic.hold) {   // the browser's prompt, still open: `hold` is true for the next request, or a number of them
      mic.hold = mic.hold === true || mic.hold === 1 ? false : mic.hold - 1;
      await new Promise((ok, no) => { mic.held.push({ ok, no }); });
    }
    const track = { stop() { mic.stops++; } };
    return { getTracks: () => [track] };
  };
  window.MediaRecorder = class extends EventTarget {
    static isTypeSupported(t) { return mic.types.includes(t); }
    constructor(stream, o) { super(); this.mimeType = (o && o.mimeType) || ''; this.state = 'inactive'; mic.made.push(this); }
    start() { if (mic.failStart) throw new DOMException('no', 'NotSupportedError'); this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      const e = new Event('dataavailable'); e.data = new Blob([new Uint8Array([82, 73, 70, 70])], { type: this.mimeType });
      const events = () => { this.dispatchEvent(e); this.dispatchEvent(new Event('stop')); };
      if (mic.lateStop) this.flush = events; else events();   // a real recorder's events come later: `lateStop` holds them for flush()
    }
  };
})();"""


class Hub:
    """What the browser context answers for the hub's /_/transcribe, and the POSTs it saw."""

    def __init__(self, context, available=True, text="hello there", post=200):
        self.available, self.text, self.post, self.posts, self.gets = available, text, post, [], 0
        context.route("**/_/transcribe", self.answer)

    def answer(self, route):
        r = route.request
        if r.method == "GET":
            self.gets += 1
            if self.available is None:
                return route.fulfill(status=403, content_type="application/json", body='{"error":"forbidden"}')
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"available": self.available}))
        self.posts.append({"headers": r.headers, "body": r.post_data_buffer})
        body = {"text": self.text} if self.post == 200 else {"error": "unavailable"}
        route.fulfill(status=self.post, content_type="application/json", body=json.dumps(body))


@pytest.fixture
def hub(context):
    context.add_init_script(FAKE_MIC)
    return Hub(context)


def open_thread(tab, site):
    open_with_comment(tab, None, "apples", "Why?", "Bea")
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def own_thread(tab):
    """A thread the viewer wrote through the page, so that its menu has Edit; its reply box open."""
    tab.open()
    comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def dictate(p, hub, posts=1):
    """Click the microphone, click again, and wait for the answer to be in."""
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.click(MIC)
    until(lambda: len(hub.posts) >= posts, what="the sound sent to the hub")


def test_the_button_is_in_the_box_when_the_hub_can_transcribe(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    assert p.locator(MIC).get_attribute("title") == "Dictate"
    assert p.locator(MIC).get_attribute("aria-pressed") == "false"
    assert p.locator("#rd-popover .rd-send").count() == 1, "the microphone does not replace the arrow"
    assert p.evaluate("window.__mic.asked") == 0, "the microphone is asked for at the click, not at the load"


@pytest.mark.parametrize("available", [False, None])
def test_no_button_when_the_hub_cannot_transcribe_or_refuses_to_say(tab, site, context, available):
    context.add_init_script(FAKE_MIC)
    Hub(context, available=available)
    p = open_thread(tab, site)
    p.wait_for_function("() => document.querySelector('#rd-popover .rd-send') !== null")
    p.wait_for_timeout(300)
    assert p.locator(MIC).count() == 0, "a dead button"


def test_no_button_when_the_browser_cannot_record(tab, site, context):
    context.add_init_script("delete window.MediaRecorder;")
    Hub(context)
    p = open_thread(tab, site)
    p.wait_for_timeout(300)
    assert p.locator(MIC).count() == 0


def test_a_dictation_puts_the_text_in_the_field_and_sends_nothing_to_the_agent(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.fill(FIELD, "Is it ready?")
    p.evaluate("document.querySelector('#rd-popover textarea').addEventListener('input', () => window.__mic.inputs++)")
    before = site.file.read_text(encoding="utf-8")
    dictate(p, hub)
    until(lambda: p.input_value(FIELD) == "Is it ready? hello there", what="the text in the field")
    post = hub.posts[0]
    assert post["headers"]["x-filename"] == "dictee.webm"
    assert post["headers"]["content-type"] == "audio/webm"
    assert post["body"] == b"RIFF"
    assert p.evaluate("window.__mic.inputs") == 1, "the draft does not follow a dictated text as it follows a typed one"
    assert p.evaluate("window.__mic.stops") == 1, "the microphone is not released"
    assert p.locator(MIC).get_attribute("aria-pressed") == "false"
    p.keyboard.type(" Yes.")                       # still editable
    assert p.input_value(FIELD) == "Is it ready? hello there Yes."
    assert site.file.read_text(encoding="utf-8") == before, "the dictated text was sent"


def test_the_text_goes_at_the_cursor(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.fill(FIELD, "ab cd")
    p.evaluate("document.querySelector('#rd-popover textarea').setSelectionRange(2, 2)")
    dictate(p, hub)
    until(lambda: p.input_value(FIELD) == "ab hello there cd", what="the text at the cursor")


def test_a_refused_microphone_says_so_and_leaves_the_text(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.fill(FIELD, "keep me")
    p.evaluate("window.__mic.denied = true")
    p.click(MIC)
    p.wait_for_selector(SAYS)
    assert "Microphone blocked" in p.inner_text(SAYS)
    assert p.input_value(FIELD) == "keep me"
    assert hub.posts == []
    assert p.locator(MIC).count() == 1, "a refusal of the browser is not the service going away"


def test_escape_during_a_recording_throws_the_sound_away(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.keyboard.press("Escape")
    p.wait_for_function("() => window.__mic.stops === 1")
    p.wait_for_timeout(300)
    assert hub.posts == [], "the sound of a closed box was sent"
    assert p.evaluate("window.__mic.made[0].state") == "inactive"


def test_sending_the_text_during_a_recording_throws_the_sound_away(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.fill(FIELD, "Typed while recording.")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.focus(FIELD)
    p.keyboard.press("Enter")
    p.wait_for_function("() => window.__mic.stops === 1")
    until(lambda: "Typed while recording." in site.file.read_text(encoding="utf-8"), what="the reply in the file")
    p.wait_for_timeout(300)
    assert hub.posts == [], "the sound of a form that went was sent"


def test_the_service_going_away_removes_the_button_and_says_so(tab, site, context):
    context.add_init_script(FAKE_MIC)
    h = Hub(context, post=503)
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    dictate(p, h)
    p.wait_for_selector(SAYS)
    assert "did not work" in p.inner_text(SAYS)
    p.wait_for_function("() => document.querySelector('#rd-popover .rd-mic') === null")
    assert p.evaluate("Object.keys(sessionStorage).filter(k => k.includes('rd-dict-off'))") == [], "a hub page kept the hold"


def test_a_recording_is_dropped_when_the_service_is_lost_during_it(tab, site, hub):
    tab.page.clock.install()
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    hub.available = False
    p.clock.run_for(15000)
    p.wait_for_function("() => window.__mic.stops === 1")
    p.wait_for_function("() => document.querySelector('#rd-popover .rd-mic') === null")
    assert "did not work" in p.inner_text(SAYS)
    p.wait_for_timeout(300)
    assert hub.posts == [], "a recording of a lost service was sent"
    assert p.evaluate("window.__mic.made[0].state") == "inactive"


def test_a_recording_goes_on_while_the_service_is_still_there(tab, site, hub):
    tab.page.clock.install()
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.clock.run_for(35000)
    assert p.evaluate("window.__mic.made[0].state") == "recording"
    assert p.locator(MIC).count() == 1


def test_a_late_answer_is_dropped_when_the_box_is_gone(tab, site, context):
    context.add_init_script(FAKE_MIC)
    h = Hub(context)
    gate = {}
    real = h.answer

    def slow(route):
        if route.request.method == "POST":
            gate["route"] = route                  # held until the test lets it go
            return
        real(route)
    context.unroute("**/_/transcribe")
    context.route("**/_/transcribe", slow)
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.click(MIC)
    until(lambda: "route" in gate, what="the sound on its way")
    assert p.locator(MIC).get_attribute("aria-label") == "Transcribing…", "a screen reader hears Dictate while it transcribes"
    p.evaluate("window.__old = document.querySelector('#rd-popover textarea'); window.__old.closest('.rd-form').remove()")
    gate["route"].fulfill(status=200, content_type="application/json", body='{"text":"late"}')
    p.wait_for_timeout(300)
    assert p.evaluate("window.__old.value") == "", "a late answer wrote into a field that is gone"
    assert p.evaluate("document.activeElement === window.__old") is False, "a late answer took the focus back"
    assert p.evaluate("document.body.innerText.includes('late')") is False


def test_a_send_while_the_sound_is_on_its_way_that_fails_gives_the_form_back_with_a_working_microphone(tab, site, context):
    context.add_init_script(FAKE_MIC)
    h = Hub(context)
    gate, sent = {}, []
    real = h.answer

    def slow(route):
        if route.request.method == "POST":
            gate["route"] = route                  # held: the sound stays on its way
            return
        real(route)
    context.unroute("**/_/transcribe")
    context.route("**/_/transcribe", slow)
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.fill(FIELD, "Typed while transcribing.")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.click(MIC)
    until(lambda: "route" in gate, what="the sound on its way")
    p.route("**/_/comment", lambda route: sent.append(route))
    p.focus(FIELD)
    p.keyboard.press("Control+Enter")
    until(lambda: sent or p.wait_for_timeout(20), what="the send to go out")
    sent[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.wait_for_selector(FIELD)
    until(lambda: p.input_value(FIELD) == "Typed while transcribing.", what="the form back with its text")
    assert p.locator(MIC).is_enabled(), "the microphone of the form that came back is dead"
    assert p.locator(MIC).get_attribute("aria-label") == "Dictate", "a screen reader hears Transcribing of a form that is idle"
    assert p.locator(MIC).get_attribute("aria-pressed") == "false"


def test_another_form_replacing_the_one_that_records_throws_the_sound_away(tab, site, hub):
    p = own_thread(tab)
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.click("#rd-popover .rd-more summary")
    p.click("#rd-popover button[data-a=edit]")             # the edit form takes the place of the reply form
    until(lambda: p.evaluate("window.__mic.stops") == 1, what="the microphone of the replaced form let go")
    assert p.evaluate("window.__mic.made[0].state") == "inactive", "the form went and its microphone went on"
    p.wait_for_timeout(300)
    assert hub.posts == [], "the sound of a form that was replaced was sent"
    p.wait_for_selector(MIC)
    p.click(MIC)                                           # and the new form's microphone works
    p.wait_for_function("() => window.__mic.made.length === 2 && window.__mic.made[1].state === 'recording'")


def test_a_recorder_that_cannot_start_lets_the_microphone_go_and_the_next_press_work(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.evaluate("window.__mic.failStart = true")
    p.click(MIC)
    p.wait_for_selector(SAYS)
    assert "could not start" in p.inner_text(SAYS)
    p.wait_for_function("() => window.__mic.stops === 1")        # the stream it got was let go
    p.evaluate("window.__mic.failStart = false")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 2 && window.__mic.made[1].state === 'recording'")


def test_closing_the_box_while_the_sound_is_on_its_way_cancels_the_request_and_frees_the_microphone(tab, site, context):
    context.add_init_script(FAKE_MIC)
    h = Hub(context)
    gate = {}
    real = h.answer

    def slow(route):
        if route.request.method == "POST":
            gate["route"] = route                  # the hub took the sound and never answers
            return
        real(route)
    context.unroute("**/_/transcribe")
    context.route("**/_/transcribe", slow)
    p = open_thread(tab, site)
    failed = []
    p.on("requestfailed", lambda r: failed.append(r.url))
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.click(MIC)
    until(lambda: "route" in gate, what="the sound on its way")
    p.keyboard.press("Escape")
    until(lambda: any(u.endswith("/_/transcribe") for u in failed), what="the request cancelled")
    p.click(".rd-badge")                                   # the box again: its microphone is free
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 2 && window.__mic.made[1].state === 'recording'")


def test_closing_the_box_while_the_browser_asks_for_the_microphone_leaves_the_next_box_its_microphone(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.evaluate("window.__mic.hold = true")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.asked === 1")        # the prompt is open: no stream yet
    p.keyboard.press("Escape")
    p.click(".rd-badge")                                   # the box again, the prompt still open
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.asked === 2")        # its microphone asks too, it is not stuck behind the first
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.evaluate("window.__mic.answer()")                    # the person answers the first prompt late
    p.wait_for_function("() => window.__mic.stops === 1")        # its stream is let go
    assert p.evaluate("window.__mic.made.length") == 1, "the late stream was recorded"
    assert p.evaluate("window.__mic.made[0].state") == "recording", "the late stream stopped the new recording"


@pytest.mark.parametrize("first", [0, 1])
def test_two_prompts_held_open_are_answered_in_either_order_and_only_the_new_box_records(tab, site, hub, first):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.evaluate("window.__mic.hold = 2")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.asked === 1")
    p.keyboard.press("Escape")
    p.click(".rd-badge")
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.asked === 2")
    p.evaluate(f"window.__mic.answer({first})")
    p.evaluate(f"window.__mic.answer({1 - first})")
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.stops === 1")   # the old prompt's stream is let go, the new one's kept
    p.wait_for_timeout(300)
    assert p.evaluate("window.__mic.made.length") == 1
    assert p.evaluate("window.__mic.made[0].state") == "recording"
    assert p.evaluate("window.__mic.stops") == 1


def test_a_prompt_refused_after_its_box_was_closed_says_nothing_and_leaves_the_new_recording_alone(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.evaluate("window.__mic.hold = true")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.asked === 1")
    p.evaluate("window.__oldBox = document.querySelector('#rd-popover textarea').parentElement")   # the box that will be closed
    p.keyboard.press("Escape")
    p.click(".rd-badge")
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.evaluate("window.__mic.refuse()")                    # the person refuses the first prompt late
    p.wait_for_timeout(300)
    assert p.evaluate("window.__oldBox.querySelector('.rd-mic-says') === null"), "a refusal nobody waits for was written into the closed box"
    assert p.locator(SAYS).count() == 0 or p.locator(SAYS).inner_text() == "", "a refusal nobody waits for was shown"
    assert p.evaluate("window.__mic.made[0].state") == "recording", "the late refusal stopped the new recording"
    assert p.locator(MIC).get_attribute("aria-pressed") == "true"


def test_the_stop_event_of_a_discarded_recorder_that_comes_late_leaves_the_new_recording_alone(tab, site, hub):
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.evaluate("window.__mic.lateStop = true")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.keyboard.press("Escape")                              # discarded: its stop event is still on its way
    p.click(".rd-badge")
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 2 && window.__mic.made[1].state === 'recording'")
    p.evaluate("window.__mic.made[0].flush()")              # now it arrives
    p.wait_for_function("() => window.__mic.stops === 1")         # the old stream is let go
    assert p.evaluate("window.__mic.made[1].state") == "recording"
    assert p.locator(MIC).get_attribute("aria-pressed") == "true", "the old recorder's stop undid the new button"
    assert hub.posts == [], "a discarded sound was sent"
    p.click(MIC)                                            # the new recording is still the page's: this press stops it
    p.wait_for_function("() => window.__mic.made[1].state === 'inactive'")
    p.evaluate("window.__mic.made[1].flush()")
    until(lambda: len(hub.posts) == 1, what="the new sound sent")


def test_the_stop_event_that_comes_late_after_a_failed_send_leaves_the_new_recording_of_the_same_form_alone(tab, site, hub):
    p = open_thread(tab, site)
    sent = []
    p.wait_for_selector(MIC)
    p.evaluate("window.__mic.lateStop = true")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.fill(FIELD, "Typed while recording.")
    p.route("**/_/comment", lambda route: sent.append(route))
    p.focus(FIELD)
    p.keyboard.press("Control+Enter")                       # the sound is thrown away, its stop event is still on its way
    until(lambda: sent or p.wait_for_timeout(20), what="the send to go out")
    sent[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.wait_for_selector(FIELD)
    until(lambda: p.input_value(FIELD) == "Typed while recording.", what="the form back with its text")
    p.click(MIC)                                            # the same form, the same button: a new recording
    p.wait_for_function("() => window.__mic.made.length === 2 && window.__mic.made[1].state === 'recording'")
    p.evaluate("window.__mic.made[0].flush()")              # now the old stop arrives
    p.wait_for_function("() => window.__mic.stops === 1")
    assert p.evaluate("window.__mic.made[1].state") == "recording"
    assert p.locator(MIC).get_attribute("aria-pressed") == "true", "the old recorder's stop undid the new button"
    assert hub.posts == [], "a discarded sound was sent"
    p.click(MIC)                                            # still the page's recording: this press stops it
    p.wait_for_function("() => window.__mic.made[1].state === 'inactive'")
    p.evaluate("window.__mic.made[1].flush()")
    until(lambda: len(hub.posts) == 1, what="the new sound sent")


STORE_FULL = """(full) => {
  if (!window.__realSet) window.__realSet = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    if (full && String(k).includes('sheaf-comment-draft')) throw new DOMException('full', 'QuotaExceededError');
    return window.__realSet.call(this, k, v);
  };
}"""


def test_the_stop_event_that_comes_late_leaves_the_idle_button_of_a_form_that_came_back_beside_another_threads_recording(tab, site, hub):
    """A form whose send fails goes back to its own thread; when text is typed in the thread that is open and the store
    cannot keep the failed one, it comes back beside that text (data-for). A recording in that other form is the page's
    when the late stop of the first form's recorder arrives: the first button is idle, the second recording goes on."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "Why pears?",
                                                     "Bea", "2026-10-14T10:01")[0])
    p = open_thread(tab, site)
    sent = []
    p.wait_for_selector(MIC)
    p.evaluate("window.__mic.lateStop = true")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.fill(FIELD, "Words for the first thread.")
    p.evaluate(STORE_FULL, True)                            # the text of a failed send cannot go to the not-sent list
    p.route("**/_/comment", lambda route: sent.append(route))
    p.focus(FIELD)
    p.keyboard.press("Control+Enter")                       # the sound is thrown away, its stop event is still on its way
    until(lambda: sent or p.wait_for_timeout(20), what="the send to go out")
    p.locator(".rd-badge").nth(1).dispatch_event("click")   # another thread opens while the send is out
    p.wait_for_function("() => document.querySelector('#rd-popover').innerText.includes('Why pears?')")
    p.wait_for_selector(FIELD)
    p.fill(FIELD, "Words for the second thread.")
    sent[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    until(lambda: p.locator("#rd-popover .rd-form[data-for]").count() == 1, what="the first form back beside the second")
    own, other = "#rd-popover .rd-form:not([data-for]) .rd-mic", "#rd-popover .rd-form[data-for] .rd-mic"
    p.click(own)                                            # a recording in the second thread's form
    p.wait_for_function("() => window.__mic.made.length === 2 && window.__mic.made[1].state === 'recording'")
    p.evaluate("window.__mic.made[0].flush()")              # now the first recorder's stop arrives
    p.wait_for_function("() => window.__mic.stops === 1")
    assert p.locator(other).get_attribute("aria-pressed") == "false", "the button of the form that came back stayed on Stop"
    assert p.evaluate("window.__mic.made[1].state") == "recording"
    assert p.locator(own).get_attribute("aria-pressed") == "true"


def self_stopped_then_dictate_again(tab, site, hub):
    """The first recording ends by itself (a microphone unplugged, a recorder error) 60 s in, its text comes in, and a
    second one starts. Returns the page, the second recorder being up."""
    tab.page.clock.install()
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.clock.run_for(60000)
    p.evaluate("window.__mic.made[0].stop()")               # not through the page's own stop
    p.wait_for_function("() => document.querySelector('#rd-popover textarea').value.includes('hello there')")
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 2 && window.__mic.made[1].state === 'recording'")
    return p


def test_a_recorder_that_stopped_by_itself_does_not_cut_the_next_recording_short(tab, site, hub):
    p = self_stopped_then_dictate_again(tab, site, hub)
    p.clock.run_for(61000)                                  # past the first recording's 120 s, short of the second's
    p.wait_for_timeout(300)
    assert p.evaluate("window.__mic.made[1].state") == "recording", "the first recording's timer cut the second"
    assert len(hub.posts) == 1, "the second recording was sent early"


def test_a_recorder_that_stopped_by_itself_leaves_no_watch_on_the_hub(tab, site, hub):
    tab.page.clock.install()
    p = open_thread(tab, site)
    p.wait_for_selector(MIC)
    p.click(MIC)
    p.wait_for_function("() => window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'")
    p.evaluate("window.__mic.made[0].stop()")
    p.wait_for_function("() => document.querySelector('#rd-popover textarea').value.includes('hello there')")
    asked = hub.gets
    p.clock.run_for(60000)
    p.wait_for_timeout(300)
    assert hub.gets == asked, "a finished recording still asks the hub whether it is there"
