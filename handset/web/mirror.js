const MIRROR = "/mirror";

// Mirroring runs in its own iframe and obtains its own same-origin request token.
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

async function mirrorFetch(path, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("X-Pane-Token", await paneToken());
  return fetch(`${MIRROR}${path}`, { ...options, headers });
}
const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d", { alpha: false });
const statusEl = document.getElementById("mirror-status");

let visualRotation = 0;
let zoom = 1;
const ZOOM_STEP = 1.2;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;

let pendingFrame = null;
let rafScheduled = false;
let lastFrame = null;
let lastFrameLandscape = null;
let frameCount = 0;
let runGeneration = 0;
let abortStream = null;

let previousStatus = "";
function setStatus(text, tone) {
  if (!statusEl || previousStatus === `${tone}:${text}`) return;
  previousStatus = `${tone}:${text}`;
  window.parent.postMessage({source:"pane-stream-status",text,tone},location.origin);
  statusEl.textContent = text;
  statusEl.className = "mirror-status" + (tone ? ` ${tone}` : "");
}

function fitCanvas() {
  if (!canvas.width || !canvas.height) return;
  const parent = canvas.parentElement;
  if (!parent) return;
  const rect = parent.getBoundingClientRect();
  const naturalW = canvas.width;
  const naturalH = canvas.height;
  const base = Math.min(rect.width / naturalW, rect.height / naturalH);
  const scale = base * zoom;
  canvas.style.width = `${naturalW * scale}px`;
  canvas.style.height = `${naturalH * scale}px`;
}

window.addEventListener("resize", fitCanvas);

function setZoom(value) {
  zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, value));
  if (Math.abs(zoom - 1) < 0.02) zoom = 1;
  fitCanvas();
}

