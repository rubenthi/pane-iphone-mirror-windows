const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'test-results');
  fs.mkdirSync(output, {recursive:true});
  const child = spawn(process.env.PANE_TEST_PYTHON || 'python', ['tests/native_preview.py'], {cwd:root, windowsHide:true, stdio:['ignore','pipe','pipe']});
  let logs = '';
  child.stdout.on('data', data => logs += data);
  child.stderr.on('data', data => logs += data);
  let browser, page;
  try {
    for (let attempt=0; attempt<150; attempt++) {
      try { if ((await fetch('http://127.0.0.1:18777/json/version')).ok) break; } catch (_) {}
      if (child.exitCode !== null) throw new Error(`Preview exited: ${logs}`);
      await sleep(200);
    }
    browser = await chromium.connectOverCDP('http://127.0.0.1:18777');
    for (let attempt=0; attempt<150; attempt++) {
      page = browser.contexts().flatMap(c => c.pages()).find(p => p.url().startsWith('http://127.0.0.1:18776/'));
      if(page) break;
      await sleep(200);
    }
    assert.ok(page, 'dedicated test page exists');
    const errors=[];
    page.on('pageerror', error => errors.push(error.message));
    await page.reload();
    await page.waitForFunction(async () => {
      const auth = await fetch('/api/auth').then(r=>r.json());
      const state = await fetch('/api/window',{headers:{'X-Pane-Token':auth.token}}).then(r=>r.json());
      return state.native && innerWidth === state.width && innerHeight === state.height;
    });
    await page.getByText('No iPhone detected.',{exact:true}).waitFor({state:'attached'});
    assert.equal(await page.locator('#connection-drawer').isVisible(),false);
    const compact=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    await page.screenshot({path:path.join(output,'pane-compact.png')});
    await page.getByRole('button',{name:'Open connection sidebar',exact:true}).click();
    await page.waitForFunction(w=>innerWidth===w+328,compact.width);
    assert.equal(await page.evaluate(()=>innerHeight),compact.height);
    await page.getByRole('button',{name:/iOS 27 setup guide/}).click();
    await page.locator('#run-guide').waitFor({state:'visible'});
    const developer = page.locator('#run-guide > details').filter({has:page.locator('summary', {hasText:'Enable Developer Mode'})});
    await developer.locator(':scope > summary').click();
    await page.locator('.altstore-guide > summary').click();
    assert.equal(await page.locator('.altstore-guide').getAttribute('open'),'');
    assert.match(await page.locator('.altstore-guide').innerText(), /Install AltStore/);
    assert.match(await page.locator('.altstore-guide').innerText(), /iTunes and iCloud/);
    await page.screenshot({path:path.join(output,'pane-guide.png')});
    await page.getByRole('button',{name:/iOS 27 setup guide/}).click();
    await page.getByRole('radio',{name:/Wi-Fi/}).click();
    await page.getByRole('heading',{name:'A little more freedom'}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Set up Wi-Fi',exact:true}).isDisabled(),true);
    await page.getByRole('radio',{name:/Cable/}).click();
    await page.getByRole('button',{name:'Keep on top',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#pin-window').getAttribute('aria-pressed')==='true');
    await page.getByRole('button',{name:'Keep on top',exact:true}).click();
    // A same-origin message from the mirror iframe represents a decoded display size.
    const mirror = page.frames().find(frame=>frame.parentFrame()===page.mainFrame());
    await mirror.evaluate(()=>parent.postMessage({source:'pane-display',width:932,height:430},parent.location.origin));
    await page.waitForFunction(()=>{const css=getComputedStyle(document.documentElement);return (parseFloat(css.getPropertyValue('--phone-width'))-16)/(parseFloat(css.getPropertyValue('--phone-height'))-16)>2;});
    await mirror.evaluate(()=>parent.postMessage({source:'pane-display',width:390,height:844},parent.location.origin));
    await page.waitForFunction(w=>parseInt(getComputedStyle(document.documentElement).getPropertyValue('--phone-width'))===w-28,compact.width);
    await page.screenshot({path:path.join(output,'pane-expanded.png')});
    await page.getByRole('button',{name:'Close connection sidebar',exact:true}).click();
    await page.waitForFunction(w=>innerWidth===w,compact.width);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'native-ui.json'),JSON.stringify({ok:true,compact,checks:['native client dimensions','expand/collapse','iOS 27 guide','AltStore fallback','transport tabs','pin toggle','simulated display aspect','no page errors']},null,2));
    console.log('PASS: native window, drawer, guide/AltStore, tabs, pinning, display aspect, and page errors.');
  } finally {
    if(page) await page.getByRole('button',{name:'Close Pane',exact:true}).click().catch(()=>{});
    if(browser) await browser.close();
    for(let i=0;i<30&&child.exitCode===null;i++)await sleep(200);
    if(child.exitCode===null)child.kill();
    fs.writeFileSync(path.join(output,'native-ui.log'),logs);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
