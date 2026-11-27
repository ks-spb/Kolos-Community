import test from 'node:test';
import assert from 'node:assert/strict';
import {runCase} from '../states/core.mjs';

const assertDecayEngine = e => {
  assert.ok(e.model.config.decay > 0 && e.model.config.decay < 1,
    'acceptance scenarios must run with non-zero leak/decay');
};

test('ACCEPTANCE-1: desktop command reaches window through learned A -> Enter sequence', () => {
  const r = runCase(1), e = r.engine;
  assertDecayEngine(e);
  assert.equal(r.pass, true);
  assert.equal(e.model.world.surface, 'window');
  const actions = e.model.world.effects.filter(x => x.ok).map(x => x.action);
  assert.ok(actions.some(a => a.kind === 'click' && a.object === 'A'));
  assert.ok(actions.some(a => a.kind === 'enter' && a.object === 'A'));
  assert.equal(e.model.heldGoal, false);
});

test('ACCEPTANCE-2: window command returns to desktop through learned close icon', () => {
  const r = runCase(2), e = r.engine;
  assertDecayEngine(e);
  assert.equal(r.pass, true);
  assert.equal(e.model.world.surface, 'desk');
  const clicks = e.model.world.effects.filter(x => x.ok && x.action.kind === 'click').map(x => x.action.object);
  assert.deepEqual(clicks, ['X']);
  assert.equal(e.model.heldGoal, false);
});

test('ACCEPTANCE-3: hidden target composes learned state transition; no X -> A -> Enter lesson exists', () => {
  const r = runCase(3), e = r.engine;
  assertDecayEngine(e);
  assert.equal(r.pass, true);
  assert.equal(e.model.lessons.length, 2);
  assert.deepEqual(
    e.model.lessons.map(l => l.receipts.filter(x => x.action.kind === 'click').map(x => x.action.object)),
    [['A'], ['X']]
  );
  assert.ok(e.events.some(ev => ev.kind === 'spread' && ev.flows?.length),
    'goal activation must actually spread through weighted state-transition edges');
  assert.ok(e.events.some(ev => ev.kind === 'route'),
    'a learned transition must win by activation');
  const clicks = e.model.world.effects.filter(x => x.ok && x.action.kind === 'click').map(x => x.action.object);
  assert.deepEqual(clicks, ['X', 'A']);
  assert.equal(e.model.world.surface, 'window');
  assert.equal(e.model.heldGoal, false);
});

test('ACCEPTANCE-4: one expense lesson 1700 + prior key exposure executes unseen 2345 without learning it', () => {
  const r = runCase(4), e = r.engine;
  assertDecayEngine(e);
  assert.equal(r.pass, true);
  assert.equal(e.model.lessons.length, 1);
  assert.equal(e.model.lessons[0].query, 'добавь траты 1700');
  assert.equal(e.model.exposures.length, 1);
  assert.equal(e.model.exposures[0].receipts.map(x => x.action.value).join(''), '5432');
  assert.ok(!e.model.lessons.some(l => l.query.includes('2345')),
    'the control request must never be present in training lessons');
  const keys = e.model.world.effects.filter(x => x.ok && x.action.kind === 'key').map(x => x.action.value).join('');
  assert.equal(keys, '2345');
  assert.equal(e.model.world.output, '2345');
  assert.equal(e.model.heldGoal, false);
});
