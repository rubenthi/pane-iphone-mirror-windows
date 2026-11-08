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
    await page.route("**/api/bluetooth/devices", (r) =>
      r.fulfill({
        json: {
          audio: [{ id: "audio-phone", name: "My iPhone" }],
          notifications: [{ id: "ble-phone", name: "My iPhone" }],
        },
      }),
    );
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
    await page.locator("#notification-device").selectOption("ble-phone");
    await page.locator("#notifications-enabled").check();
    await page.locator('#notification-types input[value="mail"]').check();
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
    await page.locator("#pane-tooltip").waitFor({ state: "visible" });
    assert.match(
      await page.locator("#pane-tooltip").innerText(),
      /audio receiver/,
    );
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
