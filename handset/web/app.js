const statusList = document.querySelector("#status");
const statusNote = document.querySelector("#status-note");
const devicesEl = document.querySelector("#devices");
const detail = document.querySelector("#detail");
const refresh = document.querySelector("#refresh");
const screenNote = document.querySelector("#screen-note");
const showScreen = document.querySelector("#show-screen");
const screenView = document.querySelector("#screen-view");
const phoneShell = document.querySelector("#phone-shell");
const placeholderHint = document.querySelector("#placeholder-hint");
const pillConnection = document.querySelector("#pill-connection");
const pillDevice = document.querySelector("#pill-device");
const toggleGuide = document.querySelector("#toggle-guide");
const runGuide = document.querySelector("#run-guide");
const workspace = document.querySelector("#workspace");
const remotePanel = document.querySelector("#remote-panel");
const restartScreen = document.querySelector("#restart-screen");
const phoneScreen = document.querySelector("#phone-screen");
const kbToggle = document.querySelector("#kb-toggle");
const wifiState = document.querySelector("#wifi-state");
const wifiPair = document.querySelector("#wifi-pair");
const MIRROR_PAGE = "/mirror.html";
const MIRROR_API = "/mirror";

// The token is process-local and only readable by this same-origin UI.
let paneTokenPromise = null;
function paneToken() {
  if (!paneTokenPromise) {
    paneTokenPromise = fetch("/api/auth", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Pane authorization unavailable.");
        return response.json();
      })
      .then((data) => {
        if (typeof data.token !== "string") throw new Error("Invalid Pane authorization response.");
        return data.token;
      })
      .catch((error) => {
        paneTokenPromise = null;
        throw error;
      });
  }
  return paneTokenPromise;
}

const loadGeneration = window.createPaneGeneration();
const detailGeneration = window.createPaneGeneration();
const screenGeneration = window.createPaneGeneration();
window.paneControl = window.createPaneControlQueue((path, payload) => postJson(`${MIRROR_API}${path}`, payload));
let selectedUdid = null;
let screenTimer = 0;
let transport = localStorage.getItem("handset-transport") === "wifi" ? "wifi" : "usb";
let wifiPaired = [];
let usbConnected = false;
let connectionPhase = "idle";
let connectionBusy = false;

document.querySelectorAll("[data-transport]").forEach((btn) => {
  btn.addEventListener("click", () => setTransport(btn.dataset.transport));
});
wifiPair.addEventListener("click", () => setUpWifi());
setTransport(transport, false);

function setTransport(value, reload = true) {
  transport = value === "wifi" ? "wifi" : "usb";
  document.querySelector('#connection-title').textContent = transport === 'wifi' ? 'Wireless connection' : 'Connect over USB';
  document.querySelector('#connection-description').textContent = transport === 'wifi' ? 'Keep your iPhone on the same Wi-Fi.' : 'Keep your iPhone connected.';
  localStorage.setItem("handset-transport", transport);
  document.querySelectorAll("[data-transport]").forEach((btn) => {
    const active = btn.dataset.transport === transport;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-checked", String(active));
  });
  if (reload) load();
}

function renderWifi() {
  const ready = selectedUdid ? wifiPaired.includes(selectedUdid) : wifiPaired.length > 0;
  wifiState.textContent = ready ? "✓ Wi‑Fi ready" : "Wi‑Fi not set up";
  wifiState.classList.toggle("ok", ready);
  wifiPair.hidden = ready;
  wifiPair.disabled = !usbConnected;
  wifiPair.title = usbConnected ? "One-time setup over the cable" : "Plug in the cable once to set up Wi‑Fi";
  const setupNeeded = transport === 'wifi' ? !ready : !usbConnected;
  document.querySelector('#setup-title').textContent = setupNeeded ? "Let's get you connected." : 'Need a hand?';
  document.querySelector('#setup-card .eyebrow').textContent = setupNeeded ? 'SETUP NEEDED' : 'HELP & SETUP';
}

