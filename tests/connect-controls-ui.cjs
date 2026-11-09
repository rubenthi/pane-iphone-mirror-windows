const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
(async()=>{
  const input=require('./input-proxy.cjs');
  const upstream=await input.start();
  const child=spawn(process.env.PANE_TEST_PYTHON||'python',['tests/browser_preview.py'],{env:{...process.env,PANE_STREAM_PORT:String(upstream.port)},stdio:['ignore','pipe','pipe'],windowsHide:true});
  let browser,logs='';child.stderr.on('data',data=>logs+=data);
  try {
    const url=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(logs||'Preview not ready')),10000);child.stdout.once('data',d=>{clearTimeout(timer);resolve(d.toString().trim().split(' ').at(-1));});});
    browser=await chromium.launch({headless:true});const page=await browser.newPage();
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    let screen={phase:'idle'};const connects=[],controls=[];
    await page.route('**/api/setup',r=>r.fulfill({json:{phase:'idle',onboardingRequired:false,boundUdid:'phone'}}));
    await page.route('**/api/status',r=>r.fulfill({json:{driver:{ready:true},library:{ready:true},devices:[],wifi:{paired:['phone']},screen}}));
    await page.route('**/api/screen',r=>{
      if(r.request().method()==='POST'){connects.push(r.request().postDataJSON());screen={phase:'error',error:'Traceback internal socket failure /private/test-secret'};}
      return r.fulfill({json:screen});
    });
    await page.route('**/mirror.html',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><title>Mock mirror</title>'}));
    await page.route('**/mirror/button',r=>{controls.push(r.request().postDataJSON());return r.fulfill({body:'ok'});});
    await page.goto(url);await page.waitForFunction(()=>window.paneLastSnapshot?.wifi?.paired?.includes('phone'));
    await page.getByRole('button',{name:'Connect your iPhone',exact:false}).click();
    await page.waitForFunction(()=>document.querySelector('#placeholder-hint').textContent.includes('reconnect'));
    assert.equal(connects.length,1);assert.deepEqual(connects[0],{udid:'phone',transport:'wifi'});
    assert.equal(await page.locator('#connection-drawer').isVisible(),false);
    assert.doesNotMatch(await page.locator('#placeholder-hint').innerText(),/Traceback|socket|private|test-secret/);
    screen={phase:'running',udid:'phone',transport:'wifi'};await page.evaluate(s=>renderScreen(s),screen);
    const up=page.locator('.rail-navigation [data-btn="volume-up"]'),down=page.locator('.rail-navigation [data-btn="volume-down"]');
    await up.dispatchEvent('wheel',{deltaY:-80,deltaMode:0,cancelable:true});
    await down.dispatchEvent('wheel',{deltaY:80,deltaMode:0,cancelable:true});
    await page.waitForTimeout(100);
    assert.deepEqual(controls.map(c=>c.name),['volume-up','volume-down']);
    await up.dispatchEvent('wheel',{deltaY:80,ctrlKey:true,cancelable:true});
    screen={phase:'idle'};await page.evaluate(s=>renderScreen(s),screen);
    await up.dispatchEvent('wheel',{deltaY:-80,cancelable:true});await page.waitForTimeout(50);
    assert.equal(controls.length,2);assert.deepEqual(errors,[]);
    await input.check(browser,url,upstream);
    console.log('PASS: Real keyboard and touch messages traversed the authenticated Pane proxy.');
    console.log('PASS: Connect attempts Wi-Fi immediately; safe short failures; wheel volume directions and disabled/zoom guards.');
  } finally {if(browser)await browser.close();child.kill();upstream.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
