// HEVC SPS dimensions are required by Windows' decoder; its unspecified default is 1280x720.
(function(root){
  function dimensions(description){
    const d=new Uint8Array(description);if(d.length<23)throw Error('Truncated HEVC configuration');
    let p=23,sps;
    const u16=()=>{if(p+2>d.length)throw Error('Truncated HEVC array');const v=d[p]*256+d[p+1];p+=2;return v;};
    for(let a=0;a<d[22];a++){if(p>=d.length)throw Error('Truncated HEVC array');const type=d[p++]&63;const count=u16();for(let n=0;n<count;n++){const length=u16();if(p+length>d.length)throw Error('Truncated HEVC NAL');if(type===33)sps=d.slice(p,p+length);p+=length;}}
    if(!sps)throw Error('HEVC configuration has no SPS');
    const rb=[];for(let i=2;i<sps.length;i++){if(i>=4&&sps[i]===3&&sps[i-1]===0&&sps[i-2]===0)continue;rb.push(sps[i]);}
    let bit=0;const read=n=>{let v=0;for(let i=0;i<n;i++){if(bit>=rb.length*8)throw Error('Truncated HEVC SPS');v=v*2+((rb[bit>>3]>>(7-(bit&7)))&1);bit++;}return v;};
    const ue=()=>{let z=0;while(read(1)===0){if(++z>24)throw Error('Invalid HEVC integer');}return 2**z-1+read(z);};
    read(4);const layers=read(3);read(1);read(96);
    const flags=[];for(let i=0;i<layers;i++)flags.push([read(1),read(1)]);
    if(layers)read((8-layers)*2);
    for(const [profile,level] of flags){if(profile)read(88);if(level)read(8);}
    ue();const chroma=ue();let separate=0;if(chroma===3)separate=read(1);
    const codedWidth=ue(),codedHeight=ue();let left=0,right=0,top=0,bottom=0;
    if(read(1)){left=ue();right=ue();top=ue();bottom=ue();}
    const format=separate?0:chroma,subW=format===1||format===2?2:1,subH=format===1?2:1;
    const width=codedWidth-subW*(left+right),height=codedHeight-subH*(top+bottom);
    if(width<=0||height<=0||codedWidth>16384||codedHeight>16384)throw Error('Invalid HEVC dimensions');
    return {codedWidth,codedHeight,width,height,x:left*subW,y:top*subH};
  }
  function update(description, chunk){
    const sets=new Map();let p=0;
    while(p+4<=chunk.length){
      const n=new DataView(chunk.buffer,chunk.byteOffset+p,4).getUint32(0);p+=4;
      if(n<2||p+n>chunk.length)throw Error('Invalid HEVC access unit');
      const type=(chunk[p]>>1)&63;if(type>=32&&type<=34)sets.set(type,chunk.slice(p,p+n));p+=n;
    }
    if(!sets.size)return null;
    const d=new Uint8Array(description),out=Array.from(d.slice(0,23));p=23;
    for(let a=0;a<d[22];a++){
      const kind=d[p++],count=d[p]*256+d[p+1];p+=2;const nals=[];
      for(let n=0;n<count;n++){const length=d[p]*256+d[p+1];p+=2;nals.push(d.slice(p,p+length));p+=length;}
      const replacements=sets.has(kind&63)?[sets.get(kind&63)]:nals;
      out.push(kind,replacements.length>>8,replacements.length&255);
      for(const nal of replacements)out.push(nal.length>>8,nal.length&255,...nal);
    }
    const result=new Uint8Array(out);
    return result.length===d.length&&result.every((v,i)=>v===d[i])?null:result;
  }
  root.PaneHEVC={dimensions,update};if(typeof module!=='undefined')module.exports=root.PaneHEVC;
})(typeof window==='undefined'?globalThis:window);
