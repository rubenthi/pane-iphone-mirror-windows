const test=require('node:test');const assert=require('node:assert/strict');const hevc=require('../handset/web/hevc.js');
function fixture(width,height,crop=[0,0,0,0]){
 const bits=[];const bit=(v,n)=>{for(let i=n-1;i>=0;i--)bits.push((v>>i)&1)};const ue=v=>{const b=(v+1).toString(2);bits.push(...Array(b.length-1).fill(0),...b.split('').map(Number))};
 bit(0,4);bit(0,3);bit(1,1);for(let i=0;i<96;i++)bits.push(0);ue(0);ue(1);ue(width);ue(height);bit(1,1);crop.forEach(ue);while(bits.length%8)bits.push(0);
 const nal=[66,1];for(let i=0;i<bits.length;i+=8){const v=parseInt(bits.slice(i,i+8).join(''),2);if(nal.length>=4&&nal.at(-1)===0&&nal.at(-2)===0&&v<=3)nal.push(3);nal.push(v);}
 const hvcc=Array(23).fill(0);hvcc[0]=1;hvcc[22]=1;hvcc.push(33,0,1,nal.length>>8,nal.length&255,...nal);return {description:Uint8Array.from(hvcc),nal};
}
test('HEVC portrait dimensions replace Windows 1280x720 fallback',()=>{const d=hevc.dimensions(fixture(1328,2896).description);assert.equal(d.width,1328);assert.equal(d.height,2896)});
test('HEVC conformance crop uses chroma subsampling',()=>{const d=hevc.dimensions(fixture(1920,1088,[0,0,0,4]).description);assert.equal(d.height,1080)});
test('in-band rotation SPS updates decoder dimensions',()=>{const portrait=fixture(1328,2896),landscape=fixture(2896,1328);const n=landscape.nal.length;const chunk=Uint8Array.from([0,0,n>>8,n&255,...landscape.nal]);const updated=hevc.update(portrait.description,chunk);assert.equal(hevc.dimensions(updated).width,2896);assert.equal(hevc.update(updated,chunk),null)});
test('truncated HEVC metadata is rejected',()=>{for(const description of [new Uint8Array(),fixture(1328,2896).description.slice(0,-2)])assert.throws(()=>hevc.dimensions(description));});
