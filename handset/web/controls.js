// One queue shared by the main window and its iframe preserves input order.
window.createPaneControlQueue = function (send) {
  let chain = Promise.resolve();
  return (path, payload) => {
    const snapshot = JSON.stringify(payload);
    const result = chain.then(() => send(path, JSON.parse(snapshot)));
    chain = result.catch(() => {});
    return result;
  };
};
window.createPaneGeneration = function () {
  let generation = 0;
  return { next: () => ++generation, current: (value) => value === generation };
};

// Accumulate small trackpad deltas and bound pending volume changes.
window.createPaneVolumeWheel = function(send) {
  let remainder=0, pending=0, running=null, last=0;
  async function drain() {
    try {
      while(pending) {
        const direction=Math.sign(pending); pending-=direction;
        await send(direction<0?'volume-up':'volume-down');
      }
    } catch(error) { pending=remainder=0;throw error; }
  }
  return (delta, mode=0) => {
    const now=Date.now(); if(now-last>200)remainder=0;last=now;
    remainder+=delta*(mode===1?40:mode===2?80:1);
    const steps=Math.trunc(remainder/80); remainder-=steps*80;
    pending=Math.max(-8,Math.min(8,pending+steps));
    if(!running && pending)running=drain().finally(()=>{running=null;});
    return running || Promise.resolve();
  };
};

// Geometry is state, unlike ordered HID input. Keep only the newest pending
// position while a native call is in flight; never replay a long drag backlog.
window.createPaneLatestQueue = function (send, apply = () => {}, intermediate = false) {
  let pending = null, running = null;
  async function drain() {
    while (pending) {
      const value = pending; pending = null;
      const result = await send(value);
      if (intermediate || !pending) apply(result);
    }
  }
  return value => {
    pending = {...value};
    if (!running) running = drain().finally(() => { running = null; });
    return running;
  };
};
