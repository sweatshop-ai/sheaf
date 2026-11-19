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
    if (e === 'hub-stopping' || e === 'signed-out' || e === 'gone') {
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
      Object.keys(mine).forEach(function (k) { ask({ t: 'join', key: k, doc: mine[k].doc, tab: TAB }); });
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
  window.addEventListener('pagehide', function () {
    Object.keys(mine).forEach(function (k) { chan.postMessage({ t: 'leave', key: k }); });
  });

  // ---- the leader: the one tab that holds the connection ---------------------------
  var lead = null;
  function Leader() {
    this.joined = {};          // key -> {doc, tab, at}: every stream this browser wants
    this.sid = rnd();
    this.es = null;
    this.open = false;
    this.connect();
    var self = this;
    setInterval(function () { self.sweep(); }, SWEEP);
  }
  Leader.prototype.connect = function () {
    var self = this;
    this.open = false;
    this.es = new EventSource('/_/live?shared=' + this.sid);
    this.es.onopen = function () {
      self.open = true;
      Object.keys(self.joined).forEach(function (k) { self.post('join', k); });
    };
    this.es.onerror = function () {
      var s = self.es.readyState === 2 ? 2 : 0;
      self.open = false;
      // Refused (401, 5xx): no browser retry comes. The tabs hear their streams closed, ask the hub why as they
      // did, and join again; the leader opens the connection again for them.
      if (s === 2) { self.joined = {}; setTimeout(function () { self.connect(); }, RETRY); }
      tell({ t: 'down', s: s });
    };
    this.es.addEventListener('m', function (ev) {
      var d;
      try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d.e === 'refused' || d.e === 'hub-stopping' || d.e === 'signed-out' || d.e === 'gone') delete self.joined[d.k];
      tell({ t: 'ev', k: d.k, e: d.e, d: d.d });
    });
  };
  Leader.prototype.post = function (what, key) {
    var self = this, j = this.joined[key];
    var body = what === 'join' ? { stream: this.sid, key: key, doc: j.doc } : { stream: this.sid, key: key };
    fetch('/_/live/' + what, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) {
        // A join the hub would not take (signed out, the connection gone) is that tab's stream refused.
        if (what === 'join' && !r.ok && self.joined[key] === j) {
          delete self.joined[key];
          tell({ t: 'ev', k: key, e: 'refused', d: { status: r.status } });
        }
      })
      .catch(function () {});
  };
  Leader.prototype.take = function (m) {
    if (m.t === 'join') {
      this.joined[m.key] = { doc: m.doc, tab: m.tab, at: Date.now() };
      if (this.open) this.post('join', m.key);
    } else if (m.t === 'leave' && this.joined[m.key]) {
      if (this.open) this.post('leave', m.key);
      delete this.joined[m.key];
    }
  };
  // A tab that closed without its pagehide (it crashed, it was killed) leaves its lock behind.
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
  navigator.locks.request('sheaf-live', function () {
    lead = new Leader();
    chan.postMessage({ t: 'who' });
    hear({ t: 'who' });
    return new Promise(function () {});        // held until this tab goes
  });

  window.SheafLive = { source: function (doc) { return new Source(doc || ''); }, shared: true };
})();
