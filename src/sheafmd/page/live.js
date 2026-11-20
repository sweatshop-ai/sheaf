// sheaf: one live stream for every tab of a browser (ticket 160).
//
// A browser opens six HTTP/1.1 connections to a host at most, and every open sheaf page held one
// for its `/_/live` stream: with six tabs open, the seventh page and every request after it (a
// comment, a save) waited for ever. Now one tab of the browser, the one that holds the Web Lock
// `sheaf-live`, opens `/_/live?shared=ID` and joins every tab's stream to it (`/_/live/join`); the
// others hear their events from it over the BroadcastChannel `sheaf-live`. When that tab closes,
// the lock passes to another, which opens the stream again and asks every tab to join it.
//
// `SheafLive.source(doc)` returns what `new EventSource('/_/live?doc=' + doc)` did, as far as the
// pages use it: addEventListener, onopen, onerror, readyState, close. `doc` "" is the index's stream.
// A browser without Web Locks or BroadcastChannel gets a plain EventSource, as before.
(function () {
  if (window.SheafLive) return;
  var plain = function (doc) { return new EventSource(doc ? '/_/live?doc=' + encodeURIComponent(doc) : '/_/live'); };
  if (!window.EventSource || !window.BroadcastChannel || !navigator.locks || !window.fetch) {
    window.SheafLive = { source: plain, shared: false };
    return;
  }
  var RETRY = 2000;          // the hub's `retry:`: how soon a stream that ended is asked for again
  var SWEEP = 2000;          // how often the leader drops the streams of tabs that are gone
  var ENDS = ['hub-stopping', 'signed-out', 'gone'];   // the hub's last event on a stream (events.Shared.ENDS)
  var rnd = function () {
    var a = new Uint8Array(16);
    crypto.getRandomValues(a);
    return Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  };
  var TAB = rnd();
  var chan = new BroadcastChannel('sheaf-live');
  var mine = {};             // key -> this tab's source
  var n = 0;
  // Held for the life of the tab: the leader asks the lock manager which tabs still hold theirs.
  navigator.locks.request('sheaf-tab-' + TAB, function () { return new Promise(function () {}); });

  function Source(doc) {
    this.key = TAB + ':' + (++n);
    this.doc = doc;
    this.readyState = 0;
    this.onopen = null;
    this.onerror = null;
    this._on = {};
    this._again = null;
    mine[this.key] = this;
    ask({ t: 'join', key: this.key, doc: doc, tab: TAB });
  }
  Source.prototype.addEventListener = function (name, fn) { (this._on[name] = this._on[name] || []).push(fn); };
  Source.prototype.removeEventListener = function (name, fn) {
    var l = this._on[name] || [];
    var i = l.indexOf(fn);
    if (i >= 0) l.splice(i, 1);
  };
  Source.prototype.close = function () {
    if (this.readyState === 2) return;
    this.readyState = 2;
    clearTimeout(this._again);
    delete mine[this.key];
    ask({ t: 'leave', key: this.key });
  };
  Source.prototype._fire = function (name, data) {
    var ev = new MessageEvent(name, { data: data === undefined ? '' : JSON.stringify(data) });
    var l = (this._on[name] || []).slice();
    for (var i = 0; i < l.length; i++) l[i].call(this, ev);
  };
  // What a closed or dropped stream does in a browser: `error` with readyState 0 while it is tried
  // again, 2 when the hub refused it.
  Source.prototype._fail = function (state) {
    if (this.readyState === 2) return;
    this.readyState = state;
    if (this.onerror) this.onerror(new Event('error'));
  };
  Source.prototype._hear = function (e, d) {
    if (this.readyState === 2) return;
    if (e === 'open') {
      this.readyState = 1;
      if (this.onopen) this.onopen(new Event('open'));
      return;
    }
    if (e === 'refused') { this.readyState = 2; delete mine[this.key]; if (this.onerror) this.onerror(new Event('error')); return; }
    this._fire(e, d);
    // The hub ends a stream after its last event; a browser would ask for it again after `retry`.
    if (ENDS.indexOf(e) >= 0) {
      var self = this;
      this._fail(0);
      this._again = setTimeout(function () {
        if (self.readyState !== 2) ask({ t: 'join', key: self.key, doc: self.doc, tab: TAB });
      }, RETRY);
    }
  };

  // ---- every tab: what it hears ----------------------------------------------------
  function hear(m) {
    if (m.t === 'ev') { var s = mine[m.k]; if (s) s._hear(m.e, m.d); }
    else if (m.t === 'down') {
      // Refused (s 2): every stream is closed for good, as each tab's own was; the page asks again itself.
      Object.keys(mine).forEach(function (k) {
        var s = mine[k];
        if (m.s === 2) delete mine[k];
        s._fail(m.s);
      });
    }
    else if (m.t === 'who') {
      // A new leader: the connection the open streams were on went with the old one. A browser would
      // fire `error` and try again, so they do the same before they join the new connection.
      rejoin();
    }
  }
  chan.onmessage = function (ev) {
    var m = ev.data || {};
    hear(m);
    if (lead) lead.take(m);
  };
  // A message for the leader: posted to the others, and taken here too when this tab is it.
  function ask(m) {
    chan.postMessage(m);
    if (lead) lead.take(m);
  }
  // Said to every tab, this one included.
  function tell(m) {
    chan.postMessage(m);
    hear(m);
  }
  // Every stream of this tab joins the leader's connection again: what it had was dropped, or went with a connection.
  // A browser would fire `error` and try again, so they do the same.
  function rejoin() {
    Object.keys(mine).forEach(function (k) {
      if (mine[k].readyState === 1) mine[k]._fail(0);
      ask({ t: 'join', key: k, doc: mine[k].doc, tab: TAB });
    });
  }
  window.addEventListener('pagehide', function () {
    Object.keys(mine).forEach(function (k) { chan.postMessage({ t: 'leave', key: k }); });
  });
  // A page the browser kept (the back/forward cache) and shows again sent its leaves on `pagehide`: the leader
  // dropped its streams. Chrome keeps no page that holds a Web Lock; others were not checked.
  window.addEventListener('pageshow', function (ev) { if (ev.persisted) rejoin(); });

  // ---- the leader: the one tab that holds the connection ---------------------------
  var lead = null;
  function Leader() {
    this.joined = {};          // key -> {doc, tab, at}: every stream this browser wants
    this.sid = rnd();
    this.sent = {};            // key -> the last post for it, which the next one waits for
    this.reopened = 0;         // when the connection was last opened again for a join the hub refused
    this.watch = {};           // tab -> the abort of its queued request for its lock, which is granted when the tab dies
    this.es = null;
    this.open = false;
    this.connect();
    var self = this;
    this.timer = setInterval(function () { self.sweep(); }, SWEEP);
  }
  // This tab stops being the leader: its stream and its sweep end, and the tabs' joins on it go with them.
  Leader.prototype.stop = function () {
    clearInterval(this.timer);
    if (this.es) { this.es.onerror = null; this.es.close(); this.es = null; }
    this.open = false;
    this.joined = {};          // a join still on the way must not refuse a stream on the next leader
    this.sent = {};
    var w = this.watch;
    this.watch = {};
    Object.keys(w).forEach(function (t) { w[t].abort(); });
    if (this.release) this.release();
  };
  Leader.prototype.connect = function () {
    var self = this;
    this.open = false;
    var es = this.es = new EventSource('/_/live?shared=' + this.sid);
    this.es.onopen = function () {
      self.open = true;
      Object.keys(self.joined).forEach(function (k) { self.post('join', k); });
    };
    this.es.onerror = function () {
      var s = es.readyState === 2 ? 2 : 0;
      self.open = false;
      // Refused (401, 5xx): no browser retry comes. The tabs hear their streams closed, ask the hub why as they
      // did, and join again; the first join opens the connection again (`take`), none opens nothing.
      if (s === 2) { self.joined = {}; self.es = null; }
      tell({ t: 'down', s: s });
    };
    this.es.addEventListener('m', function (ev) {
      var d;
      try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d.e === 'refused' || ENDS.indexOf(d.e) >= 0) delete self.joined[d.k];
      tell({ t: 'ev', k: d.k, e: d.e, d: d.d });
    });
  };
  // A key's posts go one after another: a leave sent while its join is still on the way would reach the hub first
  // (join does more work) and find nothing, and the join would then leave a tab the hub counts for ever.
  Leader.prototype.post = function (what, key) {
    var self = this, j = this.joined[key], sid = this.sid;
    var body = what === 'join' ? { stream: this.sid, key: key, doc: j.doc } : { stream: this.sid, key: key };
    var send = function () {
      return fetch('/_/live/' + what, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { return r.status; }, function () { return 0; })
        .then(function (status) {
          // The hub has no such stream for this browser (404): the connection is the closed one of another member, which
          // proxy mode keeps until it ends, or a rollover ended it. Open it again, which belongs to whoever asks now, and
          // join every stream to it; once in RETRY, so a hub that refuses every join is not asked in a loop.
          if (what === 'join' && status === 404 && self.joined[key] === j && self.es) {
            // The others of the same refused batch come back after the first reopened: their keys joined the new
            // connection already, so a refusal of the old one is no news.
            if (sid !== self.sid) return;
            if (Date.now() - self.reopened > RETRY) { self.reopen(); return; }
          }
          // A join the hub would not take (signed out, the connection gone, no answer) is that tab's stream refused.
          if (what === 'join' && (status < 200 || status > 299) && self.joined[key] === j) {
            delete self.joined[key];
            tell({ t: 'ev', k: key, e: 'refused', d: { status: status } });
          }
        });
    };
    var p = (this.sent[key] || Promise.resolve()).then(send);
    this.sent[key] = p;
    p.then(function () { if (self.sent[key] === p) delete self.sent[key]; });
  };
  Leader.prototype.reopen = function () {
    this.reopened = Date.now();
    this.es.onerror = null;
    this.es.close();
    this.sid = rnd();
    this.sent = {};
    tell({ t: 'down', s: 0 }); // the open streams were on the connection just closed: they error, as a browser's would
    this.connect();            // `onopen` joins every stream in `joined` to the new connection
  };
  Leader.prototype.take = function (m) {
    if (m.t === 'join') {
      this.joined[m.key] = { doc: m.doc, tab: m.tab, at: Date.now() };
      if (m.tab !== TAB) this.watching(m.tab);
      if (!this.es) this.connect();
      else if (this.open) this.post('join', m.key);
    } else if (m.t === 'leave' && this.joined[m.key]) {
      var tab = this.joined[m.key].tab;
      if (this.open) this.post('leave', m.key);
      delete this.joined[m.key];
      var self = this;
      // The tab has no stream left: its lock needs no watching until it joins again.
      if (this.watch[tab] && !Object.keys(this.joined).some(function (k) { return self.joined[k].tab === tab; })) {
        this.watch[tab].abort();
        delete this.watch[tab];
      }
    }
  };
  // A tab that closed without its pagehide (it crashed, it was killed) frees its lock. A request for that lock is
  // granted the moment it is freed, in a hidden leader too, whose timers Chrome slows to once a minute.
  Leader.prototype.watching = function (tab) {
    var self = this;
    if (this.watch[tab]) return;
    var ctl = this.watch[tab] = new AbortController();
    navigator.locks.request('sheaf-tab-' + tab, { signal: ctl.signal }, function () {
      if (self.watch[tab] === ctl) delete self.watch[tab];
    }).then(function () {
      // Granted and let go. A tab that is alive takes its lock back at once (this request can only beat the tab's own
      // if the two reached the lock manager out of order), so the lock must still be free to drop the tab.
      return navigator.locks.query().then(function (st) {
        var held = (st.held || []).concat(st.pending || []).some(function (l) { return l.name === 'sheaf-tab-' + tab; });
        if (!held) Object.keys(self.joined).forEach(function (k) {
          if (self.joined[k].tab === tab) self.take({ t: 'leave', key: k });
        });
      });
    }).catch(function () {});      // aborted
  };
  // The poll stays as the backstop: a tab that never held its lock, and a watch lost to an abort.
  Leader.prototype.sweep = function () {
    var self = this;
    navigator.locks.query().then(function (st) {
      var held = {};
      (st.held || []).concat(st.pending || []).forEach(function (l) { held[l.name] = true; });
      Object.keys(self.joined).forEach(function (k) {
        var j = self.joined[k];
        if (!held['sheaf-tab-' + j.tab] && Date.now() - j.at > SWEEP) self.take({ t: 'leave', key: k });
      });
    }).catch(function () {});
  };
  // Chrome freezes a background tab (memory saver, battery saver) and a frozen tab keeps its lock while relaying
  // nothing: the other tabs would stop hearing changes. So the leader lets go on `freeze` (closing its stream) and
  // queues for the lock again on `resume`; the next leader asks every tab to join its stream.
  var waiting = null;        // the abort of this tab's queued request for the lock, while it waits
  function lock() {
    var ctl = waiting = new AbortController();
    navigator.locks.request('sheaf-live', { signal: ctl.signal }, function () {
      waiting = null;
      lead = new Leader();
      chan.postMessage({ t: 'who' });
      hear({ t: 'who' });
      return new Promise(function (release) { lead.release = release; });   // held until this tab goes or freezes
    }).catch(function () {});        // aborted
  }
  document.addEventListener('freeze', function () {
    // A frozen tab queued for the lock must not be handed it either: its callback could not run.
    if (waiting) { waiting.abort(); waiting = null; }
    if (!lead) return;
    var l = lead;
    lead = null;
    l.stop();
  });
  document.addEventListener('resume', function () {
    // Its streams were on the connection it closed, or on another leader's that dropped them while it slept.
    rejoin();
    if (!lead && !waiting) lock();
  });
  lock();

  window.SheafLive = { source: function (doc) { return new Source(doc || ''); }, shared: true };
})();
