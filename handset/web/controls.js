// One queue shared by the main window and its iframe preserves input order.
window.createPaneControlQueue = function (send) {
  let chain = Promise.resolve();
  const transaction = operation => {
    const result = chain.then(() => operation(send));
    chain = result.catch(() => {});
    return result;
  };
  const queue = (path, payload) => {
    const snapshot = JSON.stringify(payload);
    return transaction(send => send(path, JSON.parse(snapshot)));
  };
  queue.transaction = transaction;
  return queue;
};
window.createPaneGeneration = function () {
  let generation = 0;
  return { next: () => ++generation, current: (value) => value === generation };
};
