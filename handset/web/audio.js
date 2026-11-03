(() => {
  const select = document.querySelector('#audio-device');
  const connect = document.querySelector('#audio-connect');
  const stop = document.querySelector('#audio-stop');
  const refresh = document.querySelector('#audio-refresh');
  const note = document.querySelector('#audio-note');
  let timer = 0, generation = 0, active = false;
  function render(state) {
    active = ['connecting','connected'].includes(state.phase);
    note.textContent = !state.supported ? 'Requires Windows 10 version 2004 or newer and Bluetooth.' : state.error || state.note || 'Bluetooth audio ready.';
    connect.hidden = active;
    stop.hidden = !active;
    select.disabled = active;
    connect.disabled = !select.value || !state.supported;
    refresh.disabled = active || !state.supported;
  }
  async function poll(current) {
    try {
      const state = await getJson('/api/audio');
      if (current !== generation) return;
      render(state);
      if (active) timer = setTimeout(() => poll(current), 2000);
    } catch (error) {
      if (current === generation) note.textContent = error.message;
    }
  }
  refresh.addEventListener('click', async () => {
    refresh.disabled = true;
    note.textContent = 'Looking for paired audio devices…';
    try {
      const state = await postJson('/api/audio', {action:'devices'});
      select.replaceChildren(new Option('Select your paired iPhone', ''));
      for (const device of state.devices) select.add(new Option(device.name, device.id));
      if (state.devices.length === 1) select.selectedIndex = 1;
      render(state);
      if (!state.devices.length && state.supported) note.textContent = 'No audio devices found. Pair your iPhone in Windows Bluetooth settings, then retry.';
    } catch (error) { note.textContent = error.message; }
    finally { if (!active) refresh.disabled = false; }
  });
  select.addEventListener('change', () => { connect.disabled = !select.value; });
  connect.addEventListener('click', async () => {
    const current = ++generation;
    clearTimeout(timer);
    connect.disabled = true;
    try {
      render(await postJson('/api/audio', {action:'connect', id:select.value}));
      timer = setTimeout(() => poll(current), 500);
    } catch (error) { note.textContent = error.message; connect.disabled = !select.value; }
  });
  stop.addEventListener('click', async () => {
    ++generation; clearTimeout(timer);
    stop.disabled = true;
    try { render(await postJson('/api/audio', {action:'stop'})); }
    catch (error) { note.textContent = error.message; }
    finally { stop.disabled = false; }
  });
  poll(generation);
})();
