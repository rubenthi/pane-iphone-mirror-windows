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
const ctx = canvas.getContext("2d");
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
let nativeDisplaySize = null;
let frameCount = 0;
let frameStats = new PaneFrameStats();
let decodeDepth = 0;
function displayTarget() {
  const target = Number(localStorage.getItem('pane-display-fps'));
  return [15, 30, 60].includes(target) ? target : 60;
}
let frameInterval = 1000 / displayTarget();
let nextPaint = 0;
window.addEventListener('storage', event => {
  if (event.key === 'pane-display-fps') {
    frameInterval = 1000 / displayTarget();
    nextPaint = 0;
  }
});
let runGeneration = 0;
let abortStream = null;
setInterval(() => {
  const sample = frameStats.sample(canvas.width, canvas.height, decodeDepth);
  if (sample) window.parent.postMessage(sample, location.origin);
}, 1000);

function setStatus(text, tone) {
  if (!statusEl) return;
  if(tone === "warn") text = window.parent.paneNotice ? window.parent.paneNotice(text) : "Connection lost. Reconnect your iPhone.";
  if (statusEl.textContent === text && statusEl.dataset.tone === String(tone)) return;
  statusEl.dataset.tone = String(tone);
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
  // Fill the symmetric bezel opening. Integer native bounds can differ from
  // the video's aspect by a fraction of a pixel; contain leaves black bands.
  // Cover preserves proportions and clips only the rounding excess normally.
  const base = Math.max(rect.width / naturalW, rect.height / naturalH);
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
  for (let i = 0; i < times; i++) {
    if (i) await new Promise((r) => setTimeout(r, 120));
    await postJson("/button", { name: "home", state: "press" });
  }
}

function releaseActive(commitEdgeGesture = false) {
  if (activePointer === null) return;
  activePointer = null;
  if (edgeSwipe) {
    const swipe = edgeSwipe;
    edgeSwipe = null;
    if (!commitEdgeGesture) return;
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
  if (e.button !== 0 || wheelBusy || activePointer !== null) return;
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
  releaseActive(true);
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
window.addEventListener("pointercancel", e => {
  if (e.pointerId === activePointer) releaseActive();
});
document.body.addEventListener("lostpointercapture", (e) => {
  if (e.pointerId === activePointer) releaseActive();
});
window.addEventListener("blur", () => releaseActive());
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") releaseActive();
});

document.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  pressHome();
});

window.HandsetKeys.attach({
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

async function fetchCodecWithRetry() {
  const delays = [200, 500, 1000, 2000, 3000, 4000];
  let lastErr = "";
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, delays[attempt - 1]));
    try {
      const resp = await mirrorFetch("/codec", { cache: "no-store" });
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
      const geometry=PaneHEVC.dimensions(description);
      let displaySize=null;
      try {
        const response=await fetch('/api/screen',{
          cache:'no-store',headers:{'X-Pane-Token':await paneToken()},signal:AbortSignal.timeout(2000)
        });
        if(response.ok)displaySize=(await response.json()).displaySize;
      } catch (_) { /* Missing metadata must not prevent a full-frame stream. */ }
      return { codec: info.codec.trim(), description, geometry, displaySize };
    } catch (err) {
      lastErr = err.message || String(err);
    }
  }
  throw new Error(lastErr || "codec unreachable");
}

function drawFrame(f) {
  const sideways = Math.abs(visualRotation % 180) === 90;
  const aperture=PaneDisplayAperture(f.displayWidth,f.displayHeight,nativeDisplaySize);
  const fw = aperture.width;
  const fh = aperture.height;
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
  ctx.drawImage(f, 0, 0, fw, fh, -fpW / 2, -fpH / 2, fpW, fpH);
  ctx.restore();
}

function drawPending(now) {
  if (pendingFrame && now + 0.75 < nextPaint) {
    requestAnimationFrame(drawPending);
    return;
  }
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
    // Carry a fractional refresh interval forward without catch-up draws.
    nextPaint = Math.max(now, nextPaint) + frameInterval;
    if (nextPaint - now > frameInterval + 0.75) nextPaint = now + frameInterval;
    frameStats.presented++;
    if (frameCount > 0) setStatus("Live", "ok");
  } catch (_) {}
  if (lastFrame && lastFrame !== f) {
    try {
      lastFrame.close();
    } catch (_) {}
  }
  lastFrame = f;
}