async function setUpWifi() {
  wifiPair.disabled = true;
  wifiPair.textContent = "Setting up…";
  try {
    const result = await postJson("/api/wifi/pair", { udid: selectedUdid });
    if (!result.ok) throw new Error(result.error || "Wi‑Fi setup failed.");
    screenNote.textContent = "Wi‑Fi is set up. You can unplug the cable and choose Wi‑Fi.";
    screenNote.className = "";
  } catch (error) {
    screenNote.textContent = window.paneNotice(error.message);
    screenNote.className = "warn";
  } finally {
    wifiPair.textContent = "Set up Wi‑Fi";
    load();
  }
}

refresh.addEventListener("click", () => load());
showScreen.addEventListener("click", () => showPhone());
document.querySelector('#welcome-setup').addEventListener('click', () => {
  if (['running','starting'].includes(connectionPhase)) return;
  setTransport('wifi',false);
  if (!wifiPaired.includes(selectedUdid)) selectedUdid=wifiPaired.length===1?wifiPaired[0]:null;
  showPhone();
});
restartScreen.addEventListener("click", () => restartMirror());
wireRemoteControls();

toggleGuide.addEventListener('click', () => window.paneView.open('setup'));

async function load() {
  const generation = loadGeneration.next();
  refresh.disabled = true;
  detail.hidden = true;
  detail.replaceChildren();
  try {
    const state = await getJson("/api/status");
    if (!loadGeneration.current(generation)) return;
    document.querySelector("#update-note").textContent = `Pane ${state.update?.version || ""} · ${state.update?.note || state.update?.phase || ""}`;
    wifiPaired = state.wifi?.paired || [];
    usbConnected = (state.devices || []).length > 0;
    renderStatus(state);
    renderDevices(state.devices || []);
    renderWifi();
    renderScreen(state.screen);
    renderPills(state);
    window.paneLastSnapshot = state;
    window.dispatchEvent(new CustomEvent("pane-status", {detail:state}));
  } catch (error) {
    if (!loadGeneration.current(generation)) return;
    setPill(pillConnection, "Offline", "bad");
    statusNote.textContent = window.paneNotice(error.message);
    statusNote.className = "warn";
  } finally {
    if (loadGeneration.current(generation)) refresh.disabled = false;
  }
}

function renderPills(state) {
  const driver = state.driver || {};
  const connected = (state.devices || []).length > 0;
  const overWifi = transport === "wifi" && wifiPaired.length > 0;
  if (state.screen?.phase === "running") {
    setPill(pillConnection, state.screen.transport === "wifi" ? "Mirroring · Wi‑Fi" : "Mirroring", "ok");
  } else if (overWifi) {
    setPill(pillConnection, "Wi‑Fi ready", "ok");
  } else if (state.error) {
    setPill(pillConnection, "Error", "bad");
  } else if (!driver.ready) {
    setPill(pillConnection, "Install Apple Devices", "warn");
  } else if (!connected) {
    setPill(pillConnection, "Plug in iPhone", "warn");
  } else if (state.developerMode === false) {
    setPill(pillConnection, "Developer Mode off", "warn");
  } else if (state.screen?.phase === "running") {
    setPill(pillConnection, "Mirroring", "ok");
  } else {
    setPill(pillConnection, "Ready", "ok");
  }

  if (!connected) {
    pillDevice.hidden = !overWifi;
    pillDevice.textContent = "Wi‑Fi";
    return;
  }
  pillDevice.hidden = false;
  const count = state.devices.length;
  pillDevice.textContent = count === 1 ? "1 device · USB" : `${count} devices`;
}

function setPill(el, text, tone) {
  el.textContent = text;
  el.className = "pill" + (tone ? ` pill-${tone}` : "");
}

