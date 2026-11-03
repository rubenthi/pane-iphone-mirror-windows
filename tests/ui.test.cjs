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