function touchCoords(e) {
  const rect = canvas.getBoundingClientRect();
  const sx = ((e.clientX - rect.left) * canvas.width) / rect.width;
  const sy = ((e.clientY - rect.top) * canvas.height) / rect.height;
  const cw = canvas.width;
  const ch = canvas.height;
  const sideways = Math.abs(visualRotation % 180) === 90;
  const dw = sideways ? ch : cw;
  const dh = sideways ? cw : ch;
  const dx = sx - cw / 2;
  const dy = sy - ch / 2;
  const rad = (-visualRotation * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  const bx = dx * cos - dy * sin + dw / 2;
  const by = dx * sin + dy * cos + dh / 2;
  return {
    x: Math.max(0, Math.min(65535, Math.round((bx / dw) * 65535))),
    y: Math.max(0, Math.min(65535, Math.round((by / dh) * 65535))),
  };
}

async function postJson(path, payload) {
  try {
    if (window.parent !== window && window.parent.paneControl) return await window.parent.paneControl(path, payload);
    const response = await mirrorFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Control failed (${response.status})`);
  } catch (error) {
    setStatus(error.message, "warn");
  }
}

let activePointer = null;
let lastCoords = { x: 0, y: 0 };

// The proxy opens one connection per request, so concurrent fetches can land
// out of order and break drags. Send touches strictly in sequence, collapsing
// queued moves into the newest one.
const touchQueue = [];
let touchBusy = false;

function sendTouch(type, coords, isMove = false) {
  const last = touchQueue[touchQueue.length - 1];
  const event = { type, x: coords.x, y: coords.y, isMove };
  if (isMove && last && last.isMove) touchQueue[touchQueue.length - 1] = event;
  else touchQueue.push(event);
  pumpTouches();
}

async function pumpTouches() {
  if (touchBusy) return;
  touchBusy = true;
  while (touchQueue.length) {
    const { type, x, y } = touchQueue.shift();
    await postJson("/touch", { type, x, y });
  }
  touchBusy = false;
}

// iOS system gestures (Home bar, Control Center, Notification Center) only
// trigger when the contact begins on the screen edge itself.
const EDGE = 2500;
function snapToEdge(c) {
  return {
    x: c.x < EDGE ? 0 : c.x > 65535 - EDGE ? 65535 : c.x,
    y: c.y < EDGE ? 0 : c.y > 65535 - EDGE ? 65535 : c.y,
  };
}

// Injected touches arrive too slowly for iOS to read a bottom-edge flick as
// the Home gesture, so a drag that starts on the bottom edge is kept local and
// turned into the Home button (or a double press for the app switcher when
// the finger pauses before lifting).
const HOME_SWIPE_MIN = 5000;
const SWITCHER_HOLD_MS = 450;
let edgeSwipe = null;

async function pressHome(times = 1) {
  window.parent.paneSetTyping?.(false);
  for (let i = 0; i < times; i++) {
    if (i) await new Promise((r) => setTimeout(r, 120));
    await postJson("/button", { name: "home", state: "press" });
  }
}

function releaseActive() {
  if (activePointer === null) return;
  activePointer = null;
  if (edgeSwipe) {
    const swipe = edgeSwipe;
    edgeSwipe = null;
    if (swipe.armed) {
      const paused = performance.now() - swipe.lastMoveAt > SWITCHER_HOLD_MS;
      pressHome(paused ? 2 : 1);
    } else {
      sendTouch("contact", swipe.start);
      sendTouch("release", swipe.start);
    }
    return;
  }
  sendTouch("release", lastCoords);
}

// Listen on the whole document so a drag can start on the black margin just
// below the picture; coordinates clamp onto the screen edge.
document.addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || wheelBusy) return;
  e.preventDefault();
  canvas.focus({ preventScroll: true });
  try {
    document.body.setPointerCapture(e.pointerId);
  } catch (_) {}
  activePointer = e.pointerId;
  lastCoords = snapToEdge(touchCoords(e));
  if (lastCoords.y === 65535) {
    edgeSwipe = { start: lastCoords, armed: false, lastMoveAt: performance.now(), lastY: lastCoords.y };
    return;
  }
  sendTouch("contact", lastCoords);
});

function onMove(e) {
  if (e.pointerId !== activePointer) return;
  e.preventDefault();
  lastCoords = touchCoords(e);
  if (edgeSwipe) {
    if (edgeSwipe.start.y - lastCoords.y > HOME_SWIPE_MIN) edgeSwipe.armed = true;
    if (Math.abs(lastCoords.y - edgeSwipe.lastY) > 600) {
      edgeSwipe.lastMoveAt = performance.now();
      edgeSwipe.lastY = lastCoords.y;
    }
    return;
  }
  sendTouch("contact", lastCoords, true);
}

function onUp(e) {
  if (e.pointerId !== activePointer) return;
  e.preventDefault();
  lastCoords = touchCoords(e);
  releaseActive();
}

// Translate wheel/trackpad movement only on the phone picture into a bounded swipe.
let wheelBusy = false;
let wheelX = 0, wheelY = 0;
let wheelPoint = null;
canvas.addEventListener('wheel', event => {
  event.preventDefault();
  if(activePointer !== null || !lastFrame) return;
  const unit=event.deltaMode===1?16:event.deltaMode===2?canvas.getBoundingClientRect().height:1;
  wheelX=Math.max(-500,Math.min(500,wheelX+event.deltaX*unit));
  wheelY=Math.max(-500,Math.min(500,wheelY+event.deltaY*unit));
  wheelPoint={clientX:event.clientX,clientY:event.clientY};
  if(!wheelBusy) pumpWheel();
},{passive:false});
async function pumpWheel(){
  wheelBusy=true;
  try{
    while(wheelX || wheelY){
      const rect=canvas.getBoundingClientRect();
      const dx=wheelX,dy=wheelY;wheelX=wheelY=0;
      const start={clientX:Math.max(rect.left+rect.width*.2,Math.min(rect.right-rect.width*.2,wheelPoint.clientX)),clientY:Math.max(rect.top+rect.height*.2,Math.min(rect.bottom-rect.height*.2,wheelPoint.clientY))};
      const end={clientX:Math.max(rect.left+1,Math.min(rect.right-1,start.clientX-dx)),clientY:Math.max(rect.top+1,Math.min(rect.bottom-1,start.clientY-dy))};
      let coordinates=touchCoords(start);
      await postJson('/touch',{type:'contact',...coordinates});
      try{for(let i=1;i<=8;i++){
        await new Promise(resolve=>setTimeout(resolve,12));
        coordinates=touchCoords({clientX:start.clientX+(end.clientX-start.clientX)*i/8,clientY:start.clientY+(end.clientY-start.clientY)*i/8});
        await postJson('/touch',{type:'contact',...coordinates});
      }}finally{await postJson('/touch',{type:'release',...coordinates});}
    }
  }finally{wheelBusy=false;}
}

window.addEventListener("pointermove", onMove);
window.addEventListener("pointerup", onUp);
window.addEventListener("pointercancel", onUp);
document.body.addEventListener("lostpointercapture", (e) => {
  if (e.pointerId === activePointer) releaseActive();
});
window.addEventListener("blur", releaseActive);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") releaseActive();
});

document.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  pressHome();
});

const mirrorKeyboard = window.HandsetKeys.attach({
  home: () => pressHome(),
  typing: () => window.parent.paneTyping !== false,
  setTyping: on => window.parent.paneSetTyping?.(on),
  paste: payload => window.parent.panePaste(payload),
  report: error => setStatus(error.message, 'warn'),
  post: (payload) => postJson("/key", payload),
  enabled: () => {
    try {
      return window.parent.handsetKeyboardOn !== false;
    } catch (_) {
      return true;
    }
  },
});

window.addEventListener("message", (e) => {
  if (e.origin !== window.location.origin) return;
  const d = e.data;
  if (!d || d.source !== "handset") return;
  if (d.cmd === "release-keys") { mirrorKeyboard.releaseAll(); return; }
  if (d.cmd === "rotate") {
    visualRotation = (visualRotation + (d.deg || 0)) % 360;
    if (lastFrame) drawFrame(lastFrame);
    fitCanvas();
  } else if (d.cmd === "zoom-in") {
    setZoom(zoom * ZOOM_STEP);
  } else if (d.cmd === "zoom-out") {
    setZoom(zoom / ZOOM_STEP);
  } else if (d.cmd === "zoom-reset") {
    setZoom(1);
  } else if (d.cmd === "reload") {
    beginRun();
  }
});

async function fetchCodecWithRetry(signal) {
  const delays = [200, 500, 1000, 2000, 3000, 4000];
  let lastErr = "";
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, delays[attempt - 1]));
    try {
      signal.throwIfAborted();
      const resp = await mirrorFetch("/codec", { cache: "no-store", signal });
      if (!resp.ok) {
        lastErr = `HTTP ${resp.status}`;
        continue;
      }
      const info = await resp.json();
      if (!info.codec || !info.description) {
        lastErr = "waiting for video parameters";
        continue;
      }
      const description = Uint8Array.from(atob(info.description), (c) => c.charCodeAt(0));
      return { codec: info.codec.trim(), description, geometry: PaneHEVC.dimensions(description) };
    } catch (err) {
      if (signal.aborted) throw err;
      lastErr = err.message || String(err);
    }
  }
  throw new Error(lastErr || "codec unreachable");
}

function drawFrame(f) {
  const sideways = Math.abs(visualRotation % 180) === 90;
  const fw = f.displayWidth;
  const fh = f.displayHeight;
  const targetW = sideways ? fh : fw;
  const targetH = sideways ? fw : fh;
  if (targetW !== canvas.width || targetH !== canvas.height) {
    canvas.width = targetW;
    canvas.height = targetH;
    window.parent.postMessage({source: 'pane-display', width: targetW, height: targetH}, location.origin);
    fitCanvas();
  }
  const dstW = canvas.width;
  const dstH = canvas.height;
  const fpW = sideways ? dstH : dstW;
  const fpH = sideways ? dstW : dstH;
  ctx.save();
  ctx.translate(dstW / 2, dstH / 2);
  if (visualRotation) ctx.rotate((visualRotation * Math.PI) / 180);
  ctx.drawImage(f, -fpW / 2, -fpH / 2, fpW, fpH);
  ctx.restore();
}

function drawPending() {
  rafScheduled = false;
  const f = pendingFrame;
  pendingFrame = null;
  if (!f) return;
  const landscape = f.displayWidth > f.displayHeight;
  if (lastFrameLandscape !== null && landscape !== lastFrameLandscape && visualRotation !== 0) {
    visualRotation = 0;
  }
  lastFrameLandscape = landscape;
  try {
    drawFrame(f);
    if (frameCount > 0) setStatus("Live", "ok");
  } catch (_) {}
  if (lastFrame && lastFrame !== f) {
    try {
      lastFrame.close();
    } catch (_) {}
  }
  lastFrame = f;
}

function waitForDecoder(decoder, signal) {
  if (decoder.decodeQueueSize <= 8) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer);
      decoder.removeEventListener('dequeue', check);
      signal.removeEventListener('abort', abort);
    };
    const check = () => {
      if (decoder.state !== 'configured' || decoder.decodeQueueSize <= 4) { cleanup(); resolve(); }
    };
    const abort = () => { cleanup(); reject(signal.reason); };
    const timer = setTimeout(() => { cleanup(); reject(Error('Video decoder stalled — restart the screen.')); }, 3000);
    decoder.addEventListener('dequeue', check);
    signal.addEventListener('abort', abort, {once:true});
    if (signal.aborted) abort(); else check();
  });
}

async function run(generation, signal) {
  let decoder = null, reader = null;
  setStatus("Connecting to stream…");
  frameCount = 0;
  const startedAt = performance.now();
  const watchdog = window.setInterval(() => {
    if (generation !== runGeneration) {
      window.clearInterval(watchdog);
      return;
    }
    if (frameCount > 0) {
      window.clearInterval(watchdog);
      return;
    }
    if (performance.now() - startedAt > 12000) {
      window.clearInterval(watchdog);
      setStatus("No picture yet — press Restart screen on the right", "warn");
    }
  }, 1000);

  try {
  const { codec, description, geometry } = await fetchCodecWithRetry(signal);
  if (generation !== runGeneration) return;

  let decoderConfig = { codec, description, codedWidth: geometry.width, codedHeight: geometry.height, optimizeForLatency: true };
  let support = await VideoDecoder.isConfigSupported({...decoderConfig, hardwareAcceleration:"prefer-hardware"});
  if (support.supported) decoderConfig = support.config;
  else support = await VideoDecoder.isConfigSupported(decoderConfig);
  if (!support.supported) {
    setStatus("This browser cannot decode the iPhone video stream.", "warn");
    return;
  }

  let needsResync = false;
  let autoRestartUsed = false;

  const buildDecoder = () =>
    new VideoDecoder({
      output: (frame) => {
        if (generation !== runGeneration || signal.aborted) { frame.close(); return; }
        if (pendingFrame) {
          try {
            pendingFrame.close();
          } catch (_) {}
        }
        pendingFrame = frame;
        if (!rafScheduled) {
          rafScheduled = true;
          requestAnimationFrame(drawPending);
        }
        frameCount += 1;
      },
      error: () => {
        if (generation !== runGeneration || signal.aborted) return;
        needsResync = true;
        if (!autoRestartUsed && frameCount < 5) {
          autoRestartUsed = true;
          mirrorFetch("/restart", { method: "POST", cache: "no-store" }).catch(() => {});
        } else {
          mirrorFetch("/pli", { method: "POST", cache: "no-store" }).catch(() => {});
        }
      },
    });

  decoder = buildDecoder();
  decoder.configure(decoderConfig);
  setStatus("Waiting for video…");

  let resp = null;
  const streamDelays = [300, 600, 1200, 2000, 3000, 5000, 8000];
  for (let a = 0; a <= streamDelays.length; a++) {
    if (generation !== runGeneration) return;
    if (a > 0) {
      setStatus(`Waiting for video stream (retry ${a})…`);
      await new Promise((r) => setTimeout(r, streamDelays[a - 1]));
      signal.throwIfAborted();
      if (generation !== runGeneration) return;
      if (a === 2) {
        await mirrorFetch("/pli", { method: "POST", cache: "no-store" }).catch(() => {});
      }
    }
    try {
      const r = await mirrorFetch("/stream.bin", { cache: "no-store", signal });
      if (r.ok) {
        resp = r;
        break;
      }
      if (r.status === 503) {
        setStatus("Stream starting on the iPhone…");
        continue;
      }
      setStatus(`Stream error (HTTP ${r.status})`, "warn");
    } catch (err) {
      if (signal.aborted) throw err;
      setStatus(err.message || "Stream unreachable", "warn");
    }
  }
  if (!resp || generation !== runGeneration) {
    setStatus("Cannot reach the video stream. Press Restart screen.", "warn");
    return;
  }

  reader = resp.body.getReader();
  const packets = new PanePacketReader();
  let timestamp = 0;
  let gotKey = false;

  while (generation === runGeneration) {
    await waitForDecoder(decoder, signal);
    signal.throwIfAborted();
    const { value, done } = await reader.read();
    if (done) break;
    packets.push(value, packet => {
      const type = packet[0];
      if (type > 2) throw Error('Invalid video packet type');
      const data = packet.subarray(1);

      const updated = PaneHEVC.update(decoderConfig.description, data);
      if (updated) {
        const size = PaneHEVC.dimensions(updated);
        decoderConfig = {...decoderConfig, description:updated, codedWidth:size.width, codedHeight:size.height};
        needsResync = true;
      }

      if (type === 2) {
        try {
          decoder.close();
        } catch (_) {}
        decoder = buildDecoder();
        decoder.configure(decoderConfig);
        needsResync = false;
        gotKey = true;
      } else if (type === 0) {
        gotKey = true;
        if (needsResync) {
          try {
            decoder.close();
          } catch (_) {}
          decoder = buildDecoder();
          decoder.configure(decoderConfig);
          needsResync = false;
        }
      }
      if (!gotKey || needsResync) return;
      if (decoder.state !== "configured") {
        try {
          decoder.close();
        } catch (_) {}
        decoder = buildDecoder();
        decoder.configure(decoderConfig);
        needsResync = true;
        return;
      }
      try {
        decoder.decode(
          new EncodedVideoChunk({
            type: type === 0 || type === 2 ? "key" : "delta",
            timestamp,
            data,
          }),
        );
        timestamp += 16666;
      } catch (_) {
        needsResync = true;
      }
    });
  }
  packets.finish();
  if (generation === runGeneration) {
    setStatus("Stream ended — press Restart screen", "warn");
  }
  } finally {
    window.clearInterval(watchdog);
    if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    if (decoder && decoder.state !== "closed") decoder.close();
  }
}

function beginRun() {
  runGeneration += 1;
  const generation = runGeneration;
  if (abortStream) {
    abortStream();
    abortStream = null;
  }
  if (pendingFrame) {
    try {
      pendingFrame.close();
    } catch (_) {}
    pendingFrame = null;
  }
  if (lastFrame) {
    try {
      lastFrame.close();
    } catch (_) {}
    lastFrame = null;
  }
  frameCount = 0;
  const controller = new AbortController();
  abortStream = () => controller.abort();
  run(generation, controller.signal).catch((err) => {
    if (generation === runGeneration && !controller.signal.aborted)
      setStatus(err.message || "Mirror failed", "warn");
  });
}

window.addEventListener("pagehide", () => {
  runGeneration++;
  abortStream?.();
  pendingFrame?.close(); pendingFrame = null;
  lastFrame?.close(); lastFrame = null;
});
beginRun();
