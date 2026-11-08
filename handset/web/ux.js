// Keep diagnostic responses in the local API; show a short next action in the UI.
window.paneNotice = function(error, context = 'connection', code = '') {
  const text = String(error || '').toLowerCase();
  if (code === 'certificate_limit' || /certificate.limit|maximum number of certificates|7460/.test(text)) return 'Signing limit reached. Replace an old certificate.';
  if (code === 'app_id_limit') return 'Apple’s app limit reached. Try again later.';
  if (code === 'rate_limited' || /too many requests|rate.limit/.test(text)) return 'Too many attempts. Try again later.';
  if (code === 'tls' || code === 'service_unavailable') return 'Apple is unavailable. Try again later.';
  if (/developer mode|reveal/.test(text)) return 'Developer Mode is off. Turn it on in Settings.';
  if (/trust|pairing file|lockdown/.test(text)) return 'iPhone needs trust. Unlock it and tap Trust.';
  if (context === 'upload') {
    if (/too large|size limit|exceeds.*limit|maximum.*size/.test(text)) return 'File too large. Choose a smaller file.';
    if (/hash|checksum|incomplete/.test(text)) return 'File incomplete. Send it again.';
    if (/queue.*full|too many.*files/.test(text)) return 'Queue full. Finish or cancel a file.';
    return 'Transfer stopped. Open Pane on your iPhone.';
  }
  if (context === 'bluetooth') return 'Phone not connected. Open Pane on your iPhone.';
  if (context === 'signing' && /bundled companion.*missing|bundled iphone app.*(?:damaged|outdated)/.test(text)) return 'iPhone installer unavailable. Update Pane on this PC.';
  if (context === 'signing') return code === 'device_install' ? 'Install stopped. Unlock your iPhone and retry.' : 'Install stopped. Check your account and retry.';
  if (context === 'window') return 'Resize paused. Try dragging again.';
  if (context === 'preferences') return 'Couldn’t save. Try again.';
  return 'Phone not connected. Unlock it and reconnect.';
};

window.paneSigningNote = function(state) {
  if (state.phase === 'error') return window.paneNotice(state.note, 'signing', state.code);
  if (state.phase === 'prompt') return ({certificate:'Choose an old certificate to replace.',team:'Choose your Apple team.',verification:'Enter your Apple verification code.'})[state.prompt?.kind] || 'Check your iPhone.';
  if (state.phase === 'working') return /signing in/i.test(state.note) ? 'Signing in…' : 'Installing Pane…';
  if (state.phase === 'complete') return 'Pane installed. Open it on your iPhone.';
  if (state.phase === 'cancelled') return 'Installation cancelled.';
  return 'Ready to install.';
};

window.paneBluetoothNote = function(note) {
  const text = String(note || '');
  if (/traceback|exception|error:|hresult|0x[0-9a-f]{6}|winerror|socket|failed|could not|couldn.t|unavailable/i.test(text)) return 'Bluetooth unavailable. Open Windows Bluetooth settings and retry.';
  return text;
};
