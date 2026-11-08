// Real UI, simulated device state. PNGs are review artifacts, not snapshot assertions.
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
  child.stderr.on("data", (d) => {
    logs += d;
  });
  try {
    const url = await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(logs || "Preview timed out")),
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
    const context = await browser.newContext({
      viewport: { width: 460, height: 800 },
      deviceScaleFactor: 2,
    });
    const errors = [],
      external = [],
      shots = [];
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (!r.url().startsWith(url) && !r.url().startsWith("data:"))
        external.push(r.url());
    });
    page.setDefaultTimeout(10000);
    let setupSnapshot = {
      phase: "idle",
      onboardingRequired: false,
      boundUdid: "preview-phone",
    };
    await page.route("**/api/setup", (r) =>
      r.fulfill({
        json: setupSnapshot,
      }),
    );
    await page.route("**/api/window", async (r) => {
      const response = await r.fetch();
      await r.fulfill({ json: { ...(await response.json()), native: true } });
    });
    await page.route("**/api/bluetooth/devices", (r) =>
      r.fulfill({
        json: {
          audio: [
            { id: "audio-one", name: "Everyday iPhone" },
            { id: "audio-two", name: "Studio iPhone" },
          ],
          notifications: [
            { id: "ble-one", name: "Everyday iPhone" },
            { id: "ble-two", name: "Studio iPhone" },
          ],
        },
      }),
    );
    fs.mkdirSync("test-results/visual", { recursive: true });
    async function capture(name, move = true) {
      if (move) await page.mouse.move(450, 790);
      await page.waitForTimeout(move ? 520 : 220);
      const file = `test-results/visual/${name}.png`;
      await page.screenshot({ path: file });
      shots.push({ name, file });
      assert.ok(await page.locator("#phone-shell").isVisible());
    }
    async function settings(name) {
      if (!(await page.locator("#connection-drawer").isVisible()))
        await page.locator("#drawer-toggle").click();
      await page.locator("#connection-drawer").waitFor({ state: "visible" });
      await page.getByRole("tab", { name: "Settings", exact: true }).click();
      if (name)
        await page.locator(`.settings-links [data-settings="${name}"]`).click();
    }
    async function fits(selector) {
      const size = await page.locator(selector).evaluate((e) => ({
        w: e.clientWidth,
        sw: e.scrollWidth,
        h: e.clientHeight,
        sh: e.scrollHeight,
      }));
      assert.ok(
        size.sw <= size.w + 1,
        `${selector} horizontal overflow: ${JSON.stringify(size)}`,
      );
      assert.ok(
        size.sh <= size.h + 1,
        `${selector} vertical overflow: ${JSON.stringify(size)}`,
      );
    }
    await page.goto(url);
    await page.evaluate(() => document.fonts.ready);
    assert.ok(
      await page.evaluate(() =>
        [...document.fonts].some(
          (f) => f.family === "Commissioner" && f.status === "loaded",
        ),
      ),
    );
    const font = await page.request.get(
      url + "/fonts/commissioner-latin.woff2",
    );
    assert.match(font.headers()["content-type"], /font\/woff2/);
    await page.waitForFunction(
      () => !document.querySelector("#pin-window").hidden,
    );
    await capture("01-compact");
    await page.locator("#welcome-setup").hover();
    await capture("02-primary-hover", false);
    await page.locator(".rail-grip").hover();
    await page.locator("#close-window").waitFor({ state: "visible" });
    await capture("03-window-island", false);
    await page.locator("#drawer-toggle").click();
    await capture("04-connection");
    await page.locator('[data-transport="wifi"]').click();
    await capture("05-wifi");
    await page.locator('[data-transport="usb"]').click();
    await settings();
    await capture("06-settings");
    assert.equal(await page.locator('.settings-links .settings-row-icon').count(), 7);
    assert.equal(await page.locator('.settings-links > button > .pane-icon').count(), 7);
    assert.equal(await page.locator('.settings-links > button > .pane-icon').first().isVisible(),true);
    await fits(".drawer-scroll");
    await page
      .locator('.settings-links [data-settings="notifications"]')
      .hover();
    await capture("07-menu-hover", false);
    await page.locator("#background-enabled").check();
    await page.locator("#background-next").waitFor({ state: "visible" });
    await capture("08-background-action");
    await page.locator("#background-next").click();
    await page
      .locator("#notification-device-control")
      .waitFor({ state: "visible" });
    await capture("09-notifications-off");
    const compact = await page
      .locator("#notification-setup-help .action-summary")
      .evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
    await page.locator("#notifications-enabled").check();
    await page
      .locator("#notification-setup-help .action-expanded")
      .waitFor({ state: "visible" });
    assert.match(
      await page.locator("#notification-setup-help").innerText(),
      /Share System Notifications/,
    );
    const expanded = await page
      .locator("#notification-setup-help .action-expanded p")
      .evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
    assert.ok(expanded > compact);
    assert.equal(await page.locator("#background-next").isVisible(), false);
    await capture("10-notifications-on");
    await fits(".drawer-scroll");
    const picker = page.locator("#notification-device-control");
    await picker.focus();
    await picker.press("Enter");
    await page.getByRole("listbox").waitFor({ state: "visible" });
    await picker.press("End");
    await picker.press("Enter");
    assert.equal(
      await page.locator("#notification-device").inputValue(),
      "ble-two",
    );
    await picker.press("Enter");
    await picker.press("Home");
    await picker.press("ArrowDown");
    await capture("11-dropdown", false);
    await picker.press("Escape");
    assert.equal(await picker.getAttribute("aria-expanded"), "false");
    assert.equal(
      await page.locator("#notification-device").inputValue(),
      "ble-two",
    );
    await picker.press("s");
    await picker.press("Enter");
    assert.equal(
      await page.locator("#notification-device").inputValue(),
      "ble-two",
    );
    await picker.click();
    await page.locator("#settings-notifications h2").click();
    assert.equal(await page.getByRole("listbox").isVisible(), false);
    await picker.focus();
    await picker.press("Enter");
    await picker.press("Home");
    await picker.press("ArrowDown");
    // Device discovery may reorder options while the user is choosing a phone.
    await page.evaluate(() =>
      document
        .querySelector("#notification-device")
        .prepend(new Option("Newly discovered iPhone", "ble-new")),
    );
    await page.waitForFunction(
      () =>
        document.getElementById(
          document
            .querySelector("#notification-device-control")
            .getAttribute("aria-activedescendant"),
        )?.textContent === "Everyday iPhone",
    );
    await picker.press("Enter");
    assert.equal(
      await page.locator("#notification-device").inputValue(),
      "ble-one",
    );
    await picker.press("Enter");
    await picker.press("Tab");
    assert.equal(await page.getByRole("listbox").isVisible(), false);
    await page.locator("#notification-previews").check();
    await page.waitForFunction(() =>
      document
        .querySelector("#previews-toggle-hint")
        .textContent.includes("Titles"),
    );
    await capture("12-notification-previews");
    await fits(".drawer-scroll");
    await page.locator("#notifications-enabled").focus();
    await page.waitForTimeout(750);
    assert.equal(await page.locator('#pane-tooltip').isVisible(),false);
    assert.match(
      await page
        .locator("#notifications-enabled")
        .getAttribute("aria-describedby"),
      /notification-setup-help/,
    );
    await page.locator('#pin-window').focus();
    await page.locator('#pane-tooltip').waitFor({state:'visible'});
    await capture("13-tooltip", false);
    await page.keyboard.press("Escape");
    assert.equal(
      await page
        .locator("#notifications-enabled")
        .getAttribute("aria-describedby"),
      "notification-setup-help",
    );
    await settings("audio");
    await capture("14-audio-on");
    await fits(".drawer-scroll");
    await page.locator("#audio-enabled").uncheck();
    await page
      .locator("#audio-setup-help .action-summary")
      .waitFor({ state: "visible" });
    await capture("15-audio-off");
    await settings("display");
    await capture("16-display");
    const fps = page.locator("#fps-target-control");
    await fps.click();
    await fps.press("Home");
    await fps.press("Enter");
    assert.equal(await page.locator("#fps-target").inputValue(), "15");
    await fps.click();
    await fps.press("End");
    await fps.press("Enter");
    assert.equal(await page.locator("#fps-target").inputValue(), "60");
    await settings("details");
    await capture("17-details");
    await settings("help");
    await capture("18-help");
    await settings("setup");
    await capture("19-setup-help");
    await page.locator('[data-step="connect"] > summary').click();
    await page.locator('[data-step="install"] > summary').click();
    await page.locator("#signing-form").scrollIntoViewIfNeeded();
    await capture("20-signing");
    await page.locator("#settings-setup .trust-help:not(.privacy-help) summary").click();
    await page.locator("#settings-setup .trust-help:not(.privacy-help)").scrollIntoViewIfNeeded();
    await capture("21-trust-help");
    await page.getByRole("tab", { name: "Uploads", exact: true }).click();
    await capture("22-uploads-empty");
    await page.route("**/api/uploads", (r) =>
      r.fulfill({
        json: {
          bluetooth: { phase: "connected", note: "Sample iPhone connection" },
          destination: "Downloads",
          transfers: [
            {
              id: "one",
              name: "Weekend photo.heic",
              size: 3048000,
              state: "complete",
              direction: "to-laptop",
              done: 3048000,
            },
            {
              id: "two",
              name: "Reading list.pdf",
              size: 182000,
              state: "sending",
              direction: "to-phone",
              done: 91000,
            },
          ],
        },
      }),
    );
    await page.locator(".transfer").first().waitFor();
    await capture("23-uploads-progress");
    const longName = "A".repeat(180) + ".heic";
    await page
      .locator(".transfer strong")
      .first()
      .evaluate((element, name) => {element.textContent=name;element.title=name;}, longName);
    await page.locator(".transfer strong").first().hover();
    await page.locator("#pane-tooltip").waitFor({ state: "visible" });
    const textBounds = await page
      .locator("#pane-tooltip")
      .evaluate((element) => ({
        width: element.clientWidth,
        content: element.scrollWidth,
      }));
    assert.ok(
      textBounds.content <= textBounds.width + 1,
      "Long filenames must wrap inside tooltips",
    );
    await capture("23-long-filename-tooltip", false);
    await settings();
    await page.locator("[data-show-tour]").click();
    for (let i = 1; i <= 3; i++) {
      await capture(`24-tour-${i}`);
      await page.locator("#tour-next").click();
    }
    await page.locator("#feature-tour").waitFor({ state: "hidden" });
    // Use the real poller: an in-flight response can overwrite synthetic events.
    const setupTransfers = (route) => route.fulfill({ json: {
      transfers: [], bluetooth: { phase: "connecting", note: "Waiting for your iPhone." },
    } });
    await page.route("**/api/uploads", setupTransfers);
    // All screenshots use the same real UI and simulated backend snapshots.
    for (const [stage, state] of [
      ["connect", {}],
      ["developer", { revealed: true }],
      ["install", { developerEnabled: true }],
      ["pair", { boundUdid: "preview-phone" }],
    ]) {
      setupSnapshot = { phase: "idle", onboardingRequired: true, ...state };
      const expectedTitle = {
        connect: "Connect your iPhone",
        developer: "Enable Developer Mode",
        install: "Install Pane on iPhone",
        pair: "Open Pane on iPhone",
      }[stage];
      await page.waitForFunction(
        (title) => document.querySelector("#onboarding-title").textContent === title
          && !document.querySelector("#onboarding").hidden,
        expectedTitle,
      );
      await capture(`25-setup-${stage}`);
      if (stage === 'pair') {
        const trust = page.locator('#onboarding-bluetooth .trust-visual');
        assert.match(await trust.innerText(), /Settings[\s\S]*General[\s\S]*VPN & Device Management[\s\S]*Developer App[\s\S]*Your Apple Account[\s\S]*Tap Trust/);
        assert.equal(await trust.locator('.trust-action .pane-icon').isVisible(), true);
      }
      assert.equal(
        await page.locator("#onboarding").isVisible(),
        true,
        stage + " must remain visible",
      );
      assert.match(
        await page.locator("#onboarding-title").innerText(),
        {
          connect: /Connect your iPhone/,
          developer: /Developer Mode/,
          install: /Install Pane/,
          pair: /Open Pane/,
        }[stage],
      );
    }
    setupSnapshot = {
      phase: "idle",
      onboardingRequired: false,
      boundUdid: "preview-phone",
    };
    await page.locator("#onboarding").waitFor({ state: "hidden" });
    await page.unroute("**/api/uploads", setupTransfers);
    await page.locator("#connection-drawer").waitFor({ state: "hidden" });
    await settings("audio");
    await page.locator("#audio-device-control").click();
    await page.setViewportSize({ width: 460, height: 620 });
    // Viewport acknowledgement precedes the renderer's resize event on Windows.
    await page.getByRole("listbox").waitFor({ state: "hidden" });
    assert.equal(await page.getByRole("listbox").isVisible(), false);
    await page.evaluate(() =>
      document.documentElement.style.setProperty("--phone-height", "590px"),
    );
    await capture("26-small-window");
    await page.evaluate(() => {
      document.documentElement.style.zoom = "1.6";
      document.documentElement.style.setProperty("--phone-height", "360px");
      document.documentElement.style.setProperty("--phone-width", "260px");
    });
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.locator("#audio-device-control").scrollIntoViewIfNeeded();
    await page.locator("#audio-device-control").click();
    await capture("27-zoom-dropdown", false);
    const menu = await page.getByRole("listbox").boundingBox(),
      body = await page.locator("#connection-drawer").boundingBox();
    assert.ok(
      menu.x >= body.x && menu.x + menu.width <= body.x + body.width + 1,
    );
    assert.ok(
      menu.y >= body.y &&
        menu.y + menu.height <= Math.min(body.y + body.height, 620) + 1,
    );
    await page.keyboard.press("Escape");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.locator("#audio-device-control").click();
    assert.equal(
      await page
        .getByRole("listbox")
        .evaluate((e) => getComputedStyle(e).animationName),
      "none",
    );
    await capture("28-reduced-motion", false);
    assert.deepEqual(errors, []);
    assert.deepEqual(external, [], "Fonts and UI assets must remain local");
    fs.writeFileSync(
      "test-results/visual/manifest.json",
      JSON.stringify(shots, null, 2),
    );
    console.log(
      `PASS: ${shots.length} visual states, local font, expanded required actions, keyboard/typeahead listboxes, outside/Escape dismissal, tooltip descriptions, resize/zoom bounds and reduced motion.`,
    );
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
