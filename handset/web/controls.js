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
