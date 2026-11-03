/* Bluetooth audio/notifications work independently of the chosen control mode. */
(() => {
  const $ = id => document.getElementById(id);
  const note = $("bt-note");
  const mode = $("control-mode");
  const pad = $("bt-pad");
  let latest = {}, active = false, polling = false, capture = null;
  let buttons = 0, dx = 0, dy = 0, wheel = 0, sending = false, last = null, inFlight = Promise.resolve();
  const transitions = [];
  const clamp = n => Math.max(-127, Math.min(127, Math.round(n)));
  const command = payload => postJson("/api/bluetooth", payload);
  function fail(error) { note.textContent = error.message; }
  function options(select, values) {
    const previous = select.value;
    const list = values || [];
    // Preserve focus and the selected device across polling.
    const signature = JSON.stringify(list);
    if (select.dataset.signature === signature) return;
    select.dataset.signature = signature;
    select.replaceChildren(new Option("Select a device…", ""), ...list.map(d => new Option(d.name, d.id)));
    if (list.some(d => d.id === previous)) select.value = previous;
  }
  function render(state) {
    latest = state;
    $("bt-audio-state").textContent = state.audio?.state || "Not connected";
    $("bt-cursor-state").textContent = state.cursor?.state || "Not started";
    $("bt-notification-state").textContent = state.notifications?.error || state.notifications?.state || "Not connected";
    if (state.error) note.textContent = state.error;
    options($("bt-cursor-device"), state.cursor?.clients);
    const ready = !!state.cursor?.selected && (state.cursor.clients || []).some(c => c.id === state.cursor.selected);
    pad.setAttribute("aria-disabled", String(!ready));
    if (!ready) { buttons = dx = dy = wheel = 0; transitions.length = 0; last = null; }
    $("bt-cursor-target").textContent = ready ? "Cursor ready · move over the pad, click and scroll" : "Start cursor pairing, pair the iPhone, then select its cursor client.";
    const list = $("bt-notifications");
    list.replaceChildren(...(state.notifications?.items || []).map(item => {
      const li = document.createElement("li");
      const title = document.createElement("strong"), message = document.createElement("p"), app = document.createElement("small");
      title.textContent = item.title || "iPhone notification";
      message.textContent = item.message || "Preview not supplied by iPhone";
      app.textContent = item.app;
      li.append(title, message, app); return li;
    }));
  }
  async function refresh() {
    const devices = await command({action:"devices"});
    options($("bt-audio-device"), devices.audio);
    options($("bt-notification-device"), devices.notifications);
    active = true;
    render(await getJson("/api/bluetooth"));
  }
  document.querySelectorAll("[data-bt-action]").forEach(button => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      note.textContent = "Working…";
      try {
        const action = button.dataset.btAction;
        if (action === "devices") await refresh();
        else {
          const payload = {action};
          if (button.dataset.btDevice) payload.device = $(button.dataset.btDevice).value;
          render(await command(payload)); active = true;
        }
        note.textContent = "";
      } catch (error) { fail(error); }
      finally { button.disabled = false; }
    });
  });
  document.querySelectorAll("[data-bt-settings]").forEach(button => button.addEventListener("click", () => {
    postJson("/api/bluetooth/settings", {target:button.dataset.btSettings}).catch(fail);
  }));
  async function changeMode() {
    mode.disabled = true;
    const previous = document.body.dataset.controlMode || "developer";
    try {
      release();
      await drain();
      if (mode.value === "developer" && active) {
        await command({action:"cursor.stop"});
        stopCapture();
      }
      await window.paneSetControlMode(mode.value);
      localStorage.setItem("pane-control-mode", mode.value);
    } catch (error) { mode.value = previous; fail(error); }
    finally { mode.disabled = false; }
  }
  mode.addEventListener("change", changeMode);
  function canControl() { return mode.value === "bluetooth" && pad.getAttribute("aria-disabled") === "false"; }
  function release() {
    if (buttons) { buttons = 0; transitions.push({buttons:0, dx:0, dy:0, wheel:0}); }
    dx = dy = wheel = 0; last = null;
    drain().catch(fail);
  }
  function drain() {
    if (sending) return inFlight;
    sending = true;
    inFlight = sendReports();
    return inFlight;
  }
  async function sendReports() {
    try {
      while (transitions.length || dx || dy || wheel) {
        let report;
        if (transitions.length) report = transitions.shift();
        else {
          report = {buttons, dx:clamp(dx), dy:clamp(dy), wheel:clamp(wheel)};
          dx -= report.dx; dy -= report.dy; wheel -= report.wheel;
        }
        await command({action:"cursor.move", ...report});
      }
    } catch (error) {
      buttons = dx = dy = wheel = 0; transitions.length = 0;
      pad.setAttribute("aria-disabled", "true"); fail(error);
    } finally { sending = false; }
  }
  pad.addEventListener("pointermove", event => {
    if (!canControl()) return;
    if (last) { dx = clamp(dx + event.clientX - last.x); dy = clamp(dy + event.clientY - last.y); }
    last = {x:event.clientX, y:event.clientY};
  });
  pad.addEventListener("pointerdown", event => {
    if (!canControl()) return;
    event.preventDefault(); pad.setPointerCapture(event.pointerId);
    buttons = event.buttons & 7;
    transitions.push({buttons, dx:0, dy:0, wheel:0});
    if (transitions.length > 16) { transitions.length = 0; release(); }
    drain();
  });
  pad.addEventListener("pointerup", release);
  pad.addEventListener("pointercancel", release);
  pad.addEventListener("lostpointercapture", release);
  pad.addEventListener("pointerleave", () => { last = null; if (!buttons) dx = dy = 0; });
  pad.addEventListener("contextmenu", event => event.preventDefault());
  pad.addEventListener("wheel", event => {
    if (!canControl()) return;
    event.preventDefault(); wheel = clamp(wheel - Math.sign(event.deltaY) * 3);
  }, {passive:false});
  window.addEventListener("blur", release);
  document.addEventListener("visibilitychange", () => { if (document.hidden) release(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") release(); });
  setInterval(() => { if (canControl()) drain(); }, 33);
  // Keep a stationary drag alive; the helper releases buttons after 1.5s without input.
  setInterval(() => { if (buttons && canControl() && !sending) { transitions.push({buttons, dx:0, dy:0, wheel:0}); drain(); } }, 400);

  function stopCapture() {
    if (capture) capture.getTracks().forEach(track => track.stop());
    capture = null; $("bt-video").srcObject = null; $("bt-video").hidden = true;
  }
  $("bt-capture").addEventListener("click", async () => {
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error("Window capture is unavailable here. Keep the AirPlay receiver visible beside Pane, or open Pane in Edge/Chrome.");
      stopCapture();
      capture = await navigator.mediaDevices.getDisplayMedia({video:true, audio:false});
      $("bt-video").srcObject = capture; $("bt-video").hidden = false;
      capture.getVideoTracks()[0].addEventListener("ended", stopCapture);
      await $("bt-video").play();
    } catch (error) { stopCapture(); fail(error); }
  });
  $("bt-stop-capture").addEventListener("click", stopCapture);
  async function poll() {
    if (polling || !active) return;
    polling = true;
    try { render(await getJson("/api/bluetooth")); } catch (error) { fail(error); }
    finally { polling = false; }
  }
  setInterval(poll, 3000);
  getJson("/api/bluetooth").then(render).catch(fail);
  mode.value = localStorage.getItem("pane-control-mode") === "bluetooth" ? "bluetooth" : "developer";
  if (mode.value === "bluetooth") changeMode();
})();
