// Sheaf's own Markdown reader and writer for the plain blocks of the page editor (ADR 0003).
//
// It reads one top-level block of the file (the hub hands the page the blocks, each with its own text) into a
// ProseMirror JSON node, and writes a node back. It reads the plain blocks the editor edits: paragraph, heading,
// bullet and ordered list, quote, table, code block, rule. Everything else, and every spelling it does not keep
// exactly (a task list, a setext heading, raw HTML, a fenced div, a reference definition, an image, a footnote mark,
// a table with alignment), is a `raw` node: the block's own text, shown as it is and written back as it was.
// The pandoc fenced div syntax is never produced here; a block that holds one is a raw node until the block nodes
// of tickets 04 and 05 read it.

const RAW = (src) => ({ type: 'raw', attrs: { text: src } });

// ── inline ────────────────────────────────────────────────────────────────────

const ESCAPABLE = /[!-/:-@[-`{-~]/;
// A construct the inline reader does not keep: the block holding one stays raw, so it is never rewritten.
const UNSUPPORTED = /<[A-Za-z\/!?]|!\[|\]\[|\[\^|\^\[|\]\{|\{[.#=a-zA-Z]|\$|&[#A-Za-z0-9]+;|^\[[^\]\n]*\]:|\[[^\]\n]*\](?![(])|(^|[^\\])<https?:|:::/m;

function text(value, marks) {
  const n = { type: 'text', text: value };
  if (marks.length) n.marks = marks.map((m) => ({ ...m }));
  return n;
}

function push(out, node) {
  const last = out[out.length - 1];
  if (last && last.type === 'text' && node.type === 'text' && JSON.stringify(last.marks || []) === JSON.stringify(node.marks || [])) {
    last.text += node.text;
  } else out.push(node);
}

function closer(s, from, token) {
  // The first `token` at or after `from` that is not escaped, not inside a code span, and not preceded by a space.
  for (let i = from; i < s.length; i++) {
    if (s[i] === '\\') { i++; continue; }
    if (s[i] === '`') { const m = /^`+/.exec(s.slice(i))[0]; const e = s.indexOf(m, i + m.length); if (e < 0) continue; i = e + m.length - 1; continue; }
    if (s.startsWith(token, i) && i > from && !/\s/.test(s[i - 1])) {
      if (token.length === 1 && s[i + 1] === token) { i++; continue; }      // `*` is not the half of a `**`
      if (token === '_' && /[A-Za-z0-9]/.test(s[i + 1] || '')) continue;
      return i;
    }
  }
  return -1;
}

