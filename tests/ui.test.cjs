const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync('handset/web/controls.js', 'utf8'), context);
vm.runInNewContext(fs.readFileSync('handset/web/ux.js', 'utf8'), context);

test('rejected Wi-Fi pairing asks for USB repair rather than another unlock', () => {
  assert.equal(context.window.paneNotice('Wi-Fi pairing rejected. Reconnect USB once to repair Wi-Fi.'),'Reconnect USB to restore Wi-Fi.');
  assert.equal(context.window.paneNotice('Wi-Fi connection timed out. Retry.'),'Wi-Fi timed out. Try again.');
});
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

test('diagonal corner resizing is continuous across opposing axis deltas', () => {
  for(const corner of ['nw','ne','sw','se']){
    const origin={x:100,y:100,height:760,corner};
    const sx=corner.includes('w')?-1:1,sy=corner.includes('n')?-1:1;
    const sizes=[];
    for(let dy=38;dy<=48;dy++)sizes.push(context.window.paneResizeHeight(origin,100-20*sx,100+dy*sy,390/844));
    for(let i=1;i<sizes.length;i++)assert.ok(sizes[i]>sizes[i-1]&&sizes[i]-sizes[i-1]<1);
    const grow=context.window.paneResizeHeight(origin,100+39*sx,100+84.4*sy,390/844);
    assert.ok(Math.abs(grow-844.4)<.001);
  }
});

test('volume wheel accumulates trackpad movement and preserves direction', async () => {
  const sent=[];
  const wheel=context.window.createPaneVolumeWheel(async name=>sent.push(name));
  await wheel(-20);await wheel(-20);await wheel(-20);assert.equal(sent.length,0);
  await wheel(-20);await wheel(80);await wheel(-2,1);
  assert.deepEqual(sent,['volume-up','volume-down','volume-up']);
});
test('volume wheel bounds a burst and recovers after a failed control', async () => {
  let release,fail=true;const sent=[];
  const wheel=context.window.createPaneVolumeWheel(async name=>{sent.push(name);if(sent.length===1)await new Promise(r=>release=r);if(fail)throw new Error('offline');});
  const first=wheel(80);
  wheel(80000);release();await assert.rejects(first);
  assert.equal(sent.length,1);
  fail=false;await wheel(-80);assert.equal(sent.at(-1),'volume-up');
});