function renderStatus(state) {
  const library = state.library || {};
  const driver = state.driver || {};
  statusList.replaceChildren(
    ...row("Client", library.ready ? "ready" : "missing", library.ready),
    ...row("USB service", driver.ready ? "running" : "missing", driver.ready),
    ...row("Developer Mode", state.developerMode === false ? "off" : state.developerMode ? "on" : "—", state.developerMode !== false),
  );
  const connected = (state.devices || []).length > 0;
  if (state.developerMode === false) {
    statusNote.textContent =
      "Turn on Developer Mode on the iPhone (Settings → Privacy & Security), restart, then mirror again.";
    placeholderHint.textContent = "Developer Mode must be on before mirroring works.";
    return;
  }
  statusNote.textContent =
    (state.error ? window.paneNotice(state.error) : connected ? "iPhone connected." : !driver.ready ? "Install Apple Devices on this PC." : "") ||
    "";
  statusNote.className = state.error || !driver.ready ? "warn" : "";
  if (!connected && (state.wifi?.paired || []).length) {
    statusNote.textContent = "Keep your iPhone on the same Wi-Fi, then tap Connect.";
    statusNote.className = "";
    placeholderHint.textContent = "Connect your iPhone over Wi-Fi.";
  } else if (!connected) {
    placeholderHint.textContent = "Connect your iPhone with a data cable, unlock it, and tap Trust.";
  }
}

function renderDevices(list) {
  devicesEl.replaceChildren();
  if (!list.length && transport === "wifi" && wifiPaired.length) {
    list = wifiPaired.map((udid) => ({ udid, connection: "Wi‑Fi", wifiOnly: true }));
  }
  if (!list.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "No iPhone detected.";
    devicesEl.append(item);
    selectedUdid = null;
    return;
  }
  if (!list.some((device) => device.udid === selectedUdid)) selectedUdid = null;
  if (list.length === 1) selectedUdid = list[0].udid;

  for (const device of list) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.className = "device" + (device.udid === selectedUdid ? " selected" : "");
    button.type = "button";
    const name = document.createElement("span");
    name.className = "device-name";
    name.textContent = device.udid.slice(0, 8) + "…";
    const meta = document.createElement("span");
    meta.className = "device-meta";
    meta.textContent = device.connection || "USB";
    button.append(name, meta);
    button.addEventListener("click", () => {
      selectedUdid = device.udid;
      devicesEl.querySelectorAll(".device").forEach((el) => el.classList.remove("selected"));
      button.classList.add("selected");
      if (!device.wifiOnly) openDevice(device.udid);
      renderWifi();
    });
    item.append(button);
    devicesEl.append(item);
  }
  if (list.length === 1 && !list[0].wifiOnly) openDevice(list[0].udid);
}

async function openDevice(udid) {
  const generation = detailGeneration.next();
  detail.hidden = false;
  detail.textContent = "Reading device…";
  try {
    const device = await getJson(`/api/devices/${encodeURIComponent(udid)}`);
    if (!detailGeneration.current(generation) || selectedUdid !== udid) return;
    renderDetail(device);
    if (device.info?.DeviceName) {
      pillDevice.hidden = false;
      pillDevice.textContent = device.info.DeviceName;
    }
  } catch (error) {
    if (detailGeneration.current(generation) && selectedUdid === udid) detail.textContent = window.paneNotice(error.message);
  }
}

function renderDetail(device) {
  detail.replaceChildren();
  const title = document.createElement("h3");
  title.textContent = device.info?.DeviceName || "iPhone";
  detail.append(title);
  if (device.error) {
    const note = document.createElement("p");
    note.className = "warn";
    note.textContent = window.paneNotice(device.error);
    detail.append(note);
  }
  const list = document.createElement("dl");
  list.className = "kv";
  const labels = {
    ProductType: "Model",
    ProductVersion: "iOS",
    BuildVersion: "Build",
  };
  for (const [key, label] of Object.entries(labels)) {
    if (device.info && device.info[key] != null) list.append(...row(label, String(device.info[key]), true));
  }
  if (list.childElementCount) detail.append(list);
}