export function inline(s, marks = [], out = []) {
  let buf = '';
  const flush = () => { if (buf) { push(out, text(buf, marks)); buf = ''; } };
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === '\\' && i + 1 < s.length) {
      if (s[i + 1] === '\n') { flush(); push(out, { type: 'hardBreak' }); i++; continue; }
      if (ESCAPABLE.test(s[i + 1])) { buf += s[i + 1]; i++; continue; }
    }
    if (c === '<' && /^<br\s*\/?>/i.test(s.slice(i, i + 8))) {      // a line break inside a table cell
      flush(); push(out, { type: 'hardBreak' }); i += s.slice(i).match(/^<br\s*\/?>/i)[0].length - 1; continue;
    }
    if (c === ' ' && s.startsWith('  \n', i)) {
      flush(); push(out, { type: 'hardBreak' }); i += 2; while (s[i + 1] === ' ') i++; continue;
    }
    if (c === '`') {
      const run = /^`+/.exec(s.slice(i))[0];
      const end = s.indexOf(run, i + run.length);
      if (end > 0) {
        let code = s.slice(i + run.length, end);
        if (/^ .* $/s.test(code) && /\S/.test(code)) code = code.slice(1, -1);
        flush(); push(out, text(code, [...marks.filter((m) => m.type !== 'code'), { type: 'code' }]));
        i = end + run.length - 1; continue;
      }
    }
    if (c === '[' && !marks.some((m) => m.type === 'link')) {
      const m = /^\[((?:[^\[\]\\]|\\.)*)\]\(\s*(<[^>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\)/.exec(s.slice(i));
      if (m) {
        const href = m[2].startsWith('<') ? m[2].slice(1, -1) : m[2];
        flush();
        inline(m[1], [...marks, { type: 'link', attrs: { href, title: m[3] ? m[3].replace(/\\(.)/g, '$1') : null } }], out);
        i += m[0].length - 1; continue;
      }
    }
    let taken = false;
    for (const [token, mark] of [['**', 'bold'], ['__', 'bold'], ['~~', 'strike'], ['*', 'italic'], ['_', 'italic']]) {
      if (!s.startsWith(token, i) || /\s/.test(s[i + token.length] || ' ')) continue;
      if (token === '_' && /[A-Za-z0-9]/.test(s[i - 1] || '')) continue;
      if (token.length === 1 && s[i + 1] === token) continue;
      const end = closer(s, i + token.length, token);
      if (end < 0) continue;
      flush();
      inline(s.slice(i + token.length, end), [...marks.filter((m) => m.type !== mark), { type: mark }], out);
      i = end + token.length - 1;
      taken = true;
      break;
    }
    if (taken) continue;
    buf += c;
  }
  flush();
  return out;
}

// ── blocks ────────────────────────────────────────────────────────────────────

const FENCE = /^( {0,3})(`{3,}|~{3,})\s*([^\s`]*)[^`]*$/;
const BULLET = /^( {0,3})([-*+]) +(?=\S)/;
const ORDERED = /^( {0,3})(\d{1,9})([.)]) +(?=\S)/;
const RULE = /^ {0,3}([-*_])( *\1){2,} *$/;
const HEAD = /^ {0,3}(#{1,6})(?: +(.*?))?(?: +#+)? *$/;
const TASK = /^\[[ xX]\](\s|$)/;

function blankSplit(s) {
  // The blocks of a text that holds several: split at blank lines, never inside a fence.
  const out = []; let cur = []; let fence = null;
  for (const line of s.split('\n')) {
    const f = FENCE.exec(line);
    if (fence) { cur.push(line); if (f && f[2][0] === fence[0] && f[2].length >= fence.length && !f[3] && line.trim() === f[2]) fence = null; continue; }
    if (f && !line.includes('\u0000')) { fence = f[2]; cur.push(line); continue; }
    if (/^\s*$/.test(line)) { if (cur.length) out.push(cur.join('\n')); cur = []; } else cur.push(line);
  }
  if (cur.length) out.push(cur.join('\n'));
  return out;
}

function paragraph(src) {
  if (UNSUPPORTED.test(src)) return RAW(src);
  const content = inline(src.split('\n').map((l, i) => (i ? l.replace(/^ +/, '') : l)).join('\n'));
  return { type: 'paragraph', content };
}

function code(lines, f) {
  const close = lines[lines.length - 1];
  const closed = lines.length > 1 && new RegExp('^ {0,3}' + f[2][0] + '{' + f[2].length + ',} *$').test(close);
  if (!closed) return RAW(lines.join('\n'));
  const body = lines.slice(1, -1).map((l) => l.slice(Math.min(f[1].length, /^ */.exec(l)[0].length)));
  const node = { type: 'codeBlock', attrs: { language: f[3] || null, fence: f[2][0] } };
  if (body.length) node.content = [{ type: 'text', text: body.join('\n') }];
  return node;
}

function list(lines, ordered) {
  // Items start at a marker of the list's own kind with no indent beyond 3; their lines continue under it.
  const marker = ordered ? ORDERED : BULLET;
  const first = marker.exec(lines[0]);
  const kind = ordered ? first[3] : first[2];
  const items = []; let cur = null; let loose = false; let blank = false;
  for (const line of lines) {
    const m = marker.exec(line);
    if (m && (ordered ? m[3] : m[2]) === kind && (!cur || m[1].length < cur.width)) {   // a marker indented under the item's text is a list inside it
      if (cur) { if (blank) loose = true; items.push(cur); }
      cur = { head: line.slice(m[0].length), width: m[0].length, rest: [] }; blank = false; continue;
    }
    if (/^\s*$/.test(line)) { cur.rest.push(''); blank = true; continue; }
    const indent = /^ */.exec(line)[0].length;
    if (indent < cur.width && !cur.rest.length && !blank) { cur.rest.push(line.trim() ? line.replace(/^ +/, '') : ''); continue; }   // lazy continuation
    if (indent < cur.width) return null;
    cur.rest.push(line.slice(cur.width)); if (blank) { const k = cur.rest.length - 1; if (cur.rest.slice(0, k).some((l) => l.trim())) loose = true; } blank = false;
  }
  if (cur) items.push(cur);
  const nodes = [];
  for (const it of items) {
    while (it.rest.length && !it.rest[it.rest.length - 1]) it.rest.pop();
    if (TASK.test(it.head)) return null;
    const body = [it.head, ...it.rest].join('\n');
    const kids = parseBlocks(body, true);
    if (kids.some((k) => k.type === 'raw')) return null;
    if (kids.filter((k) => k.type === 'paragraph').length > 1) loose = true;
    nodes.push({ type: 'listItem', content: kids });
  }
  const node = { type: ordered ? 'orderedList' : 'bulletList', attrs: { loose, marker: ordered ? kind : first[2] }, content: nodes };
  if (ordered) node.attrs.start = parseInt(first[2], 10);
  return node;
}

function quote(lines) {
  const inner = lines.map((l) => l.replace(/^ {0,3}> ?/, '')).join('\n');
  const kids = parseBlocks(inner, true);
  if (!kids.length || kids.some((k) => k.type === 'raw')) return null;
  return { type: 'blockquote', content: kids };
}

function cells(row) {
  let r = row.trim();
  if (r.startsWith('|')) r = r.slice(1);
  if (r.endsWith('|') && !r.endsWith('\\|')) r = r.slice(0, -1);
  const out = []; let cur = '';
  for (let i = 0; i < r.length; i++) {
    if (r[i] === '\\' && r[i + 1] === '|') { cur += '|'; i++; } else if (r[i] === '|') { out.push(cur); cur = ''; } else cur += r[i];
  }
  out.push(cur);
  return out.map((c) => c.trim());
}

function table(lines) {
  if (lines.length < 2 || !/^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/.test(lines[1]) || !lines[0].includes('|')) return null;
  if (/:/.test(lines[1])) return null;                      // an alignment is not kept
  const head = cells(lines[0]);
  const width = head.length;
  if (cells(lines[1]).length !== width) return null;
  const rows = [head, ...lines.slice(2).map(cells)];
  if (rows.some((r) => r.length !== width) || rows.some((r) => r.some((c) => UNSUPPORTED.test(c)))) return null;
  return {
    type: 'table',
    content: rows.map((r, i) => ({
      type: 'tableRow',
      content: r.map((c) => ({ type: i ? 'tableCell' : 'tableHeader', content: [{ type: 'paragraph', content: c ? inline(c) : [] }] })),
    })),
  };
}

function one(src) {
  // One block's own text. Returns a node, or a raw node.
  const lines = src.split('\n');
  const f = FENCE.exec(lines[0]);
  if (f) return code(lines, f);
  if (RULE.test(lines[0]) && lines.length === 1) return { type: 'horizontalRule' };
  const h = HEAD.exec(lines[0]);
  if (h && lines.length === 1 && !UNSUPPORTED.test(h[2] || '')) return { type: 'heading', attrs: { level: h[1].length }, content: h[2] ? inline(h[2]) : [] };
  if (/^ {0,3}>/.test(lines[0])) return quote(lines) || RAW(src);
  if (/^( {4}|\t)/.test(lines[0])) return RAW(src);
  if (BULLET.test(lines[0]) && !RULE.test(lines[0])) return list(lines, false) || RAW(src);
  if (ORDERED.test(lines[0])) return list(lines, true) || RAW(src);
  if (lines[0].includes('|') && lines.length > 1) { const t = table(lines); if (t) return t; }
  if (lines.length > 1 && /^ {0,3}(=+|-+) *$/.test(lines[lines.length - 1])) return RAW(src);          // setext
  if (/^(---|\+\+\+)\s*$/.test(lines[0]) || /^ {0,3}<|^ {0,3}:::|^ {0,3}\[[^\]]*\]:|^ {0,3}\[\^/.test(lines[0])) return RAW(src);
  return paragraph(src);
}

// A list that starts on the line after a paragraph's text is a block of its own (CommonMark: a bullet list, or an ordered one that
// starts at 1, interrupts a paragraph).
function interrupted(chunk) {
  const lines = chunk.split('\n');
  if (FENCE.test(lines[0]) || /^ {0,3}>/.test(lines[0]) || BULLET.test(lines[0]) || ORDERED.test(lines[0]) || /^ {4}|^\t/.test(lines[0])) return [chunk];
  const at = lines.findIndex((l, i) => i > 0 && ((BULLET.test(l) && !RULE.test(l)) || (/^( {0,3})1[.)] +(?=\S)/.test(l))));
  if (at < 0) return [chunk];
  return [lines.slice(0, at).join('\n'), lines.slice(at).join('\n')];
}

