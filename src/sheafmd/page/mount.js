/* sheaf: mount.js, the loader's side of a mounted page (#116 step 2).
 *
 * The front (Open WebUI) loads this once and calls sheafMount.mount(host, {doc}). The hub answers /_/mount?doc= with the
 * page as JSON; the text in it is a stranger's (a mail, a comment, an agent's page). The server has already sanitised it
 * (sanitize.py, mount mode), and this file does not trust that: it never puts the hub's text into the page with innerHTML.
 * It parses it with DOMParser, which runs nothing and loads nothing, and builds a new tree node by node from the allow-lists
 * below with createElement / createElementNS / textContent. An element or attribute that is not named here does not exist in
 * the result, so a parser quirk that makes the browser read the text differently the second time cannot arise: it is not read
 * a second time. Limits on depth and node count keep a hostile page from hanging the front.
 *
 * Author ids are namespaced ("u-" + id) and so are the fragment links that point at them, so a document cannot take the
 * name of anything the page itself uses, and the page's own elements never carry a name from the document.
 */
(function () {
  'use strict';

  const HTML_NS = 'http://www.w3.org/1999/xhtml';
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ID_PREFIX = 'u-';
  const MAX_DEPTH = 60;
  const MAX_NODES = 200000;
  const MAX_TEXT = 4 * 1024 * 1024;
  const MAX_INPUT = 16 * 1024 * 1024;
  // What the scan below allows before DOMParser sees the text. The server cuts nesting at 100 (sanitize.py); a page that
  // reaches here deeper than this did not come through it, and DOMParser costs the square of the depth (Chromium: 20 s at 100,000).
  const MAX_SCAN_DEPTH = 1500;
  const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);

  const set = (s) => new Set(s.split(/\s+/).filter(Boolean));

  const HTML_ELEMENTS = set(`a abbr address article aside b bdi bdo blockquote br caption cite code col colgroup dd del details dfn
    div dl dt em figcaption figure footer h1 h2 h3 h4 h5 h6 header hr i img input ins kbd li main mark nav ol p pre q rp rt ruby s
    samp section small span strong sub summary sup table tbody td tfoot th thead time tr u ul var wbr`);
  // Dropped with everything inside them. An unknown element that is not here keeps its children and loses itself.
  const DROP_WITH_CONTENT = set(`script style template noscript iframe frame frameset object embed applet base meta link form
    button textarea select option optgroup datalist title head audio video source track picture canvas dialog portal math svg:use
    svg:image svg:foreignObject svg:script svg:style svg:animate svg:set svg:animateTransform svg:animateMotion svg:a xmp plaintext
    noembed noframes slot`);
  const SVG_ELEMENTS = set(`svg g path rect circle ellipse line polyline polygon text tspan defs linearGradient stop title desc`);

  const GLOBAL_ATTRS = set('id class title lang dir');
  const HTML_ATTRS = {
    a: set('href'),
    img: set('src alt width height'),
    td: set('colspan rowspan align valign'),
    th: set('colspan rowspan align valign scope'),
    col: set('span'),
    colgroup: set('span'),
    ol: set('start reversed type'),
    li: set('value'),
    details: set('open'),
    time: set('datetime'),
    input: set('type checked disabled'),
    table: set('border'),
  };
  const SVG_ATTRS = set(`id class viewBox width height x y x1 y1 x2 y2 cx cy r rx ry d points fill stroke stroke-width stroke-linecap
    stroke-linejoin stroke-dasharray stroke-opacity fill-opacity opacity font-size font-weight font-style text-anchor
    dominant-baseline offset stop-color stop-opacity gradientUnits gradientTransform transform preserveAspectRatio style`);

  // The style attribute: the declarations of this list, each value matching its grammar completely. The same list as
  // sanitize.py's _MOUNT_STYLE; a declaration that is not here is dropped alone and the rest stays.
  const LEN = '(?:0|\\d{1,4}(?:\\.\\d{1,3})?(?:px|em|rem|%|pt|ch|ex))';
  const COLOR = '(?:#[0-9a-f]{3,8}|[a-z]{3,24}|(?:rgb|hsl)a?\\(\\s*\\d{1,3}(?:\\.\\d+)?%?(?:\\s*,\\s*\\d{1,3}(?:\\.\\d+)?%?){2}' +
    '(?:\\s*,\\s*(?:0|1|0?\\.\\d+|\\d{1,3}%))?\\s*\\))';
  const LINE = '(?:none|hidden|dotted|dashed|solid|double|groove|ridge|inset|outset)';
  const STYLE = {
    'text-align': '(?:left|right|center|justify|start|end)',
    'vertical-align': '(?:baseline|sub|super|top|middle|bottom|text-top|text-bottom)',
    'font-weight': '(?:normal|bold|bolder|lighter|[1-9]00)',
    'font-style': '(?:normal|italic|oblique)',
    'text-decoration': '(?:none|(?:underline|overline|line-through)(?: (?:underline|overline|line-through))*)',
    'color': COLOR, 'background-color': COLOR, 'fill': COLOR, 'stroke': COLOR,
    'width': LEN, 'max-width': LEN,
    'list-style-type': '(?:none|disc|circle|square|decimal|lower-alpha|upper-alpha|lower-roman|upper-roman|lower-latin|upper-latin)',
  };
  for (const side of ['', '-top', '-right', '-bottom', '-left']) {
    STYLE['margin' + side] = LEN + '(?: ' + LEN + '){0,3}';
    STYLE['padding' + side] = LEN + '(?: ' + LEN + '){0,3}';
    STYLE['border' + side] = '(?:' + LEN + '|' + LINE + '|' + COLOR + ')(?: (?:' + LEN + '|' + LINE + '|' + COLOR + ')){0,2}';
  }
  const STYLE_RE = Object.fromEntries(Object.entries(STYLE).map(([k, v]) => [k, new RegExp('^' + v + '$', 'i')]));

  function cleanStyle(value) {
    const kept = [];
    for (const decl of String(value).split(';')) {
      const at = decl.indexOf(':');
      if (at < 0) continue;
      const prop = decl.slice(0, at).trim().toLowerCase();
      const val = decl.slice(at + 1).trim().replace(/\s+/g, ' ').toLowerCase();
      if (STYLE_RE[prop] && STYLE_RE[prop].test(val)) kept.push(prop + ':' + val);
    }
    return kept.join(';');
  }

  const CONTROL = /[\u0000- \u007f]+/g;
  const SCHEME = /^([^/?#]*):/;
  const LINK_SCHEMES = new Set(['http', 'https', 'mailto']);
  const IMAGE_DATA = /^data:image\/(?:png|jpeg|gif|webp)[;,]/i;

  function linkOk(value) {
    const v = value.replace(CONTROL, '');
    if (v.includes('\\')) return false;
    const m = SCHEME.exec(v);
    return !m || LINK_SCHEMES.has(m[1].toLowerCase());
  }

  function imageOk(value) {
    const v = value.replace(CONTROL, '');
    if (v.includes('\\') || v.startsWith('//')) return false;
    return !SCHEME.test(v) || IMAGE_DATA.test(v);
  }

  const UINT = /^\d{1,6}$/;
  const SIZE = /^\d{1,5}(?:\.\d{1,3})?(?:px|%|em)?$/;
  const NUMLIST = /^[-\d.,\s eE]{1,2000}$/;
  const PATH_D = /^[MmLlHhVvCcSsQqTtAaZz\d\s.,eE+-]{1,20000}$/;
  const SVG_PAINT = /^(?:none|currentColor|#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,24}|(?:rgb|hsl)a?\([\d\s.,%]{1,40}\)|url\(#[\w:.-]{1,100}\))$/;
  const TRANSFORM = /^(?:\s*(?:translate|scale|rotate|skewX|skewY|matrix)\([-\d.,\s eE]{1,120}\)\s*){1,8}$/;
  const FIT = /^[-\w\s.,:%]{1,100}$/;

  const own = (id) => ID_PREFIX + id;
  const IDENT = /^[\w:.-]{1,100}$/;

  function htmlAttr(el, tag, name, value) {
    if (name === 'id') { if (IDENT.test(value) && !/^rd-/i.test(value)) el.setAttribute('id', own(value)); return; }
    if (name === 'class') {
      const kept = value.split(/\s+/).filter((c) => c && !/^rd-/i.test(c) && /^[\w:.-]{1,100}$/.test(c));
      if (kept.length) el.setAttribute('class', kept.join(' '));
      return;
    }
    if (name === 'title' || name === 'lang' || name === 'dir' || name === 'alt') {
      if (name !== 'dir' || /^(?:ltr|rtl|auto)$/i.test(value)) el.setAttribute(name, value.slice(0, 2000));
      return;
    }
    if (name === 'href') {
      if (value.trim().startsWith('#')) { const f = value.trim().slice(1); if (IDENT.test(f)) el.setAttribute('href', '#' + own(f)); return; }
      if (linkOk(value)) el.setAttribute('href', value);
      return;
    }
    if (name === 'src') { if (imageOk(value)) el.setAttribute('src', value); return; }
    if (name === 'width' || name === 'height') { if (SIZE.test(value)) el.setAttribute(name, value); return; }
    if (name === 'colspan' || name === 'rowspan' || name === 'span' || name === 'start' || name === 'value' || name === 'border') {
      if (UINT.test(value)) el.setAttribute(name, value);
      return;
    }
    if (name === 'align') { if (/^(?:left|right|center|justify)$/i.test(value)) el.setAttribute(name, value.toLowerCase()); return; }
    if (name === 'valign') { if (/^(?:top|middle|bottom|baseline)$/i.test(value)) el.setAttribute(name, value.toLowerCase()); return; }
    if (name === 'scope') { if (/^(?:row|col|rowgroup|colgroup)$/i.test(value)) el.setAttribute(name, value.toLowerCase()); return; }
    if (name === 'type') {
      if (tag === 'ol' && /^(?:1|a|A|i|I)$/.test(value)) el.setAttribute('type', value);
      return;
    }
    if (name === 'reversed' || name === 'open' || name === 'checked' || name === 'disabled') { el.setAttribute(name, ''); return; }
    if (name === 'datetime') { if (/^[\d\-T:.+Z\s]{1,40}$/.test(value)) el.setAttribute(name, value); }
  }

  function svgAttr(el, name, value) {
    if (name === 'id') { if (IDENT.test(value) && !/^rd-/i.test(value)) el.setAttribute('id', own(value)); return; }
    if (name === 'class') { if (/^[\w\s:.-]{1,200}$/.test(value) && !/(^|\s)rd-/i.test(value)) el.setAttribute('class', value); return; }
    if (name === 'style') { const c = cleanStyle(value); if (c) el.setAttribute('style', c); return; }
    if (name === 'fill' || name === 'stroke' || name === 'stop-color') {
      const v = value.trim();
      if (!SVG_PAINT.test(v)) return;
      el.setAttribute(name, v.replace(/^url\(#([\w:.-]+)\)$/, (_, id) => 'url(#' + own(id) + ')'));
      return;
    }
    if (name === 'd') { if (PATH_D.test(value)) el.setAttribute(name, value); return; }
    if (name === 'points' || name === 'stroke-dasharray' || name === 'viewBox') { if (NUMLIST.test(value)) el.setAttribute(name, value); return; }
    if (name === 'transform' || name === 'gradientTransform') { if (TRANSFORM.test(value)) el.setAttribute(name, value); return; }
    if (name === 'preserveAspectRatio') { if (FIT.test(value)) el.setAttribute(name, value); return; }
    if (name === 'gradientUnits') { if (/^(?:userSpaceOnUse|objectBoundingBox)$/.test(value)) el.setAttribute(name, value); return; }
    if (name === 'font-weight' || name === 'font-style' || name === 'text-anchor' || name === 'dominant-baseline' ||
        name === 'stroke-linecap' || name === 'stroke-linejoin') {
      if (/^[a-z0-9-]{1,20}$/i.test(value)) el.setAttribute(name, value);
      return;
    }
    if (SIZE.test(value) || /^-?\d{1,5}(?:\.\d{1,3})?(?:px|%|em)?$/.test(value)) el.setAttribute(name, value);
  }

  /** True when a linear scan of the tags finds more nesting than MAX_SCAN_DEPTH. `<x/>` opens an element in HTML and closes
   *  at once inside svg, so it counts as an open tag except inside an <svg>. An estimate that errs toward refusing. */
  function nestedTooDeep(html) {
    const re = /<(\/?)([a-zA-Z][a-zA-Z0-9:-]*)[^>]*?(\/?)>/g;
    let depth = 0;
    let svg = 0;
    for (let m = re.exec(html); m; m = re.exec(html)) {
      const name = m[2].toLowerCase();
      if (m[1]) { depth = Math.max(0, depth - 1); if (name === 'svg') svg = Math.max(0, svg - 1); continue; }
      if (VOID.has(name)) continue;
      if (m[3] && svg > 0) continue;
      if (++depth > MAX_SCAN_DEPTH) return true;
      if (name === 'svg' && !m[3]) svg++;
    }
    return false;
  }

  function refused(doc, why) {
    const out = doc.createDocumentFragment();
    const p = doc.createElement('p');
    p.textContent = why;
    out.appendChild(p);
    out.sheafStats = { nodes: 1, truncated: true };
    return out;
  }

  /** The tree `html` describes, rebuilt from the allow-lists, as a DocumentFragment in `target`'s document. Nothing in
   *  `html` runs or loads while this is called, and nothing it names outside the lists is in the result. */
  function rebuild(html, target) {
    const doc = target && target.ownerDocument ? target.ownerDocument : document;
    if (String(html).length > MAX_INPUT) return refused(doc, 'This page is too large to show here.');
    if (nestedTooDeep(String(html))) return refused(doc, 'This page is nested too deeply to show here.');
    const parsed = new DOMParser().parseFromString('<!doctype html><body>' + String(html), 'text/html');
    const out = doc.createDocumentFragment();
    let nodes = 0;
    let chars = 0;
    const stats = { nodes: 0, truncated: false };

    // An explicit stack, not recursion: a document nested ten thousand deep must not throw.
    const work = [{ from: parsed.body, to: out, depth: 0, next: parsed.body.firstChild }];
    while (work.length) {
      const frame = work[work.length - 1];
      const n = frame.next;
      if (!n) { work.pop(); continue; }
      frame.next = n.nextSibling;
      if (nodes >= MAX_NODES) { stats.truncated = true; break; }

      if (n.nodeType === Node.TEXT_NODE) {
        chars += n.data.length;
        if (chars > MAX_TEXT) { stats.truncated = true; break; }
        frame.to.appendChild(doc.createTextNode(n.data));
        nodes++;
        continue;
      }
      if (n.nodeType === Node.COMMENT_NODE) {      // block sentinels and the sheaf's comments are comments; DOM text, never parsed again
        if (n.data.length <= 100000) { frame.to.appendChild(doc.createComment(n.data)); nodes++; }
        continue;
      }
      if (n.nodeType !== Node.ELEMENT_NODE) continue;

      const ns = n.namespaceURI;
      const local = ns === SVG_NS ? n.localName : n.localName.toLowerCase();
      let target2 = null;
      let keep = false;

      if (ns === HTML_NS) {
        if (DROP_WITH_CONTENT.has(local)) continue;
        if (HTML_ELEMENTS.has(local)) {
          if (local === 'input' && String(n.getAttribute('type') || '').toLowerCase() !== 'checkbox') continue;
          keep = true;
        }
      } else if (ns === SVG_NS) {
        if (DROP_WITH_CONTENT.has('svg:' + local)) continue;
        if (SVG_ELEMENTS.has(local)) keep = true;
      } else {
        continue;                                  // MathML, or anything else: dropped with its content
      }

      if (!keep) {                                 // unknown but harmless: the element goes, its children stay
        if (frame.depth + 1 > MAX_DEPTH) { stats.truncated = true; continue; }
        work.push({ from: n, to: frame.to, depth: frame.depth + 1, next: n.firstChild });
        continue;
      }
      if (frame.depth + 1 > MAX_DEPTH) {           // too deep: its text only, so nothing the reader wrote is lost
        stats.truncated = true;
        frame.to.appendChild(doc.createTextNode(n.textContent.slice(0, 10000)));
        continue;
      }

      const el = ns === SVG_NS ? doc.createElementNS(SVG_NS, local) : doc.createElement(local);
      nodes++;
      for (const a of Array.from(n.attributes)) {
        if (a.namespaceURI) continue;              // xlink:href, xml:*, xmlns:*: none is kept
        const name = ns === SVG_NS ? a.name : a.name.toLowerCase();
        const value = a.value;
        if (value.length > 20000) continue;
        if (ns === SVG_NS) {
          if (SVG_ATTRS.has(name)) svgAttr(el, name, value);
        } else if (GLOBAL_ATTRS.has(name) || (HTML_ATTRS[local] && HTML_ATTRS[local].has(name))) {
          htmlAttr(el, local, name, value);
        } else if (name === 'style') {
          const c = cleanStyle(value);
          if (c) el.setAttribute('style', c);
        }
      }
      if (local === 'img' && !el.hasAttribute('src')) {      // an address the page does not load: what the reader was told instead
        const alt = (n.getAttribute('alt') || '').trim();
        if (alt) frame.to.appendChild(doc.createTextNode(alt));
        continue;
      }
      if (local === 'a' && el.hasAttribute('href')) el.setAttribute('rel', 'noopener noreferrer');
      if (local === 'input') { el.setAttribute('type', 'checkbox'); el.setAttribute('disabled', ''); }
      frame.to.appendChild(el);
      work.push({ from: n, to: el, depth: frame.depth + 1, next: n.firstChild });
    }
    stats.nodes = nodes;
    out.sheafStats = stats;
    return out;
  }

  /** Mount the sheaf `opts.doc` in `host`: a CLOSED shadow root (the front's CSS and the page's cannot touch each other, and a
   *  script of the front cannot walk into it by `host.shadowRoot`), the document's own styles, then its rebuilt body, and the
   *  page's behaviour on it (page.js, served after this file in /_/mount.js: sheafPage.create). Resolves to {config, title,
   *  toc, unmount, dirty, remount}. remount() fetches the page again and builds it in place of the old one, which is what a
   *  reload of a page of its own did; the page calls it where it called location.reload(). The wrapper is the scroller and
   *  takes focus on a click, so the page's keys reach its root. With `opts.list` (a root's name) and `opts.show` instead
   *  of `opts.doc`, the list: its rows are data, drawn by list.js `render` from text, and its script is sheafList.create. */
  async function mount(host, opts) {
    const list = opts.list != null;
    const url = list
      ? '/_/mount?list=' + encodeURIComponent(opts.list) + (opts.show ? '&show=' + encodeURIComponent(opts.show) : '')
      : '/_/mount?doc=' + encodeURIComponent(opts.doc);
    const root = host.attachShadow({ mode: 'closed' });
    const doc = host.ownerDocument;
    const kit = list ? window.sheafList : window.sheafPage;          // taken now: a later front script cannot swap it in
    const create = kit && kit.create;
    const render = list && kit && kit.render;
    let page = null;
    let got = null;
    // Each draw has a number; one that a newer draw or unmount() overtook while its fetch or its stylesheet was out
    // builds nothing, so two pages never stand at once and an older answer never replaces a newer one. `cut` ends
    // the wait of the draw in flight: a <link> taken out of the root before it loads fires neither load nor error.
    let drawn = 0;
    let gone = false;
    let cut = () => {};
    async function draw() {
      const mine = ++drawn;
      cut();
      const stale = () => gone || mine !== drawn;
      const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error('the hub answered ' + res.status + ' for ' + (list ? 'the list' : opts.doc));
      const fresh = await res.json();
      if (stale()) return got;
      if (list && (fresh.kind !== 'list' || !render)) throw new Error('the hub sent no list');
      got = fresh;
      const parts = [];
      if (!list) {
        const style = doc.createElement('style');
        style.textContent = got.css;                // the hub's own text: fonts, base and theme
        parts.push(style);
      }
      const link = doc.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/_/mount.css?v=' + encodeURIComponent(got.version);
      const wrap = doc.createElement('div');
      wrap.className = list ? 'rd-root sheaf-list' : 'rd-root' + (got.toc ? '' : ' notoc');
      wrap.tabIndex = -1;
      wrap.appendChild(list ? render(got.list, wrap) : rebuild(got.html, wrap));
      if (page) page.unmount();
      page = null;
      root.replaceChildren(...parts, link, wrap);
      await new Promise((done) => { link.onload = link.onerror = done; cut = done; });   // the page measures its parts: their styles first
      if (stale()) return got;
      const again = { body: wrap, remount: () => { draw().catch(() => {}); } };
      if (create) page = list ? create(root, again) : create(root, got.config, again);
      return got;
    }
    await draw();
    return {
      get config() { return got.config; }, get title() { return got.title; }, get toc() { return got.toc; },
      unmount() { gone = true; cut(); if (page) page.unmount(); page = null; root.replaceChildren(); },
      dirty() { return !!page && page.dirty(); },
      remount: draw,
    };
  }

  window.sheafMount = Object.freeze({ rebuild, mount, ID_PREFIX, cleanStyle });
})();