function renderScreen(screen) {
  if (!screen) return;
  connectionPhase = screen.phase;
  if (screen.companion) window.paneExperience?.renderCompanion(screen.companion);
  if (screen.update) document.querySelector("#update-note").textContent = `Pane ${screen.update.version} · ${screen.update.note || screen.update.phase}`;
  const mirroring = screen.phase === "running";
  document.querySelectorAll(".rail-navigation button:not(#drawer-toggle)").forEach(button=>button.disabled=!mirroring);
  const selectedStream = screen.udid === selectedUdid && screen.transport === transport;
  if (mirroring) {
    workspace.classList.add("is-live");
    phoneShell.classList.add("live");
    remotePanel.hidden = false;
    restartScreen.hidden = false;
    kbToggle.hidden = false;
    screenNote.textContent = screen.error ? window.paneNotice(screen.error) : "Connected.";
    screenNote.className = "";
    showScreen.textContent = "Disconnect";
    showScreen.disabled = connectionBusy;
    if (screenView.getAttribute("src") !== MIRROR_PAGE) screenView.src = MIRROR_PAGE;
    screenView.hidden = false;
    return;
  }

  workspace.classList.remove("is-live");
  phoneShell.classList.remove("live");
  remotePanel.hidden = false;
  restartScreen.hidden = true;
  kbToggle.hidden = true;
  screenView.hidden = true;
  if (screenView.getAttribute("src") !== "about:blank") screenView.src = "about:blank";
  showScreen.textContent = "Connect";
  showScreen.disabled = false;

  if (screen.phase === "starting") {
    screenNote.textContent = "Connecting… Unlock your iPhone.";
    placeholderHint.textContent = transport==='wifi'?'Connecting over Wi-Fi…':'Connecting to your iPhone…';
    screenNote.className = "";
    showScreen.disabled = connectionBusy;
    showScreen.textContent = "Disconnect";
    return;
  }
  if (screen.error) {
    screenNote.textContent = window.paneNotice(screen.error);
    placeholderHint.textContent = screenNote.textContent;
    screenNote.className = "warn";
    return;
  }
  screenNote.textContent = "";
  screenNote.className = "";
}

async function showPhone() {
  if (connectionBusy) return;
  const disconnect = ["running", "starting"].includes(connectionPhase);
  connectionBusy = true;
  screenGeneration.next();
  loadGeneration.next();
  window.clearTimeout(screenTimer);
  showScreen.disabled = true;
  showScreen.textContent = disconnect ? "Disconnecting…" : "Connecting…";
  if(!disconnect)placeholderHint.textContent=transport==='wifi'?'Connecting over Wi-Fi…':'Connecting to your iPhone…';
  try {
    if (disconnect) await keyboard.releaseAll();
    const result = await postJson(disconnect ? "/api/screen/stop" : "/api/screen", disconnect ? {} : { udid: selectedUdid, transport });
    connectionBusy = false;
    renderScreen(result);
  } catch (error) {
    screenNote.textContent = window.paneNotice(error.message);
    placeholderHint.textContent = screenNote.textContent;
    screenNote.className = "warn";
  } finally {
    connectionBusy = false;
    showScreen.disabled = false;
    showScreen.textContent = ["running", "starting"].includes(connectionPhase) ? "Disconnect" : "Connect";
    watchScreen();
  }
}

function watchScreen() {
  const generation = screenGeneration.next();
  window.clearTimeout(screenTimer);
  async function poll() {
    try {
      const screen = await getJson("/api/screen");
      if (!screenGeneration.current(generation)) return;
      renderScreen(screen);
    } catch (error) {
      if (!screenGeneration.current(generation)) return;
      renderScreen({ phase: "error", error: error.message });
    } finally {
      if (screenGeneration.current(generation)) screenTimer = window.setTimeout(poll, document.hidden ? 10000 : 2000);
    }
  }
  screenTimer = window.setTimeout(poll, document.hidden ? 10000 : 2000);
}

function row(label, value, ok) {
  const term = document.createElement("dt");
  term.textContent = label;
  const data = document.createElement("dd");
  data.textContent = value;
  if (ok === true) data.className = "ok";
  if (ok === false) data.className = "warn";
  return [term, data];
}

