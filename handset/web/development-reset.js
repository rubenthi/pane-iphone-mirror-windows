(() => {
  const dialog = document.querySelector('#development-reset-dialog');
  const cancel = document.querySelector('#development-reset-cancel');
  const confirm = document.querySelector('#development-reset-confirm');
  const status = document.querySelector('#development-reset-status');
  let trigger;

  for (const button of document.querySelectorAll('[data-development-reset]')) {
    button.addEventListener('click', () => {
      trigger = button;
      status.textContent = '';
      dialog.showModal();
      cancel.focus();
    });
  }
  dialog.addEventListener('close', () => trigger?.focus());
  cancel.addEventListener('click', () => dialog.close());
  confirm.addEventListener('click', async () => {
    cancel.disabled = confirm.disabled = true;
    status.textContent = 'Restarting Pane (Development)…';
    try {
      await postJson('/api/development/reset', {confirm: true});
    } catch (error) {
      status.textContent = error.message;
      cancel.disabled = confirm.disabled = false;
    }
  });
})();
