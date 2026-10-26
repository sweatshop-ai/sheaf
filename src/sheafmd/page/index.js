/* sheaf index page: keeps itself current from the hub's index stream (SPEC 8.6, 8.8).
   The server writes every row. This script never builds markup from an event: an event only
   says that something moved, and the page then asks for itself again and swaps the list in.
   It also keeps "4 min ago" true between events. */
(function () {
  'use strict';
  var list = document.getElementById('roots');
  var note = document.getElementById('live');
  if (!list) return;

  // The same words as sheafmd.hub.index.ago, so a row reads the same before and after a refresh.
  function ago(sec) {
    if (sec < 45) return 'just now';
    if (sec < 3600) return Math.max(1, Math.floor(sec / 60)) + ' min ago';
    if (sec < 86400) return Math.floor(sec / 3600) + ' h ago';
    var d = Math.floor(sec / 86400);
    return d + (d === 1 ? ' day ago' : ' days ago');
  }
  function retime() {
    var now = Date.now() / 1000;
    var els = list.querySelectorAll('time[data-mtime]');
    for (var i = 0; i < els.length; i++) {
      var t = parseFloat(els[i].getAttribute('data-mtime'));
      var sec = now - t;
      // Past 30 days the server writes a date, and a date does not age.
      if (sec < 30 * 86400) els[i].textContent = ago(sec);
    }
  }
  setInterval(retime, 30000);

  function say(text) {
    if (!note) return;
    note.textContent = text || '';
    note.hidden = !text;
  }

  // Ask the hub for this same page again and swap the list in. One at a time, and the last
  // request wins: a burst of events is one refresh, a moment after the last one.
  var timer = null, busy = false, again = false;
  function refresh() {
    if (busy) { again = true; return; }
    busy = true;
    fetch(location.pathname, { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.text(); })
      .then(function (text) {
        var fresh = new DOMParser().parseFromString(text, 'text/html').getElementById('roots');
        if (fresh) { list.innerHTML = fresh.innerHTML; retime(); }
      })
      .catch(function () {})
      .then(function () { busy = false; if (again) { again = false; soon(); } });
  }
  function soon() {
    clearTimeout(timer);
    timer = setTimeout(refresh, 250);
  }

  if (!window.EventSource) return;
  var es = new EventSource('/_/live');
  var stopped = false;   // the hub said it stopped; until its next `hello`
  // `hello` is also what closes the gap between the page being written and the stream being
  // open, and after a reconnect what moved while the hub was away.
  es.addEventListener('hello', function () { stopped = false; say(''); soon(); });
  es.addEventListener('status', soon);
  // The hub's key was changed: this browser is no longer signed in. The server ends the stream;
  // asking for the page again shows the sign-in page, and the list is no longer on screen.
  es.addEventListener('signed-out', function () { es.close(); location.reload(); });
  // The hub closes the stream after `hub-stopping`, which fires `onerror`: the line that the hub
  // stopped stays until a `hello` says it runs again. A restart for an upgrade is no stop (the
  // document page does the same): that gap reads "Reconnecting".
  es.addEventListener('hub-stopping', function (ev) {
    var d = {};
    try { d = JSON.parse(ev.data); } catch (e) {}
    if (d.reason !== 'stop' && d.reason !== 'signal') return;
    stopped = true;
    say('The hub stopped. This page updates again when it runs.');
  });
  es.onerror = function () { if (!stopped) say('Reconnecting to the hub…'); };
})();
