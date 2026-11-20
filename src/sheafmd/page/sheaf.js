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
// The click on a laptop name; `where` is {say(text, err), live(), plain(a)} (`err` false: information, no error toast): the surface's line, whether it is still there, and
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
      if (where.live()) where.say('AgentView does not answer on this computer: this name now opens its Remote Control link directly.', false);
      return;
    }
    where.plain(a);
    if (where.live()) where.say('That session could not be brought back: AgentView does not answer on this computer.');
  });
}
// One row of the table, for the rows of render and for the rows a client tiroir's node reads through (SPEC 9.9).
function buildRow(doc, el, r) {
  var tr = el('tr', 'sheaf-row');
  tr.dataset.folder = r.folder;
  tr.dataset.title = String(r.title).toLowerCase();
  tr.dataset.doc = r.doc;
  var t = el('td', 'sheaf-title'), a = el('a', null, r.title);
  href(a, r.url);
  t.append(a);
  if (r.new) {                                // a page Shared with the member that changed since they opened it
  var dot = el('span', 'sheaf-new', 'new');
  dot.title = 'New or changed since you last opened it';
  t.append(' ', dot);
  }
  if (r.shared_by) t.append(' ', el('span', 'sheaf-shared-by', 'shared by ' + r.shared_by));
  if (r.own) {                                // the owner's own acts on a loose page (SPEC 8.6): Keep, Archive now or Restore, Delete
  [r.archived ? ['restore', 'Restore'] : ['archive', 'Archive now'], ['keep', r.kept ? 'Kept' : 'Keep'], ['delete', 'Delete']].forEach(function (a) {
    var ab = el('button', 'sheaf-act' + (a[0] === 'keep' && r.kept ? ' on' : ''), a[1]);
    ab.type = 'button';
    ab.dataset.act = a[0];
    if (a[0] === 'keep') ab.dataset.on = r.kept ? '0' : '1';
    t.append(' ', ab);
  });
  }
  if (r.share) {                              // the member's own loose page that no Share line opens: the button writes the line
  var sb = el('button', 'sheaf-share', 'Share');
  sb.type = 'button';
  sb.dataset.hash = r.share;
  sb.title = 'Share this page with every member of the tiroir';
  t.append(' ', sb);
  }
  if (r.can_move) {                           // the member's own loose page: Move… puts it in another folder of their root
  var mb = el('button', 'sheaf-move', 'Move…');
  mb.type = 'button';
  mb.title = 'Put this page in another folder of your loose root';
  t.append(' ', mb);
  var tb = el('button', 'sheaf-move-tiroir', 'Move to another tiroir…');   // to the shared Sheaf where the owner has an account too
  tb.type = 'button';
  tb.title = 'Send this page to another shared Sheaf where you have an account';
  t.append(' ', tb);
  }
  var w = el('td', 'sheaf-write', r.write);
  if (r.write_tip) w.title = r.write_tip;
  var s = el('td', 'sheaf-session');
  if (r.session) s.append(sessionNode(doc, r.session, r.session_link));
  if (r.session_tip) s.title = r.session_tip;
  var when = el('td', 'sheaf-when'), time = el('time', null, r.when);
  time.setAttribute('data-mtime', String(r.mtime));
  when.append(time);
  tr.append(t, el('td', 'sheaf-where', r.folder), w, s, when, el('td', 'sheaf-open', r.open ? r.open : ''));
  return tr;
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
      if (n.client) b.dataset.client = n.client;      // a client tiroir of the agency (SPEC 9.9): its rows are read when the node is opened
      row.append(toggle, b);
      if (n.rename) {                           // a folder of the member's own loose root: Rename folder… moves each page in it
        var rb = el('button', 'sheaf-rename-folder', 'Rename…');
        rb.type = 'button';
        rb.dataset.path = n.path;
        rb.title = 'Rename this folder of your loose root';
        rb.setAttribute('aria-label', 'Rename folder ' + n.name);
        row.append(rb);
      }
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
  (data.rows || []).forEach(function (r) { body.append(buildRow(doc, el, r)); });
  if (data.clients_line) main.append(el('p', 'sheaf-clients-line', data.clients_line));      // no Clients folder for a member with no e-mail: the line says why
  table.append(head, body);
  var empty = el('p', 'sheaf-empty', 'No pages here.');
  empty.hidden = true;
  var switcher = el('nav', 'sheaf-views');
  switcher.setAttribute('aria-label', 'Views');
  var counts = data.counts || {};
  [['', 'Pages'], ['archived', 'Archived' + (counts.archived ? ' (' + counts.archived + ')' : '')],
   ['trash', 'Trash' + (counts.trash ? ' (' + counts.trash + ')' : '')]].forEach(function (v) {
    var b = el('button', 'sheaf-viewswitch' + ((data.view === 'default' ? '' : data.view) === v[0] ? ' on' : ''), v[1]);
    b.type = 'button';
    b.dataset.view = v[0];
    switcher.append(b);
  });
  var lb = el('button', 'sheaf-laptops-open', 'Laptops');         // Connect a laptop and the member's laptops (SPEC 9.7), a panel of the pane
  lb.type = 'button';
  lb.setAttribute('aria-expanded', 'false');
  switcher.append(lb);
  main.append(switcher);
  var laptops = el('section', 'sheaf-laptops');
  laptops.hidden = true;
  var ul = el('ul', 'sheaf-laptop-list');
  var lform = el('form', 'sheaf-laptop-form'), lin = el('input', 'sheaf-laptop-input');
  lin.type = 'text';
  lin.maxLength = 60;
  lin.required = true;
  lin.autocomplete = 'off';
  lin.placeholder = 'Name of the laptop';
  lin.setAttribute('aria-label', 'Name of the laptop');
  var lgo = el('button', 'sheaf-laptop-connect', 'Connect a laptop');
  lgo.type = 'submit';
  lform.append(lin, ' ', lgo);
  var made = el('div', 'sheaf-laptop-made');
  made.hidden = true;
  var lcopy = el('button', 'sheaf-laptop-copy', 'Copy');
  lcopy.type = 'button';
  made.append(el('p', null, 'Run this line on the laptop. It is shown once and cannot be read again.'), el('code', 'sheaf-laptop-line'), ' ', lcopy);
  laptops.append(el('p', 'sheaf-laptops-intro', 'Each laptop has its own token. Revoke one and the laptop loses access at once.'), ul, lform, made);
  main.append(laptops);
  if (data.view === 'trash') {                   // the member's own deleted pages, thirty days, Restore each
    var tt = el('table', 'sheaf-trash'), th = el('tbody');
    (data.trash || []).forEach(function (t) {
      var tr = el('tr', 'sheaf-trashed');
      var rb = el('button', 'sheaf-act', 'Restore');
      rb.type = 'button';
      rb.dataset.act = 'restore-trash';
      rb.dataset.id = t.id;
      tr.append(el('td', null, t.rel), el('td', null, t.days_left + ' days left'), el('td', null));
      tr.lastChild.append(rb);
      th.append(tr);
    });
    tt.append(th);
    main.append(tt);
    if (!(data.trash || []).length) main.append(el('p', 'sheaf-trash-empty', 'The trash is empty.'));
    filter.hidden = true;
    table.hidden = true;
    empty.textContent = '';
  }
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
  function allRows() { return Array.prototype.slice.call(ROOT.querySelectorAll('.sheaf-row')); }
  var filter = ROOT.querySelector('.sheaf-filter'), empty = ROOT.querySelector('.sheaf-empty');
  var said = ROOT.querySelector('.sheaf-said');

  function show() {
    var words = filter.value.trim().toLowerCase().split(/\s+/).filter(Boolean), n = 0;
    allRows().forEach(function (tr) {
      var f = tr.dataset.folder;
      var inside = !selected || f === selected || f.indexOf(selected + '/') === 0;
      var named = words.every(function (w) { return tr.dataset.title.indexOf(w) !== -1; });
      tr.hidden = !(inside && named);
      if (!tr.hidden) n++;
    });
    empty.hidden = n !== 0;
  }
  // A client tiroir's rows are asked of the hub when its node is opened and replace the last ones: the hub keeps none, so
  // neither does the page. A row of one has no Share, Keep, Archive or Delete (the hub tells it `own: false`).
  var asked = {};                 // per client: the read that counts, so an earlier one that comes back late adds nothing
  function load(name) {
    var tbody = ROOT.querySelector('.sheaf-table tbody'), d = ROOT.ownerDocument;
    function el(tag, cls, text) { var e = d.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = String(text); return e; }
    var mine = asked[name] = (asked[name] || 0) + 1;
    say('');
    fetch('/_/clients/sheaf?client=' + encodeURIComponent(name), { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      return r.ok ? r.json() : { rows: [], line: 'This client tiroir could not be read.' };
    }).then(function (b) {
      if (gone || mine !== asked[name]) return;
      allRows().forEach(function (tr) { if (tr.dataset.client === name) tr.remove(); });
      (b.rows || []).forEach(function (r) { var tr = buildRow(d, el, r); tr.dataset.client = name; tbody.append(tr); });
      if (b.line) say(b.line);
      show();
    }, function () {
      if (gone || mine !== asked[name]) return;
      allRows().forEach(function (tr) { if (tr.dataset.client === name) tr.remove(); });
      say('This client tiroir could not be read.');
    });
  }
  function choose(path, client) {
    laptopsClose();
    selected = path;
    if (client) load(client);
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

  // Laptops (SPEC 9.7, story 58): the member's laptops from `GET /_/laptops` (names, never a token), "Connect a laptop" posting a
  // name, and the one line the hub answers with, kept only in the line's text node: not in an attribute, the address, a
  // storage or the console, and cleared when the panel closes or the Sheaf is drawn again. Revoke asks a second click.
  var lpanel = ROOT.querySelector('.sheaf-laptops'), lopen = ROOT.querySelector('.sheaf-laptops-open');
  var lmade = lpanel.querySelector('.sheaf-laptop-made'), lline = lpanel.querySelector('.sheaf-laptop-line');
  var lseq = 0;
  function laptopsClose() {
    lseq++;
    lline.textContent = '';
    lmade.hidden = true;
    lpanel.querySelector('.sheaf-laptop-copy').textContent = 'Copy';
    lpanel.querySelector('.sheaf-laptop-input').value = '';
    lpanel.hidden = true;
    main.classList.remove('laptops');
    lopen.setAttribute('aria-expanded', 'false');
  }
  function laptopsList() {
    var d = ROOT.ownerDocument, mine = ++lseq;
    fetch('/_/laptops', { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (b) {
      if (gone || mine !== lseq || lpanel.hidden) return;
      if (!b || !Array.isArray(b.laptops)) { say('Your laptops could not be read.'); return; }
      var ul = lpanel.querySelector('.sheaf-laptop-list');
      ul.textContent = '';
      b.laptops.forEach(function (l) {
        var li = d.createElement('li'), name = d.createElement('strong'), rv = d.createElement('button');
        li.className = 'sheaf-laptop-row';
        name.className = 'sheaf-laptop-name';
        name.textContent = String(l.name);
        var seen = d.createElement('span');
        seen.className = 'sheaf-laptop-seen';
        seen.textContent = ' connected ' + String(l.created || '').slice(0, 16) + ', last used ' + (l.last_used ? String(l.last_used).slice(0, 16) : 'never') + ' ';
        rv.type = 'button';
        rv.className = 'sheaf-laptop-revoke';
        rv.dataset.name = String(l.name);
        rv.textContent = 'Revoke';
        li.append(name, seen, rv);
        ul.append(li);
      });
      if (!b.laptops.length) { var none = d.createElement('li'); none.className = 'sheaf-laptop-none'; none.textContent = 'No laptop is connected yet.'; ul.append(none); }
    }, function () { if (!gone && mine === lseq) say('Your laptops could not be read: the hub does not answer.'); });
  }
  function laptopsToggle() {
    if (!lpanel.hidden) { laptopsClose(); return; }
    say('');
    lpanel.hidden = false;
    main.classList.add('laptops');
    lopen.setAttribute('aria-expanded', 'true');
    laptopsList();
  }
  function laptopMake(form) {
    var input = form.querySelector('.sheaf-laptop-input'), go = form.querySelector('.sheaf-laptop-connect');
    var name = input.value.trim();
    if (!name) return;
    go.disabled = true;
    say('');
    lline.textContent = '';
    lmade.hidden = true;
    lpanel.querySelector('.sheaf-laptop-copy').textContent = 'Copy';
    fetch('/_/laptops', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ name: name }) }).then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok && !(b && b.ok === false), error: b && b.error, command: b && b.command }; }, function () { return { ok: false }; });
    }).then(function (got) {
      go.disabled = false;
      if (gone || lpanel.hidden) return;
      if (got.ok && typeof got.command === 'string') {
        lline.textContent = got.command;
        lmade.hidden = false;
        input.value = '';
        laptopsList();
        return;
      }
      say(got.error || 'The laptop could not be connected.');
    }, function () {
      go.disabled = false;
      if (!gone && !lpanel.hidden) say('The laptop could not be connected: the hub does not answer.');
    });
  }
  function laptopRevoke(button) {
    if (!button.dataset.sure) {
      button.dataset.sure = '1';
      button.textContent = 'Really revoke?';
      return;
    }
    button.disabled = true;
    say('');
    fetch('/_/laptops/revoke', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ name: button.dataset.name }) }).then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok && !(b && b.ok === false), error: b && b.error }; }, function () { return { ok: r.ok }; });
    }).then(function (got) {
      if (gone) return;
      if (got.ok) { laptopsList(); return; }
      button.disabled = false;
      say(got.error || 'The laptop could not be revoked.');
    }, function () {
      if (gone) return;
      button.disabled = false;
      say('The laptop could not be revoked: the hub does not answer.');
    });
  }
  function laptopCopy(button) {
    var text = lline.textContent;
    if (!text || !navigator.clipboard) { say('Select the line and copy it.'); return; }
    navigator.clipboard.writeText(text).then(function () { button.textContent = 'Copied'; }, function () { say('Select the line and copy it.'); });
  }

  // The row's Share button (SPEC 9.11): the hub writes the page's Share line against the hash the row read, and ticks it.
  function share(button) {
    var tr = button.closest('.sheaf-row');
    button.disabled = true;
    say('');
    fetch('/_/share', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ doc: tr.dataset.doc, hash: button.dataset.hash }) }).then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok && !(b && b.ok === false), error: b && b.error }; }, function () { return { ok: r.ok }; });
    }).then(function (got) {
      if (gone) return;
      if (got.ok) {
        var shared = button.ownerDocument.createElement('span');
        shared.className = 'sheaf-shared';
        shared.textContent = 'Shared';
        button.replaceWith(shared);
        return;
      }
      button.disabled = false;
      say(got.error || 'The page could not be shared.');
    }, function () {
      if (gone) return;
      button.disabled = false;
      say('The page could not be shared: the hub does not answer.');
    });
  }

  // The row's Move… (SPEC 9.11): a folder of the member's loose root, typed as a path; a folder that is not there is made.
  // The old address forwards to the new one, so the row follows the page in place.
  function move(button) {
    var tr = button.closest('.sheaf-row'), cell = button.parentNode;
    var open = cell.querySelector('.sheaf-move-form');
    if (open) { open.querySelector('input').focus(); return; }
    var form = ROOT.ownerDocument.createElement('form');
    form.className = 'sheaf-move-form';
    var input = ROOT.ownerDocument.createElement('input');
    input.type = 'text';
    input.setAttribute('aria-label', 'Folder of your loose root');
    input.placeholder = 'clients/blog';
    input.value = tr.dataset.folder.split('/').slice(1).join('/');
    var go = ROOT.ownerDocument.createElement('button'), no = ROOT.ownerDocument.createElement('button');
    go.type = 'submit'; go.textContent = 'Move';
    no.type = 'button'; no.textContent = 'Cancel';
    form.append(input, ' ', go, ' ', no);
    cell.append(form);
    input.focus();
    no.addEventListener('click', function () { form.remove(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      go.disabled = true;
      say('');
      fetch('/_/move', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ doc: tr.dataset.doc, folder: input.value.trim() }) }).then(function (r) {
        return r.json().then(function (b) { return { ok: r.ok && !(b && b.ok === false), error: b && b.error, doc: b && b.doc, url: b && b.url }; }, function () { return { ok: r.ok }; });
      }).then(function (got) {
        if (gone) return;
        if (got.ok && got.doc) {
          var at = got.doc.split('/');
          tr.dataset.doc = got.doc;
          tr.dataset.folder = at.slice(0, -1).join('/');
          tr.querySelector('.sheaf-where').textContent = tr.dataset.folder;
          href(tr.querySelector('.sheaf-title a'), got.url);
          form.remove();
          say('Moved to ' + at.slice(1).join('/') + '. The old address forwards to it; reload the Sheaf to see the folders change.');
          return;
        }
        go.disabled = false;
        say(got.error || 'The page could not be moved.');
      }, function () {
        if (gone) return;
        go.disabled = false;
        say('The page could not be moved: the hub does not answer.');
      });
    });
  }

  // The tree's Rename folder… (SPEC 9.11, story 100): the folder's new path in the member's loose root, typed; each page below it moves
  // with its own Forward. The hub's refusal, a name already taken in the new folder, is shown as it answers; the view is drawn again after.
  function renameFolder(button) {
    var line = button.closest('.sheaf-line');
    var open = line.querySelector('.sheaf-rename-form');
    if (open) { open.querySelector('input').focus(); return; }
    var at = button.dataset.path.split('/').slice(1).join('/');
    var form = ROOT.ownerDocument.createElement('form');
    form.className = 'sheaf-rename-form';
    var input = ROOT.ownerDocument.createElement('input');
    input.type = 'text';
    input.setAttribute('aria-label', 'New path of the folder in your loose root');
    input.value = at;
    var go = ROOT.ownerDocument.createElement('button'), no = ROOT.ownerDocument.createElement('button');
    go.type = 'submit'; go.textContent = 'Rename';
    no.type = 'button'; no.textContent = 'Cancel';
    form.append(input, ' ', go, ' ', no);
    line.append(form);
    input.focus();
    no.addEventListener('click', function () { form.remove(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (input.value.trim() === at) { form.remove(); return; }      // nothing to move: the hub would answer 409 "into itself"
      go.disabled = true;
      say('');
      fetch('/_/move-folder', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ folder: at, to: input.value.trim() }) }).then(function (r) {
        return r.json().then(function (b) { return { ok: r.ok && !(b && b.ok === false), error: b && b.error }; }, function () { return { ok: r.ok }; });
      }).then(function (got) {
        if (gone) return;
        if (got.ok) { if (opts.remount) opts.remount(); return; }
        go.disabled = false;
        say(got.error || 'The folder could not be renamed.');
      }, function () {
        if (gone) return;
        go.disabled = false;
        say('The folder could not be renamed: the hub does not answer.');
      });
    });
  }

  // The row's Move to another tiroir… (ticket 20): the address of the other shared Sheaf, typed. The hub sends the page and, once the
  // other one says it landed, forwards the old address there for ever; the row goes from this list.
  function moveTiroir(button) {
    var tr = button.closest('.sheaf-row'), cell = button.parentNode;
    var open = cell.querySelector('.sheaf-move-tiroir-form');
    if (open) { open.querySelector('input').focus(); return; }
    var form = ROOT.ownerDocument.createElement('form');
    form.className = 'sheaf-move-tiroir-form';
    var input = ROOT.ownerDocument.createElement('input');
    input.type = 'url';
    input.setAttribute('aria-label', 'Address of the other shared Sheaf');
    input.placeholder = 'https://…';
    var go = ROOT.ownerDocument.createElement('button'), no = ROOT.ownerDocument.createElement('button');
    go.type = 'submit'; go.textContent = 'Move';
    no.type = 'button'; no.textContent = 'Cancel';
    form.append(input, ' ', go, ' ', no);
    cell.append(form);
    input.focus();
    no.addEventListener('click', function () { form.remove(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      go.disabled = true;
      say('');
      fetch('/_/move-tiroir', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ doc: tr.dataset.doc, tiroir: input.value.trim() }) }).then(function (r) {
        return r.json().then(function (b) { return { ok: r.ok && !(b && b.ok === false), say: b && (b.say || b.error), doc: b && b.doc, origin: b && b.origin }; }, function () { return { ok: r.ok }; });
      }).then(function (got) {
        if (gone) return;
        if (got.ok && got.doc) {
          tr.remove();
          say('Moved to ' + got.origin + '/' + got.doc + '. The old address leads there.');
          return;
        }
        go.disabled = false;
        say(got.say || 'The page could not be moved.');
      }, function () {
        if (gone) return;
        go.disabled = false;
        say('The page could not be moved: the hub does not answer.');
      });
    });
  }

  // Archive now, Restore, Keep, Delete of a row and Restore of a trashed page (SPEC 8.6): the owner's own acts, each a POST of the
  // page's name; the view is drawn again after it. Delete asks a second click, in the button itself, never a dialog.
  function act(button) {
    var what = button.dataset.act, tr = button.closest('.sheaf-row');
    if (what === 'delete' && !button.dataset.sure) {
      button.dataset.sure = '1';
      button.textContent = 'Really delete?';
      return;
    }
    var body = what === 'restore-trash' ? { id: button.dataset.id } : { doc: tr.dataset.doc };
    if (what === 'keep') body.on = button.dataset.on === '1';
    button.disabled = true;
    say('');
    fetch('/_/' + what, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body) }).then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok && !(b && b.ok === false), error: b && b.error }; }, function () { return { ok: r.ok }; });
    }).then(function (got) {
      if (gone) return;
      if (got.ok) { if (opts.remount) opts.remount(); return; }
      button.disabled = false;
      say(got.error || 'That could not be done.');
    }, function () {
      if (gone) return;
      button.disabled = false;
      say('That could not be done: the hub does not answer.');
    });
  }

  function onClick(e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var moving = t.closest('.sheaf-move');
    if (moving) { e.preventDefault(); e.stopPropagation(); move(moving); return; }
    var renaming = t.closest('.sheaf-rename-folder');
    if (renaming) { e.preventDefault(); e.stopPropagation(); renameFolder(renaming); return; }
    var movingAway = t.closest('.sheaf-move-tiroir');
    if (movingAway) { e.preventDefault(); e.stopPropagation(); moveTiroir(movingAway); return; }
    var acting = t.closest('.sheaf-act');
    if (acting && !acting.disabled) { e.preventDefault(); e.stopPropagation(); act(acting); return; }
    var lo = t.closest('.sheaf-laptops-open');
    if (lo) { e.preventDefault(); e.stopPropagation(); laptopsToggle(); return; }
    var lr = t.closest('.sheaf-laptop-revoke');
    if (lr && !lr.disabled) { e.preventDefault(); e.stopPropagation(); laptopRevoke(lr); return; }
    var lc = t.closest('.sheaf-laptop-copy');
    if (lc) { e.preventDefault(); e.stopPropagation(); laptopCopy(lc); return; }
    var switching = t.closest('.sheaf-viewswitch');
    if (switching) { e.preventDefault(); e.stopPropagation(); if (opts.setView) opts.setView(switching.dataset.view); return; }
    var sharing = t.closest('.sheaf-share');
    if (sharing && !sharing.disabled) { e.preventDefault(); e.stopPropagation(); share(sharing); return; }
    var toggle = t.closest('.sheaf-toggle');
    if (toggle && !toggle.disabled) { fold(toggle); return; }
    var folder = t.closest('.sheaf-folder');
    if (folder) { choose(folder.dataset.path, folder.dataset.client); return; }
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
  lpanel.querySelector('.sheaf-laptop-form').addEventListener('submit', function (e) { e.preventDefault(); laptopMake(e.currentTarget); });
  show();
  return {
    unmount: function () { gone = true; lline.textContent = ''; if (handle) handle.unmount(); handle = null; ROOT.removeEventListener('click', onClick, true); },
    dirty: function () { return !!handle && handle.dirty(); },
    failed: function (text) { say(text); },
  };
}

window.sheafView = Object.freeze({ create: create, render: render });
// What the byline of an opened page (page.js) takes from here: the same name, the same click.
window.sheafSession = Object.freeze({ node: sessionNode, follow: follow });
})();
