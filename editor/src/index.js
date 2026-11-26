// The block editor of the sheaf page (ADR 0003): TipTap inside the vanilla page, on the plain blocks.
//
//   window.sheafBlockEditor.mount(host, { lead, blocks: [{id, content, gap}], onChange }) -> handle
//   handle.markdown()       the whole document as Markdown; a block nobody touched is its own text, as it was read
//   handle.ids()            the id each top-level block held at load, null for a block made here
//   handle.freshMarkdown()  as markdown(), with every block written by this editor's writer (the tests' round trip)
//   handle.destroy()
//
// Each top-level node carries its `bid` (the hub's id for the block at load), its `src` (the text it was read from),
// its `gap` (the blank lines after it) and a `sig` (a hash of its content at load). A node whose content still has
// its `sig` is written as `src`, so a block this editor cannot spell back exactly is never rewritten by a page that
// did not edit it.
import { Editor, Extension, Node } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { BulletList, OrderedList } from '@tiptap/extension-list';
import CodeBlock from '@tiptap/extension-code-block';
import { Table, TableRow, TableCell as BaseCell, TableHeader as BaseHeader } from '@tiptap/extension-table';
import { parseBlock, blockMarkdown } from './markdown.js';

const TOP = ['paragraph', 'heading', 'bulletList', 'orderedList', 'blockquote', 'table', 'codeBlock', 'horizontalRule', 'raw'];
const OWN = ['bid', 'src', 'sig', 'gap'];

const attr = (name, fallback = null) => ({
  default: fallback, rendered: false, keepOnSplit: false,
  parseHTML: () => fallback,
});

const Own = Extension.create({
  name: 'sheafBlockOwn',
  addGlobalAttributes() {
    return [{ types: TOP, attributes: Object.fromEntries(OWN.map((n) => [n, attr(n)])) }];
  },
});

const Raw = Node.create({
  name: 'raw',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,
  addAttributes() { return { text: { default: '', rendered: false } }; },
  parseHTML() { return [{ tag: 'pre.sheaf-raw', getAttrs: (el) => ({ text: el.textContent }) }]; },
  renderHTML({ node }) { return ['pre', { class: 'sheaf-raw', title: 'Not editable here: edit this block in the .md file.' }, node.attrs.text]; },
});

const withAttrs = (n, extra) => n.extend({ addAttributes() { return { ...this.parent?.(), ...extra }; } });
const loose = { default: false, rendered: false };
const Bullets = withAttrs(BulletList, { loose, marker: { default: '-', rendered: false } });
const Ordered = withAttrs(OrderedList, { loose, marker: { default: '.', rendered: false } });
const Fenced = withAttrs(CodeBlock, { fence: { default: '`', rendered: false } });

function sigOf(node) {
  const j = node.toJSON();
  const a = { ...(j.attrs || {}) };
  for (const k of OWN) delete a[k];
  return JSON.stringify({ t: j.type, a, c: j.content || null });
}

function hash(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return String(h >>> 0) + ':' + s.length;
}

// Enter in a table cell is a line break: a Markdown cell is one line, and a second paragraph would be lost.
const enterBreaks = { addKeyboardShortcuts() { return { Enter: () => this.editor.commands.setHardBreak() }; } };
const TableCell = BaseCell.extend(enterBreaks);
const TableHeader = BaseHeader.extend(enterBreaks);

export function mount(host, { lead = '', blocks = [], onChange = () => {} } = {}) {
  const kit = StarterKit.configure({
    underline: false, link: { openOnClick: false, autolink: false }, trailingNode: false,
    bulletList: false, orderedList: false, codeBlock: false,
  });
  const editor = new Editor({
    element: host,
    extensions: [kit, Bullets, Ordered, Fenced, Table, TableRow, TableCell, TableHeader, Raw, Own],
    content: { type: 'doc', content: blocks.length ? blocks.map((b) => nodeOf(b)) : [{ type: 'paragraph' }] },
    editorProps: { attributes: { class: 'sheaf-be-doc', spellcheck: 'true' } },
    onUpdate: () => onChange(),
  });
  // Mark every block as read: its signature, so an untouched one is written as it was.
  const tr = editor.state.tr;
  editor.state.doc.forEach((node, pos) => {
    if (node.attrs.src != null) tr.setNodeMarkup(pos, undefined, { ...node.attrs, sig: hash(sigOf(node)) });
  });
  tr.setMeta('addToHistory', false);
  editor.view.dispatch(tr);
  const order = [];
  editor.state.doc.forEach((n) => order.push(n.attrs.bid));

  function write(fresh) {
    const nodes = []; editor.state.doc.forEach((n) => nodes.push(n));
    let out = lead;
    nodes.forEach((n, i) => {
      const keep = !fresh && n.attrs.src != null && n.attrs.sig === hash(sigOf(n));
      const body = keep ? n.attrs.src : blockMarkdown(n.toJSON()) + '\n';      // a block's text ends with its line break
      const last = i === nodes.length - 1;
      const next = nodes[i + 1];
      let gap;
      const was = n.attrs.bid != null ? order.indexOf(n.attrs.bid) : -1;
      const nextWas = next && next.attrs.bid != null ? order.indexOf(next.attrs.bid) : -2;
      if (n.attrs.gap != null && was >= 0 && (last ? was === order.length - 1 : nextWas === was + 1)) gap = n.attrs.gap;
      else gap = last ? '' : '\n';                                                // one blank line between blocks
      out += body + gap;
    });
    return out;
  }

  const handle = {
    editor,
    markdown: () => write(false),
    freshMarkdown: () => write(true),
    ids: () => { const ids = []; editor.state.doc.forEach((n) => ids.push(n.attrs.bid || null)); return ids; },
    destroy: () => editor.destroy(),
  };
  window.sheafBlockEditor.last = handle;       // the page tests read it
  return handle;
}

function nodeOf(b) {
  const node = parseBlock(b.content);
  node.attrs = { ...(node.attrs || {}), bid: b.id, src: b.content, gap: b.gap };
  return node;
}

if (typeof window !== 'undefined') window.sheafBlockEditor = { mount };
