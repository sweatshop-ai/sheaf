// sheaf session script: the name of the last agent session of a page or a row, and the click on it (SPEC 8.6, 6.2 item 11).
//
// Shared by the Sheaf view (sheaf.js, in the mount bundle) and by the byline of an opened page (page.js), including a member's
// page opened directly on its own address, which carries no mount bundle. It defines `window.sheafSession` and nothing else,
// so it can come before either of them.
(function () {
if (window.sheafSession) return;       // a page that loads the page script and the mount bundle has one kit, the first
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
window.sheafSession = Object.freeze({ node: sessionNode, follow: follow, href: href, web: web });
})();
