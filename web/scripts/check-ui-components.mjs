// CI check (never part of the production image): the three-dot row menu (src/RowMenu.tsx) and the first-login tour
// (src/GuidedTour.tsx) must work in a real browser. A page mounts the REAL components (scripts/ui-harness.jsx, bundled with the
// project's own Vite), headless Chrome opens it, the page clicks and presses keys, and every check is read back as JSON.
// Three runs: desktop width, phone width, and a CONTROL run (broken menu, hidden tour targets) in which the same checks must FAIL,
// so a pass means the checks can tell good from bad.
// Usage (from web/):  node scripts/check-ui-components.mjs     (CHROME_BIN overrides "google-chrome")
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const chrome = process.env.CHROME_BIN || 'google-chrome';
console.log('browser:', execFileSync(chrome, ['--version'], { encoding: 'utf8' }).trim());

const out = mkdtempSync(join(tmpdir(), 'ui-check-'));
await build({
  configFile: false,
  logLevel: 'warn',
  plugins: [react()],
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    outDir: out,
    emptyOutDir: true,
    minify: false,
    cssCodeSplit: false,
    lib: { entry: resolve('scripts/ui-harness.jsx'), name: 'NuqatiUiHarness', formats: ['iife'], fileName: () => 'harness.js' },
  },
});
const files = readdirSync(out);
const styles = files.filter((name) => name.endsWith('.css'));
if (!files.includes('harness.js') || !styles.length) throw new Error(`the harness bundle is incomplete: ${files.join(', ')}`);
writeFileSync(join(out, 'index.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
${styles.map((name) => `<link rel="stylesheet" href="${name}">`).join('\n')}
<style>html,body{margin:0;background:#0b1620;color:#eaf4fa;font:14px system-ui,sans-serif}</style></head>
<body><div id="root"></div><pre id="out" hidden></pre><script src="harness.js"></script></body></html>`);

const decodeEntities = (text) => text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&');

function run(label, size, hash = '') {
  const dom = execFileSync(chrome, [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', `--window-size=${size}`,
    '--virtual-time-budget=60000', '--dump-dom', `${pathToFileURL(join(out, 'index.html')).href}${hash}`,
  ], { encoding: 'utf8', timeout: 120000, maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  const found = dom.match(/<pre id="out"[^>]*>([\s\S]*?)<\/pre>/);
  if (!found || !found[1].trim()) {
    console.log(`FAIL [${label}] the page produced no result (it did not run to the end). Page text follows:`);
    console.log(dom.replace(/<script\b[\s\S]*?<\/script>/g, '').replace(/<style\b[\s\S]*?<\/style>/g, '').slice(0, 4000));
    return null;
  }
  return JSON.parse(decodeEntities(found[1]));
}

let failures = 0;
const expect = (label, ok, detail = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` (${detail})` : ''}`);
  if (!ok) failures += 1;
};

for (const [label, size] of [['desktop', '1280,800'], ['phone', '480,800']]) {
  console.log(`\n== ${label} ==`);
  const result = run(label, size);
  if (!result) { failures += 1; continue; }
  console.log(`window ${result.width} x ${result.height}`);
  if (label === 'phone') expect('the window is narrow enough for the phone layout (< 720 px)', result.width < 720, `${result.width} px`);
  else expect('the window is wide enough for the desktop layout (>= 720 px)', result.width >= 720, `${result.width} px`);
  for (const item of result.results) expect(`[${label}] ${item.name}`, item.ok, item.ok ? '' : item.detail);
  expect(`[${label}] at least 40 checks ran`, result.results.length >= 40, `${result.results.length} checks`);
}

console.log('\n== control (broken menu, hidden tour targets: these checks must fail) ==');
const control = run('control', '1280,800', '#control');
if (!control) failures += 1;
else {
  const failed = new Set(control.results.filter((item) => !item.ok).map((item) => item.name));
  for (const name of [
    'menu: it is drawn on top of the page, not inside the clipping table',
    'menu: opening it did not open the row behind it',
    'menu: the first action has the keyboard focus',
    'menu: Esc closes it and gives the focus back to the button',
  ]) expect(`control catches: ${name}`, failed.has(name));
  expect('control catches: a tour spotlight that is missing', [...failed].some((name) => name.includes('the spotlight surrounds its target')));
  expect('control: the checks that do not depend on the broken parts still pass', control.results.some((item) => item.ok));
}

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