export function parseBlocks(src, nested = false) {
  if (!nested) { const n = one(src); return [n]; }
  return blankSplit(src).flatMap(interrupted).map(one);
}

// The node of one block's own text. A block that holds more than a single block of this reader's kinds stays raw.
export function parseBlock(text) {
  const src = text.replace(/\n+$/, '');          // the hub's block text ends with its line break
  if (src.trim() === '') return RAW(text);
  const node = one(src);
  return node.type === 'raw' ? RAW(text) : node;
}

// ── writing ───────────────────────────────────────────────────────────────────

function esc(t, atStart) {
  let r = t.replace(/[\\*`\[\]<>~|]/g, '\\$&').replace(/_/g, (m, i) => (/[A-Za-z0-9]/.test(t[i - 1] || ' ') && /[A-Za-z0-9]/.test(t[i + 1] || ' ') ? m : '\\_'));
  r = r.replace(/&(?=[#A-Za-z0-9]+;)/g, '\\&');
  if (atStart) r = r.replace(/^(\s*)([#>+-])(?=\s|$)/, '$1\\$2').replace(/^(\s*\d{1,9})([.)])(?=\s|$)/, '$1\\$2').replace(/^(\s*)(={1,}|-{1,})\s*$/, '$1\\$2');
  return r;
}

function markKey(m) { return m.type === 'link' ? 'link:' + m.attrs.href + '\u0000' + (m.attrs.title || '') : m.type; }

const OPEN = { bold: '**', italic: '*', strike: '~~' };

export function inlineMarkdown(nodes) {
  const parts = nodes;
  let out = ''; let stack = [];
  const close = (to) => {
    while (stack.length > to) {
      const m = stack.pop();
      const ws = /\s+$/.exec(out);          // a closing mark may not follow a space: the space goes after it
      if (ws && m.type !== 'link') out = out.slice(0, ws.index);
      out += m.type === 'link' ? '](' + linkTarget(m) + ')' : OPEN[m.type];
      if (ws && m.type !== 'link') out += ws[0];
    }
  };
  parts.forEach((n, idx) => {
    const marks = (n.marks || []).filter((m) => m.type !== 'code');
    const keys = marks.map(markKey);
    let keep = 0;
    while (keep < stack.length && keep < keys.length && markKey(stack[keep]) === keys[keep]) keep++;
    close(keep);
    // marks of the node not yet open, outermost first: links, then bold, italic, strike
    const order = { link: 0, bold: 1, italic: 2, strike: 3 };
    let t = n;
    const fresh = marks.filter((x) => !stack.some((s) => markKey(s) === markKey(x)));
    if (fresh.length && n.type === 'text' && !(n.marks || []).some((m) => m.type === 'code')) {
      const lead = /^\s+/.exec(n.text);                  // an opening mark may not precede a space: the space goes before it
      if (lead) { out += lead[0]; t = { ...n, text: n.text.slice(lead[0].length) }; }
    }
    for (const m of marks.filter((x) => !stack.some((s) => markKey(s) === markKey(x))).sort((a, b) => order[a.type] - order[b.type])) {
      out += m.type === 'link' ? '[' : OPEN[m.type];
      stack.push(m);
    }
    if (n.type === 'hardBreak') out += '\\\n';
    else if ((n.marks || []).some((m) => m.type === 'code')) {
      const run = Math.max(0, ...(n.text.match(/`+/g) || []).map((x) => x.length)) + 1;
      const f = '`'.repeat(run);
      out += f + (n.text.startsWith('`') || n.text.endsWith('`') ? ' ' + n.text + ' ' : n.text) + f;
    } else out += esc(t.text, idx === 0 && !out);
  });
  close(0);
  return out;
}

