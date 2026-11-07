// Regenerate every platform icon from the existing approved SVG. Dev tooling only.
// npm ci; npx playwright install chromium; node packaging/build-icons.cjs
const { chromium } = require("playwright");
const fs = require("node:fs");
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.PANE_TEST_CHROMIUM || undefined,
    headless: true,
  });
  try {
    const page = await browser.newPage({ deviceScaleFactor: 1 });
    const svg = fs.readFileSync("handset/web/logo.svg", "utf8");
    const root = "ios/PaneFiles/Assets.xcassets";
    for (const name of ["AppIcon.appiconset", "PaneMark.imageset"])
      fs.mkdirSync(`${root}/${name}`, { recursive: true });
    const icons = [];
    for (const size of [16, 24, 32, 48, 64, 128, 256, 1024]) {
      await page.setViewportSize({ width: size, height: size });
      await page.setContent(
        `<style>body{margin:0;background:${size === 1024 ? "#0a6cff" : "transparent"}}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`,
      );
      const png = await page.screenshot({ omitBackground: size !== 1024 });
      if (size === 1024)
        fs.writeFileSync(`${root}/AppIcon.appiconset/AppIcon.png`, png);
      else icons.push({ size, png });
      if (size === 256) {
        fs.writeFileSync("packaging/logo-256.png", png);
        fs.writeFileSync(`${root}/PaneMark.imageset/PaneMark.png`, png);
      }
    }
    // PNG-backed ICO entries are supported by every Windows version Pane supports.
    const header = Buffer.alloc(6 + 16 * icons.length);
    header.writeUInt16LE(1, 2);
    header.writeUInt16LE(icons.length, 4);
    let offset = header.length;
    icons.forEach(({ size, png }, i) => {
      const at = 6 + 16 * i;
      header[at] = header[at + 1] = size % 256;
      header.writeUInt16LE(1, at + 4);
      header.writeUInt16LE(32, at + 6);
      header.writeUInt32LE(png.length, at + 8);
      header.writeUInt32LE(offset, at + 12);
      offset += png.length;
    });
    fs.writeFileSync(
      "packaging/pane.ico",
      Buffer.concat([header, ...icons.map((x) => x.png)]),
    );
    const info = { author: "xcode", version: 1 };
    for (const [file, data] of [
      ["Contents.json", { info }],
      [
        "AppIcon.appiconset/Contents.json",
        {
          images: [
            {
              filename: "AppIcon.png",
              idiom: "universal",
              platform: "ios",
              size: "1024x1024",
            },
          ],
          info,
        },
      ],
      [
        "PaneMark.imageset/Contents.json",
        { images: [{ filename: "PaneMark.png", idiom: "universal" }], info },
      ],
    ])
      fs.writeFileSync(`${root}/${file}`, JSON.stringify(data, null, 2) + "\n");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
