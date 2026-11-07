const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const baseline = process.env.PANE_BASELINE_ROOT;
  if (!baseline)
    throw new Error(
      "Set PANE_BASELINE_ROOT to an untouched v2.2.1 source checkout.",
    );
  const root = path.resolve(__dirname, "..");
  const browser = await chromium.launch({
    executablePath: process.env.PANE_TEST_CHROMIUM || undefined,
    headless: true,
    args: ["--no-sandbox"],
  });
  const result = {
    durationSeconds: 20,
    fixture:
      "saved pairing, disconnected phone, closed drawer, visible page, 2 s warmup",
    base: "6cbcdefaddc2b7415ac4b3024d4b35487d1d143d",
  };
  try {
    for (const [name, cwd] of [
      ["baseline", baseline],
      ["updated", root],
    ]) {
      const child = spawn(
        process.env.PANE_TEST_PYTHON || "python3",
        ["tests/browser_preview.py"],
        {
          cwd: root,
          env: { ...process.env, PANE_TEST_SOURCE: cwd },
          stdio: ["ignore", "pipe", "inherit"],
        },
      );
      try {
        const url = await new Promise((r) =>
          child.stdout.once("data", (d) =>
            r(d.toString().trim().split(" ").at(-1)),
          ),
        );
        const page = await browser.newPage({
          viewport: { width: 1100, height: 950 },
        });
        let count = false;
        const calls = {};
        const data = {
          "/api/status": {
            driver: { ready: true },
            library: { ready: true },
            devices: [],
            screen: { phase: "idle" },
            wifi: { paired: [] },
          },
          "/api/setup": {
            phase: "idle",
            onboardingRequired: false,
            boundUdid: "test-phone",
          },
          "/api/uploads": {
            bluetooth: { phase: "idle", note: "Offline" },
            transfers: [],
            destination: "Downloads",
          },
          "/api/signing": { phase: "idle", available: true },
          "/api/screen": { phase: "idle" },
        };
        await page.route("**/api/**", async (route) => {
          const p = new URL(route.request().url()).pathname;
          if (data[p]) {
            if (count) calls[p] = (calls[p] || 0) + 1;
            await route.fulfill({ json: data[p] });
          } else await route.continue();
        });
        await page.goto(url);
        await page.waitForTimeout(2000);
        count = true;
        await page.waitForTimeout(20000);
        count = false;
        result[name] = {
          calls,
          total: Object.values(calls).reduce((a, b) => a + b, 0),
        };
        await page.close();
      } finally {
        child.kill();
      }
    }
  } finally {
    await browser.close();
  }
  fs.mkdirSync(path.join(root, "test-results"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "test-results", "idle-poll.json"),
    JSON.stringify(result, null, 2),
  );
  console.log(result);
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
