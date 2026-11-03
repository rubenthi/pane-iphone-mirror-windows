// Browser integration with deterministic API responses; no physical Bluetooth claims.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless:true, executablePath:process.env.PANE_TEST_CHROMIUM || undefined });
  const page = await browser.newPage({viewport:{width:1100,height:900}});
  const errors = [], commands = [];
  let rejectStop = false;
  const shell = {native:false, expanded:false, phone_width:350, height:760};
  const state = {available:true, audio:{state:'Disconnected'}, cursor:{state:'Stopped', clients:[]}, notifications:{state:'Disconnected',items:[]}};
  page.on('pageerror', e => errors.push(e.message));
  await page.route('http://pane.test/**', async route => {
    const request = route.request(), url = new URL(request.url());
    const payload = request.method() === 'POST' ? request.postDataJSON() : {};
    let value = {};
    if (url.pathname === '/api/auth') value = {token:'test-token'};
    else if (url.pathname === '/api/status') value = {devices:[],driver:{ready:true},wifi:{paired:[]},screen:{phase:'idle'}};
    else if (url.pathname === '/api/screen') value = {phase:'idle'};
    else if (url.pathname === '/api/window') { if ('expanded' in payload) shell.expanded = payload.expanded; value = shell; }
    else if (url.pathname === '/api/screen/stop') {
      commands.push('screen.stop');
      if (rejectStop) return route.fulfill({status:400,json:{error:'Stream still closing'}});
      value = {ok:true};
    }
    else if (url.pathname === '/api/bluetooth') {
      value = state;
      if (request.method() === 'POST') {
        commands.push(payload);
        if (payload.action === 'devices') value = {audio:[{id:'audio-phone',name:'My iPhone'}],notifications:[{id:'ble-phone',name:'My iPhone'}]};
        if (payload.action === 'cursor.start') state.cursor = {state:'Started',clients:[{id:'cursor-phone',name:'My iPhone'}]};
        if (payload.action === 'cursor.select') state.cursor.selected = payload.device;
        if (payload.action === 'audio.connect') state.audio.state = 'Opened';
        if (payload.action === 'notifications.connect') state.notifications = {state:'Connected',items:[{title:'<img src=x onerror=alert(1)>',message:'Private preview',app:'Messages'}]};
        if (payload.action === 'notifications.disconnect') state.notifications = {state:'Disconnected',items:[]};
        if (payload.action === 'cursor.stop') state.cursor = {state:'Stopped',clients:[]};
      }
    } else {
      const file = path.join('handset/web', url.pathname === '/' ? 'index.html' : url.pathname.slice(1));
      if (!fs.existsSync(file)) return route.fulfill({status:404,body:''});
      const mime = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[path.extname(file)];
      return route.fulfill({contentType:mime || 'application/octet-stream',body:fs.readFileSync(file)});
    }
    await route.fulfill({json:value});
  });
  try {
    await page.goto('http://pane.test/');
    await page.locator('#welcome-setup').click();
    await page.locator('#control-mode').selectOption('bluetooth');
    await page.waitForFunction(() => document.body.dataset.controlMode === 'bluetooth');
    assert.ok(commands.includes('screen.stop'));
    assert.equal(await page.locator('#show-screen').isVisible(), false);
    assert.equal(await page.locator('#bluetooth-view').isVisible(), true);
    await page.locator('[data-bt-action="devices"]').click();
    await page.locator('#bt-audio-device').selectOption('audio-phone');
    await page.locator('[data-bt-action="audio.connect"]').click();
    await page.waitForFunction(() => document.querySelector('#bt-audio-state').textContent === 'Opened');
    await page.locator('[data-bt-action="cursor.start"]').click();
    await page.locator('#bt-cursor-device').selectOption('cursor-phone');
    await page.locator('[data-bt-action="cursor.select"]').click();
    await page.waitForFunction(() => document.querySelector('#bt-pad').getAttribute('aria-disabled') === 'false');
    await page.locator('#bt-pad').click();
    await page.waitForFunction(() => true);
    await page.locator('#bt-notification-device').selectOption('ble-phone');
    await page.locator('[data-bt-action="notifications.connect"]').click();
    await page.locator('#bt-notifications li').waitFor();
    assert.equal(await page.locator('#bt-notifications img').count(), 0);
    assert.match(await page.locator('#bt-notifications').innerText(), /<img src=x/);
    await page.locator('#control-mode').selectOption('developer');
    await page.waitForFunction(() => document.body.dataset.controlMode === 'developer');
    assert.equal(await page.locator('#show-screen').isVisible(), true);
    assert.equal(await page.locator('#bluetooth-view').isVisible(), false);
    assert.equal(await page.locator('#bt-audio-state').innerText(), 'Opened');
    const reports = commands.filter(c => c.action === 'cursor.move');
    assert.ok(reports.some(r => r.buttons === 1));
    assert.equal(reports.at(-1).buttons, 0);
    assert.ok(commands.some(c => c.action === 'cursor.stop'));
    rejectStop = true;
    await page.locator('#control-mode').selectOption('bluetooth');
    await page.waitForFunction(() => document.querySelector('#bt-note').textContent.includes('Stream still closing'));
    assert.equal(await page.locator('#control-mode').inputValue(), 'developer');
    await page.locator('[data-bt-action="notifications.disconnect"]').click();
    await page.waitForFunction(() => document.querySelector('#bt-notifications').children.length === 0);
    assert.deepEqual(errors, []);
    console.log('Bluetooth UI passed: mode switching, stop failure, audio preservation, cursor press/release, notification escaping and clearing.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
