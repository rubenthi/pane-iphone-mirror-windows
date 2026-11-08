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
      const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowLeft' ? tabs.length - 1 : 1)) % tabs.length];
      selectTab(next); next.focus();
    });
  }
  const bytes = size => size < 1024 ? `${size} B` : size < 1024 ** 2 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 ** 2).toFixed(1)} MB`;
  async function action(button, path, payload = {}) {
    button.disabled = true;
    try { return await postJson(path, payload); }
    catch (error) { throw error; }
    finally { button.disabled = false; }
  }
  function renderSetup(state) {
    setupState = state;
    $('#setup-progress').textContent = (state.error || state.phase === 'error' ? window.paneNotice(state.error || state.note) : '') || (transferState.bluetooth?.phase === 'connected'
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
      catch (error) { $('#setup-progress').textContent = window.paneNotice(error.message); }
      finally { setupBusy = false; }
    });
  }
  for (const button of document.querySelectorAll('[data-bluetooth]')) {
    button.addEventListener('click', async () => {
      try {
        const state = await action(button, `/api/bluetooth/${button.dataset.bluetooth}`);
        $('#bluetooth-status').textContent = state.phase==='connected'?'Ready for files.':'Open Pane on your iPhone.';
        $('#setup-progress').textContent = state.phase==='connected'?'Connected.':'Open Pane on your iPhone.';
      } catch (error) {
        $('#bluetooth-status').textContent = window.paneNotice(error.message);
        $('#setup-progress').textContent = window.paneNotice(error.message);
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
      $('#install-progress').textContent = window.paneNotice(error.message);
      if (id) await postJson('/api/uploads/cancel', {id}).catch(() => {});
    } finally { staging = false; event.target.value = ''; renderSetup(setupState); }
  });
  let signingState = {}, signingStaging = false;
  function renderSigning(state) {
    signingState = state;
    const busy = ['working', 'prompt'].includes(state.phase);
    $('#signing-start').disabled = signingStaging || busy || !state.available || !usbConnected || !selectedUdid;
    $('#signing-note').textContent = !state.available ? 'Installer missing. Reinstall Pane on this PC.'
      : !busy && !signingStaging && (!usbConnected || !selectedUdid) ? 'iPhone disconnected. Reconnect the cable.'
      : window.paneSigningNote(state);
    $('#signing-cancel').hidden = !busy;
    $('#signing-prompt').hidden = state.phase !== 'prompt';
    if (state.prompt && $('#signing-prompt').dataset.id !== state.prompt.id) {
      $('#signing-prompt').dataset.id = state.prompt.id;
      $('#signing-code').value = '';
      $('#signing-answer-label').hidden = state.prompt.kind !== 'verification';
      $('#signing-answer').hidden = state.prompt.kind !== 'verification';
      const choices = $('#signing-choices'); choices.replaceChildren();
      if (state.prompt.kind === 'certificate') {
        const warning = document.createElement('p');
        warning.className='certificate-help';
        warning.append(window.paneIcon('refresh'),document.createTextNode('Choose an old Pane certificate. Keep certificates used by other apps.'));
        choices.append(warning);
        const risk=document.createElement('p');risk.className='muted';risk.textContent='Replacing it cannot be undone. Its other apps may stop opening.';choices.append(risk);
        const confirm = document.createElement('button');
        confirm.type='button'; confirm.className='primary primary-block'; confirm.id='signing-revoke';
        confirm.textContent='Replace certificate & install'; confirm.disabled=true;
        let selected = null;
        for (const cert of state.prompt.choices) {
          const button = document.createElement('button'); button.type='button'; button.className='secondary';
          button.append(window.paneIcon('check'),document.createTextNode(cert.name || 'Development certificate'));
          if(cert.expires){const expiry=document.createElement('small');const date=new Date(cert.expires);expiry.textContent='Expires '+(Number.isNaN(date.getTime())?'later':date.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric',timeZone:'UTC'}));button.append(expiry);}
          button.setAttribute('aria-pressed','false'); button.dataset.certificate=cert.id;
          button.onclick=()=>{
            selected=cert.id;
            for(const other of choices.querySelectorAll('[data-certificate]'))other.setAttribute('aria-pressed',String(other===button));
            confirm.disabled=false;
          };
          choices.append(button);
        }
        confirm.onclick=()=>{if(selected){confirm.disabled=true;submitSigningAnswer(selected,true);}};
        choices.append(confirm);
        return;
      }
      const items = state.prompt.kind === 'team' ? state.prompt.choices.map(c => ({value:c.id, name:c.name || c.id}))
        : [{value:'resend', name:'Resend code'}, {value:'devices', name:'Send to Apple devices'}, ...state.prompt.choices.map(c=>({value:`sms:${c.id}`,name:`Text ${c.name}`}))];
      for (const item of items) {
        const button = document.createElement('button'); button.type='button'; button.className='secondary'; button.textContent=item.name;
        button.onclick=()=>submitSigningAnswer(item.value); choices.append(button);
      }
      if (state.prompt.kind !== 'team') $('#signing-code').focus();
    }
  }
  async function submitSigningAnswer(value, confirmRevocation = false) {
    try { renderSigning(await postJson('/api/signing/answer', {promptId:signingState.prompt?.id, value, confirmRevocation})); }
    catch(error) { $('#signing-note').textContent=window.paneNotice(error.message,'signing'); }
  }
  $('#signing-answer').onclick=()=>submitSigningAnswer($('#signing-code').value.trim());
  $('#signing-cancel').onclick=async()=>{try {renderSigning(await postJson('/api/signing/cancel',{}));} catch(error) {$('#signing-note').textContent=window.paneNotice(error.message,'signing');}};
  $('#signing-form').addEventListener('submit', async event => {
    event.preventDefault();
    const file=$('#signing-ipa').files[0];
    signingStaging=true; renderSigning(signingState);
    let id;
    try {
      if(file)id=await stage(file,'ipa',$('#signing-note'));
      const payload={id,udid:selectedUdid,email:$('#signing-email').value,password:$('#signing-password').value};
      $('#signing-password').value='';
      try { renderSigning(await postJson('/api/signing/start',payload)); }
      finally { payload.password=''; }
    } catch(error) {
      $('#signing-note').textContent=window.paneNotice(error.message,'signing');
      if(id)await postJson('/api/uploads/cancel',{id}).catch(()=>{});
    } finally { signingStaging=false; $('#signing-password').value=''; }
  });
  window.addEventListener('pane-status', () => { renderSigning(signingState); renderSetup(setupState); });
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
      $('#upload-progress').textContent = `${files.length} file(s) queued. ${transferState.bluetooth?.phase==='connected'?'Sending to your iPhone…':'Open Pane on your iPhone.'}`;
    } catch (error) { $('#upload-progress').textContent = window.paneNotice(error.message,'upload'); }
    finally { $('#send-files').disabled = false; event.target.value = ''; }
  });
  let transferPage = 0;
  for (const [id, delta] of [['transfers-prev', -1], ['transfers-next', 1]]) {
    $('#'+id).addEventListener('click', () => { transferPage += delta; renderTransfers(transferState); });
  }
  function renderTransfers(state) {
    transferState = state;
    $('#bluetooth-status').textContent = state.bluetooth.phase==='connected'?'Ready for files.':state.bluetooth.phase==='connecting'?'Connecting…':'Open Pane on your iPhone to connect.';
    const phase = state.bluetooth.phase;
    const badge = $('#bluetooth-badge');
    badge.textContent = {connected: 'Connected', connecting: 'Connecting', error: 'Needs attention'}[phase] || 'Not connected';
    badge.dataset.state = phase;
    for (const button of document.querySelectorAll('[data-bluetooth="disconnect"]')) button.hidden = !['connecting', 'connected'].includes(phase);
    $('#downloads-location').textContent = 'Downloads';
    $('#downloads-location').title = state.destination;
    const active = state.transfers.filter(t => ['queued', 'sending', 'receiving', 'paused'].includes(t.state)).length;
    $('#transfer-count').hidden = active === 0; $('#transfer-count').textContent = active;
    $('#transfer-count').setAttribute('aria-label', `${active} pending transfers`);
    $('#transfer-summary').textContent = active ? `${active} pending` : 'No active transfers';
    $('#history-count').textContent = state.transfers.length ? String(state.transfers.length) : '';
    const list = $('#transfer-list');
    // Polling must not rebuild an unchanged list and steal focus or selection.
    const pages = Math.max(1, Math.ceil(state.transfers.length / 2));
    transferPage = Math.max(0, Math.min(transferPage, pages - 1));
    $('#transfer-pages').hidden = pages === 1;
    $('#transfers-page').textContent = `${transferPage + 1} of ${pages}`;
    $('#transfers-prev').disabled = transferPage === 0;
    $('#transfers-next').disabled = transferPage === pages - 1;
    const visible = state.transfers.slice(transferPage * 2, transferPage * 2 + 2);
    const serialized = JSON.stringify([transferPage, visible]);
    if (list.dataset.snapshot === serialized) return;
    list.dataset.snapshot = serialized;
    const focused = document.activeElement?.dataset.transferKey;
    list.replaceChildren();
    if (!state.transfers.length) {
      const empty = document.createElement('li'); empty.className = 'transfer-empty';
      const title = document.createElement('strong'); title.textContent = 'Nothing here yet';
      const detail = document.createElement('p'); detail.textContent = 'Send a file from either device. Its progress and status will appear here.';
      empty.append(window.paneIcon('folder'), title, detail); list.append(empty);
    }
    for (const transfer of visible) {
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
      status.textContent = {complete:'Done', failed:'Failed', cancelled:'Cancelled', queued:'Queued', sending:'Sending', receiving:'Receiving', paused:'Paused'}[transfer.state] || 'Pending';
      top.append(status); item.append(top);
      if (['sending', 'receiving', 'paused'].includes(transfer.state)) {
        const progress = document.createElement('progress'); progress.max = transfer.size || 1; progress.value = transfer.done; progress.setAttribute('aria-label', `${transfer.name} progress`);
        const counts = document.createElement('p'); counts.className = 'transfer-numbers';
        counts.textContent = `${bytes(transfer.done)} of ${bytes(transfer.size)} · ${transfer.size ? Math.floor(transfer.done / transfer.size * 100) : 0}%`;
        item.append(progress, counts);
      }
      if (transfer.error) { const error = document.createElement('p'); error.className = 'warn'; error.textContent = window.paneNotice(transfer.error,'upload'); item.append(error); }
      if (['queued', 'sending', 'receiving', 'paused'].includes(transfer.state)) {
        const controls = document.createElement('div'); controls.className = 'transfer-actions';
        for (const command of [transfer.state === 'paused' ? 'resume' : 'pause', 'cancel']) {
          const button = document.createElement('button'); button.className = 'text-button transfer-control';
          button.textContent = command[0].toUpperCase() + command.slice(1);
          button.dataset.transferKey = `${transfer.id}:${command}`;
          button.setAttribute('aria-label', `${button.textContent} ${transfer.name}`);
          button.addEventListener('click', async () => {
            button.disabled = true;
            try { await postJson(`/api/uploads/${command}`, {id: transfer.id}); }
            catch (error) { $('#upload-progress').textContent = window.paneNotice(error.message, 'upload'); }
            finally { button.disabled = false; }
          });
          controls.append(button);
        }
        item.append(controls);
      }
      list.append(item);
    }
    if (focused) list.querySelector(`[data-transfer-key="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
  }
  async function poll() {
    try {
      const [setup, transfers, signing, snapshot] = await Promise.all([getJson('/api/setup'), getJson('/api/uploads'), getJson('/api/signing'), getJson('/api/status')]);
      usbConnected = (snapshot.devices || []).some(d => d.connection === 'USB');
      window.paneLastSnapshot = snapshot;
      window.dispatchEvent(new CustomEvent('pane-status', {detail:snapshot}));
      renderTransfers(transfers); renderSetup(setup); renderSigning(signing);
      window.dispatchEvent(new CustomEvent('pane-setup-state', {detail:{setup,transfers}}));
    } catch (error) { $('#bluetooth-status').textContent = window.paneNotice(error.message); }
    const busy = document.body.classList.contains('onboarding-open') || ['working','prompt'].includes(signingState.phase) || setupState.phase === 'working' || transferState.transfers?.some(t => ['queued','sending','receiving'].includes(t.state));
    setTimeout(poll, busy ? 1500 : document.hidden || !document.body.classList.contains('drawer-open') ? 10000 : 4000);
  }
  poll();
})();