async function getJson(url) {
  const response = await fetch(url, { headers: { "X-Pane-Token": await paneToken() } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Pane-Token": await paneToken() },
    body: JSON.stringify(payload),
  });
  // CoreDevice acknowledges HID commands with plain text ("ok").
  if (url.startsWith(MIRROR_API + "/")) {
    const message = await response.text();
    if (!response.ok) throw new Error(message || `Phone control failed (${response.status})`);
    return message;
  }
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function mirrorMessage(cmd, extra = {}) {
  if (!screenView.contentWindow || screenView.hidden) return;
  screenView.contentWindow.postMessage({ source: "handset", cmd, ...extra }, window.location.origin);
}

function reloadMirrorIframe() {
  if (screenView.hidden) return;
  const stamp = `t=${Date.now()}`;
  if (screenView.getAttribute("src") !== "about:blank") screenView.src = "about:blank";
  requestAnimationFrame(() => {
    screenView.src = `${MIRROR_PAGE}?${stamp}`;
  });
}

async function restartMirror() {
  restartScreen.disabled = true;
  screenNote.textContent = "Restarting screen… keep the iPhone unlocked.";
  screenNote.className = "";
  try {
    const result = await postJson("/api/screen/restart", { udid: selectedUdid });
    if (result.error) throw new Error(result.error);
    await new Promise((r) => setTimeout(r, 1500));
    reloadMirrorIframe();
    screenNote.textContent = "Restart sent — waiting for picture…";
    window.setTimeout(() => {
      if (workspace.classList.contains("is-live")) {
        screenNote.textContent = "Mirroring — use Restart screen if the picture stays black.";
      }
    }, 4000);
  } catch (error) {
    screenNote.textContent = window.paneNotice(error.message);
    screenNote.className = "warn";
  } finally {
    restartScreen.disabled = false;
  }
}

async function mirrorPost(path, payload) {
  try { await window.paneControl(path, payload); }
  catch (error) { screenNote.textContent = window.paneNotice(error.message); screenNote.className = "warn"; }
}

async function swipe(direction) {
  const yMid = 32768;
  const xStart = direction === "left" ? 60000 : 5000;
  const xEnd = direction === "left" ? 5000 : 60000;
  const steps = 10;
  const dt = 20;
  await mirrorPost("/touch", { type: "contact", x: xStart, y: yMid });
  for (let i = 1; i <= steps; i++) {
    const x = Math.round(xStart + (xEnd - xStart) * (i / steps));
    await new Promise((r) => setTimeout(r, dt));
    await mirrorPost("/touch", { type: "contact", x, y: yMid });
  }
  await mirrorPost("/touch", { type: "release", x: xEnd, y: yMid });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Coordinates are HID units (0..65535). iOS only treats a swipe as a system
// gesture when the contact starts on the very edge of the screen.
const GESTURES = {
  notifications: { from: [16000, 0], to: [16000, 42000], steps: 12, dt: 16 },
  control: { from: [58000, 0], to: [58000, 42000], steps: 12, dt: 16 },
};

// A swipe-up injected over USB is too slow for iOS to treat as the Home
// gesture, so Home and the app switcher use the Home button instead.
let gestureChain = Promise.resolve();
function queueGesture(name) {
  gestureChain = gestureChain.then(async () => {
    if (workspace.classList.contains("is-live")) await gesture(name);
  }).catch(error => {
    screenNote.textContent = window.paneNotice(error.message);
    screenNote.className = "warn";
  });
  return gestureChain;
}

async function pressHome(times) {
  for (let i = 0; i < times; i++) {
    if (i) await sleep(120);
    await window.paneControl("/button", { name: "home", state: "press" });
  }
}

async function gesture(name) {
  if (name === "siri") {
    return window.paneControl("/button", { name: "siri", state: "press" });
  }
  if (name === "home") return pressHome(1);
  if (name === "switcher") return pressHome(2);
  const g = GESTURES[name];
  if (!g) return;
  const [x0, y0] = g.from;
  const [x1, y1] = g.to;
  try {
    await window.paneControl("/touch", { type: "contact", x: x0, y: y0 });
    for (let i = 1; i <= g.steps; i++) {
      await sleep(g.dt);
      const t = i / g.steps;
      await window.paneControl("/touch", {
        type: "contact", x: Math.round(x0 + (x1 - x0) * t), y: Math.round(y0 + (y1 - y0) * t),
      });
    }
  } finally {
    await window.paneControl("/touch", { type: "release", x: x1, y: y1 });
  }
}

function toggleFullscreen() {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
    return;
  }
  phoneScreen.requestFullscreen?.().catch(() => {});
}

window.handsetKeyboardOn = true;

function setKeyboard(on) {
  window.handsetKeyboardOn = on;
  kbToggle.setAttribute("aria-pressed", String(on));
  kbToggle.textContent = `⌨ Keyboard → iPhone: ${on ? "On" : "Off"}`;
  kbToggle.classList.toggle("is-on", on);
  if (!on) keyboard.releaseAll();
}

const keyboard = window.HandsetKeys.attach({
  post: (payload) => mirrorPost("/key", payload),
  enabled: () => window.handsetKeyboardOn && workspace.classList.contains("is-live") && !document.body.classList.contains("drawer-open") && !document.body.classList.contains("onboarding-open") && !document.body.classList.contains("tour-open") && !document.querySelector("dialog[open]"),
});

function wireRemoteControls() {
  kbToggle.addEventListener("click", () => setKeyboard(!window.handsetKeyboardOn));
  setKeyboard(true);
  // A focused button would swallow Space and Enter instead of typing them.
  document.addEventListener("pointerup", (e) => {
    const btn = e.target.closest?.("button");
    if (btn) btn.blur();
  });
  document.querySelectorAll("[data-gesture]").forEach((btn) => {
    if (btn.dataset.gesture !== "home") {
      btn.addEventListener("click", () => queueGesture(btn.dataset.gesture));
      return;
    }
    let holdTimer, suppressClick = false;
    const cancelHold = () => { clearTimeout(holdTimer); holdTimer = null; };
    btn.addEventListener("pointerdown", event => {
      if (event.button !== 0 || btn.disabled) return;
      cancelHold(); suppressClick = false;
      btn.setPointerCapture(event.pointerId);
      holdTimer = setTimeout(() => {
        holdTimer = null; suppressClick = true;
        queueGesture("siri");
      }, 600);
    });
    btn.addEventListener("pointerup", cancelHold);
    btn.addEventListener("pointermove", event => {
      if (!holdTimer) return;
      const r = btn.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) {
        cancelHold(); suppressClick = true;
      }
    });
    for (const type of ["pointercancel", "lostpointercapture"]) btn.addEventListener(type, cancelHold);
    window.addEventListener("blur", cancelHold);
    btn.addEventListener("click", event => {
      if (event.detail === 0 || !suppressClick) queueGesture("home");
      suppressClick = false;
    });
  });
  document.querySelector("#fullscreen")?.addEventListener("click", toggleFullscreen);
  document.querySelector("#fs-exit")?.addEventListener("click", toggleFullscreen);
  document.addEventListener("fullscreenchange", () => {
    const btn = document.querySelector("#fullscreen");
    if (btn) btn.textContent = document.fullscreenElement ? "Exit full screen" : "⛶ Full screen";
  });
  document.querySelectorAll("[data-btn]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.btn;
      if (name) mirrorPost("/button", { name, state: "press" });
    });
  });
  const volumeWheel=window.createPaneVolumeWheel(name=>mirrorPost('/button',{name,state:'press'}));
  document.querySelectorAll('.rail-navigation [data-btn^="volume-"]').forEach(button=>{
    button.dataset.tip='Scroll up for louder, down for quieter';
    button.addEventListener('wheel',event=>{
      if(button.disabled || !Number.isFinite(event.deltaY) || event.ctrlKey)return;
      event.preventDefault();event.stopPropagation();
      volumeWheel(event.deltaY,event.deltaMode).catch(()=>{});
    },{passive:false});
  });
  document.querySelectorAll("[data-swipe]").forEach((btn) => {
    btn.addEventListener("click", () => swipe(btn.dataset.swipe));
  });
  document.querySelector("#zoom-in")?.addEventListener("click", () => mirrorMessage("zoom-in"));
  document.querySelector("#zoom-out")?.addEventListener("click", () => mirrorMessage("zoom-out"));
  document.querySelector("#zoom-reset")?.addEventListener("click", () => mirrorMessage("zoom-reset"));
  document.querySelector("#rotate-cw")?.addEventListener("click", () => mirrorMessage("rotate", { deg: 90 }));
  document.querySelector("#rotate-ccw")?.addEventListener("click", () => mirrorMessage("rotate", { deg: -90 }));
}

load();
watchScreen();
