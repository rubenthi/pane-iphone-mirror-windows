(() => {
  const $ = (id) => document.getElementById(id);
  let prefs = {},
    devices = { audio: [], notifications: [] },
    tour = 0;
  let companionState = {};
  let preferencesLoaded = false;
  let notificationSetupGeneration = 0;
  function iphoneCandidates() {
    return [...new Map((devices.notifications||[]).filter(d=>d&&typeof d.id==='string'&&d.id.trim()&&d.id.length<=2048&&!/[\x00-\x1f]/.test(d.id)&&typeof d.name==='string'&&/iphone/i.test(d.name)&&!/^pane-/i.test(d.name.trim())).map(d=>[d.id,d])).values()];
  }
  function notificationPatch() {
    const patch={notifications_enabled:true}, phones=iphoneCandidates();
    if(preferencesLoaded&&!prefs.notification_device_id&&phones.length===1)patch.notification_device_id=phones[0].id;
    return patch;
  }
  function renderNotificationSetup() {
    const enabled=!!prefs.notifications_enabled, phase=companionState.notificationPhase;
    const ready=enabled&&phase==='ready', phones=iphoneCandidates();
    const selected=(devices.notifications||[]).find(d=>d.id===prefs.notification_device_id);
    $('notifications-toggle-hint').textContent=enabled?(ready?'On':'Setting up…'):'Off';
    const detail=$('notification-setup-help');
    detail.hidden=ready;
    detail.dataset.expanded=String(enabled&&!ready);
    detail.querySelector('.action-summary').hidden=enabled&&!ready;
    detail.querySelector('.action-summary').textContent=ready?'Ready. iPhone alerts will appear here.':'Turn on to get iPhone alerts here.';
    detail.querySelector('.action-expanded').hidden=!enabled||ready;
    $('notification-phone-steps').hidden=phase==='needs_windows_permission';
    $('notification-windows-help').hidden=phase!=='needs_windows_permission';
    $('notification-pc-name').textContent=companionState.computerName||'This PC';
    $('notification-device-field').hidden=!enabled||(phones.length===1&&phones[0].id===prefs.notification_device_id);
    $('notification-selected-phone').hidden=!enabled||ready||!prefs.notification_device_id||!$('notification-device-field').hidden;
    $('notification-selected-phone').textContent=selected?`${selected.name} selected`:'Saved iPhone';
    $('notification-actions').hidden=!enabled||ready;
    $('notification-pair').hidden=!!prefs.notification_device_id;
    $('notification-options').hidden=!enabled;
    const descriptions={off:'',ready:'Connected',needs_device:'Choose your iPhone, or pair it first.',connecting:'Connecting…',needs_permission:'Allow sharing on your iPhone.',needs_windows_permission:'Allow notifications for Pane in Windows.',error:'Connection paused. Check again.',unavailable:'Use the Windows app to receive alerts.'};
    $('notifications-note').textContent=descriptions[enabled?phase:'off']??(enabled?'Allow sharing on your iPhone.':'');
    $('notifications-note').dataset.phase=enabled?phase||'connecting':'off';
  }
  const tours = [
    [
      "Your iPhone. Your mouse.",
      "Click to tap, drag to swipe, and type with your keyboard. Right-click for Home.",
      '<div class="mini-phone"><svg viewBox="0 0 40 40"><path d="M12 7v25l6-7 6 11 5-3-6-10 10-2z"/></svg></div><div class="mini-bubble">Click. Swipe. Type.<span>All in the phone window.</span></div>',
    ],
    [
      "A little room to move.",
      "Drag the three bars to move Pane. Resize from a corner, or open the window controls to pin it.",
      '<div class="mini-phone"></div><div class="mini-bubble">≡<span>One place for window controls.</span></div>',
    ],
    [
      "Stay connected, your way.",
      "Send files in Uploads. Choose audio and notifications in Settings, and enable background mode to keep alerts after closing Pane.",
      '<div class="mini-phone"><svg viewBox="0 0 40 40"><path d="M12 28h16l-3-5v-7a5 5 0 0 0-10 0v7zM18 33h4"/></svg></div><div class="mini-bubble">You choose.<span>Audio, alerts and background mode.</span></div>',
    ],
  ];
  function open(name) {
    $("settings-tab").click();
    if (name === "audio" || name === "notifications") refreshBluetooth();
    $("settings-home").hidden = true;
    document
      .querySelectorAll(".settings-page")
      .forEach((p) => (p.hidden = p.id !== `settings-${name}`));
    $("run-guide").hidden = false;
    $("toggle-guide").setAttribute("aria-expanded", String(name === "setup"));
    document.querySelector(".drawer-scroll").scrollTop = 0;
  }
  function home() {
    $("settings-home").hidden = false;
    document
      .querySelectorAll(".settings-page")
      .forEach((p) => (p.hidden = true));
  }
  $("settings-tab").addEventListener("click", home);
  document.querySelector('.preferences-heading h2').textContent='Settings';
  const settingsIcons={notifications:['bell','coral'],audio:['volume','violet'],display:['phone','blue'],setup:['settings','gray'],details:['wifi','green'],help:['alert','blue']};
  document.querySelectorAll('.settings-links > button').forEach(row=>{
    const [icon,color]=settingsIcons[row.dataset.settings] || ['play','blue'];
    const label=document.createElement('span');label.className='settings-row-label';
    label.textContent=row.firstChild.textContent;
    const badge=document.createElement('span');badge.className='settings-row-icon '+color;badge.append(window.paneIcon(icon));
    row.replaceChildren(badge,label,window.paneIcon('chevron'));
  });
  document.querySelectorAll('[data-settings-back]').forEach(button=>{button.setAttribute('aria-label','Back to Settings');button.textContent='‹ Settings';});
  document
    .querySelectorAll("[data-settings]")
    .forEach((x) =>
      x.addEventListener("click", () => open(x.dataset.settings)),
    );
  document
    .querySelectorAll("[data-settings-back]")
    .forEach((x) => x.addEventListener("click", home));
  let previousFocus;
  function showTour() {
    if ($("feature-tour").hidden) previousFocus = document.activeElement;
    const t = tours[tour];
    $("feature-tour").hidden = false;
    document.body.classList.add("tour-open");
    keyboard.releaseAll();
    $("tour-title").textContent = t[0];
    $("tour-copy").textContent = t[1];
    $("tour-art").innerHTML = t[2];
    $("tour-progress").textContent = `${tour + 1} of ${tours.length}`;
    $("tour-back").disabled = tour === 0;
    $("tour-next").textContent =
      tour === tours.length - 1 ? "Start using Pane" : "Next";
    $("tour-next").focus({ preventScroll: true });
  }
  async function finishTour() {
    await save({ tour_complete: true });
    $("feature-tour").hidden = true;
    document.body.classList.remove("tour-open");
    previousFocus?.focus({ preventScroll: true });
  }
  document.querySelectorAll("[data-show-tour]").forEach((x) =>
    x.addEventListener("click", () => {
      tour = 0;
      showTour();
    }),
  );
  $("tour-back").addEventListener("click", () => {
    tour--;
    showTour();
  });
  $("tour-next").addEventListener("click", () => {
    if (tour === tours.length - 1) finishTour();
    else {
      tour++;
      showTour();
    }
  });
  $("tour-skip").addEventListener("click", finishTour);
  $("feature-tour").addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const buttons = [
      ...$("feature-tour").querySelectorAll("button:not(:disabled)"),
    ];
    const index = buttons.indexOf(document.activeElement);
    e.preventDefault();
    buttons[
      (index + (e.shiftKey ? buttons.length - 1 : 1)) % buttons.length
    ].focus();
  });
  window.addEventListener("pane-setup-complete", async () => {
    await ready;
    if (!prefs.tour_complete) {
      tour = 0;
      showTour();
    }
  });
  window.paneView = { open };
  function renderPreferences() {
    $("previews-toggle-hint").textContent = prefs.show_previews
      ? "Titles and messages appear on this PC."
      : "Keep content private when this is off.";
    $("background-hint").textContent = prefs.background_enabled
      ? prefs.notifications_enabled
        ? "Notifications continue after closing Pane."
        : "Phone notifications must also be enabled."
      : "Optional. Keep alerts on after closing Pane.";
    $("background-next").hidden =
      !prefs.background_enabled || !!prefs.notifications_enabled;
    for (const [id, key] of [
      ["audio-setup-help", "audio_enabled"],
    ]) {
      const detail = $(id),
        expanded = !!prefs[key];
      detail.dataset.expanded = String(expanded);
      detail.querySelector(".action-summary").hidden = expanded;
      detail.querySelector(".action-expanded").hidden = !expanded;
    }
    for (const [id, key] of [
      ["background-enabled", "background_enabled"],
      ["notifications-enabled", "notifications_enabled"],
      ["notification-previews", "show_previews"],
      ["audio-enabled", "audio_enabled"],
    ])
      $(id).checked = !!prefs[key];
    document
      .querySelectorAll("#notification-types input")
      .forEach((x) => (x.checked = (prefs.categories || []).includes(x.value)));
    for (const [id, key, kind] of [
      ["audio-device", "audio_device_id", "audio"],
      ["notification-device", "notification_device_id", "notifications"],
    ]) {
      const select = $(id);
      select.replaceChildren(new Option("Choose iPhone", ""));
      const list = devices[kind] || [];
      list.forEach((d) => select.add(new Option(d.name, d.id)));
      if (prefs[key] && !list.some((x) => x.id === prefs[key]))
        select.add(
          new Option("Saved iPhone (not currently found)", prefs[key]),
        );
      select.value = prefs[key] || "";
    }
    window.paneSelects?.sync();
    renderNotificationSetup();
  }
  // Preference writes are ordered. A quick second change cannot resurrect stale state.
  let saveChain = Promise.resolve();
  function save(patch) {
    saveChain = saveChain.then(async () => {
      try {
        const state = await postJson("/api/preferences", patch);
        prefs = state.preferences;
        preferencesLoaded = true;
        renderPreferences();
        renderCompanion(state.companion);
        $("preferences-note").textContent = "Saved";
      } catch (e) {
        $("preferences-note").textContent = window.paneNotice(e.message,'preferences');
        renderPreferences();
      }
    });
    return saveChain;
  }
  for (const [id, key] of [
    ["background-enabled", "background_enabled"],
    ["notification-previews", "show_previews"],
    ["audio-enabled", "audio_enabled"],
    ["audio-device", "audio_device_id"],
    ["notification-device", "notification_device_id"],
  ]) {
    $(id).addEventListener("change", (e) =>
      save({
        [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value,
      }),
    );
  }
  $('notifications-enabled').addEventListener('change',event=>{
    notificationSetupGeneration++;
    save(event.target.checked?notificationPatch():{notifications_enabled:false});
  });
  $('notification-pair').addEventListener('click',()=>postJson('/api/bluetooth/settings',{}).catch(()=>{$('notifications-note').textContent='Couldn’t open Bluetooth settings. Try again.';}));
  $('notification-windows-settings').addEventListener('click',()=>postJson('/api/notifications/settings',{}).catch(()=>{$('notifications-note').textContent='Couldn’t open notification settings. Try again.';}));
  $('notifications-check').addEventListener('click',async()=>{
    const generation=notificationSetupGeneration;
    $('notifications-check').disabled=true;
    try { await refreshBluetooth(); if(generation===notificationSetupGeneration&&prefs.notifications_enabled&&$('notifications-enabled').checked)await save(notificationPatch()); }
    finally { $('notifications-check').disabled=false; }
  });
  document.querySelectorAll("#notification-types input").forEach((x) =>
    x.addEventListener("change", () =>
      save({
        categories: [
          ...document.querySelectorAll("#notification-types input:checked"),
        ].map((x) => x.value),
      }),
    ),
  );
  function renderCompanion(state = {}) {
    companionState=state;
    renderNotificationSetup();
    $("audio-note").textContent =
      window.paneBluetoothNote(state.audio) ||
      (state.available
        ? ""
        : "Bluetooth audio is available in the Windows release.");
  }
  async function refreshBluetooth() {
    $("bluetooth-refresh").disabled = true;
    try {
      devices = await getJson("/api/bluetooth/devices");
      renderPreferences();
      if (devices.error) $("audio-note").textContent = window.paneNotice(devices.error,'bluetooth');
    } catch (e) {
      $("audio-note").textContent = window.paneNotice(e.message,'preferences');
    } finally {
      $("bluetooth-refresh").disabled = false;
    }
  }
  $("bluetooth-refresh").addEventListener("click", refreshBluetooth);
  $("bluetooth-settings").addEventListener("click", () =>
    postJson("/api/bluetooth/settings", {}).catch(
      (e) => ($("audio-note").textContent = window.paneNotice(e.message,'bluetooth')),
    ),
  );
  const ready = getJson("/api/preferences")
    .then((state) => {
      prefs = state.preferences;
      preferencesLoaded = true;
      renderPreferences();
      renderCompanion(state.companion);
      return prefs;
    })
    .catch((e) => {
      $("preferences-note").textContent = window.paneNotice(e.message,'preferences');
      prefs = { tour_complete: true };
      return prefs;
    });
  window.paneExperience = { ready, renderCompanion };
  // Only ambiguous icon controls and actually truncated filenames need tips.
  const essentialTips = '.rail-grip,#drawer-toggle,#refresh,#pin-window,[data-gesture="switcher"],[data-gesture="control"]';
  const tipTargets = `${essentialTips},.transfer strong`;
  function pruneTitles(root) {
    const titled = [...(root.matches?.('[title]') ? [root] : []), ...(root.querySelectorAll?.('[title]') || [])];
    for (const el of titled) {
      if (el.tagName === 'IFRAME') continue; // Keep its accessible document name.
      if (el.matches(tipTargets)) el.dataset.tip = el.getAttribute('title');
      else delete el.dataset.tip;
      el.removeAttribute('title');
    }
  }
  pruneTitles(document);
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes') pruneTitles(record.target);
      else for (const node of record.addedNodes) if (node.nodeType === 1) pruneTitles(node);
    }
  }).observe(document.body, {subtree:true,childList:true,attributes:true,attributeFilter:['title']});
  const tip = $("pane-tooltip");
  let current = null,
    timer;
  function hide() {
    clearTimeout(timer);
    tip.hidden = true;
    if (current) {
      const ids = (current.getAttribute("aria-describedby") || "")
        .split(/\s+/)
        .filter((id) => id && id !== "pane-tooltip");
      if (ids.length) current.setAttribute("aria-describedby", ids.join(" "));
      else current.removeAttribute("aria-describedby");
    }
    current = null;
  }
  function show(target) {
    const el = target?.closest?.(tipTargets);
    if (!el || el === current) return;
    hide();
    if (el.disabled || (el.matches('.transfer strong') && el.scrollWidth <= el.clientWidth)) return;
    if (
      el.getAttribute("role") === "combobox" &&
      el.getAttribute("aria-expanded") === "true"
    )
      return;
    const text =
      el.getAttribute("title") ||
      el.dataset.tip ||
      el.getAttribute("aria-label") ||
      el.labels?.[0]?.textContent.trim() ||
      el.textContent.trim();
    if (!text) return;
    el.dataset.tip = text;
    el.removeAttribute("title");
    current = el;
    timer = setTimeout(() => {
      if (current !== el) return;
      tip.textContent = text;
      tip.hidden = false;
      el.setAttribute(
        "aria-describedby",
        [
          ...new Set([
            ...(el.getAttribute("aria-describedby") || "")
              .split(/\s+/)
              .filter(Boolean),
            "pane-tooltip",
          ]),
        ].join(" "),
      );
      const r = el.getBoundingClientRect(),
        phone = $("phone-shell").getBoundingClientRect(),
        drawer = $("connection-drawer").getBoundingClientRect();
      const bounds = el.closest(".drawer") ? drawer : phone;
      const scale =
        parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
      tip.style.maxWidth = `${Math.max(60, Math.min(226, (bounds.width - 16) / scale))}px`;
      const size = tip.getBoundingClientRect();
      tip.style.left = `${Math.max(bounds.left + 8, Math.min(r.left, bounds.right - size.width - 8)) / scale}px`;
      tip.style.top = `${Math.max(bounds.top + 8, Math.min(r.bottom + 8, bounds.bottom - size.height - 12, window.innerHeight - size.height - 12)) / scale}px`;
    }, 650);
  }
  document.addEventListener("pointerover", (e) => show(e.target));
  document.addEventListener("pointerout", (e) => {
    if (current && !current.contains(e.relatedTarget)) hide();
  });
  document.addEventListener("focusin", (e) => show(e.target));
  document.addEventListener("focusout", hide);
  document.addEventListener("pointerdown", hide);
  document.addEventListener("pane-select-open", hide);
  document.addEventListener(
    "keydown",
    (e) => {
      if (
        e.key === "Escape" &&
        !tip.hidden &&
        document.querySelector("#pane-select-menu")?.hidden !== false
      ) {
        hide();
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true,
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide();
  });
  document
    .querySelector(".drawer-scroll")
    .addEventListener("scroll", hide, { passive: true });
})();
