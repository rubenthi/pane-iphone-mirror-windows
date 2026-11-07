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
      connect: ['Welcome to Pane', 'Your iPhone, connected.', 'One guided setup links your phone to this laptop.', 'Connect'],
      developer: ['On your iPhone', 'Enable Developer Mode.', 'Pane has requested the developer switch. Finish these steps on your phone.', 'I’ve enabled it — check'],
      install: ['Your companion app', 'Install Pane on iPhone.', 'Pane signs and pushes the included app over USB. Complete Apple verification when asked.', 'Install'],
      bind: ['Link your connections', 'Bind this laptop.', 'Pane will provision the companion over USB and pair Wi-Fi mirroring.', 'Bind connections'],
      bluetooth: ['One last connection', 'Open Pane on iPhone.', 'Keep the cable connected for this final step.', 'Connect Bluetooth']
    }[stage];
    $('#onboarding-kicker').textContent=copy[0]; $('#onboarding-title').textContent=copy[1]; $('#onboarding-description').textContent=copy[2];
    for (const name of ['connect','developer','signing','bluetooth']) $('#onboarding-'+name).hidden = name !== ({install:'signing',bind:'bluetooth'}[stage] || stage);
    const next=$('#onboarding-next'); next.textContent=copy[3]; next.hidden=stage==='install';
    const usb=devices.some(d=>d.udid===chosen());
    next.disabled=busy || state.phase==='working' || (stage!=='bluetooth'&&!usb) || (stage==='bluetooth'&&bluetooth.phase==='connecting');
    $('#onboarding-refresh').hidden=stage==='install';
    $('#onboarding-note').textContent=state.error || (stage==='bluetooth' ? bluetooth.note : state.note) || '';
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
