import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createServer } from 'node:http';
const root = dirname(fileURLToPath(import.meta.url));
const local = join(root, 'node_modules/typescript/bin/tsc');
if (existsSync(local)) execFileSync(process.execPath, [local, '-p', join(root, 'tsconfig.json')], { stdio: 'inherit' });
else execFileSync('tsc', ['-p', join(root, 'tsconfig.json')], { stdio: 'inherit', shell: process.platform === 'win32' });
// Deliberately small bundler for these private modules only (no npm runtime).
// Their public declarations have unique names; tsc validates imports before bundling.
const script = ['engine', 'simulator', 'simulator-ui', 'graph', 'storage', 'app'].map(name =>
  readFileSync(join(root, '.build', `${name}.js`), 'utf8')
    .replace(/^import .*? from ['"].*?['"];?\s*$/gm, '')
    .replace(/^export\s+(?=(?:class|function|const|let|var)\b)/gm, '')
    .replace(/^export\s*\{\s*\};?\s*$/gm, '')
).join('\n');
const css = readFileSync(join(root, 'src/style.css'), 'utf8');
const template = readFileSync(join(root, 'index.template.html'), 'utf8');
const html = template.replace('/*__STYLE__*/', () => css).replace('/*__SCRIPT__*/', () => `(()=>{\n'use strict';\n${script}\n})();`);
if (/<script[^>]+src=|<link[^>]+href=["']https?:/i.test(html)) throw new Error('Standalone build must not request external resources.');
mkdirSync(join(root, 'dist'), { recursive: true });
writeFileSync(join(root, 'dist/index.html'), html);
writeFileSync(join(root, 'dist/.nojekyll'), '');
console.log(`Built standalone Kolos: ${Buffer.byteLength(html)} bytes, no external assets.`);
if (process.argv.includes('--serve')) {
  createServer((req, res) => {
    if (req.url !== '/' && req.url !== '/index.html') { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(readFileSync(join(root, 'dist/index.html')));
  }).listen(4173, '127.0.0.1', () => console.log('Kolos: http://127.0.0.1:4173'));
}
