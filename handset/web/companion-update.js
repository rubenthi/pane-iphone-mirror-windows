(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('companion-update-dialog');
  let previousFocus;
  let ready = false, checking = false, recheck = false;
  let usbDevices = '', nextRetry = Infinity;
  const prompted = new Set();
  function dismiss() { dialog.close(); previousFocus?.focus({preventScroll:true}); }
  $('companion-update-later').addEventListener('click', dismiss);
  $('companion-update-open').addEventListener('click', async () => {
    dismiss();
    try { await window.paneOpenDrawer(); } catch (_) {
      $('companion-version-note').textContent = 'Open Settings > Setup & signing to update the iPhone app.';
      return;
    }
    document.querySelector('[data-settings="setup"]').click();
    const step = document.querySelector('[data-step="install"]');
    step.open = true;
    step.scrollIntoView({block:'start'});
    step.querySelector('summary').focus();
  });
  async function check(notify = false) {
    if (checking) { recheck ||= notify; return; }
    checking = true;
    const button = $('check-companion-update');
    button.disabled = true;
    try {
      const state = await getJson('/api/companion-update');
      const known = state.installedVersion;
      nextRetry = !known && !state.packageUnavailable ? Date.now() + 65000 : Infinity;
      $('companion-version-note').textContent = state.packageUnavailable
        ? 'The matching iPhone update is missing from this copy of Pane.'
        : !known
        ? 'iPhone app version unknown. Connect and unlock your iPhone, tap Trust if needed, then check again.'
        : `${state.cached ? 'Last verified' : 'Installed'} iPhone app: ${known}. ${state.updateAvailable ? `Update ${state.availableVersion} is available.` : 'No newer iPhone app is bundled.'}`;
      if (notify && state.updateAvailable && known && !prompted.has(state.availableVersion)) {
        $('companion-update-copy').textContent = `Pane ${state.availableVersion} is available for your iPhone (last verified: ${known}). ${state.connected ? 'Keep your iPhone connected by USB and unlocked to install it.' : 'Plug in your iPhone by USB and unlock it to install the update.'}`;
        previousFocus = document.activeElement;
        keyboard.releaseAll();
        dialog.showModal();
        prompted.add(state.availableVersion);
        $('companion-update-later').focus();
      }
    } catch (_) {
      nextRetry = Date.now() + 65000;
      $('companion-version-note').textContent = 'Could not check the iPhone app. Connect and unlock your phone, then try again.';
    } finally {
      button.disabled = false;
      checking = false;
      if (recheck) { recheck = false; void check(true); }
    }
  }
  $('check-companion-update').addEventListener('click', () => check(false));
  // An unknown phone at launch may be plugged in or unlocked later.
  window.addEventListener('pane-status', ({detail}) => {
    if (!Array.isArray(detail?.devices)) return;
    const connected = detail.devices.filter(d => d.connection === 'USB').map(d => d.udid).sort().join(',');
    const changed = connected !== usbDevices;
    usbDevices = connected;
    if (ready && connected && (changed || Date.now() >= nextRetry)) {
      nextRetry = Infinity;
      void check(true);
    }
  });
  window.paneExperience.ready.then(() => { ready = true; return check(true); });
})();
