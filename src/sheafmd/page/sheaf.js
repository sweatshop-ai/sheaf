// sheaf view script: the Sheaf of a member (SPEC 8.6), a tree of folders on the left and a table of rectoversos on the right.
//
// Mounted in the front's document by page/mount.js (`sheafMount.mount(host, {sheaf: true})`): render() builds every node
// from the hub's data with createElement and textContent, never markup, in a closed shadow root; create(root, {body,
// remount}) makes it live. A folder of the tree shows the table of itself and everything below it; the filter keeps the
// rows whose title holds the words typed; a click on a row's title takes the pane for the rectoverso, mounted by
// sheafMount in a body of its own, under a "← Sheaf" button and the path as a breadcrumb; the button gives the table back
// as it was (the folder, the filter and the collapsed folders stay).
(function () {
// An address is kept only when it is a path on this origin: one slash, then no second slash or backslash, and no
// control or space anywhere (the URL parser drops a tab or a newline, so "/\t/host" would be "//host").
function href(a, value) {
  if (typeof value === 'string' && /^\/(?![\/\\])/.test(value) && !/[\u0000- \u007f\\]/.test(value)) a.setAttribute('href', value);
}
// A web address of a Remote Control link, or "": http or https and nothing else, with no space or control character.
function web(value) {
  if (typeof value !== 'string' || /[\u0000-\u0020\u007f]/.test(value)) return '';
  try { var u = new URL(value); return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : ''; } catch (e) { return ''; }
}
// The name of the last agent session on a row (SPEC 8.6): what the hub's `session_link` says, as data kept on the
// element and read by sheaf.js when it is clicked; nothing here builds an address out of the page's text.
function sessionNode(doc, text, link) {
  var l = link || {};
  var a;
  function node(tag, t) { var e = doc.createElement(tag); e.className = 'sheaf-session-link'; e.textContent = String(t); return e; }
  if (l.kind === 'chat') {
    a = node('a', text);
    href(a, l.href);
    if (!a.hasAttribute('href')) return doc.createTextNode(String(text));
  } else if (l.kind === 'remote') {
    var to = web(l.href);
    if (!to) return doc.createTextNode(String(text));
    a = node('a', text);
    a.setAttribute('href', to);
  } else if (l.kind === 'laptop' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(l.session || '') && (l.provider === 'claude' || l.provider === 'codex')) {
    var remote = web(l.remote);
    a = node(remote ? 'a' : 'button', text);
    if (remote) a.setAttribute('href', remote); else a.type = 'button';
    a.dataset.provider = l.provider;
    a.dataset.session = l.session;
    a.dataset.laptop = '1';
  } else {
    return doc.createTextNode(String(text));
  }
  if (a.tagName === 'A') { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener noreferrer'); }
  return a;
}

// AgentView on the member's own laptop (SPEC 8.6): the click brings the session's terminal to the front, or opens it
// again when it has ended; only the provider and id the hub recorded go in the body. A refusal or no answer is "not
// here". Shared by the rows and by the byline of an opened page (page.js), which asks the same way.
var LAPTOP = 'http://127.0.0.1:8765';
var ABSENT_FOR = 30000, absentAt = 0;
// AgentView has not answered for a while: the Remote Control link is then followed by the browser itself, as the
// link it is, in the click that made it (a tab opened after an async request may be blocked as a popup).
function absent() { return absentAt !== 0 && Date.now() - absentAt < ABSENT_FOR; }
function ask(path, body) {
  return fetch(LAPTOP + path, { method: 'POST', credentials: 'omit', headers: { 'X-Fleet': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify(body) });
}
function done(r) { return r.json().then(function (b) { return r.ok && !(b && b.ok === false); }, function () { return r.ok; }); }
function bringBack(a) {
  var provider = a.dataset.provider, id = a.dataset.session;
  return ask('/api/jump', { key: provider + ':' + id }).then(function (r) {
    if (r.status === 404 && provider === 'claude') return ask('/api/reopen', { id: id }).then(done);
    return done(r);
  });
}
// The click on a laptop name; `where` is {say(text), live(), plain(a)}: the surface's line, whether it is still there, and
// what a name with no way left becomes.
function follow(a, e, where) {
  var remote = a.getAttribute('href');
  if (remote && absent()) return;               // no preventDefault: the real link opens in this click
  e.preventDefault();
  e.stopPropagation();
  bringBack(a).then(function (ok) {
    // AgentView answered: it is there, whatever it found, so the link stays and no other way is tried.
    absentAt = 0;
    if (!ok && where.live()) where.say('AgentView found no session to bring back.');
  }, function () {
    absentAt = Date.now();
    if (remote) {
      window.open(remote, '_blank', 'noopener,noreferrer');
      if (where.live()) where.say('AgentView does not answer on this computer: this name now opens its Remote Control link directly.');
      return;
    }
    where.plain(a);
    if (where.live()) where.say('That session could not be brought back: AgentView does not answer on this computer.');
  });
}
function render(data, target) {
  var doc = target && target.ownerDocument ? target.ownerDocument : document;
  function el(tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }
  var out = doc.createDocumentFragment();
  var view = el('div', 'sheaf-view');
  var side = el('nav', 'sheaf-tree');
  side.setAttribute('aria-label', 'Folders');
  var all = el('button', 'sheaf-folder on', 'All pages');
  all.type = 'button';
  all.dataset.path = '';
  side.append(all);
  function branch(nodes) {
    var ul = el('ul');
    nodes.forEach(function (n) {
      var li = el('li', 'sheaf-node'), row = el('div', 'sheaf-line');
      var kids = n.children || [];
      var toggle = el('button', 'sheaf-toggle', kids.length ? '▾' : '');
      toggle.type = 'button';
      toggle.setAttribute('aria-label', 'Collapse ' + n.name);
      if (kids.length) toggle.setAttribute('aria-expanded', 'true'); else toggle.disabled = true;
      var b = el('button', 'sheaf-folder', n.name);
      b.type = 'button';
      b.dataset.path = n.path;
      row.append(toggle, b);
      li.append(row);
      if (kids.length) li.append(branch(kids));
      ul.append(li);
    });
    return ul;
  }
  side.append(branch(data.tree || []));
  var main = el('main', 'sheaf-main');
  var filter = el('input', 'sheaf-filter');
  filter.type = 'search';
  filter.placeholder = 'Filter by title';
  filter.setAttribute('aria-label', 'Filter by title');
  var table = el('table', 'sheaf-table'), head = el('thead'), hr = el('tr');
  ['Title', 'Folder', 'Last write', 'Last agent session', 'When', 'Open'].forEach(function (h) { hr.append(el('th', null, h)); });
  head.append(hr);
  var body = el('tbody');
  (data.rows || []).forEach(function (r) {
    var tr = el('tr', 'sheaf-row');
    tr.dataset.folder = r.folder;
    tr.dataset.title = String(r.title).toLowerCase();
    tr.dataset.doc = r.doc;
    var t = el('td', 'sheaf-title'), a = el('a', null, r.title);
    href(a, r.url);
    t.append(a);
    var w = el('td', 'sheaf-write', r.write);
    if (r.write_tip) w.title = r.write_tip;
    var s = el('td', 'sheaf-session');
    if (r.session) s.append(sessionNode(doc, r.session, r.session_link));
    if (r.session_tip) s.title = r.session_tip;
    var when = el('td', 'sheaf-when'), time = el('time', null, r.when);
    time.setAttribute('data-mtime', String(r.mtime));
    when.append(time);
    tr.append(t, el('td', 'sheaf-where', r.folder), w, s, when, el('td', 'sheaf-open', r.open ? r.open : ''));
    body.append(tr);
  });
  table.append(head, body);
  var empty = el('p', 'sheaf-empty', 'No pages here.');
  empty.hidden = true;
  main.append(filter, table, empty);
  Object.keys(data.more || {}).forEach(function (root) {
    main.append(el('p', 'sheaf-more', 'and ' + data.more[root] + ' more in ' + root));
  });
  var pane = el('section', 'sheaf-doc');
  pane.hidden = true;
  var bar = el('div', 'sheaf-bar'), back = el('button', 'sheaf-back', '← Sheaf');
  back.type = 'button';
  bar.append(back, el('span', 'sheaf-crumb'));
  pane.append(bar, el('div', 'sheaf-doc-body'));
  var said = el('p', 'sheaf-said');
  said.setAttribute('role', 'alert');
  said.hidden = true;
  view.append(side, main, pane);
  out.append(said, view);
  return out;
}

function create(ROOT, opts) {
  opts = opts || {};
  var selected = '', gone = false, handle = null, opened = 0;
  var view = ROOT.querySelector('.sheaf-view');
  var main = view.querySelector('.sheaf-main'), pane = view.querySelector('.sheaf-doc');
  var rows = Array.prototype.slice.call(ROOT.querySelectorAll('.sheaf-row'));
  var filter = ROOT.querySelector('.sheaf-filter'), empty = ROOT.querySelector('.sheaf-empty');
  var said = ROOT.querySelector('.sheaf-said');

  function show() {
    var words = filter.value.trim().toLowerCase().split(/\s+/).filter(Boolean), n = 0;
    rows.forEach(function (tr) {
      var f = tr.dataset.folder;
      var inside = !selected || f === selected || f.indexOf(selected + '/') === 0;
      var named = words.every(function (w) { return tr.dataset.title.indexOf(w) !== -1; });
      tr.hidden = !(inside && named);
      if (!tr.hidden) n++;
    });
    empty.hidden = n !== 0;
  }
  function choose(path) {
    selected = path;
    Array.prototype.forEach.call(ROOT.querySelectorAll('.sheaf-folder'), function (b) {
      b.classList.toggle('on', b.dataset.path === path);
    });
    show();
  }
  function fold(toggle) {
    var li = toggle.closest('li'), open = toggle.getAttribute('aria-expanded') === 'true';
    li.classList.toggle('collapsed', open);
    toggle.setAttribute('aria-expanded', open ? 'false' : 'true');
    toggle.setAttribute('aria-label', (open ? 'Expand ' : 'Collapse ') + li.querySelector('.sheaf-folder').textContent);
    toggle.textContent = open ? '▸' : '▾';
  }
  function close() {
    // The page asks its loader whether it holds unsaved text before the loader moves it (page.js dirty()); so Back does.
    if (handle && handle.dirty()) { say('This page has unsaved changes. Save or discard them before going back.'); return; }
    opened++;                                   // a mount still on its way is overtaken
    if (handle) { handle.unmount(); handle = null; }
    pane.hidden = true;
    main.hidden = false;
    view.querySelector('.sheaf-tree').hidden = false;
    // A root cannot be attached twice: the next rectoverso mounts in a body of its own.
    var b = pane.querySelector('.sheaf-doc-body');
    var fresh = b.cloneNode(false);
    b.replaceWith(fresh);
  }
  // Nothing answered, so no other row of this laptop can be reached from here: those without a link become text.
  var where = {
    say: function (t) { say(t); }, live: function () { return !gone; },
    plain: function () {
      Array.prototype.slice.call(ROOT.querySelectorAll('button.sheaf-session-link[data-laptop]')).forEach(function (b) {
        b.replaceWith(ROOT.ownerDocument.createTextNode(b.textContent));
      });
    },
  };
  function say(text) { said.textContent = text; said.hidden = !text; }
  function open(tr) {
    var kit = window.sheafMount;
    if (!kit) { say('The page could not be opened here.'); return; }
    say('');
    var b = pane.querySelector('.sheaf-doc-body');
    pane.querySelector('.sheaf-crumb').textContent = tr.dataset.doc.split('/').join(' / ');
    main.hidden = true;
    view.querySelector('.sheaf-tree').hidden = true;
    pane.hidden = false;
    var mine = ++opened;
    kit.mount(b, { doc: tr.dataset.doc, navigate: opts.navigate, upgrade: opts.upgrade }).then(function (h) {
      if (gone || mine !== opened) { h.unmount(); return; }
      handle = h;
    }, function (e) { if (mine === opened) { close(); say('The page could not be opened: ' + e.message); } });
  }

  function onClick(e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var toggle = t.closest('.sheaf-toggle');
    if (toggle && !toggle.disabled) { fold(toggle); return; }
    var folder = t.closest('.sheaf-folder');
    if (folder) { choose(folder.dataset.path); return; }
    if (t.closest('.sheaf-back')) { close(); return; }
    var back = t.closest('.sheaf-session-link[data-laptop]');
    if (back && !(e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) { follow(back, e, where); return; }
    var a = t.closest('.sheaf-title a');
    if (a && !(e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) {
      e.preventDefault();
      e.stopPropagation();
      open(a.closest('.sheaf-row'));
    }
  }
  ROOT.addEventListener('click', onClick, true);
  filter.addEventListener('input', show);
  show();
  return {
    unmount: function () { gone = true; if (handle) handle.unmount(); handle = null; ROOT.removeEventListener('click', onClick, true); },
    dirty: function () { return !!handle && handle.dirty(); },
    failed: function (text) { say(text); },
  };
}

window.sheafView = Object.freeze({ create: create, render: render });
// What the byline of an opened page (page.js) takes from here: the same name, the same click.
window.sheafSession = Object.freeze({ node: sessionNode, follow: follow });
})();
