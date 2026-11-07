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
