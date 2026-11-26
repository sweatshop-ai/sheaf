// Builds ../src/sheafmd/page/editor.bundle.js from src/index.js. The same command runs on the laptop and in CI
// (tests/test_editor_bundle.py and the CI step "Rebuild the editor bundle"): the output must be byte-identical.
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
await build({
  entryPoints: [path.join(here, 'src', 'index.js')],
  outfile: path.join(here, '..', 'src', 'sheafmd', 'page', 'editor.bundle.js'),
  bundle: true,
  format: 'iife',
  target: ['es2020'],
  minify: true,
  legalComments: 'none',
  charset: 'utf8',
  sourcemap: false,
  logLevel: 'warning',
  absWorkingDir: here,
  banner: { js: '/* sheaf block editor: built from editor/ by `npm run build` (ADR 0003). Do not edit. */' },
});
