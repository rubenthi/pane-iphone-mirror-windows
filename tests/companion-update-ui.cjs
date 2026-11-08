const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
(async () => {
  const child = spawn(process.env.PANE_TEST_PYTHON || 'python3', ['tests/browser_preview.py'], {stdio:['ignore','pipe','pipe']});
  let browser, logs = '';
  child.stderr.on('data', d => logs += d);
  try {
    const url = await new Promise((resolve,reject) => {
      const timer = setTimeout(() => reject(Error(logs || 'Preview timeout')),10000);
      child.stdout.once('data', d => {clearTimeout(timer); resolve(d.toString().trim().split(' ').at(-1));});
      child.once('exit', () => {clearTimeout(timer); reject(Error(logs));});
    });
    browser = await chromium.launch({headless:true, executablePath:process.env.PANE_TEST_CHROMIUM || undefined});
    const page = await browser.newPage({viewport:{width:460,height:800}, reducedMotion:'reduce'});
    const errors=[]; page.on('pageerror', e => errors.push(e.message));
    let state, calls=0;
    await page.route('**/api/setup', r => r.fulfill({json:{phase:'idle',onboardingRequired:false,boundUdid:'phone'}}));
    await page.route('**/api/preferences', r => r.fulfill({json:{preferences:{tour_complete:true},companion:{}}}));
    await page.route('**/api/companion-update', r => { calls++; return r.fulfill({json:state}); });
    for (const [label, installed] of [['current','2.3.0'],['newer desktop same mobile','2.3.0'],['unknown',null],['missing',null],['ambiguous',null]]) {
      state={availableVersion:'2.3.0',installedVersion:installed,updateAvailable:false,connected:false};
      const before=calls; await page.goto(url); await page.waitForFunction(() => !document.querySelector('#check-companion-update').disabled);
      await page.waitForTimeout(150);
      assert.equal(calls,before+1,label);
      assert.equal(await page.locator('#companion-update-dialog').isVisible(),false,label);
    }
    for (const connected of [false,true]) {
      state={availableVersion:'2.3.0',installedVersion:'2.2.0',updateAvailable:true,connected,cached:!connected};
      await page.goto(url); const dialog=page.locator('#companion-update-dialog'); await dialog.waitFor({state:'visible'});
      assert.match(await page.locator('#companion-update-copy').innerText(), connected ? /Keep your iPhone connected/ : /Plug in your iPhone/);
      assert.equal(await page.locator('#companion-update-later').evaluate(e => e===document.activeElement),true);
      await page.locator('#companion-update-later').click(); assert.equal(await dialog.isVisible(),false);
      await page.evaluate(() => document.querySelector('#check-companion-update').click());
      await page.waitForTimeout(200); assert.equal(await dialog.isVisible(),false,'manual check must not reopen popup');
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('pane-status',{detail:{}})));
      assert.equal(await dialog.isVisible(),false,'status poll must not reopen popup');
    }
    state={availableVersion:'2.4.0',installedVersion:null,updateAvailable:false,connected:false};
    await page.goto(url);
    await page.waitForFunction(() => document.querySelector('#companion-version-note').textContent.includes('unknown'));
    state={availableVersion:'2.4.0',installedVersion:'2.3.0',updateAvailable:true,connected:true};
    const plugCable = () => page.evaluate(() => window.dispatchEvent(new CustomEvent('pane-status',{
      detail:{devices:[{connection:'USB',udid:'phone'}]}
    })));
    await plugCable();
    await page.locator('#companion-update-dialog').waitFor({state:'visible'});
    assert.match(await page.locator('#companion-update-copy').innerText(), /2\.4\.0/);
    await page.locator('#companion-update-later').click();
    await plugCable();
    assert.equal(await page.locator('#companion-update-dialog').isVisible(),false);
    await page.goto(url); await page.locator('#companion-update-dialog').waitFor({state:'visible'});
    await page.locator('#companion-update-open').click();
    assert.equal(await page.locator('#companion-update-dialog').isVisible(),false);
    await page.locator('#settings-setup').waitFor({state:'visible'});
    assert.equal(await page.locator('#settings-setup').isVisible(),true);
    assert.equal(await page.locator('[data-step="install"]').evaluate(e=>e.open),true);
    assert.equal(await page.locator('[data-step="install"] > summary').evaluate(e=>e===document.activeElement),true);
    await page.goto(url); await page.locator('#companion-update-dialog').waitFor({state:'visible'});
    await page.keyboard.press('Escape'); assert.equal(await page.locator('#companion-update-dialog').isVisible(),false);
    await page.setViewportSize({width:419,height:760});
    await page.route('**/api/window', async r => {
      const response = await r.fetch();
      await r.fulfill({json:{...(await response.json()),native:true,phone_width:359,height:760}});
    });
    await page.goto(url); await page.locator('#companion-update-dialog').waitFor({state:'visible'});
    await page.waitForFunction(() => !document.body.classList.contains('browser-mode'));
    const bounds = await page.locator('#companion-update-dialog').boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 359, 'popup must fit native phone region, not clipped side rail');
    require('node:fs').mkdirSync('test-results',{recursive:true});
    await page.screenshot({path:'test-results/companion-update-native.png'});
    await page.setViewportSize({width:419,height:520});
    await page.locator('#companion-update-open').scrollIntoViewIfNeeded();
    await page.screenshot({path:'test-results/companion-update-small.png'});
    const actionBounds = await page.locator('#companion-update-open').boundingBox();
    assert.ok(actionBounds.x >= 0 && actionBounds.x + actionBounds.width <= 359 && actionBounds.y + actionBounds.height <= 520, 'update action stays reachable in small window');
    assert.deepEqual(errors,[]);
    console.log('PASS companion startup popup: known older only, USB/disconnected copy, dismiss, manual no-repeat, action focus, Escape');
  } finally { await browser?.close(); child.kill(); }
})().catch(e => {console.error(e);process.exitCode=1;});
