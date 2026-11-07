const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync('handset/web/controls.js', 'utf8'), context);
test('control queue preserves order, snapshots payloads, and recovers after failure', async () => {
  const seen = [];
  const queue = context.window.createPaneControlQueue(async (path, data) => {
    await new Promise(resolve => setTimeout(resolve, 5));
    seen.push([path, data.type]);
    if (path === '/fail') throw new Error('offline');
  });
  const payload = {type:'contact'};
  const first = queue('/touch', payload);
  payload.type = 'changed';
  const failure = queue('/fail', {}).catch(() => {});
  const last = queue('/touch', {type:'release'});
  await Promise.all([first, failure, last]);
  assert.deepEqual(seen, [['/touch','contact'], ['/fail',undefined], ['/touch','release']]);
});
test('late responses from previous selections are ignored', () => {
  const generations = context.window.createPaneGeneration();
  const old = generations.next();
  const latest = generations.next();
  assert.equal(generations.current(old), false);
  assert.equal(generations.current(latest), true);
});

test('window movement drops obsolete positions without losing the final position', async () => {
  const seen = [], rendered = []; let release;
  const gate = new Promise(resolve => release = resolve);
  const queue = context.window.createPaneLatestQueue(async p => { seen.push(p.x); if (p.x === 1) await gate; return p; }, p => rendered.push(p.x));
  const first = queue({x:1});
  for (let x = 2; x <= 100; x++) queue({x});
  release(); await first;
  assert.deepEqual(seen,[1,100]); assert.deepEqual(rendered,[100]);
  await queue({x:101}); assert.deepEqual(rendered,[100,101]);
});
test('geometry queue recovers from native errors', async () => {
  let fail = true;
  const queue = context.window.createPaneLatestQueue(async () => { if (fail) throw new Error('native failure'); });
  await assert.rejects(queue({x:1})); fail = false; await queue({x:2});
});
