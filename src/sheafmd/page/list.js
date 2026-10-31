// sheaf list script: the list's action buttons (SPEC 9.10, #107, #110).
//
// A press of a row's button shows Undo for UNDO_MS, then posts the action's tick to the hub; Undo in that window
// sends nothing. While a press of a row waits or is sent, the row's other buttons cannot be pressed: they name their
// action by the text the list read, which the tick changes. The list reloads once every press has been answered, so a
// reload never drops a press still in its window; a refusal is said above the rows, after that reload too, and gives
// the button back. A button drawn locked (a pressed one-off, another's Share) stays locked; a pressed toggle's press
// releases it (#110).
//
// The list runs in a document of its own (the hub's page at /<root>, which inlines this file) or mounted in the front's
// document (#116): page/mount.js draws the rows with render() from the hub's data, in a closed shadow root, and calls
// sheafList.create(root, {body, remount}). Mounted, the reload is remount() and the stored key carries a prefix of its
// own, as page.js's do. render() builds every node from text with createElement and textContent: no markup of the hub's.
(function () {
var UNDO_MS = 5000, SAID = 'sheaf-list-said';

function create(ROOT, opts) {
  opts = opts || {};
  var MOUNTED = ROOT !== document;
  var KEY = (MOUNTED ? 'sheaf-mount:' : '') + SAID;
  var open = 0, ticked = false, reloading = false, gone = false, timers = new Set();
  var said = ROOT.querySelector('.list-error'), refused = new Map();   // button: its refusal on this page
  function say(text) { said.textContent = text; said.hidden = false; }
  // A refusal beside a press that went through is said again after that press's reload, once: only the refusals
  // made on this page are kept, never one said again here (sessionStorage may refuse).
  try { var kept = sessionStorage.getItem(KEY); sessionStorage.removeItem(KEY); if (kept) say(kept); } catch (e) {}
  function settled() {
    if (--open !== 0 || !ticked || gone) return;
    reloading = true;               // a press from now on would die with the page
    try { if (refused.size) sessionStorage.setItem(KEY, Array.from(refused.values()).join(' ')); } catch (e) {}
    if (MOUNTED) opts.remount(); else location.reload();
  }
  ROOT.querySelectorAll('.list-row button.list-act:not(:disabled)').forEach(function (b) {
    var word = b.textContent, waiting = null, pressed = b.getAttribute('aria-pressed');
    var others = Array.prototype.filter.call(b.closest('.list-row').querySelectorAll('button.list-act:not(:disabled)'),
      function (o) { return o !== b; });
    function lock(on) { others.forEach(function (o) { o.disabled = on; }); }
    function back() { b.textContent = word; b.classList.remove('pending'); b.removeAttribute('aria-label'); }
    function send() {
      timers.delete(waiting);
      waiting = null;
      back();
      b.disabled = true;
      if (pressed !== null) b.setAttribute('aria-pressed', pressed === 'true' ? 'false' : 'true');
      var tick = {doc: b.dataset.doc, action: Number(b.dataset.action), word: b.dataset.word, hash: b.dataset.hash};
      if (b.hasAttribute('data-release')) tick.release = true;
      fetch('/_/tick', {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin',
        body: JSON.stringify(tick)})
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) {
          if (r.ok) { ticked = true; refused.delete(b); return; }
          throw new Error(j.error || ('the hub answered ' + r.status));
        }); })
        .catch(function (e) {
          if (pressed !== null) b.setAttribute('aria-pressed', pressed);
          b.disabled = false; lock(false);
          refused.set(b, e.message); say(e.message);
        })
        .then(settled);
    }
    b.addEventListener('click', function () {
      if (reloading || gone) return;
      if (waiting !== null) {
        clearTimeout(waiting); timers.delete(waiting); waiting = null; back(); lock(false); settled(); return;
      }
      open++;
      lock(true);
      b.textContent = 'Undo'; b.classList.add('pending'); b.setAttribute('aria-label', 'Undo ' + word);
      waiting = setTimeout(send, UNDO_MS);
      timers.add(waiting);
    });
  });
  // Unmounted, a press still in its window is dropped, as leaving the page of its own drops it; one already sent is
  // answered, and its answer remounts nothing.
  return {
    unmount: function () { gone = true; timers.forEach(function (t) { clearTimeout(t); }); timers.clear(); },
    dirty: function () { return !gone && open > 0; },
    // The remount after a press could not fetch the list: the rows stay as they were, and so do the buttons the presses
    // locked (their text is the old one); the others can be pressed again, and the next settled press remounts.
    failed: function (msg) { if (gone) return; reloading = false; say(msg); },
  };
}

// The list of TheList.data drawn as the page of its own draws it (the_list.py _row_html), in `target`'s document.
// An address is kept only when it is a path on this origin: one slash, then no second slash or backslash, and no
// control or space anywhere (the URL parser drops a tab or a newline, so "/\t/host" would be "//host").
function render(data, target) {
  var doc = target && target.ownerDocument ? target.ownerDocument : document;
  function el(tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }
  function href(a, value) {
    if (typeof value === 'string' && /^\/(?![\/\\])/.test(value) && !/[\u0000-\u0020\u007f\\]/.test(value)) a.setAttribute('href', value);
  }
  var out = doc.createDocumentFragment();
  var header = el('header');
  header.append(el('h1', null, 'Waiting on you'), el('span', 'list-sub', 'and what is in progress'));
  var nav = el('nav', 'list-filters');
  (data.filters || []).forEach(function (f) {
    var a = el('a', 'list-filter' + (f.on ? ' on' : ''), f.label);
    href(a, f.href);
    if (f.on) a.setAttribute('aria-current', 'page');
    nav.append(a);
  });
  var error = el('p', 'list-error');
  error.setAttribute('role', 'alert');
  error.hidden = true;
  var main = el('main');
  (data.sections || []).forEach(function (s) {
    var section = el('section', 'list-section'), h2 = el('h2', null, s.title + ' ');
    h2.append(el('span', 'list-count', s.count));
    section.append(h2);
    (s.groups || []).forEach(function (g) {
      var group = el('div', 'list-group'), ul = el('ul');
      group.append(el('h3', null, g.name), ul);
      (g.rows || []).forEach(function (r) {
        var li = el('li', 'list-row'), side = el('div', 'list-main'), title = el('a', 'list-title', r.title);
        href(title, r.href);
        side.append(title);
        if (r.assistant) side.append(' ', el('span', 'list-assistant', r.assistant));
        side.append(el('div', 'list-meta', r.meta));
        var acts = el('div', 'list-actions');
        (r.actions || []).forEach(function (x) {
          var locked = !x.toggle && x.pressed;
          var b = el('button', 'list-act ' + (x.toggle ? 'toggle' : 'one-off') + (locked ? ' pressed' : ''), x.label);
          b.type = 'button';
          if (x.toggle) b.setAttribute('aria-pressed', x.pressed ? 'true' : 'false');
          if (x.disabled) b.disabled = true;
          b.dataset.doc = x.doc;
          b.dataset.word = x.word;
          if (!locked) { b.dataset.action = String(x.n); b.dataset.hash = x.hash; }
          if (x.toggle && x.release) b.setAttribute('data-release', '');
          acts.append(b);
        });
        li.append(side, acts);
        ul.append(li);
      });
      section.append(group);
    });
    main.append(section);
  });
  out.append(header, nav, error, main);
  return out;
}

window.sheafList = Object.freeze({ create: create, render: render });
if (document.body && document.body.classList.contains('sheaf-list')) create(document);
})();
