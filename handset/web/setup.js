(() => {
  const $ = selector => document.querySelector(selector);
  let setupState = {}, transferState = {}, staging = false, setupBusy = false;
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function selectTab(tab) {
    for (const item of tabs) {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !active;
    }
  }
  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + 1) % tabs.length];
      selectTab(next); next.focus();
    });
  }
  $('#welcome-setup').addEventListener('click', () => selectTab(tabs[0]));
  const bytes = size => size < 1024 ? `${size} B` : size < 1024 ** 2 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 ** 2).toFixed(1)} MB`;
  async function action(button, path, payload = {}) {
    button.disabled = true;
    try { return await postJson(path, payload); }
    catch (error) { throw error; }
    finally { button.disabled = false; }
  }
  function renderSetup(state) {
    setupState = state;
    $('#setup-progress').textContent = state.error || (transferState.bluetooth?.phase === 'connected'
      ? 'Connected. Use Uploads for files, or Start mirroring for the screen.' : state.note);
    $('#setup-progress').dataset.tone = state.phase === 'error' ? 'error' : state.phase;
    const done = {connect: state.usbReady, install: state.installed, developer: state.developerEnabled,
      bind: state.wifiBound, bluetooth: transferState.bluetooth?.phase === 'connected'};
    for (const step of document.querySelectorAll('[data-step]')) {
      step.dataset.done = String(!!done[step.dataset.step]);
      if (step.dataset.step === state.step) step.setAttribute('aria-current', 'step');
      else step.removeAttribute('aria-current');
    }
    for (const button of document.querySelectorAll('[data-setup]')) {
      button.disabled = setupBusy || staging || state.phase === 'working' || !usbConnected || !selectedUdid;
    }
    $('#install-companion').disabled = setupBusy || staging || state.phase === 'working' || !usbConnected || !selectedUdid;
    for (const button of document.querySelectorAll('[data-bluetooth="connect"]')) {
      button.disabled = !state.boundUdid || ['connected', 'connecting'].includes(transferState.bluetooth?.phase);
    }
  }
  for (const button of document.querySelectorAll('[data-setup]')) {
    button.addEventListener('click', async () => {
      setupBusy = true;
      renderSetup({...setupState, note: 'Working with your iPhone…', error: null});
      try { renderSetup(await action(button, `/api/setup/${button.dataset.setup}`, {udid: selectedUdid})); }
      catch (error) { $('#setup-progress').textContent = error.message; }
      finally { setupBusy = false; }
    });
  }
  for (const button of document.querySelectorAll('[data-bluetooth]')) {
    button.addEventListener('click', async () => {
      try {
        const state = await action(button, `/api/bluetooth/${button.dataset.bluetooth}`);
        $('#bluetooth-status').textContent = state.note;
        $('#setup-progress').textContent = state.note;
      } catch (error) {
        $('#bluetooth-status').textContent = error.message;
        $('#setup-progress').textContent = error.message;
      }
    });
  }
  async function stage(file, kind, progress) {
    const {id} = await postJson('/api/uploads/start', {name: file.name, size: file.size, kind});
    try {
      for (let offset = 0; offset < file.size; offset += 256 * 1024) {
        const data = new Uint8Array(await file.slice(offset, offset + 256 * 1024).arrayBuffer());
        let binary = '';
        for (let pos = 0; pos < data.length; pos += 8192) binary += String.fromCharCode(...data.subarray(pos, pos + 8192));
        await postJson('/api/uploads/chunk', {id, offset, data: btoa(binary)});
        progress.textContent = `Preparing ${file.name}: ${Math.round((offset + data.length) / file.size * 100)}%`;
      }
      return id;
    } catch (error) {
      await postJson('/api/uploads/cancel', {id}).catch(() => {});
      throw error;
    }
  }
  $('#install-companion').addEventListener('click', () => $('#companion-ipa').click());
  $('#companion-ipa').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    staging = true;
    renderSetup(setupState);
    let id;
    try {
      id = await stage(file, 'ipa', $('#install-progress'));
      renderSetup(await postJson('/api/setup/install', {id, udid: selectedUdid}));
      $('#install-progress').textContent = 'IPA uploaded. Installation progress appears above.';
    } catch (error) {
      $('#install-progress').textContent = error.message;
      if (id) await postJson('/api/uploads/cancel', {id}).catch(() => {});
    } finally { staging = false; event.target.value = ''; renderSetup(setupState); }
  });
  $('#send-files').addEventListener('click', () => $('#outgoing-files').click());
  $('#outgoing-files').addEventListener('change', async event => {
    const files = [...event.target.files];
    $('#send-files').disabled = true;
    try {
      for (const file of files) {
        const id = await stage(file, 'file', $('#upload-progress'));
        try { await postJson('/api/uploads/finish', {id}); }
        catch (error) { await postJson('/api/uploads/cancel', {id}).catch(() => {}); throw error; }
      }
      $('#upload-progress').textContent = `${files.length} file(s) queued. Keep Pane open and Bluetooth connected.`;
    } catch (error) { $('#upload-progress').textContent = error.message; }
    finally { $('#send-files').disabled = false; event.target.value = ''; }
  });
  function renderTransfers(state) {
    transferState = state;
    $('#bluetooth-status').textContent = state.bluetooth.note;
    const phase = state.bluetooth.phase;
    const badge = $('#bluetooth-badge');
    badge.textContent = {connected: 'Connected', connecting: 'Connecting', error: 'Needs attention'}[phase] || 'Not connected';
    badge.dataset.state = phase;
    for (const button of document.querySelectorAll('[data-bluetooth="disconnect"]')) button.hidden = !['connecting', 'connected'].includes(phase);
    $('#downloads-location').textContent = 'Downloads';
    $('#downloads-location').title = state.destination;
    const active = state.transfers.filter(t => ['queued', 'sending', 'receiving'].includes(t.state)).length;
    $('#transfer-count').hidden = active === 0; $('#transfer-count').textContent = active;
    $('#transfer-count').setAttribute('aria-label', `${active} pending transfers`);
    $('#transfer-summary').textContent = active ? `${active} pending` : 'No active transfers';
    $('#history-count').textContent = state.transfers.length ? String(state.transfers.length) : '';
    const list = $('#transfer-list');
    // Polling must not rebuild an unchanged list and steal focus or selection.
    const serialized = JSON.stringify(state.transfers);
    if (list.dataset.snapshot === serialized) return;
    list.dataset.snapshot = serialized;
    const focused = document.activeElement?.dataset.cancel;
    list.replaceChildren();
    if (!state.transfers.length) {
      const empty = document.createElement('li'); empty.className = 'transfer-empty';
      const title = document.createElement('strong'); title.textContent = 'Nothing here yet';
      const detail = document.createElement('p'); detail.textContent = 'Send a file from either device. Its progress and status will appear here.';
      empty.append(window.paneIcon('folder'), title, detail); list.append(empty);
    }
    for (const transfer of state.transfers) {
      const item = document.createElement('li'); item.className = 'transfer'; item.dataset.state = transfer.state;
      const top = document.createElement('div'); top.className = 'transfer-top';
      const kind = /\.(jpg|jpeg|png|heic|gif|webp)$/i.test(transfer.name) ? 'image' : 'file';
      const icon = window.paneIcon(kind); icon.classList.add('file-icon');
      const content = document.createElement('div'); content.className = 'transfer-content';
      const title = document.createElement('strong'); title.textContent = transfer.savedAs || transfer.name; title.title = title.textContent;
      const detail = document.createElement('p'); detail.className = 'transfer-meta';
      detail.textContent = `${transfer.direction === 'to-phone' ? 'To iPhone' : 'To Downloads'} · ${bytes(transfer.size)}`;
      content.append(title, detail); top.append(icon, content);
      const status = document.createElement('span'); status.className = 'transfer-state';
      status.textContent = {complete:'Done', failed:'Failed', cancelled:'Cancelled', queued:'Queued', sending:'Sending', receiving:'Receiving'}[transfer.state] || transfer.state;
      top.append(status); item.append(top);
      if (['sending', 'receiving'].includes(transfer.state)) {
        const progress = document.createElement('progress'); progress.max = transfer.size || 1; progress.value = transfer.done; progress.setAttribute('aria-label', `${transfer.name} progress`);
        const counts = document.createElement('p'); counts.className = 'transfer-numbers';
        counts.textContent = `${bytes(transfer.done)} of ${bytes(transfer.size)} · ${transfer.size ? Math.floor(transfer.done / transfer.size * 100) : 0}%`;
        item.append(progress, counts);
      }
      if (transfer.error) { const error = document.createElement('p'); error.className = 'warn'; error.textContent = transfer.error; item.append(error); }
      if (transfer.state === 'queued') {
        const cancel = document.createElement('button'); cancel.className = 'transfer-cancel'; cancel.textContent = 'Cancel'; cancel.dataset.cancel = transfer.id;
        cancel.title = `Cancel ${transfer.name}`;
        cancel.addEventListener('click', () => postJson('/api/uploads/cancel', {id: transfer.id}).catch(error => {$('#upload-progress').textContent = error.message;}));
        item.append(cancel);
      }
      list.append(item);
    }
    if (focused) list.querySelector(`[data-cancel="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
  }
  async function poll() {
    try {
      const [setup, transfers] = await Promise.all([getJson('/api/setup'), getJson('/api/uploads')]);
      renderTransfers(transfers); renderSetup(setup);
    } catch (error) { $('#bluetooth-status').textContent = error.message; }
    setTimeout(poll, 1500);
  }
  poll();
})();
