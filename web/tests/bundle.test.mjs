import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Script} from 'node:vm';
import {stripModuleSyntax} from '../bundle-source.mjs';

for (const ending of ['\n', '\r\n']) {
  test(`private module bundling handles ${JSON.stringify(ending)} without leaking imports`, () => {
    const input = ["import {x} from './other.mjs';", 'export function answer(){return 42;}',
      'const text = "import is ordinary text here";'].join(ending);
    const source = stripModuleSyntax(input);
    assert.doesNotThrow(() => new Script(source));
    assert.ok(source.includes('function answer(){return 42;}'));
    assert.ok(source.includes('import is ordinary text here'));
    assert.equal(stripModuleSyntax("import {x} from './other.mjs';"), '');
  });
}
for (const name of ['index', 'neurons', 'shared']) {
  test(`offline ${name} bundle contains only executable standalone scripts`, () => {
    const html = readFileSync(new URL(`../dist/${name}.html`, import.meta.url), 'utf8');
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
    assert.ok(scripts.length > 0);
    for (const [, source] of scripts) assert.doesNotThrow(() => new Script(source));
  });
}
