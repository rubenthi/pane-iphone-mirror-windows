const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const assert = require("node:assert/strict");
const fs = require("node:fs");
(async () => {
  const child = spawn(
    process.env.PANE_TEST_PYTHON || "python3",
    ["tests/browser_preview.py"],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  let browser,
    logs = "";
  child.stderr.on("data", (d) => (logs += d));
  try {
    const url = await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(logs || "Preview timeout")),
        10000,
      );
      child.stdout.once("data", (d) => {
        clearTimeout(timer);
        resolve(d.toString().trim().split(" ").at(-1));
      });
      child.once("exit", () => {
        clearTimeout(timer);
        reject(new Error(logs));
      });
    });
    browser = await chromium.launch({
      executablePath: process.env.PANE_TEST_CHROMIUM || undefined,
      headless: true,
      args: ["--no-sandbox"],
    });
    const page = await browser.newPage({
      viewport: { width: 460, height: 800 },
      reducedMotion: "reduce",
    });
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/setup", (r) =>
      r.fulfill({
        json: {
          phase: "idle",
          onboardingRequired: false,
          boundUdid: "saved-phone",
        },
      }),
    );
    let deviceRequests=0;
    let delayedLookup=null;
    let delayedOptOut=null;
    const preferencePatches=[];
    await page.route('**/api/preferences',async r=>{
      if(r.request().method()==='POST'){
        const patch=r.request().postDataJSON();preferencePatches.push(patch);
        if(delayedOptOut&&patch.notifications_enabled===false){
          const response=await r.fetch();delayedOptOut.saved();await delayedOptOut.promise;
          return r.fulfill({response});
        }
      }
      return r.continue();
    });
    await page.route("**/api/bluetooth/devices", async (r) => {
      deviceRequests++;
      if(delayedLookup){delayedLookup.started();await delayedLookup.promise;}
      return r.fulfill({
        json: {
          audio: [{ id: "audio-phone", name: "My iPhone" }],
          notifications: [{ id: "ble-phone", name: "My iPhone" }],
        },
      });
    });
    // Exercise the native controls' DOM. Actual HWND behavior has separate Windows tests.
    await page.route("**/api/window", async (r) => {
      const response = await r.fetch();
      await r.fulfill({ json: { ...(await response.json()), native: true } });
    });
    async function openDrawer() {
      await page.waitForFunction(
        () => !document.querySelector("#pin-window").hidden,
      );
      if (!(await page.locator("#connection-drawer").isVisible()))
        await page.locator("#drawer-toggle").click();
      await page.locator("#connection-drawer").waitFor({ state: "visible" });
      // Native layout and saved preferences load independently on a fresh page.
      await page.evaluate(() => window.paneExperience.ready);
    }
    await page.goto(url);
    await openDrawer();
    async function fits(name) {
      await page.screenshot({ path: "test-results/check-" + name + ".png" });
      console.log(
        name,
        await page
          .locator(".drawer-scroll")
          .evaluate((e) => [e.clientHeight, e.scrollHeight]),
      );
      assert.ok(
        await page
          .locator(".drawer-scroll")
          .evaluate((e) => e.scrollHeight <= e.clientHeight + 1),
        `${name} should fit at the default phone size`,
      );
    }
    await fits("Connection");
    await page.getByRole("tab", { name: "Settings", exact: true }).click();
    await fits("Settings");
    fs.mkdirSync("test-results", { recursive: true });
    await page.screenshot({ path: "test-results/settings.png" });
    assert.equal(await page.locator("#background-enabled").isChecked(), false);
    await page.locator('.settings-links [data-settings="notifications"]').click();
    await page
      .locator('#notification-device option[value="ble-phone"]')
      .waitFor({ state: "attached" });
    assert.equal(await page.locator('#notification-device-field').isVisible(),false);
    assert.equal(await page.locator('#notification-options').isVisible(),false);
    assert.equal(await page.locator('#notification-options').getAttribute('open'),null);
    await page.locator("#notifications-enabled").check();
    await page.waitForFunction(async()=>{
      const p=(await getJson('/api/preferences')).preferences;
      return p.notifications_enabled&&p.notification_device_id==='ble-phone';
    });
    assert.equal(await page.locator('#notification-device-field').isVisible(),false,'One known iPhone should not require a picker');
    assert.equal(await page.locator('#notification-selected-phone').isVisible(),true);
    assert.equal(await page.locator('#notification-options').getAttribute('open'),null);
    let saved=(await page.evaluate(()=>getJson('/api/preferences'))).preferences;
    assert.equal(saved.show_previews,false);
    assert.equal(saved.background_enabled,false);
    const enabledPatch=preferencePatches.find(p=>p.notifications_enabled===true);
    assert.deepEqual(enabledPatch,{notifications_enabled:true,notification_device_id:'ble-phone'});
    const beforeCheck=deviceRequests,beforeRetry=preferencePatches.filter(p=>p.notifications_enabled===true).length;
    await page.locator('#notifications-check').click();
    await page.waitForFunction(()=>!document.querySelector('#notifications-check').disabled);
    assert.equal(deviceRequests,beforeCheck+1,'Check again must refresh devices');
    assert.equal(preferencePatches.filter(p=>p.notifications_enabled===true).length,beforeRetry+1,'Check again must retry the existing opt-in');
    saved=(await page.evaluate(()=>getJson('/api/preferences'))).preferences;
    assert.equal(saved.show_previews,false);
    assert.equal(saved.background_enabled,false);
    // A device scan can finish after the user turns alerts off. Its stale
    // Check-again continuation must never opt the user back in.
    let lookupStarted,releaseLookup,optOutSaved,releaseOptOut;
    const started=new Promise(resolve=>{lookupStarted=resolve;});
    const optedOut=new Promise(resolve=>{optOutSaved=resolve;});
    delayedLookup={started:lookupStarted,promise:new Promise(resolve=>{releaseLookup=resolve;})};
    delayedOptOut={saved:optOutSaved,promise:new Promise(resolve=>{releaseOptOut=resolve;})};
    await page.locator('#notifications-check').click();
    await started;
    let offPatchCount;
    try{
      await page.locator('#notifications-enabled').uncheck();
      await optedOut;
      await page.waitForFunction(async()=>!(await getJson('/api/preferences')).preferences.notifications_enabled);
      offPatchCount=preferencePatches.length;
      // Keep the opt-out HTTP reply pending: frontend prefs are still stale
      // while the scan finishes. The setup-generation guard must win anyway.
      delayedLookup=null;releaseLookup();
      await page.waitForFunction(()=>!document.querySelector('#notifications-check').disabled);
    }finally{delayedLookup=null;releaseLookup();delayedOptOut=null;releaseOptOut();}
    await page.waitForFunction(()=>document.querySelector('#notifications-toggle-hint').textContent==='Off');
    assert.equal(await page.locator('#notifications-enabled').isChecked(),false);
    assert.equal((await page.evaluate(()=>getJson('/api/preferences'))).preferences.notifications_enabled,false);
    assert.equal(preferencePatches.slice(offPatchCount).some(p=>p.notifications_enabled===true),false,'A completed scan must not undo an explicit opt-out');
    await page.locator('#notifications-enabled').check();
    await page.locator('#notifications-check').waitFor({state:'visible'});
    await page.evaluate(()=>window.paneExperience.renderCompanion({available:true,notificationPhase:'ready',computerName:'Test PC'}));
    assert.equal(await page.locator('#notification-setup-help').isVisible(),false);
    assert.equal(await page.locator('#notifications-check').isVisible(),false);
    assert.equal(await page.locator('#notifications-toggle-hint').innerText(),'On');
    let windowsSettingsRequests=0;
    await page.route('**/api/notifications/settings',r=>{
      windowsSettingsRequests++;
      return r.fulfill({json:{ok:true}});
    });
    await page.evaluate(()=>window.paneExperience.renderCompanion({available:true,notificationPhase:'needs_windows_permission',computerName:'Test PC'}));
    assert.equal(await page.locator('#notification-phone-steps').isVisible(),false);
    assert.equal(await page.locator('#notification-windows-help').isVisible(),true);
    await Promise.all([
      page.waitForResponse(response=>response.url().endsWith('/api/notifications/settings')),
      page.locator('#notification-windows-settings').click(),
    ]);
    assert.equal(windowsSettingsRequests,1,'The Windows action must use the mocked notification-settings endpoint');
    await page.evaluate(()=>window.paneExperience.renderCompanion({available:true,notificationPhase:'needs_permission',computerName:'Test PC'}));
    assert.equal(await page.locator('#notification-phone-steps').isVisible(),true);
    assert.equal(await page.locator('#notification-windows-help').isVisible(),false);
    assert.equal(await page.locator('#notification-pc-name').innerText(),'Test PC');
    await page.locator('#notifications-enabled').uncheck();
    await page.waitForFunction(()=>document.querySelector('#notifications-toggle-hint').textContent==='Off');
    assert.equal(await page.locator('#notification-device-field').isVisible(),false);
    assert.equal(await page.locator('#notification-options').isVisible(),false);
    assert.equal(await page.locator('#notification-selected-phone').isVisible(),false);
    assert.equal(await page.locator('#notifications-check').isVisible(),false);
    assert.equal(await page.locator('#notification-setup-help .action-summary').isVisible(),true);
    await page.locator('#notifications-enabled').check();
    await page.locator('#notifications-check').waitFor({state:'visible'});
    await page.locator('#notification-options > summary').click();
    await page.locator('#notification-types input[value="mail"]').check();
    await page.locator('#notification-options > summary').click();
    await page.locator("#background-enabled").check();
    await page.waitForFunction(async () => {
      const p = await getJson("/api/preferences");
      return (
        p.preferences.background_enabled &&
        p.preferences.notifications_enabled &&
        p.preferences.categories.includes("mail")
      );
    });
    await fits("Notifications");
    await page.screenshot({ path: "test-results/notifications.png" });
    await page.reload();
    await openDrawer();
    assert.equal(await page.locator("#background-enabled").isChecked(), true);
    await page.getByRole("tab", { name: "Settings", exact: true }).click();
    await page.locator('[data-settings="audio"]').click();
    await page.locator("#audio-device").selectOption("audio-phone");
    await fits("Audio");
    await page.locator("#audio-enabled").focus();
    await page.waitForTimeout(750);
    assert.equal(await page.locator('#pane-tooltip').isVisible(),false,'Labeled settings must not repeat their text in tooltips');
    await page.locator('#pin-window').focus();
    await page.locator('#pane-tooltip').waitFor({state:'visible'});
    assert.match(await page.locator('#pane-tooltip').innerText(),/Keep on top/);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#pane-tooltip").isVisible(), false);
    await page.locator(".rail-grip").hover();
    await page.locator("#close-window").waitFor({ state: "visible" });
    const island = await page.locator(".handle-cluster").boundingBox();
    for (const id of ["minimize-window", "maximize-window", "close-window"]) {
      const b = await page.locator("#" + id).boundingBox();
      assert.ok(b.y >= island.y && b.y + b.height <= island.y + island.height);
    }
    await page.screenshot({ path: "test-results/window-island.png" });
    assert.equal(
      await page
        .locator(".rail-grip svg")
        .evaluate((e) => getComputedStyle(e).transitionDuration),
      "0s",
    );
    await openDrawer();
    await page.getByRole("tab", { name: "Uploads", exact: true }).click();
    await fits("Uploads");
    await page.route("**/api/uploads", (r) =>
      r.fulfill({
        json: {
          bluetooth: { phase: "idle", note: "Ready" },
          destination: "Downloads",
          transfers: Array.from({ length: 7 }, (_, i) => ({
            id: String(i),
            name: `file-${i}.txt`,
            size: 12,
            direction: "to-phone",
            state: "complete",
          })),
        },
      }),
    );
    await page.locator("#transfers-next").waitFor({ state: "visible" });
    assert.equal(await page.locator(".transfer").count(), 2);
    await fits("Upload-history");
    await page.locator("#transfers-next").click();
    assert.match(await page.locator(".transfer").first().innerText(), /file-2/);
    await page.locator("#transfers-next").click();
    assert.match(await page.locator(".transfer").first().innerText(), /file-4/);
    await page.locator("#transfers-next").click();
    assert.match(await page.locator(".transfer").first().innerText(), /file-6/);
    // Uploads remain usable with mirroring idle, in both directions.
    const transferActions = [];
    const activeTransfers = [
      {id:'outgoing', name:'notes.pdf', size:200, done:100, direction:'to-phone', state:'sending'},
      {id:'incoming', name:'photo.heic', size:200, done:80, direction:'from-phone', state:'receiving'},
    ];
    await page.route('**/api/uploads', r => r.fulfill({json:{bluetooth:{phase:'connected'}, destination:'Downloads', transfers:activeTransfers}}));
    await page.route('**/api/uploads/*', r => {
      const action = new URL(r.request().url()).pathname.split('/').pop();
      const {id} = r.request().postDataJSON(); transferActions.push({id,action});
      const transfer = activeTransfers.find(t => t.id === id);
      transfer.state = action === 'pause' ? 'paused' : action === 'cancel' ? 'cancelled' : transfer.direction === 'to-phone' ? 'sending' : 'receiving';
      return r.fulfill({json:{ok:true}});
    });
    await page.getByRole('button',{name:'Pause notes.pdf',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>connectionPhase),'idle');
    for (const name of ['notes.pdf','photo.heic']) {
      await page.getByRole('button',{name:`Pause ${name}`,exact:true}).click();
      await page.getByRole('button',{name:`Resume ${name}`,exact:true}).click();
      await page.getByRole('button',{name:`Pause ${name}`,exact:true}).waitFor();
      await page.getByRole('button',{name:`Cancel ${name}`,exact:true}).click();
    }
    assert.deepEqual(transferActions.map(a=>a.action),['pause','resume','cancel','pause','resume','cancel']);
    await page.getByRole('button',{name:'Cancel photo.heic',exact:true}).waitFor({state:'hidden'});
    assert.deepEqual(await page.evaluate(() => ['File too large (limit 100)', 'SHA256 checksum mismatch', 'Queue is full'].map(error => paneNotice(error,'upload'))), ['File too large. Choose a smaller file.', 'File incomplete. Send it again.', 'Queue full. Finish or cancel a file.']);
    assert.equal(await page.evaluate(()=>paneNotice('The bundled iPhone app is damaged or outdated.', 'signing')), 'iPhone installer unavailable. Update Pane on this PC.');
    // Technical diagnostics stay in the API; the screen gives a short first action.
    activeTransfers[0].state='failed'; activeTransfers[0].error='Traceback HTTP 503 socket ECONNRESET C:/private/file.py';
    await page.getByText('Transfer stopped. Open Pane on your iPhone.',{exact:true}).waitFor();
    assert.doesNotMatch(await page.locator('#uploads-panel').innerText(), /Traceback|ECONNRESET|file\.py/);
    await page.getByRole('tab',{name:'Settings',exact:true}).click();
    assert.equal(await page.locator('.settings-row-icon').count(),7);
    assert.equal(await page.locator('.settings-links [data-settings="notifications"]').innerText(),'Phone notifications');
    await page.locator('[data-settings="audio"]').click();
    await page.locator('#settings-audio [data-settings-back]').click();
    assert.equal(await page.locator('#settings-home').isVisible(),true);
    // A heavily zoomed or small window must still allow access to overflow content.
    await page.evaluate(() => {
      document.documentElement.style.zoom = "1.6";
      document.documentElement.style.setProperty("--phone-height", "480px");
    });
    await page.getByRole("tab", { name: "Settings", exact: true }).click();
    assert.equal(
      await page
        .locator(".drawer-scroll")
        .evaluate((e) => getComputedStyle(e).overflowY),
      "auto",
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: compact menus, persisted opt-ins, device selection, tooltips, joined island, reduced motion and paginated history.",
    );
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
