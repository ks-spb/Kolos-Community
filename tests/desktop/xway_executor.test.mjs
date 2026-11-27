import test from 'node:test';
import assert from 'node:assert/strict';
import { validateMotor } from './xway_executor.mjs';

const task = { sku: 'new-sku', shop_id: '412' };
const request = (kind, name, scope, motor, value) => ({ origin: 'learned-graph', motor,
  action: { kind, descriptor: { name, scope }, value } });

test('browser motor rejects every advertisement-setting write', () => {
  for (const name of ['Daily budget', 'CPM', 'AI enabled', 'Apply settings', 'Save']) {
    for (const kind of ['write', 'activate']) {
      assert.throws(() => validateMotor(request(kind, name,
        'XWAY shop 412 selected product', kind === 'write' ? 'search-fill' : 'search-apply', '999'), task));
    }
  }
});
test('only current SKU can be entered into the seller filter', () => {
  const valid = request('write', 'Product search', 'XWAY shop 412 search', 'search-fill', task.sku);
  assert.doesNotThrow(() => validateMotor(valid, task));
  assert.throws(() => validateMotor(valid, { ...task, shop_id: '413' }));
  assert.throws(() => validateMotor({ ...valid, action: { ...valid.action, value: 'old-sku' } }, task));
  assert.throws(() => validateMotor({ ...valid, origin: 'manual' }, task));
});
test('a local report permission cannot be used to mutate an XWAY field', () => {
  assert.doesNotThrow(() => validateMotor(request('write', 'Report budget', 'Local XWAY report', 'local-report', '30 ₽'), task));
  assert.throws(() => validateMotor(request('write', 'Report budget', 'XWAY shop 412 search', 'local-report', '30 ₽'), task));
  assert.throws(() => validateMotor(request('write', 'unrelated', 'Local XWAY report', 'local-report', '30 ₽'), task));
});
