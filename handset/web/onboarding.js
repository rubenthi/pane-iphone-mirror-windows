(() => {
  const $ = selector => document.querySelector(selector);
  const panel = $('#onboarding');
  const signing = $('#signing-ui');
  const signingHome = document.createComment('signing controls');
  signing.before(signingHome);
  let state = {}, bluetooth = {}, active = false, busy = false, stage = 'connect';
  let autoBound = false, autoConnected = false;
  let devices = [];
  function chosen() { return $('#onboarding-device').value || state.udid || selectedUdid; }
  function refreshDevices(snapshot) {
    devices = (snapshot.devices || []).filter(d => d.connection === 'USB');
    const select = $('#onboarding-device');
    const wanted = select.value || state.udid || selectedUdid;
    const key = JSON.stringify(devices.map(d => [d.udid,d.name]));
    if (select.dataset.snapshot !== key) {
      select.dataset.snapshot = key; select.replaceChildren();
      if (!devices.length) select.add(new Option('Waiting for your iPhone…', ''));
      for (const device of devices) select.add(new Option(device.name || device.udid, device.udid));
      if (devices.some(d => d.udid === wanted)) select.value = wanted;
      $('#onboarding-device-picker').hidden = devices.length < 2;
      const status = $('#onboarding-usb-status');
      status.hidden = devices.length > 1;
      status.dataset.connected = String(devices.length === 1);
      status.textContent = devices.length ? (devices[0].name || 'iPhone connected by USB') : 'Waiting for a USB connection…';
    }
    if (active) {
      if (select.value) selectedUdid = select.value;
      usbConnected = devices.some(device => device.udid === selectedUdid);
    }
  }
  function render() {
    if (!active) return;
    stage = state.boundUdid ? 'bluetooth' : state.developerEnabled ? (state.installed ? 'bind' : 'install') : state.revealed ? 'developer' : 'connect';
    const copy = {
      connect: ['Connect your iPhone', 'Plug your unlocked iPhone into this laptop with a USB data cable. Tap Trust if asked.', 'Connect'],
      developer: ['Enable Developer Mode', '', 'Check Developer Mode'],
      install: ['Install Pane on iPhone', 'Use your Apple Account to sign and install the app over USB.', 'Install'],
      bind: ['Link this laptop', 'Keep your iPhone unlocked and connected by USB while Pane pairs it.', 'Retry pairing'],
      bluetooth: ['Open Pane on iPhone', 'Keep the USB cable connected until pairing finishes.', 'Connect Bluetooth']
    }[stage];
    $('#onboarding-title').textContent=copy[0]; $('#onboarding-description').textContent=copy[1];
    for (const name of ['connect','developer','signing','bluetooth']) $('#onboarding-'+name).hidden = name !== (stage==='install' ? 'signing' : stage);
    const next=$('#onboarding-next'); next.textContent=next.title=copy[2]; next.hidden=stage==='install';
    const usb=devices.some(d=>d.udid===chosen());
    next.disabled=busy || state.phase==='working' || (stage!=='bluetooth'&&!usb) || (stage==='bluetooth'&&bluetooth.phase==='connecting');
    $('#onboarding-refresh').hidden=stage!=='connect';
    $('#onboarding-note').textContent=state.error || (stage==='bluetooth' ? bluetooth.note : state.phase==='working' ? state.note : '') || '';
    const steps=['connect','developer','install','bluetooth'];const current=steps.indexOf(stage==='bind'?'bluetooth':stage);
    for(const item of document.querySelectorAll('[data-stage]')) {
      item.dataset.done=String(steps.indexOf(item.dataset.stage)<current);
      if(item.dataset.stage===steps[current])item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');
    }
    // Automatic actions happen once per attempt; failures leave an explicit retry button.
    if(stage==='bind' && usb && !autoBound && state.phase!=='working') {autoBound=true; act('bind');}
    if(stage==='bluetooth' && !autoConnected && !['connecting','connected'].includes(bluetooth.phase)) {autoConnected=true; act('bluetooth');}
  }
  async function act(action) {
    if(busy)return; busy=true;render();
    try {
      if(action==='bluetooth')bluetooth=await postJson('/api/bluetooth/connect',{});
      else state=await postJson('/api/setup/'+action,{udid:chosen()});
    } catch(error) {state={...state,phase:'error',error:error.message,note:error.message};$('#onboarding-note').textContent=error.message;}
    finally {busy=false;render();}
  }
  $('#onboarding-next').onclick=()=>act({connect:'start',developer:'developer',bind:'bind',bluetooth:'bluetooth'}[stage]);
  $('#onboarding-device').onchange=()=>{selectedUdid=chosen();autoBound=false;autoConnected=false;render();};
  window.addEventListener('pane-status', event => {refreshDevices(event.detail);render();});
  window.addEventListener('pane-setup-state', event => {
    const {setup,transfers}=event.detail;
      state=setup;bluetooth=transfers.bluetooth;
      const needed=state.onboardingRequired===true;
      if(needed&&!active) {
        active=true;panel.hidden=false;document.body.classList.add('onboarding-open');
        $('#onboarding-signing').append(signing);
        keyboard.releaseAll();
      } else if(!needed&&active) {
        active=false;panel.hidden=true;document.body.classList.remove('onboarding-open');signingHome.after(signing);
        if(document.body.classList.contains('drawer-open'))$('#drawer-toggle').click();
        window.dispatchEvent(new CustomEvent('pane-setup-complete'));
        if(bluetooth.phase==='connected'&&connectionPhase!=='running') {selectedUdid=state.boundUdid;setTransport('usb',false);showPhone();}
      }
      if(window.paneLastSnapshot)refreshDevices(window.paneLastSnapshot);render();
  });
  $('#onboarding-refresh').onclick=()=>load();
})();
