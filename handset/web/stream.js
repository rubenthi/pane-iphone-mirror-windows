// Incremental framing: allocate once per access unit, not on every network read.
(function(root){
  class PanePackets {
    constructor(){this.header=new Uint8Array(4);this.headerUsed=0;this.body=null;this.used=0;}
    *push(bytes){
      let offset=0;
      while(offset<bytes.length){
        if(!this.body){
          const count=Math.min(4-this.headerUsed,bytes.length-offset);
          this.header.set(bytes.subarray(offset,offset+count),this.headerUsed);this.headerUsed+=count;offset+=count;
          if(this.headerUsed<4)break;
          const length=new DataView(this.header.buffer).getUint32(0);
          this.headerUsed=0;
          if(length<1||length>32*1024*1024)throw new Error('Invalid video packet size');
          if (bytes.length-offset >= length) {
            const end=offset+length;
            const packet={type:bytes[offset], data:bytes.subarray(offset+1,end)};
            offset=end;
            yield packet;
            continue;
          }
          this.body=new Uint8Array(length);this.used=0;
        }
        const count=Math.min(this.body.length-this.used,bytes.length-offset);
        this.body.set(bytes.subarray(offset,offset+count),this.used);this.used+=count;offset+=count;
        if(this.used===this.body.length){const packet=this.body;this.body=null;yield {type:packet[0],data:packet.subarray(1)};}
      }
    }
  }
  class PaneFrameStats {
    constructor(now=performance.now()){this.started=now;this.received=0;this.presented=0;this.skipped=0;}
    sample(width,height,queue,now=performance.now()){
      const seconds=(now-this.started)/1000;if(seconds<1)return null;
      const result={source:'pane-video-stats',width,height,received:this.received/seconds,presented:this.presented/seconds,skipped:this.skipped,queue};
      this.started=now;this.received=0;this.presented=0;this.skipped=0;return result;
    }
  }
  function PaneDisplayAperture(frameW,frameH,displaySize){
    const full={width:frameW,height:frameH};
    if(!displaySize)return full;
    let {width,height}=displaySize;
    if(![frameW,frameH,width,height].every(v=>Number.isInteger(v)&&v>0&&v<=16384))return full;
    // DeviceInfo reports the physical display, while the encoder can rotate
    // and align its capture buffer. Trim only a small, known padding margin;
    // downscaled frames and unknown geometry retain their entire picture.
    if((frameW>frameH)!==(width>height))[width,height]=[height,width];
    const padW=frameW-width,padH=frameH-height;
    return padW>=0&&padH>=0&&padW<=32&&padH<=32?{width,height}:full;
  }
  root.PanePackets=PanePackets;root.PaneFrameStats=PaneFrameStats;root.PaneDisplayAperture=PaneDisplayAperture;
  if(typeof module!=='undefined')module.exports={PanePackets,PaneFrameStats,PaneDisplayAperture};
})(typeof window!=='undefined'?window:globalThis);
