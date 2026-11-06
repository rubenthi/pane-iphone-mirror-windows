const test=require('node:test'),assert=require('node:assert/strict');
const {PanePackets,PaneFrameStats}=require('../handset/web/stream.js');
test('incremental packets preserve split headers, bodies and multiple frames',()=>{
  const bytes=Uint8Array.from([0,0,0,4,0,11,12,13,0,0,0,3,1,21,22]);
  for(let stride=1;stride<=bytes.length;stride++){
    const parser=new PanePackets(),out=[];
    for(let i=0;i<bytes.length;i+=stride)out.push(...parser.push(bytes.subarray(i,i+stride)));
    assert.deepEqual(out.map(p=>[p.type,...p.data]),[[0,11,12,13],[1,21,22]]);
  }
});
test('malformed lengths cannot accumulate unbounded video data',()=>{
  for(const value of [0,0xffffffff,33554433]){const b=new Uint8Array(4);new DataView(b.buffer).setUint32(0,value);assert.throws(()=>[...new PanePackets().push(b)]);}
});
test('video telemetry reports measured decode and presentation rates, not target FPS',()=>{
  const stats=new PaneFrameStats(0);stats.received=54;stats.presented=49;stats.skipped=5;
  assert.equal(stats.sample(1170,2532,2,999),null);
  assert.deepEqual(stats.sample(1170,2532,2,1000),{source:'pane-video-stats',width:1170,height:2532,received:54,presented:49,skipped:5,queue:2});
  assert.equal(stats.sample(1170,2532,0,2000).received,0);
});
