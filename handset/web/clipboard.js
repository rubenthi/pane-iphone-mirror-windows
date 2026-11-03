// Only explicit Paste actions read/send the host clipboard; no polling.
(() => {
  const limit = 1024 * 1024;
  const note = document.querySelector('#paste-note');
  const button = document.querySelector('#paste-iphone');
  const show = message => { note.textContent = message; };
  window.panePaste = async payload => {
    if (!document.querySelector('#workspace').classList.contains('is-live'))
      throw Error('Start mirroring before pasting.');
    if (payload.image) {
      if (payload.image.type !== 'image/png' || payload.image.size > limit)
        throw Error('Paste supports PNG images up to 1 MiB.');
    } else if (!payload.text) {
      throw Error('Copy text or a PNG image first.');
    } else if (new TextEncoder().encode(JSON.stringify({text:payload.text})).length > limit) {
      throw Error('Clipboard text exceeds 1 MiB.');
    }
    await window.paneControl.transaction(async send => {
      // Clear held modifiers before replacing the phone clipboard.
      await send('/key', {usages:[]});
      if (payload.image) {
        const response = await fetch('/mirror/clipboard/image', {
          method:'POST', headers:{'Content-Type':'image/png','X-Pane-Token':await paneToken()},
          body:payload.image
        });
        if (!response.ok) throw Error('Could not copy the image to the iPhone.');
      } else {
        await send('/clipboard', {text:payload.text});
      }
      try { await send('/key', {usages:[0xe3,0x19]}); }
      finally { await send('/key', {usages:[]}); }
    });
    window.paneSetTyping(true);
    show('Sent to iPhone. A text field or image-capable app must be focused.');
  };
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      let payload;
      if (navigator.clipboard?.read) {
        const items = await navigator.clipboard.read();
        const png = items.find(item => item.types.includes('image/png'));
        const text = items.find(item => item.types.includes('text/plain'));
        if (png) payload = {image:await png.getType('image/png')};
        else if (text) payload = {text:await (await text.getType('text/plain')).text()};
      } else if (navigator.clipboard?.readText) {
        payload = {text:await navigator.clipboard.readText()};
      }
      if (!payload) throw Error('Copy text or a PNG image, focus the mirror, then press Ctrl+V.');
      await window.panePaste(payload);
    } catch (error) {
      show(error.name === 'NotAllowedError' ? 'Clipboard access blocked. Focus the mirror and press Ctrl+V.' : error.message);
    } finally { button.disabled = false; }
  });
})();
