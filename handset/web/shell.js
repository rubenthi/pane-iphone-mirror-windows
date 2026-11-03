(() => {
  const arrow = document.querySelector('#drawer-toggle');
  const drawer = document.querySelector('#connection-drawer');
  let expanded = false;
  let aspect = 390 / 844;
  let native = false;
  let chain = Promise.resolve();
  function render(state) {
    native = state.native;
    expanded = state.expanded;
    document.documentElement.style.setProperty('--phone-width', `${state.phone_width}px`);
    document.documentElement.style.setProperty('--phone-height', `${state.height}px`);
    document.body.classList.toggle('drawer-open', expanded);
    document.body.classList.toggle('browser-mode', !native);
    for (const id of ['pin-window','minimize-window','close-window']) document.querySelector('#'+id).hidden = !native;
    drawer.hidden = !expanded;
    arrow.setAttribute('aria-expanded', String(expanded));
    arrow.setAttribute('aria-label', expanded ? 'Close connection sidebar' : 'Open connection sidebar');
    document.querySelector('#pin-window').setAttribute('aria-pressed', String(state.pinned));
  }
  function command(action, extra = {}) {
    const result = chain.then(() => postJson('/api/window', { action, ...extra }));
    chain = result.catch(error => { document.querySelector('#screen-note').textContent = error.message; });
    return result;
  }
  async function layout(open = expanded) {
    render(await command('layout', { expanded: open, aspect }));
  }
  arrow.addEventListener('click', () => layout(!expanded).catch(() => {}));
  document.querySelector('#welcome-setup').addEventListener('click', async () => {
    await layout(true);
    if (document.querySelector('#run-guide').hidden) document.querySelector('#toggle-guide').click();
  });
  document.querySelector('#drag-handle').addEventListener('pointerdown', event => {
    if (event.button === 0 && native) { event.preventDefault(); command('drag').catch(() => {}); }
  });
  for (const action of ['close', 'minimize', 'pin']) {
    document.querySelector(`#${action}-window`).addEventListener('click', () => command(action).then(render).catch(() => {}));
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== document.querySelector('#screen-view').contentWindow || event.data?.source !== 'pane-display') return;
    const { width, height } = event.data;
    const next = width / height;
    if (!Number.isFinite(next) || next < .35 || next > 2.5 || Math.abs(next - aspect) < .005) return;
    aspect = next;
    layout().catch(() => {});
  });
  async function initialize() {
    // The browser can load before the launcher has attached the native shell.
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        const state = await getJson('/api/window');
        if (state.native || attempt === 39) { render(state); return; }
      } catch (_) {}
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
  initialize();
})();
