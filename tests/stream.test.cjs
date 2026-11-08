const test=require('node:test'),assert=require('node:assert/strict');
const {PanePackets,PaneFrameStats,PaneDisplayAperture}=require('../handset/web/stream.js');
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

test('display aperture removes only small encoder padding confirmed by native display dimensions',()=>{
  const native={width:1320,height:2868};
  assert.deepEqual(PaneDisplayAperture(1328,2896,native),native);
  assert.deepEqual(PaneDisplayAperture(1320,2868,native),native);
  assert.deepEqual(PaneDisplayAperture(2896,1328,native),{width:2868,height:1320});
  assert.deepEqual(PaneDisplayAperture(2868,1320,native),{width:2868,height:1320});
  assert.deepEqual(PaneDisplayAperture(1328,2896,{width:2868,height:1320}),native);
  // The helper uses metadata, never black/gray pixel detection: valid dark
  // app content remains part of the complete physical display aperture.
  assert.deepEqual(PaneDisplayAperture(1352,2900,native),native);
});

test('missing or invalid native dimensions preserve the complete decoded picture',()=>{
  const full={width:1328,height:2896};
  for(const value of [null,undefined,{},[],false,'1320x2868',
      {width:0,height:2868},{width:1320,height:-1},{width:1320.5,height:2868},
      {width:'1320',height:2868},{width:true,height:2868},
      {width:NaN,height:2868},{width:1320,height:Infinity},{width:20000,height:2868}]){
    assert.deepEqual(PaneDisplayAperture(full.width,full.height,value),full);
  }
});

test('downscaled, oversized-padding and mismatched frames are never guessed or zoomed',()=>{
  const native={width:1320,height:2868};
  for(const [width,height] of [[720,1280],[1312,2868],[1320,2850],[1360,2896],
      [1328,2912],[1920,1080],[2896,1360]]){
    assert.deepEqual(PaneDisplayAperture(width,height,native),{width,height});
  }
});
