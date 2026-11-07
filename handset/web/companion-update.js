(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('companion-update-dialog');
  let previousFocus;
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
  async function check(startup = false) {
    const button = $('check-companion-update');
    button.disabled = true;
    try {
      const state = await getJson('/api/companion-update');
      const known = state.installedVersion;
      $('companion-version-note').textContent = !known
        ? 'iPhone app version unknown. Connect and unlock your iPhone, tap Trust if needed, then check again.'
        : `${state.cached ? 'Last verified' : 'Installed'} iPhone app: ${known}. ${state.updateAvailable ? `Update ${state.availableVersion} is available.` : 'No newer iPhone app is bundled.'}`;
      if (startup && state.updateAvailable && known) {
        $('companion-update-copy').textContent = `Pane ${state.availableVersion} is available for your iPhone (last verified: ${known}). ${state.connected ? 'Keep your iPhone connected by USB and unlocked to install it.' : 'Plug in your iPhone by USB and unlock it to install the update.'}`;
        previousFocus = document.activeElement;
        keyboard.releaseAll();
        dialog.showModal();
        $('companion-update-later').focus();
      }
    } catch (_) {
      $('companion-version-note').textContent = 'Could not check the iPhone app. Connect and unlock your phone, then try again.';
    } finally { button.disabled = false; }
  }
  $('check-companion-update').addEventListener('click', () => check(false));
  // Exactly one startup decision. Manual checks never interrupt with a popup.
  window.paneExperience.ready.then(() => check(true));
})();