async function run(generation) {
  setStatus("Connecting to stream…");
  frameCount = 0;
  frameStats = new PaneFrameStats();
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

  const { codec, description, geometry, displaySize } = await fetchCodecWithRetry();
  if (generation !== runGeneration) return;
  nativeDisplaySize=displaySize??null;

  let decoderConfig = { codec, description, codedWidth: geometry.width, codedHeight: geometry.height, optimizeForLatency: true, hardwareAcceleration: 'prefer-hardware' };
  let support = await VideoDecoder.isConfigSupported(decoderConfig);
  if (!support.supported) {
    decoderConfig = {...decoderConfig, hardwareAcceleration:'no-preference'};
    support = await VideoDecoder.isConfigSupported(decoderConfig);
  }
  if (!support.supported) {
    setStatus("This browser cannot decode the iPhone video stream.", "warn");
    return;
  }

  let needsResync = false;
  let autoRestartUsed = false;

  const buildDecoder = () =>
    new VideoDecoder({
      output: (frame) => {
        if (generation !== runGeneration) { frame.close(); return; }
        if (pendingFrame) {
          try {
            pendingFrame.close();
            frameStats.skipped++;
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
        needsResync = true;
        if (!autoRestartUsed && frameCount < 5) {
          autoRestartUsed = true;
          mirrorFetch("/restart", { method: "POST", cache: "no-store" }).catch(() => {});
        } else {
          mirrorFetch("/pli", { method: "POST", cache: "no-store" }).catch(() => {});
        }
      },
    });

  let decoder = buildDecoder();
  decoder.configure(decoderConfig);
  setStatus("Waiting for video…");

  try {
  let resp = null;
  const streamDelays = [300, 600, 1200, 2000, 3000, 5000, 8000];
  for (let a = 0; a <= streamDelays.length; a++) {
    if (generation !== runGeneration) return;
    if (a > 0) {
      setStatus(`Waiting for video stream (retry ${a})…`);
      await new Promise((r) => setTimeout(r, streamDelays[a - 1]));
      if (a === 2) {
        await mirrorFetch("/pli", { method: "POST", cache: "no-store" }).catch(() => {});
      }
    }
    try {
      const r = await mirrorFetch("/stream.bin", { cache: "no-store" });
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
      setStatus(err.message || "Stream unreachable", "warn");
    }
  }
  if (!resp || generation !== runGeneration) {
    setStatus("Cannot reach the video stream. Press Restart screen.", "warn");
    return;
  }

  const reader = resp.body.getReader();
  abortStream = () => reader.cancel().catch(() => {});
  const packets = new PanePackets();
  let lastBacklogRecovery = -Infinity;
  let timestamp = 0;
  let gotKey = false;

  while (generation === runGeneration) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const {type, data} of packets.push(value)) {
      frameStats.received++;
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
      if (!gotKey || needsResync) continue;
      if (decoder.state !== "configured") {
        try {
          decoder.close();
        } catch (_) {}
        decoder = buildDecoder();
        decoder.configure(decoderConfig);
        needsResync = true;
        continue;
      }
      decodeDepth = decoder.decodeQueueSize;
      if (decodeDepth > 6) {
        // Drop a stale dependency chain as a unit; resume only at a clean key.
        // Keep interactive latency bounded without feeding broken delta frames.
        needsResync = true;
        if (performance.now()-lastBacklogRecovery > 1000) {
          lastBacklogRecovery = performance.now();
          mirrorFetch('/pli', {method:'POST',cache:'no-store'}).catch(()=>{});
        }
        continue;
      }
      try {
        decoder.decode(
          new EncodedVideoChunk({
            type: type === 0 || type === 2 ? "key" : "delta",
            timestamp: timestamp = Math.max(timestamp + 1, Math.round(performance.now() * 1000)),
            data,
          }),
        );
      } catch (_) {
        needsResync = true;
      }
    }
  }
  } finally {
    if (decoder.state !== "closed") decoder.close();
  }
  if (generation === runGeneration) {
    setStatus("Stream ended — press Restart screen", "warn");
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
  run(generation).catch((err) => {
    setStatus(err.message || "Mirror failed", "warn");
  });
}

beginRun();
