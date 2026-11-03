const test = require('node:test');
const assert = require('node:assert/strict');
const Reader = require('../handset/web/packets.js');
function packet(data) {
  const result = new Uint8Array(data.length + 4);
  new DataView(result.buffer).setUint32(0, data.length);
  result.set(data, 4);
  return result;
}
test('every split point preserves packet boundaries and payload', () => {
  const bytes = packet(new Uint8Array([0,1,2,3,4]));
  for (let split = 0; split <= bytes.length; split++) {
    const reader = new Reader(), seen = [];
    reader.push(bytes.subarray(0, split), p => seen.push([...p]));
    reader.push(bytes.subarray(split), p => seen.push([...p]));
    reader.finish();
    assert.deepEqual(seen, [[0,1,2,3,4]]);
  }
});
test('fragmented 4 MiB frame uses linear copying and reuses storage', () => {
  const bytes = packet(new Uint8Array(4 * 1024 * 1024).fill(7));
  const reader = new Reader();
  let count = 0;
  for (let i = 0; i < bytes.length; i += 4096)
    reader.push(bytes.subarray(i, i + 4096), p => { count++; assert.equal(p.length, bytes.length-4); assert.equal(p.at(-1), 7); });
  reader.finish();
  assert.equal(count, 1);
  assert.ok(reader.copiedBytes < bytes.length * 3);
  const storage = reader.buffer;
  reader.push(packet(new Uint8Array([1])), () => {});
  assert.equal(reader.buffer, storage);
});
test('coalesced packets and invalid lengths are handled without unbounded allocation', () => {
  const one = packet(new Uint8Array([2,3]));
  const bytes = new Uint8Array(one.length * 40000);
  for (let i = 0; i < bytes.length; i += one.length) bytes.set(one, i);
  const reader = new Reader(); let count = 0;
  reader.push(bytes, p => { assert.deepEqual([...p], [2,3]); count++; });
  reader.finish();
  assert.equal(count,40000);
  assert.ok(reader.buffer.length <= 131072);
  for (const length of [0, 0xffffffff]) {
    const bad = new Uint8Array(4); new DataView(bad.buffer).setUint32(0,length);
    assert.throws(() => new Reader().push(bad, () => {}), /Invalid/);
  }
  const partial = new Reader();
  partial.push(one.subarray(0,5), () => {});
  assert.throws(() => partial.finish(), /Truncated/);
});
