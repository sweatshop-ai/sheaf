// sheaf page script: block editing, the ☰ menu, review comments, Ask and Tell.
//
// Injected by sheaf into editable renders only. Self-contained: no CDN, no external
// stylesheet. The page talks to one sheaf hub, always at absolute /_/ paths, with the
// browser's session cookie (a same-origin fetch sends it) and the document named in
// every request (CFG.doc). Opened over file:// there is no hub, so every write is
// absent and the comments are shown read-only.
//
// The page's Content-Security-Policy allows no inline handler, no javascript: URL and
// no eval: handlers are attached with addEventListener, never written into HTML.
(function () {
  var meta = document.getElementById('rd-edit-meta');
  if (!meta) return;
  var CFG = JSON.parse(meta.textContent);
  var main = document.querySelector('main');
  if (!main) return;

  var COMMENTS = CFG.comments || [];
  var byId = {};
  COMMENTS.forEach(function (c) { byId[c.id] = c; });

  // The agent this page was rendered from, if any: CFG.agent is {agent, display, product,
  // name, label}, never its session id or its socket. Its own name when it has one, else its
  // display name, labels the Ask and Tell buttons and its replies; nothing in the page names an
  // agent itself.
  // CFG.can lists what it can do: "ask" offers Ask, "deliver" offers Tell. What it cannot
  // do shows as a disabled button with one line under it, CFG.lines.ask or .tell (SPEC
  // 10.6). The hub's answer to /_/doc refreshes all three (takeTarget).
  var NO_AGENT = 'Render this page from an agent session to Ask and Tell it.';
  // Drafts are kept per hub and per document. On the loopback port the port tells hubs apart; through
  // the proxy socket (SPEC 9.9) every member shares the front's origin, so the key holds the member's
  // id, which a rename in the hub's config does not change (10.4, 10.8).
  var DRAFTS_OF = CFG.proxy ? 'm:' + CFG.member : location.port;
  // On a member's page of a sheaf whose live session runs on the box, CFG.can holds "box-ask" and "box-tell":
  // Ask and Tell go with the comment to /_/comment, the hub drops it for James's window, and James answers in
  // the thread through the door. The page starts no wait of its own for it (SPEC 9.12). On a sheaf whose live
  // session is a member's fork, CFG.can holds "relay-tell" while that fork's relay is connected: Tell goes the
  // same way, to the relay, and Ask is not offered (9.14).
  var AGENT, AGENT_UC, CAN, canAsk, canTell, toBox;
  function takeAgent() {
    CAN = CFG.can || [];
    toBox = CAN.indexOf('box-ask') >= 0 || CAN.indexOf('box-tell') >= 0 || CAN.indexOf('relay-tell') >= 0;
    // The session's own name when it has one ("Linnea"), else the agent's display name (SPEC 10.5); on a
    // box sheaf the member the live session runs as (James), and James on his sheaf with no session yet.
    AGENT = toBox ? upper(liveSession().member) || 'James'
          : (CFG.agent && (CFG.agent.name || CFG.agent.display)) || 'the agent';
    AGENT_UC = AGENT.charAt(0).toUpperCase() + AGENT.slice(1);
    canAsk = CAN.indexOf(toBox ? 'box-ask' : 'ask') >= 0;
    canTell = CAN.indexOf('relay-tell') >= 0 || CAN.indexOf(toBox ? 'box-tell' : 'deliver') >= 0;
  }
  function liveSession() { return (CFG.work && CFG.work.sessions && CFG.work.sessions[0]) || {}; }
  // Where a member's Ask or Tell goes: James's window on the box, or the fork's session through its relay (9.14).
  function whereTo() {
    return CAN.indexOf('relay-tell') >= 0 ? AGENT + '’s session on ' + liveSession().host : AGENT + '’s window on the box';
  }
  function upper(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }
  takeAgent();
  // What the hub's answer to /_/doc says of the agent: a rename, or a session that ended, reaches
  // an open page by any of the three places that ask (SPEC 10.5).
  function takeTarget(j) {
    if (!j || !('capabilities' in j)) return;
    var before = JSON.stringify([CFG.agent, CFG.can, CFG.lines, CFG.work]);
    CFG.agent = j.target || null;
    CFG.can = j.capabilities || [];
    CFG.lines = j.lines || {};
    if ('work' in j) CFG.work = j.work;       // a fork moves the live session off the box (9.12)
    takeAgent();
    if (workOpen()) drawWork();               // an open Work on this shows the sessions the hub knows now
    var wasOpen = menu.classList.contains('open');
    buildMenu();
    if (wasOpen) openMenu();
    // An open thread draws the agent's name and the Answer button; it is drawn again when they changed.
    if (before !== JSON.stringify([CFG.agent, CFG.can, CFG.lines, CFG.work]) && pop && popId && byId[popId]) fillPopover(popId);
  }
  // A sheaf whose live session runs on a member's machine is worked on there (SPEC 10.6).
  function lineOf(what) {
    if (CFG.work && CFG.work.live === 'laptop') return 'This session runs on ' + upper(liveSession().member) + '’s machine: open it there.';
    return (CFG.lines && CFG.lines[what]) || NO_AGENT;
  }
  function agentLine() {
    if (toBox && (canAsk || canTell)) return (canAsk && canTell ? 'Ask and Tell' : canAsk ? 'Ask' : 'Tell') + ' → ' + whereTo();
    var a = CFG.agent;
    if (!a || (!canAsk && !canTell)) return lineOf('ask');
    return (canAsk && canTell ? 'Ask and Tell' : canAsk ? 'Ask' : 'Tell') +
           ' → ' + a.label + ' · ' + a.product;
  }
  function yourSession() {
    return CFG.agent ? 'your ' + AGENT + ' session' : 'the session';
  }

  // ---- map sentinel comments back to source blocks -------------------------
  var blocks = [], cur = null;
  (function walk(parent) {
    for (var n = parent.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 8) {
        var m = /^\s*MDB:(\d+)\s*$/.exec(n.nodeValue || '');
        if (m) { cur = { i: +m[1], nodes: [] }; blocks.push(cur); continue; }
      }
      if (cur) cur.nodes.push(n);
    }
  })(main);

  var editable = new Set(CFG.editable || []);
  var commentable = new Set(CFG.commentable || []);

  // ---- comments become anchors ----------------------------------------------
  // Each rd-comment node is replaced by an empty, non-editable anchor span that
  // holds the badge. This happens BEFORE `pristine` is taken, so an untouched
  // block serialises exactly as it did, and ser() reduces every anchor to the bare
  // span the server turns back into the comment's original bytes. The comment's
  // text never travels from the page: the page can move or delete an anchor, not
  // rewrite what a comment says.
  var anchors = {};
  // The badge says where a thread stands, in the colours of the popover's buttons,
  // decided by the role of the last message (SPEC 5.3): blue after an answer (Ask),
  // orange after an action (Tell), ink when a person spoke last (or a reply without
  // a role), grey once resolved. Filled means this viewer has not read the latest
  // message yet; a hollow ring means read. A running Ask or Tell takes its colour at
  // once and breathes until the reply lands.
  function lastReply(c) {
    var r = c.replies || [];
    return r.length ? r[r.length - 1] : null;
  }
  function lastBy(c) {
    var r = lastReply(c);
    return r ? r.by : c.by;
  }
  function badgeState(c) {
    if (c.status === 'resolved') return 'res';
    if (asking && asking[c.id]) return 'ask';
    if (telling && telling[c.id]) return 'tell';
    var r = lastReply(c), role = r ? r.role : null;
    return role === 'answer' ? 'ask' : role === 'action' ? 'tell' : 'ink';
  }
  // Read state lives on the hub (SPEC 8.7): how many messages of each thread this
  // person has had open. CFG.seen is where it stood at render time; a successful
  // POST /_/seen moves the page's copy forward. A failed one is silent: the thread
  // only stays shown as unread.
  var SEEN = CFG.seen || {}, seenOut = {};
  function unread(c) {
    if (c.status === 'resolved' || lastBy(c) === CFG.me) return false;
    return 1 + (c.replies || []).length > (SEEN[c.id] || 0);
  }
  function markRead(id) {
    var c = byId[id];
    if (!c || !canSave) return;
    var n = 1 + (c.replies || []).length;
    if ((SEEN[id] || 0) >= n || seenOut[id] >= n) return;
    seenOut[id] = n;
    post('/_/seen', { id: id, count: n }).then(function () {
      SEEN[id] = Math.max(SEEN[id] || 0, n);
      reBadge();
    }).catch(function () {}).then(function () { if (seenOut[id] === n) delete seenOut[id]; });
  }
  // Re-read every badge, and the panel's list, after the read state moved.
  function reBadge() {
    Object.keys(anchors).forEach(function (id) {
      var a = anchors[id], c = byId[id];
      if (a && c) a.className = anchorClass(c) + (a.classList.contains('rd-new') ? ' rd-new' : '');
    });
    redrawPanel();
  }
  function badgeClass(c) {
    var st = badgeState(c);
    return ' rd-st-' + st + (unread(c) ? ' rd-unread' : '') +
           (st !== 'res' && ((asking && asking[c.id]) || (telling && telling[c.id] && !tellQ)) ? ' rd-working' : '');
  }
  function anchorClass(c) {
    return 'rd-anchor' + (c.status === 'resolved' ? ' rd-resolved' : '') + (c.orphan ? ' rd-orphan' : '') +
           badgeClass(c);
  }
  // Re-read one thread's state onto its badge, and into its popover if open.
  function touched(id) {
    var a = anchors[id], c = byId[id];
    if (a && c) a.className = anchorClass(c) + (a.classList.contains('rd-new') ? ' rd-new' : '');
    if (pop && popId === id && c) { markRead(id); fillPopover(id); if (a) a.className = anchorClass(c); }
  }
  function makeAnchor(c) {
    var a = document.createElement('span');
    a.className = anchorClass(c);
    a.setAttribute('data-rd-id', c.id);
    a.setAttribute('contenteditable', 'false');
    a.setAttribute('data-rd-ui', '');
    var b = document.createElement('b');
    b.className = 'rd-badge';
    // No title attribute: comment text inside the anchor could contain "</span>"
    // and break the pattern clean() uses to reduce the anchor for a save.
    b.textContent = c.id.replace(/^c/, '');
    a.appendChild(b);
    anchors[c.id] = a;
    return a;
  }
  (function () {
    var tw = document.createTreeWalker(main, NodeFilter.SHOW_COMMENT), found = [];
    while (tw.nextNode()) found.push(tw.currentNode);
    found.forEach(function (n) {
      var m = /^\s*(?:sheaf|rd)-comment\s+id=(\S+)/.exec(n.nodeValue || '');
      if (!m || !byId[m[1]]) return;
      n.parentNode.replaceChild(makeAnchor(byId[m[1]]), n);
    });
  })();

  // Edit mode itself writes contenteditable="true" and class="rd-locked" into the
  // DOM. Those must be invisible to change detection, or merely ENTERING edit mode
  // marks every block dirty and the next save pushes the whole document through
  // pandoc - renumbering lists, reflowing tables, rewriting rules.
  var LOCKED_TIP = 'Not editable here: code, charts, images and raw HTML would not survive the ' +
                   'round trip. Edit this block in the .md file.';
  function clean(h) {
    return h.replace(/<span class="rd-anchor[^"]*" data-rd-id="([^"]+)"[^>]*>[\s\S]*?<\/span>/g,
                     '<span class="rd-anchor" data-rd-id="$1"></span>')
            .replace(/\s*contenteditable="[^"]*"/g, '')
            .replace(/\s+class="rd-locked"/g, '')
            .replace(/(\s+class="[^"]*?)\s*\brd-locked\b/g, '$1')
            .replace(/\s+title="Not editable here: [^"]*"/g, '');
  }
  function ser(b) {
    return clean(b.nodes.map(function (n) {
      return n.nodeType === 1 ? n.outerHTML : (n.nodeType === 3 ? n.nodeValue : '');
    }).join('')).trim();
  }
  blocks.forEach(function (b) { b.pristine = ser(b); });

  var canSave = !CFG.readonly && (location.protocol === 'http:' || location.protocol === 'https:');
  // Two different questions. canSave: is there a hub behind this page at all
  // (no on a forwarded file or an --internal render). canEdit: did this document
  // keep block editing. The second can be false while the first is true, and then
  // the DOCUMENT group is absent and the menu is export and comments only.
  var canEdit = canSave && CFG.edit !== false;
  // `dead` and `lost` (below) are two names on purpose. `dead`: nothing can be written, because the hub is
  // out of reach or the document is gone from it (`meetDocGone`). `lost`: the outage banner is up, which
  // only an outage raises and only the hub's return clears.
  var editing = false, hash = CFG.hash, stale = false, dead = false;
  var asking = {}, telling = {}, tellQ = '';

  if (!canSave && !COMMENTS.length && !(CFG.malformed || []).length) {
    // No server and nothing to show: a copy of the file, forwarded or opened
    // directly. No chrome at all, exactly as before comments existed.
    console.info('[sheaf] read-only: opened without the sheaf hub. ' +
                 'Open ' + CFG.name + ' with sheaf to edit.');
    return;
  }

  // ---- text of a block, as offsets the server understands --------------------
  // Offsets count non-whitespace characters only, skipping every element the page
  // or the renderer added (data-rd-ui). The server projects the same block with
  // pandoc's sourcepos and counts the same way; whitespace between tags differs
  // between the two renders, the visible characters do not.
  function isUi(n) {
    for (var e = n.nodeType === 1 ? n : n.parentNode; e && e !== main; e = e.parentNode) {
      if (e.nodeType === 1 && e.hasAttribute('data-rd-ui')) return true;
    }
    return false;
  }
  function textNodes(root) {
    var nodes = [], tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) if (!isUi(tw.currentNode)) nodes.push(tw.currentNode);
    return nodes;
  }
  function blockOf(node) {
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i];
      for (var j = 0; j < b.nodes.length; j++) {
        var n = b.nodes[j];
        if (n === node || (n.nodeType === 1 && n.contains(node))) return b;
      }
    }
    return null;
  }
  function blockText(b) {
    var nodes = [];
    b.nodes.forEach(function (n) {
      if (n.nodeType === 3) nodes.push(n);
      else if (n.nodeType === 1 && !n.hasAttribute('data-rd-ui')) nodes = nodes.concat(textNodes(n));
    });
    return nodes;
  }
  // Non-whitespace characters before the point (node, offset) within the block.
  function countTo(nodes, node, offset) {
    var at = document.createRange();
    at.setStart(node, offset);
    at.collapse(true);
    var k = 0;
    for (var i = 0; i < nodes.length; i++) {
      var t = nodes[i];
      if (t === node) return k + t.nodeValue.slice(0, offset).replace(/\s+/g, '').length;
      if (at.comparePoint(t, t.nodeValue.length) > 0) break;   // t ends after the point
      k += t.nodeValue.replace(/\s+/g, '').length;
    }
    return k;
  }

  // ---- highlights -----------------------------------------------------------
  // The CSS Custom Highlight API paints the commented text without touching the
  // DOM, so highlights can never leak into what a save serialises.
  var HL = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined';
  var ranges = {};
  function containerOf(a) {
    for (var e = a.parentNode; e && e !== main; e = e.parentNode) {
      if (/^(P|LI|TD|TH|H[1-6]|BLOCKQUOTE|DD|DT|FIGCAPTION)$/.test(e.tagName)) return e;
    }
    return a.parentNode;
  }
  function rangeFor(c) {
    var a = anchors[c.id], q = (c.quote || '').replace(/\s+/g, '');
    if (!a || !q || c.orphan) return null;
    var box = containerOf(a), nodes = textNodes(box).filter(function (t) {
      return a.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_PRECEDING;
    });
    var flat = '', map = [];
    nodes.forEach(function (t) {
      for (var i = 0; i < t.nodeValue.length; i++) {
        if (/\s/.test(t.nodeValue[i])) continue;
        flat += t.nodeValue[i]; map.push([t, i]);
      }
    });
    var at = flat.lastIndexOf(q);
    if (at < 0) return null;
    var r = document.createRange();
    r.setStart(map[at][0], map[at][1]);
    var last = map[at + q.length - 1];
    r.setEnd(last[0], last[1] + 1);
    return r;
  }
  function paint(activeId) {
    if (!HL) return;
    var open = new Highlight(), res = new Highlight(), act = new Highlight();
    var showRes = document.body.classList.contains('rd-show-resolved');
    COMMENTS.forEach(function (c) {
      var r = ranges[c.id] || (ranges[c.id] = rangeFor(c));
      if (!r) return;
      if (c.id === activeId) act.add(r);
      else if (c.status === 'open') open.add(r);
      else if (showRes) res.add(r);
    });
    CSS.highlights.set('rd-open', open);
    CSS.highlights.set('rd-resolved', res);
    CSS.highlights.set('rd-active', act);
  }

  // ---- chrome ---------------------------------------------------------------
  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    for (var k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (html != null) e.innerHTML = html;
    e.setAttribute('data-rd-ui', '');
    return e;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch];
    });
  }

  var btn = el('button', { id: 'rd-menu-btn', title: 'Menu', 'aria-label': 'Menu' },
               '☰<span class="rd-dot"></span>');
  var menu = el('div', { id: 'rd-menu', role: 'menu' });
  var toast = el('div', { id: 'rd-toast' });
  var panel = el('aside', { id: 'rd-panel' });
  // A quiet line that stays until the hub says hello again (hub-stopping).
  var notice = el('div', { id: 'rd-notice', role: 'status' });
  notice.hidden = true;
  document.body.appendChild(btn);
  document.body.appendChild(menu);
  document.body.appendChild(toast);
  document.body.appendChild(panel);
  document.body.appendChild(notice);

  var openCount = function () {
    return COMMENTS.filter(function (c) { return c.status === 'open'; }).length;
  };

  function buildMenu() {
    var h = '<div class="rd-state" id="rd-state"></div>';
    // Work on this (CFG.work): on a member's page of a sheaf, the ways to work on its session (SPEC 10.2).
    if (canEdit || CFG.work) h += '<div class="rd-group">Document</div>';
    if (canEdit) {
      h += '<button id="rd-edit"><span>Edit</span><span class="rd-key">E</span></button>' +
           '<button id="rd-save"><span>Save</span><span class="rd-key">Ctrl+S</span></button>';
    }
    if (CFG.work) h += '<button id="rd-work-btn"><span>Work on this</span></button>';
    h += '<div class="rd-group">Comments</div>' +
         '<button id="rd-show"><span>Show comments (' + openCount() + ')</span></button>';
    if (canSave) h += '<div class="rd-as">Commenting as ' + esc(CFG.me || 'unknown') +
                      ' · select text to comment</div>';
    if (canSave) {
      h += '<div class="rd-group">Agent</div><div class="rd-as" id="rd-agent">' + esc(agentLine()) + '</div>';
      h += '<div class="rd-group">Export</div>' +
           '<button id="rd-html" title="Download the share copy as one self-contained HTML file"><span>Share copy · HTML</span></button>' +
           '<button id="rd-pdf" title="Download the share copy as a PDF"><span>Share copy · PDF</span></button>';
    }
    menu.innerHTML = h;
    q('#rd-edit') && q('#rd-edit').addEventListener('click', function () { closeMenu(); setEditing(!editing); });
    q('#rd-save') && q('#rd-save').addEventListener('click', function () { closeMenu(); save(); });
    q('#rd-show').addEventListener('click', function () { closeMenu(); openPanel(); });
    q('#rd-work-btn') && q('#rd-work-btn').addEventListener('click', function (e) { e.stopPropagation(); closeMenu(); openWork(); });
    q('#rd-html') && q('#rd-html').addEventListener('click', function () { closeMenu(); grab('html'); });
    q('#rd-pdf') && q('#rd-pdf').addEventListener('click', function () { closeMenu(); grab('pdf'); });
    refresh();
  }
  function q(sel) { return menu.querySelector(sel); }

  // ---- diagnostics ----------------------------------------------------------
  // Every red toast, JS error and lost hub also goes to the hub's diagnostics log
  // (POST /_/diag, read with sheaf diag), so a race seen once on screen is not lost.
  // When the hub is the thing that went away, rows wait in localStorage (newest 50)
  // and go out on the next reconnect. Reporting never shows a toast of its own.
  var IQ = 'rd-incidents';
  function iqLoad() { try { return JSON.parse(localStorage.getItem(IQ) || '[]'); } catch (e) { return []; } }
  function iqSave(rows) { try { localStorage.setItem(IQ, JSON.stringify(rows.slice(-50))); } catch (e) {} }
  function sendIncident(row) {
    return fetch('/_/diag', { method: 'POST', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(row) }).then(function (r) { if (!r.ok && r.status !== 403) throw 0; });
  }
  function incident(kind, detail) {
    if (!canSave) return;
    var row = Object.assign({ kind: kind, when: new Date().toISOString(), doc: CFG.doc,
                              state: stateText(), dirty: dirty().length, stale: stale,
                              dead: dead, editing: editing }, detail || {});
    sendIncident(row).catch(function () { var q = iqLoad(); q.push(row); iqSave(q); });
  }
  function flushIncidents() {
    var q = iqLoad();
    if (!q.length) return;
    iqSave([]);
    q.forEach(function (row) {
      sendIncident(Object.assign({ queued: true }, row))
        .catch(function () { var r = iqLoad(); r.push(row); iqSave(r); });
    });
  }
  window.addEventListener('error', function (e) {
    incident('js-error', { message: e.message, where: (e.filename || '') + ':' + e.lineno });
  });
  window.addEventListener('unhandledrejection', function (e) {
    incident('js-rejection', { message: String(e.reason && e.reason.message || e.reason) });
  });

  var tmr;
  function say(msg, err) {
    if (err) incident('toast', { message: msg });
    toast.textContent = msg;
    toast.className = 'show' + (err ? ' err' : '');
    clearTimeout(tmr);
    tmr = setTimeout(function () { toast.className = ''; }, err ? 7000 : 2600);
  }
  function dirty() {
    return blocks.filter(function (b) {
      return editable.has(b.i) && ser(b) !== b.pristine;
    });
  }
  function stateText() {
    var d = dirty().length;
    return docGone ? 'Not on the hub'
      : stale ? 'Reload needed'
      : fileMissing ? 'File missing'
      : dead ? 'Hub unreachable'
      : !canSave ? 'Read-only'
      : !canEdit ? 'Export only'
      : d ? (d + ' block' + (d > 1 ? 's' : '') + ' changed')
      : (editing ? 'Editing' : 'Ready');
  }
  function refresh() {
    var d = dirty().length;
    btn.classList.toggle('on', editing);
    btn.classList.toggle('dirty', d > 0);
    btn.title = stateText();
    var st = q('#rd-state');
    if (st) st.textContent = stateText();
    var be = q('#rd-edit'), bs = q('#rd-save');
    if (be) be.firstChild.textContent = editing ? 'Done' : 'Edit';
    if (bs) bs.disabled = !(d > 0 && canSave && !stale && !dead);
  }

  function openMenu() { closeWork(); menu.classList.add('open'); refresh(); }     // the popover stands where the menu is
  function closeMenu() { menu.classList.remove('open'); }
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    if (menu.classList.contains('open')) closeMenu(); else openMenu();
  });
  document.addEventListener('click', function (e) {
    if (menu.classList.contains('open') && !menu.contains(e.target) && e.target !== btn) closeMenu();
  });

  // ---- Work on this (SPEC 10.2) ----------------------------------------------------------------
  // On a member's page of a sheaf, CFG.work holds the commands that work on its session (attach on the
  // box, fork to the member's machine) and the sessions of its front matter, newest first. The popover
  // stands where the menu was; Escape and a click outside close it, as they close the menu.
  var workPop = null;
  // "2026-10-28T05:12:03Z" reads "2026-10-28 05:12 UTC"; anything else is shown as written.
  function utcDate(d) {
    var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):\d{2}Z$/.exec(String(d || ''));
    return m ? m[1] + ' ' + m[2] + ' UTC' : String(d || '');
  }
  function cmdRow(text) {
    return '<div class="rd-cmd"><code>' + esc(text) + '</code><button type="button">Copy</button></div>';
  }
  // A laptop with nothing installed: uv's own installer, one line per system, folded under the fork. uv brings its
  // own Python, so the fork command needs no Python of its own.
  // A fresh Ubuntu Desktop has wget and no curl; macOS has curl and no wget.
  var UV_MACOS = 'curl -LsSf https://astral.sh/uv/install.sh | sh',
      UV_LINUX = 'wget -qO- https://astral.sh/uv/install.sh | sh',
      UV_WINDOWS = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"';
  function installUv() {
    var row = function (text) { return cmdRow(text).replace('class="rd-cmd"', 'class="rd-cmd rd-install"'); };
    return '<details class="rd-need"><summary>No uv on this laptop yet?</summary>' +
      '<p>macOS, in Terminal:</p>' + row(UV_MACOS) +
      '<p>Linux, in a terminal:</p>' + row(UV_LINUX) +
      '<p>Windows, in PowerShell or Command Prompt:</p>' + row(UV_WINDOWS) +
      '<p>Then open a new terminal and paste the command above.</p>' +
      '</details>';
  }
  function drawWork() {
    var w = CFG.work || {}, ss = (w.sessions || []).slice(0, 5);
    var h = '';
    if (w.attach) h += '<h4>Attach on the box</h4><p>James’s session is live in tmux. You join it in your terminal; ' +
                       'same transcript, same tools, James’s account.</p>' + cmdRow(w.attach);
    // The fork fetches the live session's transcript; the hub leaves `fork` out unless the live session runs on
    // the box and it keeps a copy of the box's transcripts (`sessions_dir`).
    // It asks for a sign-in code (9.13), which this button gets: shown once, in the popover only, never kept.
    if (w.fork) h += '<h4>Fork to your machine</h4>' + cmdRow(w.fork) +
                     '<p>Runs on your laptop: fetches the session through this hub, forks it under your name. ' +
                     'Needs uv there.</p>' + installUv() +
                     '<div class="rd-code"><button type="button">Get a sign-in code</button></div>';
    // A live session on a laptop is continued there: the hub holds no copy of it, and offers no fork of an older one.
    var live = liveSession(), none = w.live === 'laptop'
      ? 'The live session runs on ' + upper(live.member) + '’s machine, ' + live.host + ': open it there. This hub keeps no copy of it to fork.'
      : 'Nothing to fork from this hub: it keeps no copy of the box’s transcripts.';
    // Whether a Tell reaches that fork now: its relay connected or not (9.14).
    if (w.live === 'laptop' && 'relay' in w) h += '<p class="rd-relay">' + esc(w.relay
      ? 'Tell goes to ' + upper(live.member) + '’s session on ' + live.host + '.'
      : upper(live.member) + '’s session on ' + live.host + ' is not connected: Tell works again when it is.') + '</p>';
    h += '<h4>Sessions</h4>' + (ss.length ? ss.map(function (x) {
      return '<div class="rd-sess">' + esc(upper(x.member)) + ' on ' + esc(x.host) + ' · ' + esc(utcDate(x.date)) + '</div>';
    }).join('') : '<p class="rd-none">No session yet.</p>') +
    (ss.length && !w.fork ? '<p class="rd-none">' + esc(none) + '</p>' : '');
    workPop.innerHTML = h;
    Array.prototype.forEach.call(workPop.querySelectorAll('.rd-cmd button'), function (b) {
      b.addEventListener('click', function () { copyCommand(b.previousElementSibling); });
    });
    var get = workPop.querySelector('.rd-code button');
    if (get) get.addEventListener('click', function () { getCode(get.parentNode); });
  }
  // A sign-in code for the fork (9.13): POST /_/code, and the code shown once in `box`. It is not put on the
  // clipboard by itself, and drawing the popover again forgets it; a lost code is replaced by a new one.
  async function getCode(box) {
    var b = box.querySelector('button'), line = box.querySelector('p');
    var tell = function (text) {
      b.disabled = false;
      if (!line) line = box.appendChild(el('p', { 'class': 'rd-none' }));
      line.textContent = text;
    };
    b.disabled = true;
    try {
      var res = await fetch('/_/code', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                         body: JSON.stringify({ doc: CFG.doc }), cache: 'no-store' });
      var j = {};
      try { j = await res.json(); } catch (e) { /* not JSON: said by its status below */ }
      if (!res.ok || typeof j.code !== 'string') return tell(j.error || 'The hub answered ' + res.status + '.');
      box.innerHTML = cmdRow(j.code) + '<p>Good for 10 minutes, for this sheaf only. Paste it when ' +
                      'the command above asks for it. It is shown once.</p>';
      var c = box.querySelector('.rd-cmd button');
      c.addEventListener('click', function () { copyCommand(c.previousElementSibling); });
    } catch (e) {
      tell('The hub is unreachable: try again in a moment.');
    }
  }
  function openWork() {
    if (!workPop) {
      workPop = el('div', { id: 'rd-work', role: 'dialog', 'aria-label': 'Work on this' });
      document.body.appendChild(workPop);
    }
    drawWork();
    workPop.hidden = false;
  }
  function workOpen() { return !!workPop && !workPop.hidden; }
  function closeWork() { if (workPop) workPop.hidden = true; }
  // The clipboard where the browser lends it (a secure context); else the command is selected, for Ctrl+C.
  function copyCommand(code) {
    var text = code.textContent;
    var pick = function () {
      var r = document.createRange();
      r.selectNodeContents(code);
      var s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
      say('Selected: press Ctrl+C to copy.');
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { say('Copied'); }, pick);
    } else pick();
  }
  document.addEventListener('click', function (e) {
    if (workOpen() && !workPop.contains(e.target) && e.target !== btn && !menu.contains(e.target)) closeWork();
  });

  function setEditing(on) {
    if (!canEdit) return;
    editing = on;
    document.body.classList.toggle('rd-editing', on);
    blocks.forEach(function (b) {
      var ok = editable.has(b.i);
      b.nodes.forEach(function (n) {
        if (n.nodeType !== 1) return;
        if (ok && on) n.setAttribute('contenteditable', 'true');
        else n.removeAttribute('contenteditable');
        n.classList.toggle('rd-locked', on && !ok);
        if (on && !ok) n.title = LOCKED_TIP; else if (n.title === LOCKED_TIP) n.removeAttribute('title');
      });
    });
    hideCommentBtn();
    refresh();
  }

  // Keeps scroll position (and the open comment) across the reloads that follow
  // every comment write and every outside change.
  function reloadKeep(openId) {
    if (docGone) return;        // it would load another folder's document, or none (meetDocGone)
    if (pressOpen) { waitForPress({ open: openId, keep: true }); return; }     // as in settle (SPEC 10.11)
    try {
      if (pressSaid && Date.now() < pressSaid.until) sessionStorage.setItem('rd-press-said', pressSaid.text);
      sessionStorage.setItem('rd-keep', JSON.stringify({ doc: CFG.doc, y: window.scrollY, open: openId || null,
                                                         panel: panel.classList.contains('open'),
                                                         known: counts(), editing: editing,
                                                         caret: caretNow(), held: heldReload,
                                                         interrupted: Object.keys(interrupted), sent: sentBox }));
    } catch (e) {}
    location.reload();
  }

  // ---- the caret across a reload ---------------------------------------------
  // A merge or an outside change reloads the page. Typing then has to carry on
  // where it was, so the caret is kept as (block, non-whitespace characters
  // before it, the block's opening words). The words find the block again when
  // paragraphs were added or removed above it; the count survives the whitespace
  // differences between the two renders, and spills into the next block when a
  // paragraph was split in two by the save.
  function squashText(nodes) {
    return nodes.map(function (t) { return t.nodeValue; }).join('').replace(/\s+/g, '');
  }
  function caretNow() {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount || !main.contains(sel.anchorNode)) return null;
    var b = blockOf(sel.anchorNode);
    if (!b) return null;
    var nodes = blockText(b);
    return { i: b.i, off: countTo(nodes, sel.anchorNode, sel.anchorOffset),
             head: squashText(nodes).slice(0, 40) };
  }
  function placeCaret(k) {
    if (!k) return;
    var at = -1;
    blocks.forEach(function (b, n) {
      if (k.head && squashText(blockText(b)).indexOf(k.head) === 0 &&
          (at < 0 || Math.abs(b.i - k.i) < Math.abs(blocks[at].i - k.i))) at = n;
    });
    if (at < 0) blocks.forEach(function (b, n) { if (b.i === k.i) at = n; });
    if (at < 0) return;
    var off = k.off;
    for (var n = at; n < blocks.length; n++) {
      var nodes = blockText(blocks[n]);
      for (var x = 0; x < nodes.length; x++) {
        var v = nodes[x].nodeValue;
        for (var c = 0; c <= v.length; c++) {
          if (off === 0 && (c === v.length || !/\s/.test(v[c]))) {
            var host = nodes[x].parentNode.closest && nodes[x].parentNode.closest('[contenteditable="true"]');
            if (host) host.focus({ preventScroll: true });
            var r = document.createRange();
            r.setStart(nodes[x], c);
            r.collapse(true);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(r);
            return;
          }
          if (c < v.length && !/\s/.test(v[c])) off--;
        }
      }
    }
  }

  // Every write: an absolute /_/ path, a JSON body that names the document, and no
  // token header (the hub reads the browser's session cookie).
  // A comment is sent from a form that removes itself as it is sent, so while its POST is in
  // flight nothing on screen shows it is being written. `writes` counts the POSTs in flight;
  // a reload that the hub asks for (a new version, a rotated key) waits in `afterWrites` until
  // the last one is answered, and then looks at the screen again.
  // A save or a comment is also counted in `ownWrites` while it is out: the hub tells every tab
  // of it, this one too, and that event can come before the answer (see `heard`).
  var UNREACHABLE = 'The hub is unreachable; nothing was saved. Your edits stay on screen.';
  var DOC_GONE = 'Nothing was sent or saved: this document is no longer on the sheaf hub.';
  // A write that is never answered held its form, the reloads and the events of the page for as long as
  // the page was open. The page stops waiting after WAIT and the write fails, as LATE says. The hub is not
  // always quicker: a comment renders the page again as a save does, under the same lock, so a long
  // document, or a save ahead of it, can hold one past WAIT while the hub writes it. A form's send carries a
  // request id (`rid`) for that: sent again, the same text goes with the same id and the hub writes it once,
  // and the `changed` event of the write names the id, so the page hears that a send it gave up on was
  // taken (`taken`). A save waits longer, SAVE_WAIT: a long document can take pandoc longer than WAIT, and it
  // holds no form. One the hub still has not answered then is given up as an unreachable hub is, so that
  // `saving`, `ownWrites` and `writes` fall and the page can be typed in and reloaded again; the hub may
  // have written it all the same, so the next send is that save again, under its request id (`unanswered`, see `save`).
  var SAVE_WAIT = 120000;
  var WAIT = 30000, LATE = 'The hub did not answer within ' + WAIT / 1000 + ' seconds. What you sent may have arrived all the same: look before you send it again.';
  // Three counters answer "is a send out", for three readers, so none is another's total. `writes`: every
  // POST, whatever its path, read by `afterWrites`, which waits for the last one before a reload (an upgrade,
  // a sign-out). `ownWrites`: the POSTs to /_/save and /_/comment only, the writes whose `changed` event the
  // hub also tells this page, read by `heard` and `checkText`, which hold what they would do until the last
  // one is answered; a standalone Ask, Tell, cancel or pin sends no such event, so counting them there would
  // hold events for as long as a job runs. `out` (below): the forms between their click and their answer,
  // each with the popover it holds, read by `writingNow`, `sendingIn` and the `sent*` questions.
  var writes = 0, afterWrites = [], docGone = false;     // docGone: no request goes out any more (meetDocGone)
  var ownWrites = 0, ownSeq = 0, held = [];       // ownSeq: how many of them have started
  var lateSends = {};          // the request ids of the sends the page gave up on, until the hub's event names them
  var lastLate = {};           // of those, the ones whose latest attempt was given up on (a send again may have failed otherwise)
  // The answer of a send started its Ask or Tell: the hub reports none that failed (`errKey`), and the send
  // is not `again`, which the hub took earlier and started nothing for.
  function took(j, errKey) { return !!j && !j[errKey] && !j.again; }
  // A send sent again under its id that fails for another reason is not one the page gave up on this time, but the
  // send before it may still be running at the hub, so its marker stays for the event that names it (taken).
  function notLate(body) { if (body.rid) delete lastLate[body.rid]; }
  function lateError(body) {
    if (body.rid) lateSends[body.rid] = lastLate[body.rid] = true;
    var e = new Error(LATE);
    e.late = true;
    return e;
  }
  async function post(path, body) {
    if (docGone) { var no = new Error(DOC_GONE); no.unreachable = true; notLate(body); throw no; }     // a whole sentence too
    var isSave = path === '/_/save';
    var own = isSave || path === '/_/comment';
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var stop = ctl ? setTimeout(function () { ctl.abort(); }, isSave ? SAVE_WAIT : WAIT) : null;
    var gaveUp = function () { return !!ctl && ctl.signal.aborted; };
    var gaveUpError = function () {
      if (!isSave) return lateError(body);
      var e = new Error(UNREACHABLE);
      e.unreachable = e.timedOut = true;
      return e;
    };
    writes++;
    if (own) { ownWrites++; ownSeq++; }
    try {
      var res;
      try {
        res = await fetch(path, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.assign({ doc: CFG.doc }, body)),
          signal: ctl ? ctl.signal : undefined
        });
      } catch (e) {
        if (gaveUp()) throw gaveUpError();
        var down = new Error(UNREACHABLE);
        down.unreachable = true;
        notLate(body);
        throw down;
      }
      var j = {};
      try { j = await res.json(); } catch (e) {}
      if (gaveUp()) throw gaveUpError();       // the answer started and stopped
      notLate(body);                           // answered, whatever it says (a send `again` too): this attempt was not given up on
      if (!res.ok || !j.ok) {
        var err = new Error(j.error || ('failed (' + res.status + ')'));
        err.status = res.status;
        err.code = j.code;
        throw err;
      }
      if (autosaveOwed && !isSave) setTimeout(payOwed, 0);    // after the caller has used its answer: the hub is there, so what an autosave missed goes now
      return j;
    } finally {
      clearTimeout(stop);
      writes--;
      if (!writes && afterWrites.length) {
        var again = afterWrites;
        afterWrites = [];
        setTimeout(function () { again.forEach(function (f) { f(); }); }, 50);   // after the caller has used its answer
      }
      // A timer, not a call: what awaits this answer takes it in (the new hash, the new
      // anchor) on the microtasks that follow the return, before the timer runs.
      if (own && !--ownWrites) setTimeout(replayHeld, 0);
    }
  }

  // What the toast says after a save that met a change in the file. `conflicts` is the
  // server's [{i, kind}]: 'locked' is a paragraph the file turned into a block this page
  // cannot edit (the page's text went into a comment), any other kind a paragraph changed
  // or deleted in the file (the page's version was kept). Its own function, with no
  // access to the page, so that a test can run it alone (tests/test_page_toast.py).
  function conflictNote(conflicts) {
    var n = conflicts.length;
    var locked = conflicts.filter(function (c) { return c.kind === 'locked'; }).length;
    if (locked === n) {
      return locked + ' paragraph' + (locked > 1 ? 's were' : ' was') +
             ' replaced in the file by a block this page cannot edit. The file’s block was kept; your text is in a comment by sheaf.';
    }
    var note = n + ' paragraph' + (n > 1 ? 's were' : ' was') +
               ' also changed in the file. Your version was kept; the file’s is in a comment by sheaf.';
    if (locked) {
      note += ' ' + locked + ' of them ' + (locked > 1 ? 'were' : 'was') +
              ' replaced by a block this page cannot edit: there the file’s block was kept and your text is in the comment.';
    }
    return note;
  }

  // One save at a time: autosave, Ctrl+S and the merge on an outside change all
  // come through here. A save against an older version of the .md is merged by
  // the server paragraph by paragraph (sheafmd.edit.merge_edits); only a
  // version the server no longer knows is refused.
  //
  // A save carries a request id (`rid`, SPEC 8.5). One the hub did not answer (given up after SAVE_WAIT, or the
  // hub away) is kept in `unanswered`, {rid, hash, sent}, and goes again first, as it was, with its id: the hub
  // answers `again` if it took it and writes it once if it did not, so a block the page split is not split
  // twice and the save after it names it (`saved`) whatever was typed meanwhile. The draft holds the id of
  // the save whose text it is (editDraftMirror), for a page that is gone by then.
  var saving = null, asTmr = null, autosaveOwed = false, unanswered = null;
  function sentEdits(sent) {
    return sent.map(function (x) {
      var e = { i: x.b.i, html: x.html };
      if (x.saved) e.saved = x.saved;
      return e;
    });
  }
  // An autosave the hub did not take is owed (see `save`). It is paid at the hello, when the stream is back, and
  // after the next request the hub answers, since a save that fails with the stream still open brings neither
  // (SPEC 10.7).
  function payOwed() {
    if (!autosaveOwed) return;
    if (dead) return;               // the outage banner is up: the stream coming back (streamBack) pays it, not a request that got through first
    autosaveOwed = false;
    if (!stale && !docGone && dirty().length) save(true);
  }
  async function save(quiet) {
    if (!canEdit) { say('This page has nothing to save to. Open the document with sheaf to edit it.', true); return false; }
    if (stale) { say('The document changed. Reload the page before saving again.', true); return false; }
    if (saving) { await saving; return save(quiet); }
    // A tick out names the text on disk: a save now would change it under the tick, which the hub would refuse.
    if (ticking) { await ticking; return save(quiet); }
    var d = dirty();
    if (!d.length) { unanswered = null; if (!quiet) say('Nothing changed'); return true; }
    var st = q('#rd-state');
    if (st) st.textContent = 'Saving…';
    var done, sent, reload = false, conflicts = [], j, note;
    saving = new Promise(function (r) { done = r; });
    try {
      for (var again = !!unanswered; ; again = false) {
        // A block saved while the page kept the hash of the text on screen goes with what that save sent
        // (ownSave), by which the hub knows the page's own save in the file when it merges this one (merge_edits).
        var req = unanswered || { rid: newRid(), hash: hash, sent: dirty().map(function (b) {
          return { b: b, html: ser(b), saved: b.ownSave || null };
        }) };
        sent = req.sent;
        unanswered = req;
        editDraftMirror();
        var was = hash;
        j = await post('/_/save', { hash: req.hash, edits: sentEdits(sent), rid: req.rid });
        unanswered = null;
        // A merged or remapped save brings a reload (reloadWhenFree, now or once a form is done with); until
        // then the page shows the old text and its block numbers, so it keeps the hash of that text and what is
        // saved meanwhile (a tick, an edit while a form holds the reload) is merged, not laid over the new one.
        // So does an answer of `again`: its hash is the text the first send wrote, not always the file's now.
        var kept = j.remap || j.merged || j.again;
        hash = kept ? was : j.hash;
        if (!kept && j.actions) drawActions(j.actions, j.hash);     // the buttons of the text the hash names (SPEC 10.11)
        // What was sent is now saved; anything typed while the request was out
        // stays dirty for the next save.
        sent.forEach(function (x) { x.b.pristine = x.html; x.b.ownSave = kept ? x.html : null; });
        editDraftMirror();
        reload = reload || !!(j.remap || j.merged);
        conflicts = conflicts.concat(j.conflicts || []);
        if (!again || !dirty().length) break;
      }
      note = j.changed.length + ' block' + (j.changed.length === 1 ? '' : 's') + ' → ' + CFG.name;
      if (j.skipped && j.skipped.length) {
        note += ' · skipped: ' + j.skipped.map(function (s) { return '#' + s[0] + ' ' + s[1]; }).join('; ');
      }
      if (conflicts.length) note = conflictNote(conflicts);
      if (reload) {
        try { sessionStorage.setItem('rd-toast', quiet && !conflicts.length ? '' : note); } catch (e) {}
        done(); saving = null;
        reloadWhenFree(popId);
        refresh();
        return true;
      }
      if (!quiet) say(note);
      refresh();
      return true;
    } catch (e) {
      // An autosave the hub did not take, because it is away, says nothing: the banner tells the person once
      // the outage has lasted (outageBanner), and Ctrl+S, which they asked for, says it at once. One given up
      // after SAVE_WAIT has no banner behind it and still says so.
      // What it did not save is owed: payOwed saves it at the hello, when the stream is back or after the next request the hub answers, since no key may be pressed by then.
      var silent = quiet && e.unreachable && !e.timedOut;
      if (silent) autosaveOwed = true;
      else say(e.unreachable ? e.message : 'save failed: ' + e.message, true);     // UNREACHABLE is a whole sentence
      // A save the hub refused is not kept, nothing was written. One that got no answer may have been written:
      // it stays in `unanswered` and goes again with its id (so does one whose 200 was cut off before its body).
      if (e.status >= 400 && e.status < 500) unanswered = null;
      // A hub that forgot the id (a restart) takes it for a second save: the edits go with the HTML they
      // carry as `saved`, so it finds them in the file instead of writing them twice (SPEC 7.3).
      else if (unanswered) unanswered.sent.forEach(function (x) { x.saved = x.html; });
      // The edits are on screen and nowhere else. Typing mirrors them half a second after the last key,
      // but a task box ticks without one, so a save that fails mirrors them itself.
      editDraftMirror();
      refresh();
      return false;
    } finally {
      if (saving) { done(); saving = null; }
    }
  }

  // The file moved on (a session, the CLI, another program) or a save changed the block
  // structure: save what is still on screen, which the server merges, then
  // reload onto the merged file with scroll, edit mode and caret kept.
  var settling = false;
  async function settle(openId) {
    if (settling || docGone) return;
    // Every reload of an outside change, a held one too, comes here: one waits for an open press (SPEC 10.11).
    if (pressOpen) { waitForPress({ open: openId }); return; }
    settling = true;
    for (var n = 0; n < 3 && dirty().length; n++) {
      if (!(await save(true))) {
        settling = false;
        heldReload = false;             // nothing reloads; a later reload is not the held one
        stale = true; refresh();
        say('The file changed on disk and this edit could not be merged. Copy it, then reload the page.', true);
        return;
      }
    }
    // A form opened while those saves were out holds the reload like any other (reloadWhenFree). With no
    // save there was no time to open one, and a send whose answer called this still counts in `out`.
    if (n > 0 && writingNow({ sent: 'any' })) { settling = false; reloadWhenFree(openId, heldReload); return; }
    reloadKeep(openId);
  }

  // ---- export ---------------------------------------------------------------
  // The hub exports the share copy of the file, not this DOM, so the download is
  // byte-for-byte what --pdf and a forwarded .html already give. The cost of that
  // is that unsaved edits are not in it, which is silent and would be discovered
  // by the person receiving the document. So refuse instead, and say why.
  async function grab(kind) {
    if (docGone) { say(DOC_GONE, true); return; }
    var d = dirty().length;
    if (d) {
      say(d + ' block' + (d > 1 ? 's are' : ' is') + ' still only on screen. ' +
          'Save first (Ctrl+S) or the export will not have ' + (d > 1 ? 'them' : 'it') + '.', true);
      return;
    }
    if (kind === 'pdf') say('Printing the PDF with headless Chrome…');
    try {
      var res = await fetch('/_/export', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc: CFG.doc, kind: kind }) });
      if (!res.ok) {
        var msg = 'export failed (' + res.status + ')';
        try { msg = (await res.json()).error || msg; } catch (e) {}
        say(msg, true);
        return;
      }
      var cd = res.headers.get('Content-Disposition') || '', name = null;
      var m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
      if (m) { try { name = decodeURIComponent(m[1]); } catch (e) {} }
      if (!name) { m = /filename="([^"]+)"/.exec(cd); name = m ? m[1] : null; }
      var blob = await res.blob();
      var href = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = href;
      a.download = name || CFG.name.replace(/\.md$/, '') + '.' + kind;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Revoked late: Chrome has been seen to cancel a download whose blob URL
      // was released in the same tick as the click.
      setTimeout(function () { URL.revokeObjectURL(href); }, 30000);
      say(a.download + ' · ' + Math.round(blob.size / 1024) + ' KB → Downloads');
    } catch (e) {
      say('export failed: ' + e.message + ' — is sheaf still running?', true);
    }
  }

  // ---- popover --------------------------------------------------------------
  var pop = null, popId = null;
  // A kept comment (showKept) comes back once nothing else is open: a thread or another
  // passage's form opened over it does not take it away. Not under a mouse that is down: a press that
  // closes a thread may start a drag that ends where the kept comment is pinned, and a mouseup on the popover
  // is no selection of the document. It comes back after the mouseup (keptAfterMouse).
  var keptDue = false;
  function closePopover() {
    if (pop) {
      pop.remove(); pop = null; popId = null; paint(null); setTimeout(flushHold, 0);
      setTimeout(function () { if (mouseDown) keptDue = true; else drawKept(); }, 0);
    }
  }
  function drawKept() { if (!pop && canSave) showKept(); }
  function keptAfterMouse() { if (keptDue) { keptDue = false; setTimeout(drawKept, 0); } }

  // ---- never interrupt writing (SPEC 10.4, D23) ---------------------------------
  // "Writing" is a comment form open (a new comment, a reply, an edit) or one just sent
  // and not yet answered. A reload the page needs is held until then: it waits as a
  // pending flag with a quiet line above the form, and runs when the form is sent or
  // cancelled, with the thread just written kept open.
  // `heldReload` is why the reload that has just run was held ('text', 'arrived', 'restore'), false for one
  // that was not; `holdWhy` is the reason of the pending one; `holdOpen` the thread a new comment sent
  // behind another send has, which that reload opens.
  var reloadPending = false, heldReload = false, holdWhy = null, holdOpen = null;
  var HELD_SAYS = { text: 'The text changed while you wrote.', restore: 'Your restored edits are in.' };
  // The forms whose send is out, one {host, own, says, rid} each: the popover it was sent from, the thread
  // of that popover (null for a new comment), the line that popover shows meanwhile and the send's request
  // id. A send is per form: it holds back what would close the popover it comes back to, not every popover
  // on the page. A reload still waits for all.
  var out = [];
  // Thread ids are numbers in the hub's answers and strings in the DOM.
  function same(a, b) { return String(a) === String(b); }
  function sentOf(id) { return out.some(function (r) { return r.own !== null && same(r.own, id); }); }
  function sentHere() { return out.some(function (r) { return r.own === null ? r.host === pop : popId !== null && same(r.own, popId); }); }
  function newSentHere() { return out.some(function (r) { return r.own === null && r.host === pop; }); }
  // While a form's send is out its popover says so, where the form and the thread's buttons were: in
  // the popover it was sent from, and in its thread's popover opened again meanwhile. `p` is drawn
  // again from `out`, so every change of `out` and every redraw of a thread calls this.
  function sendingIn(p) {
    if (!p) return;
    var r = out.filter(function (x) {
      return x.own === null ? x.host === p : p === pop && popId !== null && same(x.own, popId);
    })[0];
    var line = p.querySelector(':scope > .rd-sending');
    if (!r) { if (line) line.remove(); return; }
    if (!line) { line = el('div', { 'class': 'rd-sending', role: 'status' }); p.appendChild(line); }
    line.textContent = r.says;
  }
  var HOLD = 'The document changed. The page refreshes when you send or cancel this comment.';
  // A kept comment (showKept) is a standing notice, not a form being written: its text is in
  // localStorage from every keystroke, and it is drawn again after any close. So it is neither
  // the open form nor a reason to hold a reload, and Escape and a click outside leave it alone.
  var OPEN_FORM = '.rd-form:not([data-done]):not([data-kept])';
  // A kept comment with the cursor in it, or a selection that has its Comment button: what a thread opened by
  // itself would take away. (A form with text typed in it is `writingNow`.)
  function writingElsewhere() { return !!cbtn || (!!pop && pop.hasAttribute('data-kept') && pop.contains(document.activeElement)); }
  function openForm() { return pop ? pop.querySelector(OPEN_FORM) : null; }
  // The open form of the popover's own thread: the form of another thread's failed send put here (data-for)
  // carries a line of its own about its thread.
  function ownForm() { return pop ? pop.querySelector(OPEN_FORM + ':not([data-for])') : null; }
  function standing() { return !!pop && pop.hasAttribute('data-kept') && !openForm(); }
  // Text is typed in a form and not sent yet: it is in no store (a new comment is kept from its send, a
  // reply or an edit from a failed one), so what drops the form drops the text. Every open form counts,
  // not the first only: the form of another thread's failed send that the store could not keep can sit
  // after an empty one.
  function formsWithText(page) {
    var forms = page ? document.querySelectorAll('.rd-form:not([data-kept])') : pop ? pop.querySelectorAll(OPEN_FORM) : [];
    return Array.prototype.filter.call(forms, function (f) {
      var t = f.querySelector('textarea');
      return !!(t && t.value.trim());
    });
  }
  // Is someone writing? One question, asked with the differences in `o`:
  //   page  text typed in any form of the page that is not a kept comment, one sent and not yet answered
  //         included (the notices of an upgrade and a sign-out); else the forms of the open popover
  //   text  only text typed counts; else an open form does, empty or not
  //   sent  a send out counts too: 'new' the send of a new comment from this popover, 'any' every form's
  function writingNow(o) {
    if (o.sent === 'any' && out.length > 0) return true;
    if (o.sent === 'new' && newSentHere()) return true;
    if (o.page) return formsWithText(true).length > 0;
    return o.text ? formsWithText().length > 0 : !!openForm();
  }
  // What the leave question asks about: text in a form that the store does not hold. A form filled from the
  // store (a reply or an edit whose send failed, a comment refused for its paragraph) holds the store's text
  // until that text is changed, and the store draws it again on the next page (f.kept, see textForm).
  function unkept() {
    return formsWithText().some(function (f) { return !(f.kept && f.kept(f.querySelector('textarea').value)); });
  }
  // Text is typed in the form: a stray click or Escape must not throw it away. A new comment being
  // sent from this popover counts too: it has no thread to come back to, so a failed send gives the
  // form back here. A reply or an edit that is out does not: a failed send goes back to its own
  // thread, so Escape and a click outside close its popover, as its badge does.
  // Text typed in the popover, a new comment sent from it, or a send out for its thread: a thread deleted
  // elsewhere then says "gone" in the popover instead of closing it.
  function holdsPopover() { return writingNow({ text: true, sent: 'new' }) || sentHere(); }
  // A badge, a panel item and the Comment button open something else, and opening it closes the
  // popover: with text in its form they wait, and say why, until it is sent or cancelled. So does a
  // new comment that is being sent: it has no thread to come back to. A reply or an edit that is
  // being sent does not wait for anything: a failed send goes back to its own thread.
  var BEING_SENT = 'Your comment is being sent. Wait for its answer first.';
  function writingFirst() {
    if (writingNow({ text: true })) { say('Send or cancel the comment you are writing first.'); return true; }
    if (newSentHere()) { say(BEING_SENT); return true; }
    return false;
  }
  // Escape or a click outside the open popover: it closes, unless that would throw typed text away.
  // A new comment that is being sent says why it stays.
  function leavePopover() {
    if (!writingNow({ text: true, sent: 'new' })) closePopover();
    else if (newSentHere()) say(BEING_SENT);
  }
  function holdNote() {
    var f = ownForm() || openForm();
    // The line of a thread gone from the file (`rd-gone`) and the one for another thread (`rd-for`) are holds of
    // their own; only this line says the reload waits.
    var said = f && Array.prototype.some.call(f.querySelectorAll('.rd-hold'), function (n) { return n.textContent === HOLD; });
    if (f && !said) f.insertAdjacentHTML('afterbegin', '<div class="rd-hold">' + HOLD + '</div>');
  }
  // A held reload keeps the hash of the text on screen until it runs, a merged save's among them (save). The hub
  // keeps only its newest versions of a document, so the page asks it to keep this one too (SPEC 7.4): what it
  // sends with that hash once the form is done (a save, the reply, an Ask, a Tell) is then taken however much
  // was written meanwhile. Once per version, not for every change that comes while it holds, nor while that
  // request is out: one that failed is made again with the next change after its answer, one the hub refused
  // (a version it no longer knows, 409) is not, and what is sent with that version is refused as before.
  // The hub drops a pin that is a week old (SPEC 7.4), and a form can be held longer: while the reload is held
  // the page pins the same version again once a day, and stops when the hold ends, the document is gone or the hub refuses.
  var keeping = null, renewTimer = null, renewing = null, pinnedAt = 0;
  var RENEW_MS = 24 * 3600 * 1000, RENEW_CHECK_MS = 3600 * 1000;
  function stopRenewing() {
    if (renewTimer) clearInterval(renewTimer);
    renewTimer = renewing = null;
  }
  // A timer stops while a laptop sleeps and the hub's week does not, so the page looks every hour at the wall
  // clock and pins again once the last pin is a day old. One timer for the page, aimed at the version held now.
  // A tick that finds the page cut off from the hub waits for the next; a failed renewal is made again then too.
  function renewPin(h) {
    renewing = h;
    if (renewTimer) return;
    renewTimer = setInterval(function () {
      if (!reloadPending) { stopRenewing(); return; }
      if (dead || Date.now() - pinnedAt < RENEW_MS) return;
      var r = renewing;
      post('/_/pin', { hash: r }).then(function () { pinnedAt = Date.now(); }, function (e) { if (e.status === 409 && renewing === r) stopRenewing(); });
    }, RENEW_CHECK_MS);
  }
  function holdReload(why) {
    reloadPending = true;
    why = why || 'text';          // a reload asked for with no reason of its own is the text having moved
    // Two reasons together: the text changed. A restore's own `changed` event arrives as a text change, so
    // beside a restore it is the restore that is told.
    holdWhy = !holdWhy || holdWhy === why ? why : holdWhy === 'restore' || why === 'restore' ? 'restore' : 'text';
    holdNote();
    var h = hash;
    if (!canSave) return;
    if (keeping !== h) pinnedAt = Date.now();
    renewPin(h);
    if (keeping === h) return;
    keeping = h;
    post('/_/pin', { hash: h }).catch(function (e) { if (keeping === h && e.status !== 409) keeping = null; });
  }
  // The thread of the open popover is gone from the file while a form in it holds text: the popover
  // stays with what was typed, says so, and closes once the form is sent or cancelled (flushHold).
  // A send's answer that would reload the page finds a form opened while the send was out (a new
  // comment), or the send of another form still out (a reply, then a new comment): the reload waits for
  // them too, and runs when the last of them is answered (flushHold). `mine` tells the answered send's
  // own entry of `out`, if it has one.
  function holdForOpenForm(mine, why) {
    if (!openForm() && !out.some(function (r) { return !mine(r); })) return false;
    holdReload(why);
    return true;
  }
  // The hub refuses what is sent to a thread that is gone ("no comment"), so the text can only be copied.
  var GONE = 'This thread was deleted elsewhere, so what you wrote cannot be sent to it. Copy it, then cancel.';
  function goneNote() { goneLine(ownForm()); }
  function goneLine(f) {
    if (!f) return;
    if (f.forgetKept) f.forgetKept();
    if (!f.querySelector('.rd-gone')) f.insertAdjacentHTML('afterbegin', '<div class="rd-hold rd-gone">' + GONE + '</div>');
    noSend(f);
  }
  // The buttons that would send a form to a thread that is gone: its text is to copy, or to cancel.
  function noSend(f) {
    f.setAttribute('data-nosend', '');
    Array.prototype.forEach.call(f.querySelectorAll('button[data-f]:not([data-f="no"])'), function (b) {
      b.disabled = true;
      b.title = GONE;
    });
  }
  function reloadWhenFree(openId, why) {
    if (docGone) return;
    // A press of an action button waits or is out (SPEC 10.11): the reload waits for its answer, as the list's does.
    if (pressOpen) { waitForPress({ open: openId, why: why }); return; }    // its form is not waited for either
    if (!writingNow({ sent: 'any' })) { settle(openId); return; }
    holdReload(why);
  }
  // The reload that a send's answer, a held reload or a refused comment asks for, keeping `openId`
  // open. When a reload was waiting for the form, the page says so once it has run (heldReload).
  function reloadNow(openId) {
    heldReload = reloadPending && holdWhy;
    var open = holdOpen || openId;
    reloadPending = false; holdWhy = null; holdOpen = null;
    stopRenewing();
    settle(open);
  }
  function flushHold() {
    if (pop && popId && !byId[popId] && !writingNow({ sent: 'any' })) { closePopover(); return; }
    if (!reloadPending || writingNow({ sent: 'any' })) return;
    reloadNow(popId);
  }
  // A new comment is kept in localStorage from the moment it is sent until the hub has
  // taken it, so a refusal, a failed request or a closed tab loses nothing. Its own
  // key, per hub port and document; nothing else is stored there. It holds a list, one
  // entry per quote ({quote, body, at, block, head, occ}): a send writes and clears its own entry
  // only. A reply or an edit is kept
  // the same way, one entry per thread and kind ({thread, born, about, kind, body, at}), comes back
  // in its form when the thread is opened (keptThreadForm) and is said beside the ☰ button meanwhile
  // (unsentLine). The thread is told by its id, its `at` and its quote together: next_id reuses the id
  // of a deleted last comment. An entry also holds the
  // request id it was sent with (`rid`), which its form sends again with the same text (textForm).
  var COMMENT_DRAFT_KEY = 'sheaf-comment-draft:' + DRAFTS_OF + ':' + CFG.doc;
  // Each entry holds the id of the root it was written under (`root`): two folders can hold one name on one
  // port, one after the other, and the key cannot tell them apart. An entry of another root is not this page's:
  // not listed, not sent, and kept when this page writes the store. One with no `root` (an older entry) is
  // this page's, and takes its root when the store is next written.
  function commentDraftsRaw() {
    var v;
    try { v = JSON.parse(localStorage.getItem(COMMENT_DRAFT_KEY) || '[]'); } catch (e) { return []; }
    return (Array.isArray(v) ? v : [v]).filter(function (d) {
      return d && typeof d.body === 'string' && (typeof d.quote === 'string' || typeof d.thread === 'string');
    });
  }
  function ofOtherRoot(d) { return !!CFG.root && d.root !== undefined && d.root !== CFG.root; }
  function commentDraftsLoad() { return commentDraftsRaw().filter(function (d) { return !ofOtherRoot(d); }); }
  // Every write of the store goes through here, so the line of replies and edits not sent, which says what the
  // store holds, is drawn again here: a writer added later cannot leave it behind.
  function commentDraftsSave(ds) {
    try {
      var all = commentDraftsRaw().filter(ofOtherRoot).concat(ds.map(function (d) {
        return d.root === undefined && CFG.root ? Object.assign({ root: CFG.root }, d) : d;
      }));
      if (all.length) localStorage.setItem(COMMENT_DRAFT_KEY, JSON.stringify(all)); else localStorage.removeItem(COMMENT_DRAFT_KEY);
    } catch (e) {}
    unsentLine();
  }
  // The entries `gone` names go, then `add` (if any) is added, in one write, stamped `at` now unless it brings its
  // own. For a form that knows which entry is its own: the same quote in another paragraph is another comment.
  function draftsReplace(gone, add) {
    var ds = commentDraftsLoad().filter(function (d) { return !gone(d); });
    if (add) ds.push({ quote: add.quote, body: add.body, block: add.block, head: add.head, tail: add.tail, occ: add.occ, rid: add.rid,
                       at: add.at || new Date().toISOString() });
    commentDraftsSave(ds);
  }
  // Is `d` the kept `kind` entry of the thread `c`: its id, its `at` (born) and its quote (about) all agree.
  // An older entry has no `born` and no `about` (it was told by its id): that is all it can agree on.
  function keptOf(d, c, kind) {
    return d.thread === c.id && d.kind === kind && (d.born === undefined || (d.born === c.at && d.about === c.quote));
  }
  // A thread can hold several entries of one kind, one per send: two pages of the document send a reply of
  // the same thread. An entry belongs to the form it came from by its send's request id (`rid`), or, once
  // its text was changed since it was sent (no `rid`: the id names the text sent), by the `of` that names that send.
  function sendOf(d) { return d.rid || d.of; }
  // Is the send of `d` out on a page right now? Its entry is written at the send (threadKeep's `out`, the time),
  // and written again without it when the send fails, so another page does not offer the text as unsent. A page
  // that was closed with its send out leaves the mark: it lapses after WAIT, when that page would have given up.
  var HELD = WAIT + 2000;
  function inFlight(d) { return typeof d.out === 'number' && Math.abs(Date.now() - d.out) < HELD; }
  // The reply or edit of a thread: written when it is sent, cleared when the hub has taken it or it is
  // cancelled. A thread that is gone (`c` unknown) keeps nothing. A write or a clear touches the entry of its own
  // form only: `rid` is the send it writes or ends, `line` the send its form's earlier entry came from (the
  // entry it replaces). The entry of another send of the thread and kind, one that another page has out, stays.
  // Only an entry with no id (an older entry's) goes with whichever write or clear comes.
  function threadKeep(c, kind, body, rid, line, out) {
    if (!c) return;
    var ends = body ? [rid, line] : [rid];
    var ds = commentDraftsLoad().filter(function (d) { return !keptOf(d, c, kind) || (sendOf(d) && ends.indexOf(sendOf(d)) < 0); });
    if (body) ds.push({ thread: c.id, born: c.at, about: c.quote, kind: kind, body: body, rid: rid, of: rid ? undefined : line || undefined,
                        out: out, at: new Date().toISOString() });
    commentDraftsSave(ds);
  }
  // The request ids a `changed` event named: the hub has them, whatever the send's answer says.
  var sawTaken = {};
  // A send was taken (its request id is in a `changed` event), maybe one that the page gave up on: its text
  // leaves the store, and its form the page unless the text was changed since (whenTaken, in textForm).
  // Says whether the page had given up on it.
  function taken(rid) {
    sawTaken[rid] = true;
    // The draft offered on load is the text of a save the hub took: it is in the file, and the offer goes.
    var offeredTaken = !!offered && offered.rid === rid;
    if (offeredTaken) { decided(); dropOffer(); lateSends[rid] = true; }
    var ds = commentDraftsLoad(), left = ds.filter(function (d) { return d.rid !== rid; });
    if (left.length < ds.length) commentDraftsSave(left);
    // The notice of kept comments is drawn again from what is left (closePopover does it), unless it is being typed in.
    var shown = ds.some(function (d) { return d.rid === rid && typeof d.quote === 'string'; });
    if (shown && pop && pop.hasAttribute('data-kept') && !pop.contains(document.activeElement)) closePopover();
    Array.prototype.forEach.call(document.querySelectorAll('.rd-form'), function (f) { if (f.whenTaken) f.whenTaken(rid); });
    var late = !!lateSends[rid];
    delete lateSends[rid];
    delete lastLate[rid];
    return late;
  }
  // The request ids `/_/doc` says the hub took: sends whose `changed` event this page missed (an outage, a tab
  // closed before the write ended). Each is handled as the event would, so the text kept for it goes.
  function meetTaken(j) {
    var ours = {};
    commentDraftsLoad().forEach(function (d) { if (d.rid) ours[d.rid] = true; });
    var late = (j && j.rids || []).filter(function (rid) {
      return ours[rid] || lateSends[rid] || (offered && offered.rid === rid);
    }).map(taken).some(Boolean);
    if (late) say('What you sent reached the hub after all.');
  }
  // The jobs the hub is running on this document and the read state as it has it now, from the start-up read
  // and from every check after a hello: an Ask or a Tell started while the page could not hear it shows in its
  // thread at once. Jobs are only added here; one that ended is taken off by its own event or by the reload.
  function takeJobs(j, heardBefore) {
    if (!j || j.ok === false) return;
    if (heardBefore !== jobsHeard) return;      // an event came while the answer was out: it is the newer word
    (j.asking || []).forEach(function (id) { asking[id] = true; });
    (j.telling || []).forEach(function (id) { telling[id] = true; });
    // The drops for James's window the hub still holds open (#115): the line comes back on a new load.
    if (toBox) (j.sent || []).forEach(function (d) {
      if (!byId[d.id]) return;
      if (!sentBox[d.id]) sentBox[d.id] = { n: (byId[d.id].replies || []).length, to: AGENT };
      sentBox[d.id].state = d.state;
      touched(d.id);
    });
    tellQ = j.question || '';
    Object.keys(j.seen || {}).forEach(function (id) { SEEN[id] = Math.max(SEEN[id] || 0, j.seen[id]); });
    reBadge();
    (j.asking || []).concat(j.telling || []).forEach(touched);
    refresh();
  }
  // A request id for a form's send: random, so that the same words sent twice on purpose are two comments.
  function newRid() {
    var b = new Uint8Array(12);
    crypto.getRandomValues(b);
    return Array.prototype.map.call(b, function (x) { return (x < 16 ? '0' : '') + x.toString(16); }).join('');
  }
  // A popover of kept texts: one form per entry of `ds`, drawn by `html`, its textarea filled with the entry's
  // text; `wire(f, d)` gives each form its buttons. `attr` names which popover it is.
  function keptForms(attr, ds, html, wire) {
    closePopover();
    var a = { id: 'rd-popover', role: 'dialog' };
    a[attr] = '';
    pop = el('div', a, ds.map(html).join(''));
    document.body.appendChild(pop);
    Array.prototype.forEach.call(pop.querySelectorAll('.rd-form'), function (f, i) {
      f.querySelector('textarea').value = ds[i].body;
      wire(f, ds[i]);
    });
  }
  // After the reload that follows a refusal (the paragraph changed): the quote and the
  // typed text come back; the next selection and Comment in that paragraph prefills the
  // form with them.
  function showKept() {
    var ds = commentDraftsLoad().filter(function (d) { return typeof d.quote === 'string' && d.body.trim(); });
    if (!ds.length) return;
    keptForms('data-kept', ds, function (d) {
      return '<div class="rd-quote">“' + esc(d.quote) + '”</div>' +
             '<div class="rd-form" data-kept><div class="rd-hold">Select the passage again; your comment is kept.</div>' +
             '<textarea' + NO_FILL + '></textarea><div class="rd-actions"><button class="rd-alt" data-f="no">Discard</button></div></div>';
    }, function (f, d) {
      var ta = f.querySelector('textarea');
      // This form's entry, and no other of the same quote: told by the id it was sent with and its stamp, which
      // an edit keeps (the entry is the person's comment still, not another send).
      var mine = function (x) { return x.quote === d.quote && x.at === d.at; };
      // A text changed since it was sent is no send's: it loses the request id, or the answer of the old send would take it.
      ta.addEventListener('input', function () {
        draftsReplace(mine, ta.value.trim() ? Object.assign({}, d, { body: ta.value, rid: ta.value === d.body ? d.rid : undefined }) : null);
      });
      f.querySelector('[data-f="no"]').addEventListener('click', function () { draftsReplace(mine); closePopover(); });
    });
    pin(pop);
  }
  // What tells a kept reply from a kept edit: its words in the line and the list, the form it comes back in,
  // and that only one's own comment is edited (`own`). An entry of another kind (none is written) is no thread's
  // to take (sendable), and is said as a reply.
  var KINDS = {
    reply: { one: 'reply', many: 'replies', own: false, went: 'its thread', also: 'Your reply to this thread', form: replyForm },
    edit: { one: 'edit', many: 'edits', own: true, went: 'its comment', also: 'Your edit of this comment', form: editForm }
  };
  // Is the comment `c` the person's own: the only one the thread offers to edit or delete, and the only kept edit it takes.
  function mine(c) { return c.by === CFG.me; }
  function kindOf(d) { return KINDS[d.kind] || KINDS.reply; }
  // Can the thread `c` take the kept reply or edit `d` in its form: `d` is its entry (keptOf), and an edit is
  // of the person's own comment, the only one the thread offers to edit.
  function sendable(d, c) {
    var k = KINDS[d.kind];
    return !!c && !!k && keptOf(d, c, d.kind) && (!k.own || mine(c));
  }
  // A reply or an edit whose send failed (threadKeep) is said in one line beside the ☰ button, on this page and
  // the next, before its thread is opened: "1 reply not sent · Show". The line sits in the strip the page keeps
  // free below its text for that button (render.py's bottom padding), so it covers no badge; Show lists them
  // (showUnsent). One whose send is out is not counted: its answer tells. The line, and its list if it is open,
  // follow the store: drawn again on every write of it here (commentDraftsSave) or on another page of the document
  // (the storage event below), and at the end of every send.
  var unsentBtn = null;
  function sendsKept() {
    return commentDraftsLoad().filter(function (d) {
      return typeof d.thread === 'string' && d.body.trim() && !inFlight(d) && !out.some(function (r) { return r.rid === d.rid; });
    });
  }
  var lapseTmr = null;
  function unsentLine() {
    if (!canSave) return;
    var ds = sendsKept(), listed = !!pop && pop.hasAttribute('data-unsent');
    // An entry whose send is out on another page is not listed; it is when its mark lapses, if that page says nothing.
    clearTimeout(lapseTmr);
    var lapse = commentDraftsLoad().filter(function (d) { return typeof d.thread === 'string' && inFlight(d); })
                            .map(function (d) { return d.out + HELD - Date.now(); });
    if (lapse.length) lapseTmr = setTimeout(unsentLine, Math.min.apply(null, lapse) + 50);
    if (!ds.length) {
      if (unsentBtn) unsentBtn.remove();
      unsentBtn = null;
      if (listed) closePopover();
      return;
    }
    if (!unsentBtn) {
      unsentBtn = el('button', { id: 'rd-unsent', type: 'button' });
      unsentBtn.addEventListener('click', function () { if (pop && pop.hasAttribute('data-unsent')) closePopover(); else showUnsent(); });
      document.body.appendChild(unsentBtn);
    }
    unsentBtn.textContent = Object.keys(KINDS).map(function (name) {
      var k = KINDS[name], n = ds.filter(function (d) { return kindOf(d) === k; }).length;
      return n ? n + ' ' + (n > 1 ? k.many : k.one) : '';
    }).filter(Boolean).join(' and ') + ' not sent · Show';
    if (listed) showUnsent();
  }
  // Another page of this document writes the same store (one origin, one key): a send it could not make, one it
  // got through, a Discard there, each comes here as a storage event (a page hears none of its own writes). The
  // kept comments' notice is left as it is: its text is being typed into, and it is drawn from the store again
  // after any close.
  window.addEventListener('storage', function (e) {
    if (e.key === null || e.key === COMMENT_DRAFT_KEY) unsentLine();      // null: the whole store was cleared
  });
  // The list the line opens: a popover above it, out of the text's way until asked for, that Escape, a click
  // outside or the line again close. Its forms are data-kept: their text is in the store, nothing to hold.
  // A list found empty (the store emptied without a word to this page) takes the line away instead.
  function showUnsent() {
    if (writingFirst()) return;
    var ds = sendsKept();
    if (ds.length) keptForms('data-unsent', ds, keptSend, keptSendButtons); else unsentLine();
  }
  // A kept reply or edit in that list, with the quote of its thread and its text, read-only: it is changed in
  // its thread's form, which sends it. One its thread can take opens that thread; one it cannot, its thread
  // deleted or its comment no longer the person's own (another name), is there to copy. Each can be discarded.
  function keptSend(d) {
    var c = byId[d.thread], k = kindOf(d), ok = sendable(d, c);
    var why = c && keptOf(d, c, d.kind) && k.own ? 'only your own comments can be edited' : k.went + ' was deleted';
    var line = 'Your ' + k.one + ' was not sent' + (ok ? '. It is kept: open its thread to send it.'
                                                     : ', and ' + why + ', so it cannot be sent. Copy it, then discard it.');
    return '<div class="rd-quote">“' + esc(d.about) + '”</div>' +
           '<div class="rd-form" data-kept><div class="rd-hold">' + esc(line) + '</div><textarea readonly></textarea>' +
           '<div class="rd-actions">' + (ok ? '<button data-f="open">Open the thread</button>' : '') +
           '<button class="rd-alt" data-f="no">Discard</button></div></div>';
  }
  // Discard clears the entry as its thread's Cancel does (threadKeep), the thread named as the entry names it:
  // it may be gone from the page. The line and the list follow that write.
  function keptSendButtons(f, d) {
    var open = f.querySelector('[data-f="open"]');
    if (open) open.addEventListener('click', function () { openComment(d.thread, d.kind, sendOf(d)); });
    f.querySelector('[data-f="no"]').addEventListener('click', function () {
      threadKeep({ id: d.thread, at: d.born, quote: d.about }, d.kind, null, sendOf(d));
    });
  }
  // Below the target when it fits, else above it, else pinned inside the viewport.
  // The popover's own max-height keeps it on screen; its thread scrolls inside it.
  function place(p, target) {
    p._target = target;
    if (!p.parentNode) document.body.appendChild(p);
    var r = target.getBoundingClientRect(), vh = window.innerHeight, h = p.offsetHeight;
    var w = p.offsetWidth, x = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - w - 16);
    var top = r.bottom + 8;
    if (top + h > vh - 16) top = r.top - 8 - h >= 16 ? r.top - 8 - h : Math.max(16, vh - 16 - h);
    p.style.left = Math.max(window.scrollX + 16, x) + 'px';
    p.style.top = (window.scrollY + top) + 'px';
  }
  // A target taken out of the page (forget, for a thread deleted) has no place to measure: the popover stays where it was.
  // The thread gives way to the form, but not below a comment's worth of itself (a shorter thread is not stretched).
  // Measured again on every move of the viewport: a thread that wraps differently at another width has another height.
  function keepThread() {
    var sc = pop.querySelector('.rd-scroll');
    if (!sc) return;
    sc.style.minHeight = '';
    sc.style.minHeight = Math.min(sc.scrollHeight, THREAD_FLOOR) + 'px';
  }
  function replace() {
    if (!pop) return;
    keepThread();
    if (dock()) return;
    undock();
    if (pop._target && pop._target.isConnected && pop.style.position !== 'fixed') place(pop, pop._target);
  }
  // A touch screen's keyboard shrinks the visual viewport and leaves the layout viewport as it was (iOS), so a form
  // placed in the text can lie behind it. A popover with a form is docked, fixed, to the foot of what can be seen,
  // and above the suggestion bar and the AutoFill pill that iOS draws over the page there.
  var THREAD_FLOOR = 84;                // px of a thread kept in view when the form takes the rest: the author line and two lines
  var KEY_ROOM = 56;                    // px kept clear above the keyboard, for its suggestion bar and the AutoFill pill
  var DOCK_GAP = 8, DOCK_SIDE = 16;     // px kept clear of the head of the visible area, and of its sides
  var KEY_MIN = 100, ZOOMED = 1.01;     // a visual viewport this much shorter is a keyboard; a larger scale is a pinch zoom
  var DOCKED = ['position', 'top', 'left', 'right', 'bottom', 'maxWidth', 'maxHeight', 'overflowY'];
  // What iOS reads to offer AutoFill (key, card, location) over the foot of a field: a text field that refuses it, with
  // no name or id of a credential, address or card, and the password managers' own opt-outs.
  var NO_FILL = ' autocomplete="off" spellcheck="true" data-lpignore="true" data-1p-ignore data-form-type="other"';
  // With the keyboard up, a popover with a field to write in is docked, fixed, to the head of what can be seen, its
  // quote, then its buttons, then the field, so that nothing of it is where the keyboard and its bars are drawn.
  function dock() {
    var v = window.visualViewport;
    // Not a pinch zoom (the visual viewport is then smaller than the layout one for that reason alone), and not a
    // kept comment's read-only form.
    if (!COARSE.matches || !v || v.scale > ZOOMED || v.height >= window.innerHeight - KEY_MIN ||
        !pop.querySelector('.rd-form:not([data-done]) textarea:not([readonly])')) return false;
    var st = pop.style;
    if (!pop._was) { pop._was = {}; DOCKED.forEach(function (k) { pop._was[k] = st[k]; }); }
    pop.classList.add('rd-docked');
    st.position = 'fixed';
    st.top = (v.offsetTop + DOCK_GAP) + 'px';
    st.bottom = 'auto';
    st.right = 'auto';
    st.left = (v.offsetLeft + DOCK_SIDE) + 'px';
    st.maxWidth = (v.width - 2 * DOCK_SIDE) + 'px';
    st.maxHeight = Math.max(0, v.height - KEY_ROOM - DOCK_GAP) + 'px';
    st.overflowY = 'auto';              // a screen too short for the form (landscape) scrolls it
    return true;
  }
  function undock() {
    if (!pop._was) return;
    DOCKED.forEach(function (k) { pop.style[k] = pop._was[k]; });
    pop.classList.remove('rd-docked');
    pop._was = null;
  }
  if (window.visualViewport) ['resize', 'scroll'].forEach(function (ev) {
    window.visualViewport.addEventListener(ev, function () {
      if (!COARSE.matches) return;
      // iOS pans the page sideways when a field takes focus: put it back (the page has nothing to the side).
      if (pop && window.visualViewport.scale <= ZOOMED && window.visualViewport.offsetLeft > 0) window.scrollTo(0, window.scrollY);
      if (pop) replace();
    });
  });
  // A frame resized, a phone turned, with a mouse as with a thumb: the thread wraps at another width.
  window.addEventListener('resize', function () { if (pop) keepThread(); });
  // A popover with no place in the text (a kept comment, a thread whose badge is hidden or gone) is pinned
  // beside the panel.
  function pin(p) { p.style.position = 'fixed'; p.style.top = '80px'; p.style.left = ''; p.style.right = '390px'; }

  // Comments and replies are written in markdown, an agent's especially. A small safe
  // subset is rendered: everything is escaped first, so no tag in a comment ever
  // becomes HTML, then bold, italic, inline code, http(s) links, lists, paragraphs.
  function mdLite(src) {
    var inline = function (t) {
      var codes = [];
      t = t.replace(/`([^`]+)`/g, function (m, c) { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
      t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
           .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
           .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, '$1<em>$2</em>')
           .replace(/(^|[^\w])_([^_\s][^_]*)_(?!\w)/g, '$1<em>$2</em>');
      return t.replace(/\u0000(\d+)\u0000/g, function (m, i) { return '<code>' + codes[+i] + '</code>'; });
    };
    return esc(src).split(/\n\s*\n/).map(function (block) {
      var lines = block.split('\n').filter(function (l) { return l.trim(); });
      if (!lines.length) return '';
      if (lines.every(function (l) { return /^\s*[-*+] /.test(l); })) {
        return '<ul>' + lines.map(function (l) { return '<li>' + inline(l.replace(/^\s*[-*+] /, '')) + '</li>'; }).join('') + '</ul>';
      }
      if (lines.every(function (l) { return /^\s*\d+[.)] /.test(l); })) {
        return '<ol>' + lines.map(function (l) { return '<li>' + inline(l.replace(/^\s*\d+[.)] /, '')) + '</li>'; }).join('') + '</ol>';
      }
      return '<p>' + lines.map(inline).join('<br>') + '</p>';
    }).join('');
  }
  // A reply's kind is its role, derived by the hub (SPEC 5.3): "answer" is an Ask
  // answer (blue), "action" is what a session did after a Tell (orange). Anything
  // else, a person or a reply without a role, is the plain name in ink.
  // The agent's own replies are signed with its display name in the file (SPEC 5.2); a reply
  // of the agent attached to this page is shown by the session's name, the file unchanged.
  function whoName(m) {
    var n = m.display || m.by || '';
    if ((m.role === 'answer' || m.role === 'action') && CFG.agent && CFG.agent.name &&
        n === CFG.agent.display) return CFG.agent.name;
    return n;
  }
  function whoHtml(m) {
    var name = esc(whoName(m));
    if (m.role === 'answer') return '<span class="rd-who rd-who-ask">' + name + '\u2019s answer</span>';
    if (m.role === 'action') return '<span class="rd-who rd-who-tell">' + name + '\u2019s action</span>';
    return '<span class="rd-who">' + name + '</span>';
  }
  function thread(c) {
    var h = '<div class="rd-quote">“' + esc(c.quote) + '”' +
            (c.orphan ? '<span class="rd-tag">text deleted</span>' : '') +
            (c.status === 'resolved' ? '<span class="rd-tag">resolved</span>' : '') + '</div>' +
            '<div class="rd-msg">' + whoHtml({ by: c.by, role: null }) + '<span class="rd-when">' +
            esc(c.at) + '</span><div class="rd-text">' + mdLite(c.body) + '</div></div>';
    (c.replies || []).forEach(function (r) {
      h += '<div class="rd-msg rd-reply">' + whoHtml(r) + '<span class="rd-when">' +
           esc(r.at) + '</span><div class="rd-text">' + mdLite(r.text) + '</div></div>';
    });
    return h;
  }
  function needClean() {
    if (dirty().length) { say('Save your edits first (Ctrl+S), then comment.', true); return true; }
    if (stale) { say('The document changed. Reload the page first.', true); return true; }
    return false;
  }

  // ---- comments update in place ---------------------------------------------
  // Every comment write returns the document's comments, and so do the `changed`
  // and `ask-done` events. The page takes them without reloading, so an open
  // popover stays open while the agent answers, and the answer appears in it.
  function flash(id) {
    var a = anchors[id];
    if (!a) return;
    a.classList.add('rd-new');
    setTimeout(function () { a.classList.remove('rd-new'); }, 6000);
  }
  function news(before, after, quiet) {
    var lines = [];
    after.forEach(function (c) {
      if ((quiet || []).indexOf(c.id) >= 0) return;
      var old = before[c.id];
      if (old === undefined) lines.push({ id: c.id, text: 'New comment ' + c.id + ' by ' + c.by });
      else if ((c.replies || []).length > old) {
        var r = c.replies[c.replies.length - 1];
        lines.push({ id: c.id, text: 'New reply on ' + c.id + ' by ' + whoName(r) });
      }
    });
    return lines;
  }
  function counts() {
    var k = {};
    COMMENTS.forEach(function (c) { k[c.id] = (c.replies || []).length; });
    return k;
  }
  // Returns false when a comment arrived that has no anchor on this page yet:
  // only a reload can place it, because only the server knows where it goes.
  function applyComments(d, quiet) {
    var missing = (d.comments || []).some(function (c) { return !c.orphan && !anchors[c.id]; });
    if (missing) return false;
    var before = counts();
    COMMENTS = d.comments || [];
    byId = {};
    COMMENTS.forEach(function (c) { byId[c.id] = c; });
    CFG.malformed = d.malformed || [];
    if (d.hash) hash = d.hash;
    if (d.telling) { telling = {}; d.telling.forEach(function (id) { telling[id] = true; }); }
    Object.keys(anchors).forEach(function (id) {
      var c = byId[id], a = anchors[id];
      if (!c) { forget(id); return; }
      var keep = a.classList.contains('rd-new');
      a.className = anchorClass(c) + (keep ? ' rd-new' : '');
    });
    ranges = {};
    var wasOpen = menu.classList.contains('open');
    buildMenu();
    if (wasOpen) openMenu();
    redrawPanel();
    if (pop && popId) { if (byId[popId]) touched(popId); else if (holdsPopover()) goneNote(); else closePopover(); }
    paint(popId);
    var n = news(before, COMMENTS, quiet);
    n.forEach(function (x) { flash(x.id); });
    if (n.length) say(n.map(function (x) { return x.text; }).join(' · '));
    return true;
  }
  // One thread of a hub answer, taken in place when the whole answer cannot be (a comment arrived that only a
  // reload places): the reply just sent shows in its open thread at once.
  function takeThread(j, id) {
    if (id === undefined || !byId[id]) return;
    var c = (j.comments || []).filter(function (x) { return same(x.id, id); })[0];
    if (!c) return;
    COMMENTS = COMMENTS.map(function (x) { return same(x.id, id) ? c : x; });
    byId[id] = c;
    touched(id);
  }
  // Take an anchor out of the page. Its block's pristine moves with it, so the
  // block does not look edited because the page itself changed it. A block that holds
  // words typed and not saved loses the anchor from its pristine only: taken from the
  // screen, the pristine would hold those words, and they would count as saved.
  function forget(id) {
    var a = anchors[id];
    delete anchors[id];
    if (!a || !a.parentNode) return;
    var b = blockOf(a), same = b && ser(b) === b.pristine, bare = clean(a.outerHTML);
    a.remove();
    if (b) b.pristine = same ? ser(b) : b.pristine.replace(bare, '');
  }
  // The pristine of block b once the page has put the anchor `a` into it, `was` being the block on screen
  // before: the anchor goes into the pristine at the same place, so that words typed in the block and not
  // saved still count as edited, as in forget. Such words on both sides of the anchor leave the pristine as
  // it is: the block stays edited, and its save writes the comment where the anchor is.
  function pristineWithAnchor(b, a, was) {
    var now = ser(b), pr = b.pristine, bare = clean(a.outerHTML), k = now.indexOf(bare), tail = was.length - k;
    if (pr === was) return now;
    if (k < 0) return pr;
    if (pr.slice(0, k) === was.slice(0, k)) return pr.slice(0, k) + bare + pr.slice(k);
    if (pr.length >= tail && pr.slice(pr.length - tail) === was.slice(k)) {
      return pr.slice(0, pr.length - tail) + bare + pr.slice(pr.length - tail);
    }
    return pr;
  }
  async function op(body, quiet) {
    if (needClean()) return null;
    body.hash = hash;
    try {
      var j = await post('/_/comment', body);
      // The popover of the thread that is gone closes, or stays with what is typed in it, as for a
      // thread deleted elsewhere (applyComments); another one, a new comment with its send out among
      // them, is not this answer's to close.
      if (body.op === 'delete') {
        forget(body.id);
        if (popId !== null && same(popId, body.id)) { if (holdsPopover()) goneNote(); else closePopover(); }
      }
      var mine = function (r) { return r.own !== null && same(r.own, body.id); };
      if (j.textSame === false || reloadPending) { if (!holdForOpenForm(mine, j.textSame === false ? 'text' : holdWhy)) reloadNow(j.id); return j; }
      // An answer that cannot be taken in place reloads as a new comment's does: settle() saves what is typed
      // in the text first, so the reload asks nothing.
      if (!applyComments(j, [j.id].concat(quiet || []))) {
        if (!holdForOpenForm(mine, 'arrived')) reloadNow(j.id);
        else takeThread(j, body.id);          // held: the thread this answer is for shows it until the reload
      }
      return j;
    } catch (e) {
      // The thread was deleted while this was out (410), and the event that says so waits behind this
      // write (heard): the page takes the thread off now, so that the form coming back knows it is gone.
      if (e.status === 410 && body.id) dropThread(body.id);
      say(notSent(e, SENDS[body.op]), true);
      return null;
    }
  }
  // Take a thread off the page before its deletion's event is taken in (applyComments does the rest then).
  function dropThread(id) {
    forget(id);
    delete byId[id];
    COMMENTS = COMMENTS.filter(function (c) { return !same(c.id, id); });
    if (popId !== null && same(popId, id)) { if (holdsPopover()) goneNote(); else closePopover(); }
  }

  // ---- the popover of one thread ----------------------------------------------
  // Two agent buttons that do different things, told apart by colour as well as
  // by name: Ask (blue) answers in the thread, like /btw, and changes nothing;
  // Tell (orange) sends the comment into the live session, which acts on it. Each
  // is offered only when the agent can do it (CFG.can); a job already running
  // always shows, so it can be cancelled.
  var ASK_TIP = 'Answers here in the thread, from a copy of the session. Reads, changes nothing.';
  function askTip() { return toBox ? 'Sends this to ' + whereTo() + '; ' + AGENT + ' answers here in the thread.' : ASK_TIP; }
  function tellTip() {
    return toBox ? 'Sends this to ' + whereTo() + ', to act on; ' + AGENT + ' replies here.'
                 : 'Sends this to ' + yourSession() + ', which acts on it and replies here.';
  }
  // A comment sent to James's window: its thread says so until a reply comes after it, with no spinner, as
  // nothing on the page waits for it (9.12). Kept by thread id with the number of replies it had then and the
  // name it went to, which a fork reported since does not change.
  var sentBox = {};
  function sentLine(id) {
    var c = byId[id];
    var s = sentBox[id];
    if (!s || !c || (c.replies || []).length > s.n) { delete sentBox[id]; return ''; }
    if (s.at) return '<div class="rd-msg rd-sent">Sent to ' + esc(s.at) + '; the answer appears in this thread.</div>';
    // What the box's supervisor said of the drop, read by the hub (9.15, #139).
    if (s.state === 'picked-up') return '<div class="rd-msg rd-sent">' + esc(s.to) + '’s window is opening' + DOTS + '</div>';
    if (s.state === 'delivered') return '<div class="rd-msg rd-sent rd-working">' + esc(s.to) +
      ' is working on it in his window' + DOTS + '</div>';
    return '<div class="rd-msg rd-sent">Sent to ' + esc(s.to) + '’s window; his answer appears in this thread.</div>';
  }
  // What a send with Ask or Tell started: on a box sheaf the line, counted from the thread as the hub's answer
  // holds it (the send's own reply in it), else the page's own wait.
  function started(id, k, j) {
    if (!took(j, k + 'Error')) return;
    if (toBox) {
      var c = (j.comments || []).filter(function (x) { return x.id === id; })[0] || byId[id];
      sentBox[id] = { n: ((c && c.replies) || []).length, to: AGENT };
      if (CAN.indexOf('relay-tell') >= 0) sentBox[id].at = whereTo();
    } else if (k === 'ask') asking[id] = true;
    else telling[id] = true;
  }
  // The Ask and Tell entries of a form: a working button for what the agent can do, a
  // disabled one carrying its line for what it cannot (textForm shows the lines).
  function agentButtons(askLabel, tellLabel) {
    return [canAsk ? { k: 'ask', label: askLabel, cls: 'rd-ask', tip: askTip() }
                   : { off: lineOf('ask'), label: askLabel, cls: 'rd-ask' },
            canTell ? { k: 'tell', label: tellLabel, cls: 'rd-tell', tip: tellTip() }
                    : { off: lineOf('tell'), label: tellLabel, cls: 'rd-tell' }];
  }
  // The lines under the disabled buttons, each once. A job still running keeps its own
  // busy button, so it needs no line.
  function offLines(skipAsk, skipTell) {
    var seen = [];
    if (!canAsk && !skipAsk) seen.push(lineOf('ask'));
    if (!canTell && !skipTell && seen.indexOf(lineOf('tell')) < 0) seen.push(lineOf('tell'));
    return seen.map(function (l) { return '<div class="rd-agent-line">' + esc(l) + '</div>'; }).join('');
  }
  function offButton(what, label) {
    return '<button class="rd-alt rd-na rd-' + what + '" disabled title="' + esc(lineOf(what)) + '">' + esc(label) + '</button>';
  }
  var DOTS = '<span class="rd-dots" aria-hidden="true"><i></i><i></i><i></i></span>';
  function fillPopover(id) {
    var c = byId[id], sc = pop.querySelector('.rd-scroll');
    if (asking[id] || telling[id]) delete interrupted[id];       // sent again: no longer interrupted
    var atEnd = !sc || sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 4;
    // Every form that is still to be sent goes through the redraw, not the first one only: a failed send
    // whose text is not in the store stays on the page beside the form of this thread.
    var forms = Array.prototype.filter.call(pop.querySelectorAll('.rd-form'), function (x) { return !x.hasAttribute('data-done'); });
    pop.innerHTML = '<div class="rd-scroll">' + thread(c) +
      (asking[id] ? '<div class="rd-msg rd-reply rd-pending"><span class="rd-who rd-who-ask">' + esc(AGENT_UC) + '</span>' +
                    '<div class="rd-text">is answering' + DOTS + '</div></div>' : '') +
      (telling[id] ? '<div class="rd-msg rd-reply rd-pending rd-pending-tell"><span class="rd-who rd-who-tell">' + esc(AGENT_UC) + '</span>' +
                     (tellQ ? '<div class="rd-text">is waiting for your answer in your session: ' + esc(tellQ) + '</div>' +
                              answerButton() + '</div>'
                            : '<div class="rd-text">is working on it in your session' + DOTS + '</div></div>') : '') +
      sentLine(id) +
      (interrupted[id] ? '<div class="rd-msg rd-reply rd-interrupted"><span class="rd-who">' + esc(AGENT_UC) + '</span>' +
                         '<div class="rd-text">interrupted by a hub restart, send it again</div></div>' : '') + '</div>';
    var ans = pop.querySelector('.rd-answer');
    if (ans) ans.addEventListener('click', function () { jumpToSession(ans); });
    if (canSave) {
      var acts = el('div', { 'class': 'rd-actions' });
      acts.hidden = sentOf(id);      // a reply or an edit of this thread is out: its buttons wait for the answer
      acts.innerHTML = '<button data-a="reply">Reply</button>' +
        (asking[id] ? busy('ask', AGENT_UC + ' is answering')
         : canAsk ? '<button class="rd-alt rd-ask" data-a="ask" title="' + esc(askTip()) + '">Ask ' + esc(AGENT) + '</button>'
         : offButton('ask', 'Ask ' + AGENT)) +
        (telling[id] ? busy('tell', AGENT_UC + ' is working')
         : canTell ? '<button class="rd-alt rd-tell" data-a="tell" title="' + esc(tellTip()) + '">Tell ' + esc(AGENT) + '</button>'
         : offButton('tell', 'Tell ' + AGENT)) +
        '<button class="rd-alt" data-a="status">' + (c.status === 'open' ? 'Resolve' : 'Reopen') + '</button>' +
        (mine(c) ? '<button class="rd-alt" data-a="edit">Edit</button><button class="rd-alt" data-a="delete">Delete</button>' : '') +
        offLines(asking[id], telling[id]);
      pop.appendChild(acts);
      acts.addEventListener('click', function (e) {
        var t = e.target.closest ? e.target.closest('button') : null;
        var a = t && t.getAttribute('data-a');
        if (!a) return;
        if (a === 'cancel-ask' || a === 'cancel-tell') { cancel(id, a.slice(7)); return; }
        // On a box sheaf Ask and Tell carry a text for James: they open the reply form, which sends it (9.12).
        if ((a === 'ask' || a === 'tell') && toBox) { replyForm(id); return; }
        if (a === 'ask') { ask(id); return; }
        if (a === 'tell') { tell(id); return; }
        if (a === 'status') op({ op: 'status', id: id, status: c.status === 'open' ? 'resolved' : 'open' });
        else if (a === 'delete') op({ op: 'delete', id: id });
        else if (a === 'edit') editForm(id);
        else replyForm(id);
      });
    }
    if (forms.length) {
      forms.forEach(function (x) { pop.appendChild(x); });
      var a2 = pop.querySelector(':scope > .rd-actions');
      if (a2) a2.hidden = true;
    }
    sendingIn(pop);
    sc = pop.querySelector('.rd-scroll');
    if (atEnd) sc.scrollTop = sc.scrollHeight;
    replace();
  }
  // Text typed into a form that was sent (a failed send brought it back, or the store drew it) is kept as typed,
  // so a closed tab loses none of it; emptied, it leaves the store, as Cancel clears it (Escape and a click
  // outside never run Cancel). The request id stays only while the text is the one sent: it names that text.
  function keepTyped(id, kind, text, rid, line) {
    var c = byId[id];
    if (c) threadKeep(c, kind, text.trim() ? text : null, text.trim() ? rid : line, line);
  }
  // A reply or an edit is kept from its send until the hub has taken it (threadKeep), so a failed
  // send, a closed tab or a reload loses nothing; a null answer is a send that did not go.
  function editForm(id, text) {
    var c = byId[id];
    if (!c) return;          // the thread went (a 410) while its button was still drawn
    textForm(pop, text === undefined ? c.body : text, [{ k: 'ok', label: 'Save' }], function (t, k, rid, line) {
      threadKeep(c, 'edit', t, rid, line, Date.now());
      return op({ op: 'edit', id: id, body: t, rid: rid }).then(function (j) { if (j) threadKeep(c, 'edit', null, rid); return j; });
    }, function (line) { threadKeep(c, 'edit', null, line); }, 'Your edit is being sent…', function (t) { return keptFor(id, t, 'edit'); },
    function (t, rid, line) { keepTyped(id, 'edit', t, rid, line); });
  }
  function replyForm(id, text) {
    var c = byId[id];
    textForm(pop, text || '', [{ k: 'ok', label: 'Send reply' },
                               { k: 'res', label: 'Send and resolve' }].concat(
                               agentButtons('Send and ask ' + AGENT, 'Send and tell ' + AGENT)),
             function (t, k, rid, line) {
      // The Ask and the Tell go with the reply, as they do with a new comment: the hub starts
      // them when it takes it. A request of its own after the answer would race the reload
      // that op() may be starting, and be lost with the page. Taken before (`again`), the reply
      // started them then, and the page hears of them by their events.
      threadKeep(c, 'reply', t, rid, line, Date.now());
      return op({ op: 'reply', id: id, body: t, resolve: k === 'res', ask: k === 'ask', tell: k === 'tell', rid: rid }).then(function (j) {
        if (j) threadKeep(c, 'reply', null, rid);
        if (k === 'ask' || k === 'tell') { started(id, k, j); touched(id); }
        if (j && j.askError) say(j.askError, true);
        if (j && j.tellError) say(j.tellError, true);
        return j;
      });
    }, function (line) { threadKeep(c, 'reply', null, line); }, 'Your reply is being sent…', function (t) { return keptFor(id, t, 'reply'); },
    function (t, rid, line) { keepTyped(id, 'reply', t, rid, line); });
  }
  // Is `text` in the store as a reply or an edit (`kind`, else either) kept for the thread `id`? threadKeep
  // swallows a storage error (blocked site data, a full quota), so a form that was sent is not to be dropped
  // on its word. A thread that is gone keeps nothing: no form of it draws the text again.
  function keptFor(id, text, kind) {
    var c = byId[id];
    return !!c && commentDraftsLoad().some(function (d) {
      return typeof d.thread === 'string' && keptOf(d, c, kind || d.kind) && d.body === text;
    });
  }
  // The thread just opened gets back the form of a reply or an edit that was sent and not taken. It can hold
  // one of each: the one of `kind` comes first (Open the thread in the list of unsent ones asks for it), the
  // form says that the other is kept too, and that one is drawn once this one is sent or cancelled (textForm's
  // restore).
  function keptThreadForm(id, kind, which) {
    if (!canSave || sentOf(id)) return;    // a form of this thread is out: the kept text is that form's
    var c = byId[id];
    var ds = commentDraftsLoad().filter(function (x) { return sendable(x, c) && !inFlight(x); });    // not one that another page has out
    var d = ds.filter(function (x) { return which && sendOf(x) === which; })[0] ||
            ds.filter(function (x) { return x.kind === kind; })[0] || ds[0];
    if (!d) return;
    var rest = ds.filter(function (x) { return x !== d; }), also = rest.filter(function (x) { return x.kind !== d.kind; })[0] || rest[0];
    KINDS[d.kind].form(id, d);
    var f = ownForm();
    if (also && f) {
      f.insertAdjacentHTML('afterbegin', '<div class="rd-also">' + KINDS[also.kind].also + ' is kept too: it comes here once this ' +
                           KINDS[d.kind].one + ' is sent or cancelled.</div>');
    }
  }
  function openComment(id, kind, which) {
    var c = byId[id];
    if (!c) return;
    closePopover();
    hideCommentBtn();
    popId = id;
    pop = el('div', { id: 'rd-popover', role: 'dialog' });
    var target = anchors[id];
    if (target && target.offsetParent === null) target = null;
    document.body.appendChild(pop);
    touched(id);
    place(pop, target || btn);
    if (!target) pin(pop);
    var sc = pop.querySelector('.rd-scroll');
    sc.scrollTop = sc.scrollHeight;
    paint(id);
    keptThreadForm(id, kind, which);
  }
  // Ask: the session that rendered this page answers, in a fork that has the
  // whole conversation the document came from (the agent adapter's ask). The
  // popover stays open and shows the answer when it lands.
  // A running Ask or Tell shows as a busy button; hovering it turns it into
  // Cancel, and a click cancels. Tell already delivered gets a second message
  // telling the session to stop.
  function busy(what, label) {
    return '<button class="rd-alt rd-busy rd-' + what + '" data-a="cancel-' + what + '" title="Click to cancel">' +
           '<span class="rd-on">' + esc(label) + DOTS + '</span><span class="rd-off">Cancel</span></button>';
  }
  // "Answer <name>" brings the session's terminal forward. The page only says "this document's
  // session"; the hub runs the command of its own config (SPEC 4.3, 8.5), so the page names
  // no session and no command.
  function answerButton() {
    return CFG.agent && CFG.agent.jump
      ? '<button class="rd-alt rd-answer" data-a="answer" title="Bring the session to the front">Answer ' + esc(AGENT) + '</button>'
      : '';
  }
  async function jumpToSession(btn) {
    btn.disabled = true;
    try { await post('/_/jump', {}); }
    catch (e) { say(e.message, true); }
    finally { btn.disabled = false; }
  }
  // UNREACHABLE is the sentence of a save ("nothing was saved"); a request that saves nothing says what did not go out.
  var SENDS = { add: 'Your comment', reply: 'Your reply', edit: 'Your edit', status: 'The status change', 'delete': 'The deletion' };
  function notSent(e, what) {
    return e.unreachable && e.message === UNREACHABLE ? what + ' did not go out: the hub is unreachable.' : e.message;
  }
  async function cancel(id, what) {
    var off = function () { if (what === 'ask') delete asking[id]; else delete telling[id]; touched(id); };
    try {
      await post('/_/cancel', { id: id, what: what });
      off();
      say(what === 'ask' ? 'Ask ' + AGENT + ' cancelled.'
                         : 'Tell ' + AGENT + ' cancelled. If it had arrived, the session was told to stop.');
    } catch (e) {
      // Not answered within WAIT, the cancel may have arrived all the same, and the hub says nothing of one
      // that found nothing running: the job comes off as on an answer. A Tell still waiting shows again with
      // the hub's next snapshot (applyComments), an Ask still running ends in its thread.
      if (e.late) off();
      say(notSent(e, 'Cancel'), true);
    }
  }
  async function tell(id) {
    if (needClean()) return;
    try {
      await post('/_/tell', { id: id, hash: hash });   // the id names a thread of this text (SPEC 7.3)
      telling[id] = true;
      touched(id);
    } catch (e) { say(notSent(e, 'Tell ' + AGENT), true); }
  }
  async function ask(id) {
    if (needClean()) return;
    try {
      await post('/_/ask', { id: id, hash: hash });
      asking[id] = true;
      touched(id);
    } catch (e) { say(notSent(e, 'Ask ' + AGENT), true); }
  }
  // buttons: [{k, label}], the first is the primary one. done(text, k, rid) may return a promise;
  // it settles to null or false when nothing was sent, and the form comes back with its text.
  // cancelled() runs when the person cancels. `says` is the line its popover shows while its send is out.
  // `initial` is the text the form opens with, or the kept entry it is drawn from ({body, rid}). A text sent
  // again unchanged goes with the request id it was last sent with (`rid`, see WAIT). kept(text) says whether
  // the store holds `text` for this form (unkept). mirror(text), if given, runs on every keystroke in the form:
  // the text the store keeps for it follows what is typed (keepTyped), with the request id of the text as sent
  // while it is that text.
  function textForm(host, initial, buttons, done, cancelled, says, kept, mirror) {
    var old = host.querySelector('.rd-form');
    if (old) old.remove();
    var own = host === pop ? popId : null;       // the thread this form is for; a new comment has none
    var about = own !== null && byId[own] ? byId[own].quote : '';     // its quote, still known once it is gone
    var born = own !== null && byId[own] ? byId[own].at : null;       // its birth: next_id gives a deleted id to the next comment
    var offs = [];
    var f = el('div', { 'class': 'rd-form' },
      '<textarea' + NO_FILL + '></textarea><div class="rd-actions">' +
      buttons.map(function (b, i) {
        if (b.off) {
          if (offs.indexOf(b.off) < 0) offs.push(b.off);
          return '<button class="rd-alt rd-na ' + (b.cls || '') + '" disabled title="' + esc(b.off) + '">' + esc(b.label) + '</button>';
        }
        return '<button data-f="' + b.k + '" class="' + (i ? 'rd-alt ' : '') + (b.cls || '') + '"' +
               (b.tip ? ' title="' + esc(b.tip) + '"' : '') + '>' + esc(b.label) + '</button>';
      }).join('') + '<button class="rd-alt" data-f="no">Cancel</button>' +
      offs.map(function (l) { return '<div class="rd-agent-line">' + esc(l) + '</div>'; }).join('') + '</div>');
    f.kept = kept;
    host.appendChild(f);
    // The thread's own buttons would sit above the form's and ignore what is being
    // typed, so they step aside until the form is cancelled or its send is answered: a second
    // Reply, a Resolve or a Delete under a send that may still fail is not offered.
    var acts = host.querySelector(':scope > .rd-actions');
    if (acts) acts.hidden = true;
    // The popover this form belongs to, if it is open; the buttons are looked up again: a live
    // update may have rebuilt them.
    var vanished = function () { return own !== null && !byId[own]; };
    var home = function () { return own !== null ? (popId !== null && same(popId, own) ? pop : null) : (host.isConnected ? host : null); };
    var restore = function () {
      var h = home(), a = h && h.querySelector(':scope > .rd-actions');
      // They stay hidden while a form is still open in the popover (the text of another thread's failed
      // send that the store could not keep is one): Reply would remove it and Delete would close it.
      if (!a || (own !== null && sentOf(own)) || h.querySelector('.rd-form:not([data-done])')) return;
      a.hidden = false;
      if (own !== null) keptThreadForm(own);     // the other text the store keeps for this thread, if any
    };
    var ta = f.querySelector('textarea');
    var from = initial && typeof initial === 'object' ? initial : { body: initial || '' };
    // The text last sent, and its id: a form drawn from the store holds a text that was sent (an older store kept
    // no id with it).
    var sent = { text: initial && typeof initial === 'object' ? from.body : null, rid: from.rid || null };
    // The send this form's entry in the store came from, for its writes and its clear to find it by (threadKeep): the
    // id of the last send, or, for a text changed since it was sent, the `of` of the entry it was drawn from.
    var line = from.rid || from.of || null;
    ta.value = from.body;
    replace();
    ta.focus();
    // A send of this form failed and the form came back: it holds the text sent, which the store keeps for the
    // thread. A thread that is gone keeps nothing (keptFor): the text is on this form, to copy, and the store lets
    // it go once the page knows the thread is gone, whether before the form came back or after (the deletion's
    // event waits behind the page's own write). A form drawn from the store was not sent here: its entry stays.
    var failed = false;
    f.forgetKept = function () { if (failed && cancelled) cancelled(sent.rid); };
    var back = function () {
      f.removeAttribute('data-done');
      f.hidden = false;
      var at = home(), gone = vanished();
      failed = true;
      if (gone) f.forgetKept();
      if (!at && own !== null) {
        // The popover this form was sent from is not the one that is open: another thread was opened
        // meanwhile, or none. The form goes back to its own thread, not into the one that is open.
        // A popover with text typed in it is not taken over: when the text of this form is in the store
        // (threadKeep) it stays there, and the thread has it in its form again when it is opened; when it
        // is not (the store could not be written) the form stays on the page, here, and says whose it is.
        // A thread deleted elsewhere cannot be opened, and nothing would show its text from the store
        // again: its form stays on the page, beside the text typed here or in its own popover once more.
        // The thread opens only when nothing is being written or selected: opening it closes a kept comment
        // being typed in, takes the Comment button of a selection and the keyboard. The text is kept; the line says where.
        if (!gone && (writingNow({ text: true, sent: 'new' }) || writingElsewhere()) && keptFor(own, ta.value)) {
          say(lastLate[sent.rid] ? LATE + ' Your text is kept in the thread it was for.'
                                  : 'Not sent. Your text is kept in the thread it was for: open that thread to send it.', true);
          return;
        }
        if (writingNow({ text: true, sent: 'new' })) {
          var old = f.querySelector('.rd-for, .rd-gone');
          while (old) { old.remove(); old = f.querySelector('.rd-for, .rd-gone'); }     // "this thread" would be the open one
          f.setAttribute('data-for', '');
          f.insertAdjacentHTML('afterbegin', '<div class="rd-hold rd-for">This is for the thread “' + esc(about) + '”' +
                               (gone ? ', which was deleted elsewhere: it cannot be sent. Copy it, then cancel.' : ', not this one.') + '</div>');
          if (gone) noSend(f);
        } else if (gone) {
          closePopover();
          pop = host; popId = own;
          document.body.appendChild(host);
          pin(host);
          at = host;
        } else {
          openComment(own);
          var drawn = openForm();                     // keptThreadForm drew the kept text again
          if (drawn && drawn.querySelector('textarea').value === ta.value) { f.remove(); return; }
          at = pop;
        }
      }
      if (gone && !f.hasAttribute('data-for')) goneLine(f);
      at = at || pop || host;
      if (f.parentNode !== at) at.appendChild(f);
      var a = at.querySelector(':scope > .rd-actions');
      if (a) a.hidden = true;
      sendingIn(at);          // a popover shown again still has the line it had when it was left
      replace();
      ta.focus();
    };
    var go = function (k) {
      if (!ta.value.trim()) { ta.focus(); return; }
      // The hub refuses it, or writes it into the comment that took the id: it is to copy. The buttons are off
      // for the same reason (noSend), whether or not the thread has come back since.
      if (vanished() || own !== null && ((born !== null && byId[own].at !== born) || f.hasAttribute('data-nosend'))) {
        say(GONE, true);
        return;
      }
      var prev = line;
      if (ta.value !== sent.text || !sent.rid) sent = { text: ta.value, rid: newRid() };
      line = sent.rid;
      failed = false;
      f.setAttribute('data-done', '');
      f.hidden = true;
      var rec = { host: host, own: own, says: says, rid: sent.rid };
      out.push(rec);
      sendingIn(home());
      var end = function (answer) {
        out.splice(out.indexOf(rec), 1);
        sendingIn(home());
        // A send that did not go: its entry is no longer one that is out (another page may offer the text).
        if ((answer === null || answer === false) && !(sawTaken[sent.rid] && ta.value === sent.text)) keep();
        unsentLine();
        if (answer === null || answer === false) {
          // The hub took it, and said so before the page gave up (taken): the form goes, as when the event comes late.
          // Said after the held events: their news would cover it (the give-up lets them go on a timer).
          if (sawTaken[sent.rid] && ta.value === sent.text) { leave(); setTimeout(function () { say('What you sent reached the hub after all.'); }, 0); }
          else back();
        } else { f.remove(); restore(); }
        flushHold();
      };
      var res;
      try { res = done(ta.value, k, sent.rid, prev); } catch (e) { res = false; }
      Promise.resolve(res).then(end, function () { end(false); });
    };
    // The hub took a send of this form that the page had given up on (taken): the form goes, as on an answer,
    // unless it is being sent again or its text was changed since.
    var leave = function () {
      f.remove();
      restore();
      if (own === null && host === pop && !openForm()) closePopover();
      replace();
    };
    f.whenTaken = function (rid) {
      if (rid !== sent.rid || f.hasAttribute('data-done') || ta.value !== sent.text || !f.isConnected) return;
      leave();
      flushHold();
    };
    // Only a form that was sent follows the store (a failed send brought it back, or the store drew it).
    var keep = function () {
      // Not once another comment has taken the id of this form's thread: the store would tie the text to that one.
      var c = own !== null ? byId[own] : null;
      if (mirror && sent.text !== null && c && (born === null || c.at === born)) mirror(ta.value, ta.value === sent.text ? sent.rid : undefined, line);
    };
    if (mirror) ta.addEventListener('input', keep);
    // Cancel clears what the store keeps for the form before restore, which draws the thread's other kept text.
    f.addEventListener('click', function (e) {
      var k = e.target.getAttribute && e.target.getAttribute('data-f');
      if (k === 'no') { f.remove(); if (cancelled) cancelled(line); restore(); replace(); flushHold(); }
      else if (k) go(k);
    });
    ta.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); go(buttons[0].k); }
    });
  }
  main.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.rd-badge');
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    var id = b.parentNode.getAttribute('data-rd-id');
    if (writingFirst()) return;
    if (popId === id) closePopover(); else openComment(id);
  });
  document.addEventListener('mousedown', function (e) {
    if (pop && !standing() && !pop.contains(e.target) && !(e.target.closest && e.target.closest('.rd-badge, #rd-panel, #rd-unsent'))) leavePopover();
  });

  // ---- side panel -----------------------------------------------------------
  var filter = 'open', who = '';
  function openPanel() { panel.classList.add('open'); drawPanel(); }
  function closePanel() { panel.classList.remove('open'); delete panel.dataset.keeps; }
  // A change in the comments redraws the list when the panel is open, but not over the text of a refused draft
  // (`keeps`): that panel is where the text is copied from, and only opening the panel again replaces it.
  function redrawPanel() { if (panel.classList.contains('open') && !panel.dataset.keeps) drawPanel(); }
  // The right edge of the window opens the panel; a click anywhere else closes it.
  // It re-arms only after the pointer has left the edge, so Escape or a click-away
  // with the mouse still parked there does not bounce it open again.
  var EDGE = 6, edgeArmed = true;
  document.addEventListener('mousemove', function (e) {
    var w = document.documentElement.clientWidth;      // excludes the page scrollbar
    var atEdge = e.clientX >= w - EDGE && e.clientX < w;
    if (!atEdge) { edgeArmed = true; return; }
    if (!edgeArmed || e.buttons || panel.classList.contains('open')) return;
    edgeArmed = false;
    openPanel();
  });
  document.addEventListener('mousedown', function (e) {
    if (!panel.classList.contains('open')) return;
    var t = e.target;
    if (t.closest && t.closest('#rd-panel, #rd-popover, #rd-menu, #rd-work, #rd-menu-btn, #rd-comment-btn, .rd-badge')) return;
    closePanel();
  });
  function drawPanel() {
    var authors = [];
    COMMENTS.forEach(function (c) { if (authors.indexOf(c.by) < 0) authors.push(c.by); });
    var list = COMMENTS.filter(function (c) {
      return (filter === 'all' || c.status === filter) && (!who || c.by === who);
    });
    var item = function (c) {
      return '<button class="rd-item' + (c.status === 'resolved' ? ' rd-res' : '') + badgeClass(c) + '" data-id="' + esc(c.id) + '">' +
             '<span class="rd-num">' + esc(c.id.replace(/^c/, '')) + '</span><b>' + esc(c.by) + '</b> ' +
             esc((c.body || '').slice(0, 140)) + '<span class="rd-q">“' + esc(c.quote) + '”</span></button>';
    };
    var placed = list.filter(function (c) { return !c.orphan; }),
        orphans = list.filter(function (c) { return c.orphan; });
    var h = '<button class="rd-close" title="Close">×</button><h3>Comments</h3>' +
      '<div class="rd-filters">' +
      ['open', 'resolved', 'all'].map(function (f) {
        return '<button data-filter="' + f + '"' + (filter === f ? ' class="on"' : '') + '>' + f + '</button>';
      }).join('') +
      '<select><option value="">everyone</option>' + authors.map(function (a) {
        return '<option' + (a === who ? ' selected' : '') + '>' + esc(a) + '</option>';
      }).join('') + '</select></div>';
    h += placed.length ? placed.map(item).join('') : '<p class="rd-empty">No ' + (filter === 'all' ? '' : filter + ' ') + 'comments.</p>';
    if (orphans.length) h += '<h3>Text deleted</h3>' + orphans.map(item).join('');
    if ((CFG.malformed || []).length) {
      h += '<h3>Malformed</h3>' + CFG.malformed.map(function (m) {
        return '<div class="rd-item" style="cursor:default">line ' + m.line + ': ' + esc(m.reason) + '</div>';
      }).join('');
    }
    delete panel.dataset.keeps;
    panel.innerHTML = h;
    document.body.classList.toggle('rd-show-resolved', filter !== 'open');
    paint(popId);
  }
  panel.addEventListener('click', function (e) {
    var t = e.target.closest ? e.target.closest('button') : null;
    if (!t) return;
    if (t.classList.contains('rd-close')) { closePanel(); return; }
    if (t.hasAttribute('data-filter')) { filter = t.getAttribute('data-filter'); drawPanel(); return; }
    var id = t.getAttribute('data-id');
    if (id) {
      if (writingFirst()) return;
      var a = anchors[id];
      if (a && a.offsetParent !== null) a.scrollIntoView({ block: 'center' });
      // 60 ms on, the popover this would close may hold text typed, or a comment sent, since the click.
      setTimeout(function () { if (!writingFirst()) openComment(id); }, 60);
    }
  });
  panel.addEventListener('change', function (e) {
    if (e.target.tagName === 'SELECT') { who = e.target.value; drawPanel(); }
  });

  // ---- adding a comment -----------------------------------------------------
  var cbtn = null, pending = null;
  var mouseDown = false, offerTimer = null, thumbOn = false, thumbTimer = null;
  var COARSE = window.matchMedia('(pointer: coarse)');   // a touch screen: iOS draws a callout beside the selection
  var BAR_CLEAR = 24;                   // px between the touch bar and a selection before the bar moves out of its way
  var TAP_SLOP = 8, TAP_MOVE = 10;      // px a finger may be off the button, and may travel, and still tap it
  var SETTLE = 350;                     // ms a touch selection stands still before the button is offered
  var IN_UI = '#rd-popover, #rd-panel, #rd-menu, #rd-work, #rd-comment-btn';   // selections that are not the document's
  function unpaintWidened() { if (HL) CSS.highlights.delete('rd-widened'); }
  function dropCommentBtn() { if (cbtn) { cbtn.remove(); cbtn = null; } clearTimeout(thumbTimer); thumbOn = false; }
  function hideCommentBtn() { dropCommentBtn(); unpaintWidened(); }
  // One function decides what a selection is, on every mouseup and every settled selectionchange
  // (SPEC 10.4, D24): it is trimmed of what the renderer added, widened to the whole of a
  // formatted run it starts or ends in, and then either usable or refused with its reason, before any click.
  var WHY = {
    para: 'One paragraph at a time',
    cell: 'One table cell at a time',
    code: 'No comments in code, charts, images or raw HTML',
    ui: 'This text is not in the .md'
  };
  var RUN = /^(STRONG|B|EM|I|A|CODE|DEL|S|STRIKE|U|MARK)$/;
  var LINE = /^(P|LI|TD|TH|H[1-6]|DD|DT|FIGCAPTION|PRE)$/;
  function elementOf(n) { return n.nodeType === 1 ? n : n.parentNode; }
  function blockLineOf(n) {
    for (var e = elementOf(n); e && e !== main; e = e.parentNode) {
      if (LINE.test(e.tagName)) return e;
    }
    return null;
  }
  // The outermost formatted run a point sits in, within its line (inline code only; a
  // code block is a line of its own).
  function runAround(n) {
    var line = blockLineOf(n), run = null;
    for (var e = elementOf(n); e && e !== line && e !== main; e = e.parentNode) {
      if (RUN.test(e.tagName) && !e.closest('pre')) run = e;
    }
    return run;
  }
  // A point inside a run moves to the run's edge. A point past the run's last word (the
  // selection begins after the bold word) or before its first (it ends before it) stays.
  function widen(r) {
    var s = runAround(r.startContainer), e = runAround(r.endContainer), part = document.createRange();
    if (s) {
      part.setStart(r.startContainer, r.startOffset);
      part.setEnd(s, s.childNodes.length);
      if (part.toString().trim()) r.setStartBefore(s);
    }
    if (e) {
      part.setStart(e, 0);
      part.setEnd(r.endContainer, r.endOffset);
      if (part.toString().trim()) r.setEndAfter(e);
    }
  }
  function selectionTarget() {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    var r = sel.getRangeAt(0).cloneRange(), was = sel.getRangeAt(0);
    if (!main.contains(r.commonAncestorContainer) || !r.toString().trim()) return null;
    var fail = function (why) { return { error: why, rect: r.getBoundingClientRect() }; };
    var piece = function (t) {
      var v = t.nodeValue;
      return v.slice(t === r.startContainer ? r.startOffset : 0, t === r.endContainer ? r.endOffset : v.length);
    };
    var root = elementOf(r.commonAncestorContainer);
    var kept = textNodes(root).filter(function (t) { return r.intersectsNode(t) && piece(t).trim(); });
    if (!kept.length) return fail(WHY.ui);
    var last = kept[kept.length - 1];
    if (r.startContainer.nodeType !== 3 || isUi(r.startContainer)) r.setStart(kept[0], 0);
    if (r.endContainer.nodeType !== 3 || isUi(r.endContainer)) r.setEnd(last, last.nodeValue.length);
    widen(r);
    var b1 = blockOf(r.startContainer), b2 = blockOf(r.endContainer);
    if (!b1 || b1 !== b2 || blockLineOf(r.startContainer) !== blockLineOf(r.endContainer)) {
      var cell = function (n) { return elementOf(n).closest('td, th'); };
      // A cell and anything else in the block (another cell, or text beside the table) is one cell too many.
      var c1 = cell(r.startContainer), c2 = cell(r.endContainer);
      return fail(b1 && b1 === b2 && (c1 || c2) && c1 !== c2 ? WHY.cell : WHY.para);
    }
    if (!commentable.has(b1.i) || elementOf(r.startContainer).closest('pre')) return fail(WHY.code);
    var nodes = blockText(b1);
    var start = countTo(nodes, r.startContainer, r.startOffset),
        end = countTo(nodes, r.endContainer, r.endOffset);
    var quote = '';
    nodes.forEach(function (t) {
      if (r.intersectsNode(t)) quote += piece(t);
    });
    quote = quote.replace(/\s+/g, ' ').trim();
    if (end <= start || !quote) return null;
    // Redrawn, so the person sees what will be quoted. In edit mode the selection is what the
    // next keystroke replaces, so it stays as the person made it and the widened passage is
    // painted instead: typing over one word of a bold run or a link replaces that word only.
    if (r.compareBoundaryPoints(Range.START_TO_START, was) || r.compareBoundaryPoints(Range.END_TO_END, was)) {
      if (editing) {
        if (HL) CSS.highlights.set('rd-widened', new Highlight(r.cloneRange()));
      } else {
        sel.removeAllRanges();
        sel.addRange(r);
      }
    }
    return { block: b1.i, head: blockHead(b1), tail: blockTail(b1), occ: headOccurrence(b1), start: start, end: end, quote: quote, rect: r.getBoundingClientRect(), range: r.cloneRange() };
  }
  function offerComment() {
    unpaintWidened();                   // selectionTarget paints the passage again when this selection has one
    var t = selectionTarget();
    // The widened selection is redrawn and fires one more selectionchange: the button already there stands.
    if (t && !t.error && cbtn && pending && pending.block === t.block && pending.start === t.start && pending.end === t.end) return;
    dropCommentBtn();
    if (!t) return;
    pending = t;
    // A refused selection gets the button's place, disabled, with the reason as its label.
    cbtn = el('button', t.error ? { id: 'rd-comment-btn', disabled: '', title: t.error } : { id: 'rd-comment-btn' },
              t.error || 'Comment');
    document.body.appendChild(cbtn);
    if (COARSE.matches) {
      // A touch screen has a callout of its own (Copy, Search, ...) beside the selection, above or below it,
      // drawn over anything there: the button is a bar at the foot of the screen, fixed, clear
      // of the ☰ button. A selection that reaches the foot takes the bar to the head of the screen instead.
      cbtn.className = 'rd-bar';
      var band = cbtn.offsetHeight + BAR_CLEAR,
          barAtHead = t.rect.bottom > window.innerHeight - band && t.rect.top > band;   // a selection that fills the screen keeps the foot
      cbtn.style.top = barAtHead ? 'calc(8px + env(safe-area-inset-top, 0px))' : 'auto';
      cbtn.style.bottom = barAtHead ? 'auto' : 'calc(8px + env(safe-area-inset-bottom, 0px))';
    } else {
      // Under the selection and inside the screen.
      var left = window.scrollX + t.rect.right - cbtn.offsetWidth,
          least = window.scrollX + 8, most = window.scrollX + document.documentElement.clientWidth - cbtn.offsetWidth - 8,
          top = window.scrollY + t.rect.bottom + 6,
          foot = window.scrollY + window.innerHeight - cbtn.offsetHeight - 8;
      cbtn.style.left = Math.max(least, Math.min(left, most)) + 'px';
      cbtn.style.top = Math.max(window.scrollY + 8, Math.min(top, foot)) + 'px';
    }
    cbtn.addEventListener('mousedown', function (ev) { ev.preventDefault(); });
    // A thumb on the button may collapse the selection before the click arrives: the button stays meanwhile.
    cbtn.addEventListener('pointerdown', function () {
      thumbOn = true;
      clearTimeout(thumbTimer);
      thumbTimer = setTimeout(function () {   // a click that never came (the finger slid off) leaves no stale button
        thumbOn = false;
        if (!cbtn) return;
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed) hideCommentBtn();
        else if (!mouseDown && !document.getElementById('rd-popover')) offerComment();   // a selection made meanwhile was held back by the thumb: the button is for it now
      }, 2000);
    });
    if (!t.error) {
      var target = pending, btn = cbtn;
      cbtn.addEventListener('click', function () { newComment(target, btn); });
      // On a phone the browser can take a tap on a selection for the end of the selection (it clears it, or sends
      // no click). The form opens on touchend, with the selection the button was raised for, and the click that
      // would follow is cancelled with it.
      var from = null;
      cbtn.addEventListener('touchstart', function (ev) {
        if (ev.cancelable) ev.preventDefault();
        from = ev.changedTouches[0];
      });
      cbtn.addEventListener('touchend', function (ev) {
        if (ev.cancelable) ev.preventDefault();
        var f = ev.changedTouches[0], r = btn.getBoundingClientRect();
        // A finger that travelled (a scroll that began on the bar) is not a tap.
        if (!f || !from || Math.abs(f.clientX - from.clientX) > TAP_MOVE || Math.abs(f.clientY - from.clientY) > TAP_MOVE) return;
        if (f.clientX >= r.left - TAP_SLOP && f.clientX <= r.right + TAP_SLOP && f.clientY >= r.top - TAP_SLOP && f.clientY <= r.bottom + TAP_SLOP) newComment(target, btn);
      });
    }
  }
  // The mouse is down from mousedown to the next mouseup anywhere, or until the window loses focus
  // (a mouseup outside the page, or in another frame, never reaches it).
  document.addEventListener('mousedown', function () { mouseDown = true; }, true);
  document.addEventListener('mouseup', function () { mouseDown = false; }, true);
  window.addEventListener('blur', function () { mouseDown = false; keptAfterMouse(); });
  document.addEventListener('dragend', function () { mouseDown = false; keptAfterMouse(); }, true);
  document.addEventListener('mouseup', function (e) {
    if (!canSave || (e.target.closest && e.target.closest(IN_UI))) return;
    setTimeout(offerComment, 0);
  });
  // After the offer above: the Comment button of the drag is on the page before the kept comment is drawn again.
  document.addEventListener('mouseup', keptAfterMouse);
  // A selection made by touch (a long press, then the handles) changes the selection and sends no mouse
  // event (SPEC 10.4, D24), so the page also listens to `selectionchange`. Each step of a handle's drag
  // fires one, so the button waits until the selection has stood still for SETTLE ms. A selection
  // made with the mouse is left to `mouseup`: nothing is offered while a mouse button is held.
  document.addEventListener('selectionchange', function () {
    clearTimeout(offerTimer);
    if (!canSave || mouseDown) return;
    offerTimer = setTimeout(function () {
      var sel = window.getSelection(), anchor = sel && sel.anchorNode && elementOf(sel.anchorNode);
      if (mouseDown || document.getElementById('rd-popover')) return;   // not while a comment is written
      // The form's own text box, the panel and the menu hold selections of their own.
      if (anchor && anchor.closest && anchor.closest(IN_UI + ', input, textarea')) return;
      if (!sel || sel.isCollapsed) { if (!thumbOn) hideCommentBtn(); return; }   // a thumb on the button keeps it through a collapse
      offerComment();   // a selection that stands, thumb or not: the button is for it, so a second tap cannot reach the old passage
    }, SETTLE);
  });
  // Which block of those that open with the same 12 characters this is (0 for the first): a block added or
  // removed above changes a block's index, never its place among the blocks that open like it.
  function blockHead(b) { return squashText(blockText(b)).slice(0, 12); }
  // The 12 characters it ends with: a second key for a kept comment, for the paragraph that changed in its opening words.
  function blockTail(b) { return squashText(blockText(b)).slice(-12); }
  function headOccurrence(b) {
    var h = blockHead(b), n = 0;
    for (var k = 0; k < blocks.length && blocks[k] !== b; k++) if (blockHead(blocks[k]) === h) n++;
    return n;
  }
  function newComment(t, anchorEl) {
    if (needClean() || writingFirst()) return;
    closePopover();
    pop = el('div', { id: 'rd-popover', role: 'dialog' },
             '<div class="rd-quote">“' + esc(t.quote) + '”</div>');
    place(pop, anchorEl);
    hideCommentBtn();
    // A kept text belongs to the passage it was written for: any selection in the paragraph it was written
    // in (it changed, which is why the comment was refused) takes it into the form, and no selection of
    // another paragraph does, whatever its words. The paragraph is told by its opening words and which
    // occurrence of them it is (`head`, `occ`), not by its index: paragraphs added or removed above make
    // that index another paragraph, and a paragraph that opens like it (two tables with one header row) is
    // told by its place among them. The words are few (12 characters, caretNow keeps 40) because the change
    // that refused the comment is rarely in a paragraph's opening words; when it was, no block opens with
    // the entry's words any more and its quote tells it. An entry kept before `occ` existed is told by its
    // block when other blocks open alike; one kept before `head` existed, by its quote or its block, as it
    // always was. From then on this form's send or Cancel stands for it. Another passage opens empty, and
    // its send or Cancel writes and clears only its own entry.
    var ds = commentDraftsLoad().filter(function (x) { return typeof x.quote === 'string'; });
    var alike = blocks.filter(function (b) { return blockHead(b) === t.head; }).length;
    var heads = blocks.map(blockHead);
    var tails = blocks.map(blockTail);
    var d = ds.filter(function (x) {
              // Not an entry whose last words are those of another paragraph, and only of that one: it is that paragraph's.
              if (x.tail && x.tail !== t.tail && tails.filter(function (y) { return y === x.tail; }).length === 1) return false;
              return x.head && x.head === t.head && (x.occ !== undefined ? x.occ === t.occ : alike < 2 || x.block === t.block);
            })[0] ||
            ds.filter(function (x) { return !x.head && x.block === t.block; })[0] ||
            ds.filter(function (x) { return x.quote === t.quote && (!x.head || heads.indexOf(x.head) < 0); })[0] ||
            // The paragraph changed in its opening words and another one opens with the entry's: the words it ends
            // with, when no other paragraph ends with them.
            ds.filter(function (x) { return x.tail && x.tail === t.tail && x.head !== t.head && tails.filter(function (y) { return y === t.tail; }).length === 1; })[0];
    var was = d ? d.quote : t.quote, host = pop;
    var wrote = [];                       // the request ids of this form's sends (each text has its own): their entries are its own
    // This form's entries: the one it took into itself and those its own sends wrote, and no other: the same
    // quote in another paragraph is another comment.
    var own = function (x) { return (d && x.quote === d.quote && x.at === d.at) || wrote.indexOf(x.rid) >= 0; };
    var mine = function (r) { return r.own === null && r.host === host; };    // this form's entry of `out`
    textForm(pop, d || '', [{ k: 'ok', label: 'Comment' }].concat(agentButtons('Ask ' + AGENT, 'Tell ' + AGENT)),
             async function (text, k, rid) {
      if (needClean()) return false;
      wrote.push(rid);
      draftsReplace(own, { quote: t.quote, body: text, block: t.block, head: t.head, tail: t.tail, occ: t.occ, rid: rid });
      try {
        var j = await post('/_/comment', { op: 'add', block: t.block, start: t.start, end: t.end,
                                        quote: t.quote, body: text, hash: hash, ask: k === 'ask',
                                        tell: k === 'tell', rid: rid });
        // The page puts the anchor where the selection ended, as the server did in
        // the file, and moves that block's pristine with it: the block is not edited.
        var c = (j.comments || []).filter(function (x) { return x.id === j.id; })[0];
        var b = blockOf(t.range.endContainer);
        if (c && b) {
          var r = t.range.cloneRange(), before = ser(b), a = makeAnchor(c);
          r.collapse(false);
          r.insertNode(a);
          b.pristine = pristineWithAnchor(b, a, before);
        }
        if (k === 'ask' || k === 'tell') started(j.id, k, j);
        window.getSelection().removeAllRanges();
        draftsReplace(own);
        if (j.textSame === false || reloadPending || !applyComments(j, [j.id])) {
          // With another send out the reload waits for it (holdForOpenForm). This comment was taken, so its
          // popover goes; its thread is in the page that comes back.
          if (!holdForOpenForm(mine, j.textSame === false ? 'text' : reloadPending ? holdWhy : 'arrived')) reloadNow(j.id);
          else {
            holdOpen = j.id;
            // Its badge is on the page: a click on it finds the thread, though the reload that places it waits.
            // A thread of the same id that a held reload has not yet dropped (next_id reuses the id of a deleted last one) goes.
            if (c) {
              byId[c.id] = c;
              COMMENTS = COMMENTS.filter(function (x) { return !same(x.id, c.id); }).concat([c]);
            }
            if (pop === host && !writingNow({ text: true })) closePopover();
          }
          return true;
        }
        // The failed form of another thread may have come back into this popover during the send: it stays.
        if (!writingNow({ text: true })) openComment(j.id);
        if (j.askError) say(j.askError, true);
        if (j.tellError) say(j.tellError, true);
        return true;
      } catch (e) {
        // The paragraph changed under the comment: the page reloads onto the new text and
        // gives the quote and the typed text back (showKept); the draft holds them meanwhile.
        // With another send out the reload waits, and the kept popover takes this one's place meanwhile.
        if (e.status === 409 && e.code === 'select-again') {
          if (!holdForOpenForm(mine, 'text')) reloadNow(); else if (pop === host && !writingNow({ text: true })) closePopover();
          return true;
        }
        say(notSent(e, SENDS.add), true);
        return false;
      }
    }, function () { draftsReplace(own); }, 'Your comment is being sent…', function (text) {
      return commentDraftsLoad().some(function (x) { return own(x) && x.body === text; });
    });
    // The quote above is the selection's; the text below it may be a comment kept on other words.
    if (d && d.quote !== t.quote) {
      var f = host.querySelector('.rd-form'), ta = f && f.querySelector('textarea');
      if (ta) ta.parentNode.insertBefore(el('div', { 'class': 'rd-kept-quote' },
        'Your kept comment on \u201c' + esc(d.quote) + '\u201d is in this form.'), ta);
    }
  }

  // ---- keyboard -------------------------------------------------------------
  document.addEventListener('keydown', function (e) {
    var typing = e.target.isContentEditable ||
                 /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName || '');
    if (e.key === 'Escape') {
      // One thing per press, the first that applies.
      if (workOpen()) { e.preventDefault(); closeWork(); return; }
      if (pop && !standing()) { e.preventDefault(); leavePopover(); return; }
      if (panel.classList.contains('open')) { e.preventDefault(); closePanel(); return; }
      if (menu.classList.contains('open')) { e.preventDefault(); closeMenu(); return; }
      if (editing) { e.preventDefault(); setEditing(false); return; }
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      // Ctrl+S on a page that cannot save is someone expecting to save. Saying
      // why beats a shortcut that does nothing at all.
      if (canEdit) save();
      else say(canSave ? 'This document is not editable in the browser' +
                         (CFG.why ? ': ' + CFG.why : '') + '. Edit the markdown instead.'
                       : 'Opened without the sheaf hub, so there is nothing to save to.', true);
      return;
    }
    if (!canEdit || typing) return;
    if (!e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === 'e') {
      e.preventDefault(); setEditing(!editing);
    }
  });

  // While a save is out, the page must stay exactly what was sent: a merge or a
  // split paragraph reloads the page on the reply, and a keystroke typed in
  // between would be on screen only. A save takes a fraction of a second, and
  // autosave only starts once typing has paused.
  main.addEventListener('beforeinput', function (e) { if (saving || settling) e.preventDefault(); });

  // ---- Enter in a task item ---------------------------------------------------
  // The browser's own Enter in an <li> makes an <li> with no box, which the .md would hold as a plain item.
  // The convention (GitHub, Obsidian) is a task item of its own with an unticked box, and on an item with
  // nothing in it, the end of the list: what follows is a paragraph, and the items after it a list of their own.
  // The new nodes join the block they came from, so they are saved with it.
  var TASK_BOX = ':scope > input[type="checkbox"], :scope > label > input[type="checkbox"],' +
                 ' :scope > p > label > input[type="checkbox"]';
  main.addEventListener('beforeinput', function (e) {
    if (e.inputType !== 'insertParagraph' || e.defaultPrevented || !editing) return;
    var sel = window.getSelection();
    if (!sel.rangeCount) return;
    var range = sel.getRangeAt(0);
    var at = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentNode;
    var li = at && at.closest ? at.closest('li') : null;
    var box = li && main.contains(li) ? li.querySelector(TASK_BOX) : null;
    if (!box) return;
    if (!range.collapsed && !li.contains(range.endContainer)) { e.preventDefault(); return; }
    // across items the browser's own join would put the second item's box in the first one's words: Enter waits
    var cont = box.closest('label') || box.parentNode;       // what holds the item's words
    var list = li.parentNode, b = blockOf(list);
    var words = li.textContent.replace(/[\s\u200b-\u200d\u2060\ufeff]/g, '');
    // anything but the box and a break in the item (a comment anchor, math, an image, a sublist) is content
    if (!words && !li.querySelector('ul, ol') && !li.querySelector(':not(input):not(br):not(label):not(p)')) {
      // an empty item ends the list; inside a list that is in an item, the browser's own outdent does
      if (!b || b.nodes.indexOf(list) < 0) return;
      e.preventDefault();
      if (list.children.length < 2) return;   // the only item: ending its list would empty the block
      var para = document.createElement('p'), tail = null, rest = [];
      para.setAttribute('contenteditable', 'true');
      para.setAttribute('data-rd-fresh', '');
      para.appendChild(document.createElement('br'));
      for (var n = li.nextSibling; n; n = n.nextSibling) rest.push(n);
      if (rest.some(function (x) { return x.nodeType === 1; })) {
        tail = list.cloneNode(false);
        tail.removeAttribute('start');
        rest.forEach(function (x) { tail.appendChild(x); });
      }
      list.removeChild(li);
      var added = tail ? [para, tail] : [para], where = b.nodes.indexOf(list);
      list.parentNode.insertBefore(para, list.nextSibling);
      if (tail) list.parentNode.insertBefore(tail, para.nextSibling);
      if (!list.querySelector('li')) { list.parentNode.removeChild(list); b.nodes.splice(where, 1); where--; }
      b.nodes.splice.apply(b.nodes, [where + 1, 0].concat(added));
      var caret = document.createRange();
      caret.setStart(para, 0);
      caret.collapse(true);
      sel.removeAllRanges();
      sel.addRange(caret);
      main.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    e.preventDefault();
    if (!range.collapsed) {
      // a selection of all the item's words starts before the box (Home, Shift+End): the box is not in what goes
      var past = document.createRange();
      past.setStartAfter(box);
      if (range.compareBoundaryPoints(Range.START_TO_START, past) < 0) range.setStart(past.startContainer, past.startOffset);
      range.deleteContents();
    }
    var fresh = li.cloneNode(false), shell = fresh;
    fresh.setAttribute('data-rd-fresh', '');   // the server leaves it out until words are typed in it
    var wrap = li.querySelector(':scope > p');
    if (wrap && wrap.contains(box)) { shell = wrap.cloneNode(false); fresh.appendChild(shell); }
    var label = cont.tagName === 'LABEL' ? cont.cloneNode(false) : null;
    if (label) shell.appendChild(label);
    var host = label || shell;
    var nb = box.cloneNode(false);
    nb.removeAttribute('checked');
    nb.checked = false;
    host.appendChild(nb);
    // a caret ahead of the box (the item's start) has the box behind it, not in what moves
    var sc = range.startContainer, ahead = false;
    if (sc === box) ahead = true;
    else if (sc === cont || sc === li) ahead = range.startOffset <= Array.prototype.indexOf.call(sc.childNodes, sc === cont ? box : cont);
    else if (cont.contains(sc)) ahead = !!(box.compareDocumentPosition(sc) & Node.DOCUMENT_POSITION_PRECEDING);
    if (!ahead && (sc === cont || cont.contains(sc))) {
      // the caret before the first letter has the box and white space before it (Chromium puts it at the label's
      // offset 1 after ArrowLeft or a click just after the box): the item's start all the same
      var pre = document.createRange();
      pre.setStart(cont, 0);
      pre.setEnd(sc, range.startOffset);
      var before = pre.cloneContents();
      Array.prototype.forEach.call(before.querySelectorAll('input, [data-rd-ui]'), function (u) { u.remove(); });
      ahead = !before.querySelector('img') && !/[^\s\u200b-\u200d\u2060\ufeff]/.test(before.textContent);
      if (ahead) {
        // and words behind it: with none left (all of them were selected) the caret goes to the item that follows
        var post = document.createRange();
        post.setStart(sc, range.startOffset);
        post.setEnd(cont, cont.childNodes.length);
        var behind = post.cloneContents();
        ahead = !!behind.querySelector('img') || /[^\s\u200b-\u200d\u2060\ufeff]/.test(behind.textContent);
      }
    }
    if (ahead) {
      // Enter at the start of the item: the empty item goes above it, and the caret and the words stay
      li.parentNode.insertBefore(fresh, li);
      var lead = box.nextSibling, at0 = document.createRange();
      if (lead && lead.nodeType === 3) at0.setStart(lead, /^\s*/.exec(lead.nodeValue)[0].length);
      else at0.setStartAfter(box);
      at0.collapse(true);
      sel.removeAllRanges();
      sel.addRange(at0);
      main.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    if (cont.contains(range.startContainer)) {
      var tailR = document.createRange();
      tailR.setStart(range.startContainer, range.startOffset);
      tailR.setEnd(cont, cont.childNodes.length);
      // nothing but a comment anchor after the caret (End of a commented item): the anchor stays with its words
      var after = tailR.cloneContents();
      Array.prototype.forEach.call(after.querySelectorAll('[data-rd-ui]'), function (u) { u.remove(); });
      if (after.querySelector('img') || /[^\s\u200b-\u200d\u2060\ufeff]/.test(after.textContent)) {
        host.appendChild(tailR.extractContents());
      }
    }
    var first = nb.nextSibling, inner = null;
    // the words after the caret open with markup (the rest of a bold word): the caret goes into it, not behind a space
    if (first && first.nodeType === 1 && !first.hasAttribute('data-rd-ui')) {
      inner = document.createTreeWalker(first, NodeFilter.SHOW_TEXT).nextNode();
    }
    if (!inner && (!first || first.nodeType !== 3)) host.insertBefore(first = document.createTextNode(' '), nb.nextSibling);
    li.parentNode.insertBefore(fresh, li.nextSibling);
    var caret = document.createRange();
    if (inner) caret.setStart(inner, 0);
    else caret.setStart(first, /^\s*/.exec(first.nodeValue)[0].length);
    caret.collapse(true);
    sel.removeAllRanges();
    sel.addRange(caret);
    main.dispatchEvent(new Event('input', { bubbles: true }));
  });
  main.addEventListener('input', function () {
    refresh();
    editDraftSchedule();
    hideCommentBtn();           // the typing changed the passage the button and the highlight showed
    // Autosave a moment after typing stops, as a shared document would. The
    // shorter the time an edit lives only on screen, the rarer a real conflict.
    clearTimeout(asTmr);
    asTmr = setTimeout(function () {
      if (editing && !stale && !dead && dirty().length) save(true);
    }, 2500);
  });

  // ---- task boxes -----------------------------------------------------------
  // A click on a task box ticks or unticks it and saves at once, in or out of
  // edit mode. The tick is the `checked` ATTRIBUTE, because that is what ser()
  // sends; the server sees a block that differs only in its ticks and flips the
  // `[ ]` / `[x]` of that one item in the .md (sheafmd.edit._toggle_boxes).
  // A click on the item's text is for the caret and for selecting, so the
  // <label> pandoc wraps around the item must not tick the box.
  if (canEdit) {
    main.addEventListener('click', function (e) {
      var t = e.target;
      var isBox = t && t.tagName === 'INPUT' && t.type === 'checkbox';
      if (!isBox) {
        var lab = t && t.closest && t.closest('label');
        if (lab && main.contains(lab) && lab.querySelector('input[type="checkbox"]')) e.preventDefault();
        return;
      }
      // The browser's own toggle is cancelled and replaced by ours: inside a
      // contenteditable it is not reliable, and the attribute must move with it.
      e.preventDefault();
      // A box of the eight words is pressed with its button at the top of the page (SPEC 10.11).
      if (isActBox(t)) { say(PRESS_IT); return; }
      var b = blockOf(t);
      if (stale || dead || !b || !editable.has(b.i)) return;
      tickBox(t, b);
    });
  }
  var PRESS_IT = 'Press it with its button at the top of the page.';
  // A box in a block whose words were edited and not saved may be an action typed there, which has no button yet:
  // the block is saved first, and the answer's actions say whether the box is one (SPEC 10.11). A save that brings a
  // reload (merged or remapped) brings none: the box is left for the page that follows. Ticks alone make no action.
  var unticked = function (html) { return html.replace(/(<input\b[^>]*?) checked=""/g, '$1'); };
  async function tickBox(t, b) {
    if (unticked(ser(b)) !== unticked(b.pristine)) {
      if (!(await save(true)) || stale || dead || !main.contains(t)) return;
      if (isActBox(t)) { say(PRESS_IT); return; }
      if (hash !== actsHash && !(actsOwed && actsOwed.hash === hash)) {
        say('The page is reloading onto a change to the file: tick it once it has.');
        return;
      }
    }
    var on = !t.hasAttribute('checked');
    if (on) t.setAttribute('checked', ''); else t.removeAttribute('checked');
    // A cancelled click puts the old state back once the handlers are done.
    setTimeout(function () { t.checked = t.hasAttribute('checked'); }, 0);
    refresh();
    save(true);
  }

  // ---- the action buttons (SPEC 10.11) ------------------------------------------
  // The boxes of the eight words are the list's buttons at the top of the page (9.10): a one-off red, locked once
  // pressed, with who and when; Share a toggle, its owner's alone. A press reads Undo for 5 seconds, then posts the
  // list's tick (`/_/tick`) with the hash of the text on screen; the hub's `changed` reloads the page onto the
  // ticked file, and a reload asked meanwhile waits for the press's answer. While a press waits or is sent, the other
  // buttons cannot be pressed: they name their actions by the text the page holds, which the tick changes. The boxes
  // themselves stay in the document, and a click on one says where its button is. A save's answer brings the buttons
  // of the text it wrote (`actsOwed`, with its hash), drawn once no press is open; a press whose buttons that save
  // changed is not sent, since its number may now name another box. While the tick is out (`ticking`), a save
  // waits for its answer: it would move the text the tick names.
  var UNDO_MS = 5000, actBoxes = new WeakSet(), actBar = null, pressOpen = false, reloadAfterPress = null;
  var actsHash = CFG.hash, actsShown = [], actsOwed = null, pressSaid = null, ticking = null;
  // Every reload asked during a press waits as one: the reload of a change to the file goes through its settle,
  // which saves the edits on screen first, even when a plain reload (an upgrade) is asked after it; the newest
  // thread to open is kept, and a restore's reason over any other (as holdReload).
  function waitForPress(r) {
    var o = reloadAfterPress;
    reloadAfterPress = !o ? r : {
      open: r.open || o.open, keep: !!(o.keep && r.keep),
      why: o.why === 'restore' || r.why === 'restore' ? 'restore' : r.why || o.why
    };
  }
  // The boxes of these actions in the document, by the blocks on screen.
  function boxesOfActs(acts) {
    var set = new WeakSet();
    (acts || []).forEach(function (a) {
      var b = a.box && blocks.filter(function (x) { return x.i === a.box[0]; })[0];
      var box = b && boxesOf(b)[a.box[1]];
      if (box) set.add(box);
    });
    return set;
  }
  // A box of an action: of the buttons drawn, or of those a save brought while a press was open.
  function isActBox(t) { return actBoxes.has(t) || (!!actsOwed && boxesOfActs(actsOwed.acts).has(t)); }
  function sameActions(a, b) {
    var sig = function (xs) { return JSON.stringify(xs.map(function (x) { return [x.label, x.pressed, x.n]; })); };
    return sig(a) === sig(b);
  }
  function boxesOf(b) {
    var out = [];
    b.nodes.forEach(function (n) {
      if (n.nodeType !== 1) return;
      if (n.matches('input[type="checkbox"]')) out.push(n);
      Array.prototype.push.apply(out, n.querySelectorAll('input[type="checkbox"]'));
    });
    return out;
  }
  function drawActions(acts, h) {
    if (pressOpen) { actsOwed = { acts: acts, hash: h }; return; }
    actsHash = h; actsShown = acts || [];
    actBoxes = boxesOfActs(acts);
    if (actBar) actBar.remove();
    actBar = null;
    if (!acts || !acts.length) return;
    actBar = el('div', { id: 'rd-actions', role: 'group', 'aria-label': 'Actions' });
    var all = acts.map(function (a) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'rd-act ' + (a.toggle ? 'toggle' : 'one-off') + (a.pressed && !a.toggle ? ' pressed' : '');
      btn.textContent = a.label + (a.pressed && !a.toggle ? ' ✓' + (a.by ? ' ' + a.by : '') : '');
      if (a.toggle) btn.setAttribute('aria-pressed', a.pressed ? 'true' : 'false');
      btn.disabled = !a.may;
      actBar.appendChild(btn);
      return { btn: btn, a: a };
    });
    all.forEach(function (x) { if (!x.btn.disabled) pressable(x.btn, x.a, all); });
    main.parentNode.insertBefore(actBar, main);
  }
  function pressable(btn, a, all) {
    var word = btn.textContent, waiting = null;
    function lock(on) { all.forEach(function (o) { if (o.btn !== btn && o.a.may) o.btn.disabled = on; }); }
    function back() { btn.textContent = word; btn.classList.remove('pending'); btn.removeAttribute('aria-label'); }
    function done() {
      pressOpen = false;
      if (actsOwed) { var owed = actsOwed; actsOwed = null; drawActions(owed.acts, owed.hash); }
      if (reloadAfterPress) {
        var r = reloadAfterPress;
        reloadAfterPress = null;
        if (r.keep) reloadKeep(r.open); else reloadWhenFree(r.open, r.why);
      }
    }
    async function send() {
      waiting = null;
      back();
      btn.disabled = true;
      if (a.toggle) btn.setAttribute('aria-pressed', a.pressed ? 'false' : 'true');
      // A save out now changes the hash: the tick names the text that save leaves.
      while (saving || settling) await (saving || new Promise(function (r) { setTimeout(r, 100); }));
      // The number names a box of the text the buttons were drawn from. A save answered since moved the hash: its
      // buttons say whether the numbers still hold; without them (a text the page did not write) the hub judges.
      var at = actsHash;
      if (hash !== actsHash && actsOwed && actsOwed.hash === hash) {
        if (!sameActions(actsOwed.acts, actsShown)) {
          if (a.toggle) btn.setAttribute('aria-pressed', a.pressed ? 'true' : 'false');
          say('The actions changed while ' + a.label + ' waited: it was not sent. Press it again.', true);
          done();
          return;
        }
        at = hash;
      }
      var tick = { action: a.n, word: a.word, hash: at, where: 'page' };
      if (a.release) tick.release = true;
      var ticked;
      ticking = new Promise(function (r) { ticked = r; });
      var free = function () { ticking = null; ticked(); };       // before done(): the reload it runs may save
      try {
        await post('/_/tick', tick);
        free();
        // Ticked: the hub's `changed` reloads the page; until then nothing more is pressed on the old text.
        all.forEach(function (o) { o.btn.disabled = true; });
        actsOwed = null;
        done();
      } catch (e) {
        if (ticking) free();
        if (a.toggle) btn.setAttribute('aria-pressed', a.pressed ? 'true' : 'false');
        btn.disabled = false;
        lock(false);
        say(e.message, true);
        // A reload waits for this answer: the refusal is said again on the page it brings, if it comes while the
        // toast would still be up (a form may hold it longer).
        if (reloadAfterPress) pressSaid = { text: e.message, until: Date.now() + 7000 };
        done();
      }
    }
    btn.addEventListener('click', function () {
      if (waiting !== null) { clearTimeout(waiting); waiting = null; back(); lock(false); done(); return; }
      if (stale || dead || pressOpen) return;
      // A settle ends in a reload onto the change: a press now would die with the page, so it is not taken.
      if (settling) { say('The page is reloading onto a change to the file: press ' + a.label + ' once it has.'); return; }
      pressOpen = true;
      lock(true);
      btn.textContent = 'Undo'; btn.classList.add('pending'); btn.setAttribute('aria-label', 'Undo ' + word);
      waiting = setTimeout(send, UNDO_MS);
    });
  }
  if (canSave) drawActions(CFG.actions, CFG.hash);

  // Asked when edits are on screen, stale or not: a stale page refuses Save and says to copy the
  // text and reload, so it is the one whose edits are most likely to be left behind. A comment, reply
  // or edit being typed is asked about too: until it is sent, nothing but the form holds it. A form
  // that holds what the store keeps for it is not: the next page draws that text again (unkept).
  window.addEventListener('beforeunload', function (e) {
    if (dirty().length || unkept() || (docGone && storedTexts().length)) { e.preventDefault(); e.returnValue = ''; }
  });

  // The document's event stream (GET /_/live?doc=…). Held open, it is also how the
  // hub knows a tab is open on the document: there is no ping. An EventSource is
  // held by the browser process rather than the renderer, so it survives a hidden
  // tab's throttled timers and closes when the tab really does. It carries
  // `changed` and the progress of Ask and Tell.
  var overLine = null;        // the line showNoticeOverOffer put over the offer, while the notice still holds it
  function showNotice(html) { notice.innerHTML = html; notice.hidden = false; overLine = null; }
  function hideNotice() { notice.hidden = true; notice.innerHTML = ''; overLine = null; }
  // The offer is decided (Discard, Restore): its buttons go, and the line that sat over them stays.
  function dropOffer() {
    var line = overLine;
    hideNotice();
    if (line) { showNotice(line); overLine = line; }
  }
  // A line that is not the hub's own (an upgrade, a sign-out) goes over a draft's offer: the offer's
  // buttons stay under it, since the draft is still undecided and its click handler is still set.
  function showNoticeOverOffer(html) {
    showNotice(html);
    overLine = html;
    if (offered) notice.insertAdjacentHTML('beforeend', '<div>' + offerHtml(offered) + '</div>');
  }
  // A `changed` event. The hub sends one for every write, this page's own included, and
  // it can arrive before the answer to that write, while `hash` is still the one the
  // page sent: it would read as somebody else's write (a reload after every save, and
  // after every new comment, whose anchor the page places only once the answer is in).
  // So while a save or a comment is out, events are held, and looked at when the answer
  // has been taken in (replayHeld, from post): the page's own is then the hash it holds
  // and is ignored, another writer's is told as ever.
  function heard(d) {
    if (ownWrites) { held.push(d); return; }
    if (d.hash === hash) return;
    // Only comments moved: take them in place, even with unsaved edits on
    // screen, since the saved blocks keep their comments on the server side. Only
    // when this page holds the version the hub compared with (d.base): a page that
    // missed a save would adopt the new hash over old text, and its next save would
    // overwrite that save without a merge.
    if (d.textSame && d.base === hash && applyComments(d)) return;
    reloadWhenFree(popId);
  }
  function replayHeld() {
    var fs = held.splice(0);
    // The check a write put off goes first, and what was held behind the write waits for its answer.
    if (checkAgain) { checkAgain = false; checkText(); fs.forEach(function (d) { heardAfterCheck(function () { heard(d); }); }); }
    else fs.forEach(heard);
  }

  // ---- riding through an outage (SPEC 10.7) -----------------------------------------
  // The stream reconnects by itself (retry 2 s), so the page says something only when it
  // matters. A 1 s tick counts how long the stream has been failing on a visible tab, and at
  // 15 s the banner goes up. Coming back to the tab, or a tick that jumped over 5 s (the
  // machine slept), starts the 15 s again: a suspend is not an outage. The notice line is
  // the hub's voice here (stopped, unreachable, not signed in); `hubLine` says it holds one,
  // so the line that goes when the hub answers is never somebody else's.
  var GRACE = 15000, JUMP = 5000;
  var fileMissing = false, stopped = false, failing = false, failFrom = 0, lastTick = Date.now(), lost = false;
  var hubService = CFG.service !== false, hubLine = false, signedOut = false, closedTmr = null;
  var interrupted = {};
  function showHubLine(html) { hubLine = true; showNotice(html); }
  function clearHubLine() {
    if (!hubLine) return;
    hubLine = false;
    hideNotice();
    if (offered) offerDraft(offered);
  }
  function streamFailed() { if (!failing) { failing = true; failFrom = Date.now(); } }
  function graceAgain() { if (failing) failFrom = Date.now(); }
  function outageTick() {
    var now = Date.now();
    if (now - lastTick > JUMP) graceAgain();
    lastTick = now;
    if (failing && !lost && document.visibilityState === 'visible' && now - failFrom >= GRACE) outageBanner();
  }
  function outageBanner() {
    lost = true; dead = true; refresh();
    incident('server-lost', { stopped: stopped });
    if (stopped || signedOut || docGone || fileMissing) return;       // each of those already says what is wrong
    showUnreachable();
  }
  function showUnreachable() {
    showHubLine('Hub unreachable, reconnecting… your edits are safe on screen.' +
                (hubService ? '' : ' If it does not come back, run <code>sheaf start</code>.'));
  }
  // The hub does not answer the page's ask (no answer, or a proxy's 5xx or HTML page in its place): what is
  // missing is no longer only the file. A banner that `outageBanner` held back for the missing file goes up now.
  function hubUnreachable() {
    if (!fileMissing) return;                 // the file was not what the line said: nothing to take back
    fileMissing = false; clearHubLine(); refresh();
    if (lost && !stopped && !signedOut && !docGone) showUnreachable();
  }
  function streamBack() {
    failing = false;
    clearTimeout(closedTmr); closedTmr = null;
    if (lost) { lost = false; dead = false; refresh(); say('Reconnected to the sheaf hub.'); incident('server-back'); }
    payOwed();
  }
  // A stream the hub answered with 401 or 5xx is closed for good: the browser does not retry
  // it. The page does, every 2 s, and asks once what the answer was, since a 401 is a rotated
  // key and nothing a retry fixes: that gets the sign-in message of 8.5.
  var closedN = 0;
  function streamClosed() {
    if (closedTmr || docGone) return;
    closedTmr = setTimeout(function () {
      closedTmr = null;
      var again = function () { if (!live || live.readyState === 2) connect(); };
      if (signedOut) { again(); return; }
      var mine = ++closedN;
      var last = function () { return mine === closedN; };      // an older answer, come late, is not applied
      readDoc()
        .then(function (r) {
          if (!last()) return;
          if (r.status === 401) showSignIn();
          else if (r.status === 200) return r.json().then(function (j) { if (last()) takeTarget(j); });
          // The address names no document (8.5). Its root gone from the name, or another in its place, no
          // retry brings it back; a file gone from this same root may come back (a branch switched).
          else if (r.status === 404) {
            return r.json().then(function (j) {
              if (!last()) return;
              if (otherRoot(j)) meetDocGone(whyGone(j)); else meetFileMissing();
            });
          }
          else if (r.status >= 502 && r.status <= 504) hubUnreachable();      // a proxy's answer in the hub's place
        })
        .catch(function () { if (last()) hubUnreachable(); }).then(again);   // no answer, or a 404 that is no JSON
    }, 2000);
  }
  // The hub answers and the root is this page's, but the file is not there (a branch switched, a file moved):
  // it may be back, so the stream is tried again every 2 s, and the page says what is missing, not that the
  // hub is unreachable. A hello (the file is back) takes the line away (clearHubLine).
  function meetFileMissing() {
    if (fileMissing || docGone) return;
    fileMissing = true;
    refresh();
    showHubLine('The hub is running, but this file is not on the hub right now (deleted, or moved by a branch ' +
                'switch). This page looks again every 2 seconds, and your edits are safe on screen.');
  }
  function showSignIn() {
    signedOut = true;
    editDraftMirror();
    var kept = dirty().length && !offered;
    // Through the proxy socket the front's sign-in is the credential (9.9): sign in there again.
    showHubLine((CFG.proxy ? 'This browser is not signed in to this site any more. Sign in to this site again, ' +
                             'then reload this page.' :
                'This browser is not signed in to your sheaf hub. On the machine that runs the hub, run ' +
                '<code>sheaf open ' + esc(location.href) + '</code>. If the hub runs on another machine, run ' +
                '<code>sheaf signin-url</code> there and open what it prints in this browser.') +
                (kept ? ' Your edits stay on screen, and are kept as a draft.' : ''));
  }
  // The document is no longer on the hub (SPEC 8.2, 10.7): its root was forgotten (`gone`), or the hub's
  // answer for its address names no root, or another one: a folder that took the name (otherRoot).
  // The stream is closed for good and the page is never reloaded, which would take it into that other
  // document or a 404. What was typed stays on screen and in its drafts, nothing more is sent (post), and
  // the notice holds a copy of it, over the outage banner (outageBanner) and any other line.
  // `access`: the gone of 8.12, a change of projects.toml that no longer lets this member into the project.
  function meetDocGone(more, access) {
    if (docGone) return;
    docGone = true;
    if (live) live.close();
    clearTimeout(closedTmr); closedTmr = null;
    failing = false; hubLine = false; dead = true; reloadPending = false; heldReload = false; holdWhy = null; holdOpen = null;
    stopRenewing();
    if (dirty().length) editDraftMirror();
    Array.prototype.forEach.call(document.querySelectorAll('.rd-hold'), function (n) { if (n.textContent === HOLD) n.remove(); });
    refresh();
    var typed = dirty().map(function (b) {
      return new DOMParser().parseFromString(ser(b), 'text/html').body.textContent.trim();
    }).concat(Array.prototype.map.call(document.querySelectorAll('.rd-form textarea'), function (t) {
      return t.value.trim();
    }), storedTexts()).filter(function (t, i, all) { return t && all.indexOf(t) === i; });
    showNoticeOverOffer((access ? 'You no longer have access to this document: its project no longer lists you'
                                : 'This document is no longer on the sheaf hub: its folder was forgotten with ' +
                                  '<code>sheaf roots forget</code>' + more) +
                        '. Nothing more can be saved from this page.' +
                        (typed.length ? ' What you typed and did not save is below, to copy.' +
                                        (saving ? ' A save was still out when ' + (access ? 'access ended' : 'the folder went') + ', so some of it may be in the file.' : '') +
                                        '<textarea readonly rows="6">' + esc(typed.join('\n\n')) + '</textarea>' : ''));
    incident('document-gone', { more: more, access: !!access });
  }
  // A hello: this hub may be another boot, and the text may have moved while the page could
  // not hear `changed`. (Another version is meetVersion's, which the hello handler calls next.)
  function meetHello(h) {
    clearHubLine();
    stopped = false; signedOut = false;
    if (fileMissing) { fileMissing = false; refresh(); }
    if (h.service !== undefined) hubService = h.service !== false;
    if (h.boot && CFG.boot && h.boot !== CFG.boot) interruptJobs();
    if (h.boot) CFG.boot = h.boot;
    payOwed();
    checkText();
  }
  // A new boot lost every job the old hub was running: say so in their threads, and let them be sent again.
  function interruptJobs() {
    var ids = Object.keys(asking).concat(Object.keys(telling));
    asking = {}; telling = {}; tellQ = '';
    ids.forEach(function (id) { interrupted[id] = true; touched(id); });
  }
  // Whether the hub's answer for this address (`/_/doc`, or its 404) names a root other than the one this
  // page was served from (8.2, 10.1): none, its root forgotten, or the folder that took the name after a
  // forget. Not the same root's file that moved on, nor one whose version aged out of the store (7.4). A
  // page served with no root id, or an answer that names none (a 401), is never met as gone.
  function otherRoot(j) {
    return !!CFG.root && !!j && j.root !== undefined && j.root !== CFG.root;
  }
  // What the drafts store holds for this page (a new comment, a reply or an edit whose send failed). Once
  // the document is gone nothing draws it again: a page of the folder that took the name has another root id
  // and lists none of it (ofOtherRoot), so it is offered with what is on screen, and leaving asks (unkept).
  function storedTexts() {
    return commentDraftsLoad().map(function (d) { return d.body.trim(); }).filter(function (t) { return t; });
  }
  function whyGone(j) { return j.root ? ', and another folder now holds its name' : ''; }
  // What the hub says of this document now: the one read of `/_/doc`, at start-up, by every check (checkText,
  // which a hello makes) and by the closed stream's look at the answer.
  function readDoc() { return fetch('/_/doc?doc=' + encodeURIComponent(CFG.doc)); }
  // The text may have moved while the page could not hear it. Settled like any other change:
  // the dirty blocks are saved (the hub merges them), then the page reloads. Another root under the
  // address's name is another folder's document: this one is gone.
  // Like `heard`, the answer waits for the page's own save or comment: the hub has written the file and
  // the page does not hold its hash yet, which would read as a change from outside. The check is made
  // again once they are answered (replayHeld).
  // The events that arrive while that answer is out wait for it (heardAfterCheck): until it says whose
  // document this is, a `changed` of another folder's file under the same address would reload the page into
  // it. They are heard once it is in, or after CHECK_WAIT if it is not.
  var checkAgain = false, checking = false, checkN = 0, afterCheck = [], checkTmr = null, CHECK_WAIT = 10000;
  function heardAfterCheck(f) { if (checking) afterCheck.push(f); else f(); }
  function endCheck() {
    checking = false;
    clearTimeout(checkTmr); checkTmr = null;
    var fs = afterCheck.splice(0);
    if (!docGone) fs.forEach(function (f) { f(); });
  }
  function checkText() {
    if (docGone) return;
    if (ownWrites) { checkAgain = true; return; }
    var seen = ownSeq, mine = ++checkN, jobs = jobsHeard;
    var last = function () { return mine === checkN; };       // an older answer leaves the hold to the newest check
    checking = true;
    clearTimeout(checkTmr); checkTmr = setTimeout(endCheck, CHECK_WAIT);
    readDoc()
      .then(function (r) {
        // A 404 that is not another root's: this root's file is gone, met as when the stream finds it so.
        return r.json().then(function (j) { return { j: j, missing: r.status === 404 }; });
      })
      .then(function (a) {
        var j = a.j;
        if (ownWrites || seen !== ownSeq) { if (ownWrites) { checkAgain = true; if (last()) endCheck(); } else checkText(); return; }
        if (otherRoot(j)) { meetDocGone(whyGone(j)); if (last()) endCheck(); return; }
        if (a.missing) { if (last()) { meetFileMissing(); endCheck(); } return; }       // an older answer is no news
        takeTarget(j);
        if (j && j.hash && j.hash !== hash) reloadWhenFree(popId);
        meetTaken(j);
        takeJobs(j, jobs);
        if (last()) endCheck();
      })
      .catch(function () { if (last()) endCheck(); });
  }
  if (canSave) {
    setInterval(outageTick, 1000);
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') graceAgain();
    });

    var live = null;
    // How many job events (ask-*, tell-*) the stream has brought: a `/_/doc` answer read before the last of them
    // adds no job (takeJobs), or it would bring back one that an event has ended since.
    var jobsHeard = 0;
    var data = function (ev) { try { return JSON.parse(ev.data || '{}') || {}; } catch (e) { return {}; } };
    // A hub that now runs another version than the one that served this page (SPEC 14.4): reload,
    // to take the new script. Never over what is only on screen: unsaved edits, or a comment
    // being written, get a notice instead, and the person reloads when they are ready.
    // The hub key was rotated (SPEC 9.3): this tab's cookie is no good any more. Reloading shows
    // the hub's own sign-in page, unless something is only on screen: that stays, with the way
    // back in. `stopped` keeps `outageBanner` from putting its own line over this one: the menu
    // still reads "Hub unreachable" and Save stays off, but the notice is left as it is.
    var meetSignOut = function () {
      if (docGone) return;
      stopped = true;
      if (writes) { afterWrites.push(meetSignOut); return; }
      // A press waits or is out (SPEC 10.11): its answer, a refusal now, is said on this page, not lost to a reload.
      if (dirty().length || writingNow({ page: true }) || pressOpen) {
        hubLine = true;         // the hub's voice: a hello clears it (clearHubLine)
        showNoticeOverOffer(CFG.proxy ? 'You were signed out of this site. Your edits are safe on screen. Sign ' +
                                        'in to this site again in another tab, then save.' :
                            'You were signed out of the sheaf hub: its key was changed. Your edits are safe ' +
                            'on screen. Run <code>sheaf open</code> in a terminal to sign in again, then save.');
        return;
      }
      location.reload();
    };
    var meetVersion = function (v) {
      if (!v || !CFG.version || v === CFG.version || docGone) return;
      if (writes) { afterWrites.push(function () { meetVersion(v); }); return; }
      if (dirty().length || writingNow({ page: true })) {
        showNoticeOverOffer('The sheaf hub was upgraded. ' +
                            (dirty().length ? 'Save your edits' : 'Send or cancel your comment') +
                            ', then reload this page to use the new version.');
        return;
      }
      reloadKeep(popId);
    };
    var connect = function () {
      if (docGone) return;
      try { live = new EventSource('/_/live?doc=' + encodeURIComponent(CFG.doc)); } catch (e) { return; }
      live.onopen = function () {
        streamBack();
        flushIncidents();
      };
      live.onerror = function () {
        streamFailed();
        if (live.readyState === 2) streamClosed();
      };
      // Sent first on every connect: what the outage left behind (a new boot, moved text), then
      // the hub's version.
      live.addEventListener('hello', function (ev) {
        meetHello(data(ev));
        meetVersion(data(ev).version);
      });
      live.addEventListener('hub-stopping', function (ev) {
        var d = data(ev);
        if (d.reason === 'stop' || d.reason === 'signal') {
          stopped = true;
          showHubLine('The hub was stopped. Run <code>sheaf start</code> to continue; ' +
                      'your edits are safe on screen.');
        }
      });
      live.addEventListener('signed-out', function () { meetSignOut(); });
      // Its root was forgotten (8.2): the last event of this stream.
      live.addEventListener('gone', function (ev) {
        var d = {};
        try { d = JSON.parse(ev.data || '{}'); } catch (e) {}
        meetDocGone('', d.why === 'access');
      });
      live.addEventListener('changed', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        var late = !!d.rid && taken(d.rid);
        heardAfterCheck(function () { heard(d); });
        if (late) say('What you sent reached the hub after all.');      // over the news of applyComments
      });
      live.addEventListener('ask-started', function (ev) {
        var id = JSON.parse(ev.data || '{}').id;
        asking[id] = true;
        touched(id);
      });
      live.addEventListener('ask-done', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        delete asking[d.id];
        // Like `changed`: the comments are taken in place only when the hub measured the
        // answer against the text this page holds (d.base); else only a reload is safe.
        heardAfterCheck(function () {
          if (!(d.textSame && d.base === hash && applyComments(d))) {
            if (dirty().length) { stale = true; refresh(); say(AGENT_UC + ' answered comment ' + d.id + '. Copy your edits, then reload to read it.'); }     // a stale page refuses Save
            else reloadWhenFree(d.id);
          }
        });
      });
      live.addEventListener('tell-sent', function (ev) {
        say('Sent to ' + yourSession() + '. Its reply will appear in the thread.');
      });
      // The told session answered with a question (AskUserQuestion) and waits for
      // you in its own chat; it is not working, and it is not gone.
      live.addEventListener('tell-waiting', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        tellQ = d.question || '';
        (d.ids || []).forEach(touched);
        say(AGENT_UC + ' is asking you something in your session: ' + tellQ);
      });
      live.addEventListener('tell-working', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        tellQ = '';
        (d.ids || []).forEach(touched);
      });
      live.addEventListener('tell-failed', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        delete telling[d.id];
        touched(d.id);
        say('Tell ' + AGENT + ' failed: ' + (d.error || 'unknown error'), true);
      });
      // A member's Tell that the fork's relay will not deliver: it expired, or the session did not take it (9.14).
      live.addEventListener('tell-relay-failed', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        touched(d.id);
        say('Tell ' + AGENT + ' failed: ' + (d.error || 'unknown error'), true);
      });
      // A drop for James's window that the hub gave up on: no reply within the Tell wait (#115).
      live.addEventListener('box-failed', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        delete sentBox[d.id];
        touched(d.id);
        var what = (d.kind === 'ask' ? 'Ask ' : 'Tell ') + AGENT;
        say((d.error !== undefined ? what + ' failed: ' + (d.error || 'the box could not deliver it') + '.'
             : what + ': no answer from ' + AGENT + '’s window after ' + d.minutes + ' min.') +
            ' The comment is written: reply here, or send it again.', true);
      });
      // What the box's supervisor said of a drop: its window opening, then the session working on it (#139).
      live.addEventListener('box-status', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        if (!sentBox[d.id]) return;
        sentBox[d.id].state = d.state;
        touched(d.id);
      });
      ['ask-cancelled', 'tell-cancelled'].forEach(function (name) {
        live.addEventListener(name, function (ev) {
          var d = JSON.parse(ev.data || '{}');
          if (name === 'ask-cancelled') delete asking[d.id]; else delete telling[d.id];
          touched(d.id);
        });
      });
      live.addEventListener('ask-failed', function (ev) {
        var d = JSON.parse(ev.data || '{}');
        delete asking[d.id];
        touched(d.id);
        say('Ask ' + AGENT + ' failed: ' + (d.error || 'unknown error'), true);
      });
      ['ask-started', 'ask-done', 'ask-failed', 'ask-cancelled', 'tell-sent', 'tell-waiting', 'tell-working',
       'tell-failed', 'tell-cancelled'].forEach(function (name) {
        live.addEventListener(name, function () { jobsHeard++; });
      });
    };
    connect();
    // Belt and braces, and an event rather than a timer: coming back to the tab
    // reopens a stream the browser gave up on.
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState !== 'visible') return;
      if (!live || live.readyState === 2) connect();
    });
    // The jobs already running on this document (an Ask from another tab, a Tell
    // waiting on its person), and the read state as the hub has it now.
    var jobs = jobsHeard;
    readDoc().then(function (r) { return r.json(); }).then(function (j) {
      if (!j || j.ok === false) return;
      takeTarget(j);
      meetTaken(j);
      takeJobs(j, jobs);
    }).catch(function () {});
  }

  // ---- drafts (SPEC 10.8) ------------------------------------------------------
  // Unsaved edits are mirrored to localStorage half a second after typing stops, and the
  // key goes when a save leaves nothing dirty. Only the edited blocks and the version they
  // were made on are stored, never a key or token. A page that finds a draft on load offers
  // to restore it: the edits go to the hub as a save against that version, which merges.
  var EDIT_DRAFT_KEY = 'sheaf-draft:' + DRAFTS_OF + ':' + CFG.doc, dTmr = null, offered = null, offeredText = null, myDraft = null;
  // Every tab of this document shares the key, and so does another folder under the same name: a tab removes
  // only the draft it wrote itself (myDraft) or the one it offered (offeredText), and offers only a draft
  // whose `root` is its own. A draft with no `root` (an older entry) is offered.
  function editDraftMirror() {
    clearTimeout(dTmr);
    if (offered) return;      // a draft the person has not decided on stays as it is, never overwritten or removed
    try {
      var edits = dirty().map(function (b) { return { i: b.i, html: ser(b) }; });
      if (edits.length) {
        // The text of a save that is out or got no answer (`unanswered`) holds its request id, and the version it
        // was made on, so that a page restoring it asks for that save again (SPEC 10.8).
        var mirrors = unanswered && unanswered.sent.length === edits.length && unanswered.sent.every(function (x, n) {
          return x.b.i === edits[n].i && x.html === edits[n].html;
        }) ? unanswered : null;
        var body = { root: CFG.root, hash: mirrors ? mirrors.hash : hash, at: new Date().toISOString(), edits: edits };
        if (mirrors) body.rid = mirrors.rid;
        var text = JSON.stringify(body);
        localStorage.setItem(EDIT_DRAFT_KEY, text);
        myDraft = text;
      } else if (myDraft !== null) {
        if (localStorage.getItem(EDIT_DRAFT_KEY) === myDraft) localStorage.removeItem(EDIT_DRAFT_KEY);
        myDraft = null;
      }
    } catch (e) {}
  }
  function editDraftSchedule() { clearTimeout(dTmr); dTmr = setTimeout(editDraftMirror, 500); }
  function editDraftFound() {
    try {
      var text = localStorage.getItem(EDIT_DRAFT_KEY), d = JSON.parse(text || 'null');
      if (!d || !d.edits || !d.edits.length || ofOtherRoot(d)) return null;
      if (!/^[A-Za-z0-9_-]{16,64}$/.test(d.rid)) delete d.rid;      // the hub answers 400 to any other
      offeredText = text;
      return d;
    } catch (e) { return null; }
  }
  function offerHtml(d) {
    var when = isNaN(Date.parse(d.at)) ? d.at : new Date(d.at).toLocaleString();
    return 'Unsaved edits from ' + esc(when) + ' were found. ' +
           '<button data-d="restore">Restore</button> <button data-d="discard">Discard</button>';
  }
  // While the offer is undecided the page's own edits are on screen only (editDraftMirror leaves the draft as it
  // is), a tick whose save failed among them. Once it is decided (Discard, or a Restore the hub took) the
  // draft goes and they are mirrored in its place.
  function decided() {
    offered = null;
    try { if (localStorage.getItem(EDIT_DRAFT_KEY) === offeredText) localStorage.removeItem(EDIT_DRAFT_KEY); } catch (x) {}
    offeredText = null;
    editDraftMirror();
  }
  function keepRestoreId(d) {
    d.rid = newRid();
    try {
      if (localStorage.getItem(EDIT_DRAFT_KEY) !== offeredText) return;     // another page wrote it meanwhile
      offeredText = JSON.stringify(Object.assign({}, JSON.parse(offeredText), { rid: d.rid }));
      localStorage.setItem(EDIT_DRAFT_KEY, offeredText);
    } catch (e) {}
  }
  function offerDraft(d) {
    offered = d;
    showNotice(offerHtml(d));
    notice.onclick = async function (e) {
      var k = e.target.getAttribute && e.target.getAttribute('data-d');
      if (k === 'discard') { decided(); dropOffer(); }
      if (k !== 'restore') return;
      try {
        // A Restore the hub did not answer can be pressed again, or a page opened later can offer the draft
        // again: the same edits go under the same id, which the draft keeps (an older entry's has none).
        if (!d.rid) keepRestoreId(d);
        await post('/_/save', { hash: d.hash, edits: d.edits, rid: d.rid });
        decided();
        // The edits are in the file now; the reload that shows them waits for a comment
        // being written, like every other (D23), and says so above its form.
        dropOffer();
        reloadWhenFree(popId, 'restore');
      } catch (x) {
        // The hub refused (or cannot be reached): the text is here to copy, and stays stored.
        var text = d.edits.map(function (ed) {
          return new DOMParser().parseFromString(ed.html, 'text/html').body.textContent.trim();
        }).join('\n\n');
        // Given up after 120 s, the Restore may still have been written: pressed again, its edits say what the
        // first sent (`saved`, SPEC 7.3), as a save's do, and the hub finds them in the file. A write that
        // reached the hub reloads the page, which offers the stored draft again, so the draft carries it too.
        if (x.timedOut) {
          d.edits.forEach(function (ed) { ed.saved = ed.saved || ed.html; });
          try {
            var named = JSON.stringify(d);
            if (offeredText !== null && localStorage.getItem(EDIT_DRAFT_KEY) === offeredText) { localStorage.setItem(EDIT_DRAFT_KEY, named); offeredText = named; }     // not one the hub's `changed` event took meanwhile (offeredText is null)
          } catch (y) {}
        }
        var why = x.timedOut ? 'The hub did not answer within 2 minutes; what follows may have been saved all the same. The text is kept here.' : x.message;
        panel.innerHTML = '<h3>Your unsaved edits</h3><p>' + esc(why) + '</p><pre class="rd-draft"></pre>';
        panel.querySelector('pre').textContent = text;
        panel.dataset.keeps = 'draft';
        panel.classList.add('open');
      }
    };
  }

  // ---- start ----------------------------------------------------------------
  buildMenu();
  paint(null);
  try {
    var keep = JSON.parse(sessionStorage.getItem('rd-keep') || 'null');
    var msg = sessionStorage.getItem('rd-toast');
    var refusedPress = sessionStorage.getItem('rd-press-said');   // a press's refusal a reload waited for (10.11)
    sessionStorage.removeItem('rd-keep');
    sessionStorage.removeItem('rd-toast');
    sessionStorage.removeItem('rd-press-said');
    // One hub serves every document from one origin, so what a reload kept
    // belongs to this page only if it names this document.
    if (keep && keep.doc !== CFG.doc) { keep = null; msg = null; }
    if (keep) {
      window.scrollTo(0, keep.y || 0);
      if (keep.known) {
        var n = news(keep.known, COMMENTS, keep.open ? [keep.open] : []);
        n.forEach(function (x) { flash(x.id); });
        if (n.length && !msg) msg = n.map(function (x) { return x.text; }).join(' · ');
      }
      var says = HELD_SAYS[keep.held === true ? 'text' : keep.held];
      if (says) msg = msg ? msg + ' · ' + says.charAt(0).toLowerCase() + says.slice(1, -1) : says;
      // The jobs a new boot lost are still lost: the reload an upgrade or moved text brings keeps them.
      (keep.interrupted || []).forEach(function (id) { if (byId[id]) interrupted[id] = true; });
      // A comment sent to James's window keeps its line past the reload the session the hub records brings.
      Object.keys(keep.sent || {}).forEach(function (id) {
        var s = keep.sent[id];
        if (byId[id] && s && typeof s.n === 'number' && typeof s.to === 'string') {
          sentBox[id] = { n: s.n, to: s.to };
          if (typeof s.at === 'string') sentBox[id].at = s.at;
        }
      });
      if (keep.panel) openPanel();
      if (keep.editing) { setEditing(true); placeCaret(keep.caret); }
      if (keep.open && byId[keep.open]) setTimeout(function () { openComment(keep.open); }, 50);
    }
    if (refusedPress && keep) say(refusedPress, true);
    else if (msg) say(msg);
    if (canSave) { showKept(); unsentLine(); }
    var unsaved = canEdit ? editDraftFound() : null;
    if (unsaved) offerDraft(unsaved);
  } catch (e) {}
  refresh();
})();