function linkTarget(m) {
  const href = /[\s()<>]/.test(m.attrs.href) ? '<' + m.attrs.href + '>' : m.attrs.href;
  return href + (m.attrs.title ? ' "' + m.attrs.title.replace(/["\\]/g, '\\$&') + '"' : '');
}

function indent(s, first, rest) { return s.split('\n').map((l, i) => (i ? (l ? rest + l : l) : first + l)).join('\n'); }

function listMarkdown(node) {
  const ordered = node.type === 'orderedList';
  const loose = node.attrs && node.attrs.loose;
  let n = ordered ? (node.attrs.start || 1) : 0;
  const items = (node.content || []).map((item) => {
    const marker = ordered ? (n++) + ((node.attrs && node.attrs.marker) || '.') + ' ' : ((node.attrs && node.attrs.marker) || '-') + ' ';
    const body = (item.content || []).map(blockMarkdown);
    return indent(body.join(loose ? '\n\n' : '\n'), marker, ' '.repeat(marker.length));
  });
  return items.join(loose ? '\n\n' : '\n');
}

export function blockMarkdown(node) {
  switch (node.type) {
    case 'paragraph': return inlineMarkdown(node.content || []);
    case 'heading': return '#'.repeat(node.attrs.level) + (node.content && node.content.length ? ' ' + inlineMarkdown(node.content) : '');
    case 'horizontalRule': return '---';
    case 'raw': return node.attrs.text.replace(/\n+$/, '');
    case 'codeBlock': {
      const body = (node.content || []).map((c) => c.text).join('');
      const ch = (node.attrs && node.attrs.fence) || '`';
      const run = Math.max(2, ...(body.match(new RegExp(ch + '{3,}', 'g')) || []).map((x) => x.length)) + 1;
      const f = ch.repeat(Math.max(3, run));
      return f + ((node.attrs && node.attrs.language) || '') + '\n' + body + (body ? '\n' : '') + f;
    }
    case 'blockquote': {
      const inner = (node.content || []).map(blockMarkdown).join('\n\n');
      return inner.split('\n').map((l) => (l ? '> ' + l : '>')).join('\n');
    }
    case 'bulletList': case 'orderedList': return listMarkdown(node);
    case 'table': {
      // A cell holds one line of Markdown: its paragraphs and its hard breaks are written as <br>.
      const rows = (node.content || []).map((r) => (r.content || []).map((c) =>
        (c.content || []).map((p) => inlineMarkdown(p.content || []).replace(/\\\n/g, '<br>')).join('<br>')
          .replace(/(?<!\\)\|/g, '\\|').replace(/\n/g, ' ')));
      const line = (r) => '| ' + r.join(' | ') + ' |';
      return [line(rows[0]), line(rows[0].map(() => '---')), ...rows.slice(1).map(line)].join('\n');
    }
    default: return '';
  }
}
