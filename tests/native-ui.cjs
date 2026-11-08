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
      return state.native && state.windows_identity && innerWidth === state.width && innerHeight === state.height;
    });
    const windowsIdentity=(await page.evaluate(()=>getJson('/api/window'))).windows_identity;
    assert.deepEqual(windowsIdentity,{app_id:'Pane.Desktop.Development',form_icon_matches:true,small_icon:true,large_icon:true});
    await page.evaluate(()=>load());
    await page.getByText('No iPhone detected.',{exact:true}).waitFor({state:'attached'});
    assert.equal(await page.locator('#connection-drawer').isVisible(),false);
    async function checkRegion(menu) {
      const state = await page.evaluate(()=>getJson('/api/window'));
      menu ??= state.menu_open;
      assert.deepEqual(state.region_test, {kind:3, phone:true, corner:false, above_rail:false, below_rail:false, rail:true, menu, exact_handle:true, managed_region:true}, JSON.stringify(state));
    }
    await checkRegion();
    async function checkDesktopPixels(){
      await page.waitForFunction(async()=>{
        const s=await getJson('/api/window'),p=s.pixels,b=s.backdrop_color;
        return p.corner===b && p.above===b && p.below===b && p.phone!==b;
      },null,{timeout:10000}).catch(async e=>{console.log('Desktop clipping failure:',await page.evaluate(()=>getJson('/api/window')));throw e;});
    }
    await checkDesktopPixels();
    const token=(await (await fetch('http://127.0.0.1:18776/api/auth')).json()).token;
    const windowCommand=action=>fetch('http://127.0.0.1:18776/api/window', {
      method:'POST', headers:{'X-Pane-Token':token,'Content-Type':'application/json'}, body:JSON.stringify({action})
    }).then(r=>r.json());
    await windowCommand('minimize');
    await sleep(650);
    const minimized=await (await fetch('http://127.0.0.1:18776/api/window', {headers:{'X-Pane-Token':token}})).json();
    assert.equal(minimized.minimized,true);
    await windowCommand('focus');
    await page.waitForFunction(async()=>{
      const s=await getJson('/api/window');
      return !s.minimized && s.web_offset.every(v=>v===0);
    });
    await checkDesktopPixels();
    const compact=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    const position=await page.evaluate(()=>({x:screenX,y:screenY}));
    await page.locator('#drag-handle').dispatchEvent('pointerdown',{button:0,pointerId:1,screenX:400,screenY:100});
    await page.locator('#drag-handle').dispatchEvent('pointermove',{pointerId:1,screenX:450,screenY:130});
    await page.locator('#drag-handle').dispatchEvent('pointerup',{pointerId:1});
    await page.waitForFunction(p=>screenX===p.x+50&&screenY===p.y+30,position);
    await page.screenshot({path:path.join(output,'pane-compact.png')});
    await page.getByRole('button',{name:'Open connection panel',exact:true}).click();
    await page.locator('#connection-drawer').waitFor({state:'visible'});
    await page.waitForFunction(w=>innerWidth===w,compact.width);
    assert.equal(await page.evaluate(()=>innerHeight),compact.height);
    assert.equal(await page.locator('[data-resize-corner]').count(),4);
    const overlay=await page.locator('#connection-drawer').boundingBox();
    const phone=await page.locator('#phone-shell').boundingBox();
    assert.ok(overlay.x>=phone.x && overlay.x+overlay.width<=phone.x+phone.width);
    await checkRegion();

    await page.locator('#toggle-guide').click();
    await page.locator('#run-guide').waitFor({state:'visible'});
    const developer = page.locator('#run-guide > details').filter({has:page.locator('summary', {hasText:'Install Pane'})});
    await developer.locator(':scope > summary').click();
    await page.locator('.altstore-guide > summary').click();
    assert.equal(await page.locator('.altstore-guide').getAttribute('open'),'');
    assert.match(await page.locator('.altstore-guide').innerText(), /Install AltStore/);
    assert.match(await page.locator('.altstore-guide').innerText(), /iTunes and iCloud/);
    await page.screenshot({path:path.join(output,'pane-guide.png')});
    await page.getByRole('tab',{name:'Connection',exact:true}).click();
    await page.getByRole('radio',{name:/Wi-Fi/}).click();
    await page.getByRole('heading',{name:'Wireless connection'}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Set up Wi-Fi',exact:true}).isDisabled(),true);
    await page.getByRole('radio',{name:/Cable/}).click();
    await page.getByRole('button',{name:'Keep on top',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#pin-window').getAttribute('aria-pressed')==='true');
    await page.getByRole('button',{name:'Keep on top',exact:true}).click();
    // A same-origin message from the mirror iframe represents a decoded display size.
    const mirror = page.frames().find(frame=>frame.parentFrame()===page.mainFrame());
    await mirror.evaluate(()=>parent.postMessage({source:'pane-display',width:932,height:430},parent.location.origin));
    await page.waitForFunction(()=>{const css=getComputedStyle(document.documentElement);return (parseFloat(css.getPropertyValue('--phone-width'))-14)/(parseFloat(css.getPropertyValue('--phone-height'))-14)>2;});
    await mirror.evaluate(()=>parent.postMessage({source:'pane-display',width:390,height:844},parent.location.origin));
    await page.waitForFunction(w=>parseInt(getComputedStyle(document.documentElement).getPropertyValue('--phone-width'))===w-60,compact.width);
    await page.screenshot({path:path.join(output,'pane-expanded.png')});
    await page.getByRole('button',{name:'Close connection panel',exact:true}).click();
    await page.locator('#connection-drawer').waitFor({state:'hidden'});
    await page.waitForFunction(w=>innerWidth===w,compact.width);
    await page.locator('.handle-cluster').hover();
    await page.getByRole('button',{name:'Maximize window',exact:true}).waitFor({state:'visible'});
    assert.equal(await page.locator('.rail-button[aria-label="Volume up"]').getAttribute('title'),'Volume up');
    await page.getByRole('button',{name:'Maximize window',exact:true}).click();
    // Resizing moves the hover menu away from the pointer on larger monitors.
    await page.waitForFunction(async () => {
      const state = await getJson('/api/window');
      return state.maximized && innerWidth === state.width && innerHeight === state.height;
    });
    await page.locator('.rail-grip').hover();
    await page.getByRole('button',{name:'Restore window',exact:true}).click();
    await page.waitForFunction(h=>innerHeight===h,compact.height);
    await page.waitForFunction(h=>document.querySelector('.workspace').getBoundingClientRect().height===h,compact.height);
    const grip=await page.locator('[data-resize-corner=se]').boundingBox();
    await page.mouse.move(grip.x+8,grip.y+8);await page.mouse.down();await page.mouse.move(grip.x+8,grip.y-145,{steps:6});await page.mouse.up();
    await page.waitForFunction(h=>innerHeight<h,compact.height);
    // Exercise the Python bridge without rendering its reply: the viewport
    // resize event must size the shell in the browser's next paint.
    const resizeLatency=await page.evaluate(async()=>{
      const measurements=[], initial=innerHeight;
      for(const corner of ['se','sw','ne','nw']){
        for(const height of [initial+24,initial]){
          const before=(await getJson('/api/window')).native_rect;
          const started=performance.now();
          const state=await window.pywebview.api.window_command({action:'resize',corner,height});
          if(state.error)throw new Error(state.error);
          const deadline=started+1000;
          while(innerHeight!==state.height || document.querySelector('.workspace').getBoundingClientRect().height!==innerHeight){
            if(performance.now()>deadline)throw new Error('Native resize did not paint matching shell geometry within one second.');
            await new Promise(resolve=>requestAnimationFrame(resolve));
          }
          measurements.push(performance.now()-started);
          const after=(await getJson('/api/window')).native_rect;
          const anchorX=corner.includes('w')?2:0, anchorY=corner.includes('n')?3:1;
          if(before[anchorX]!==after[anchorX] || before[anchorY]!==after[anchorY])throw new Error(`Resize moved the opposite corner: ${corner}`);
        }
      }
      return measurements;
    });
    await sleep(200);
    const resizeState=await page.evaluate(()=>getJson('/api/window'));
    assert.ok(resizeState.resize_timings.length>=8,'native resize timings were sampled');
    assert.ok(resizeState.resize_paints.length>0,'desktop repaint was sampled during native resizing');
    assert.ok(Math.max(...resizeState.resize_timings)<500,`native resize blocked: ${JSON.stringify(resizeState.resize_timings)}`);
    assert.ok(Math.max(...resizeLatency)<1000,`resize presentation was delayed: ${JSON.stringify(resizeLatency)}`);
    assert.ok(Math.max(...resizeState.resize_paints)<7,`white native resize surface: ${JSON.stringify(resizeState.resize_paints)}`);
    await checkRegion();
    await checkDesktopPixels();
    const resizeEvidence={nativeMs:resizeState.resize_timings,presentedMs:resizeLatency.map(v=>Math.round(v)),desktopSamples:resizeState.resize_paints.length,maxWhitePoints:Math.max(...resizeState.resize_paints)};
    console.log('Resize timing (ms):',JSON.stringify(resizeEvidence));
    await page.evaluate(async()=>renderScreen({phase:'idle'}));
    assert.deepEqual(errors,[]);
    // Exercise the real mirror document with synthetic full-size video frames.
    // No stream or touch requests are sent to a phone in this test.
    await page.route('**/api/screen', route=>route.fulfill({json:{phase:'running',udid:'test',transport:'usb'}}));
    await page.route('**/mirror/**', route=>route.fulfill({status:503,body:'Synthetic frame test'}));
    await page.evaluate(()=>renderScreen({phase:'running',udid:'test',transport:'usb'}));
    const picture=page.frames().find(f=>f.parentFrame()===page.mainFrame());
    await picture.waitForURL('**/mirror.html');
    await picture.waitForFunction(()=>typeof drawFrame==='function');
    const geometry=await picture.evaluate(()=>{
      const source=document.createElement('canvas');source.width=1170;source.height=2532;
      const brush=source.getContext('2d');brush.fillStyle='red';brush.fillRect(0,0,1170,1266);brush.fillStyle='blue';brush.fillRect(0,1266,1170,1266);
      const frame=new VideoFrame(source,{timestamp:0});drawFrame(frame);lastFrame=frame;
      const r=canvas.getBoundingClientRect();return {width:r.width,height:r.height,viewportWidth:innerWidth,viewportHeight:innerHeight,top:r.top,bottom:r.bottom,center:touchCoords({clientX:r.left+r.width/2,clientY:r.top+r.height/2})};
    });
    console.log('Mirror geometry:',JSON.stringify(geometry));
    assert.ok(Math.abs(geometry.width/geometry.height-1170/2532)<.002);
    assert.ok(geometry.top>=-1 && geometry.bottom<=geometry.viewportHeight+1);
    assert.equal(geometry.center.x,32768);assert.equal(geometry.center.y,32768);
    await page.evaluate(()=>{window.testTouches=[];window.originalPaneControl=window.paneControl;window.paneControl=async(path,payload)=>window.testTouches.push({path,...payload});});
    await picture.evaluate(()=>{const r=canvas.getBoundingClientRect();canvas.dispatchEvent(new WheelEvent('wheel',{deltaY:100,clientX:r.left+r.width/2,clientY:r.top+r.height/2,bubbles:true,cancelable:true}));});
    await page.waitForFunction(()=>window.testTouches.some(t=>t.type==='release'));
    const touches=await page.evaluate(()=>window.testTouches);
    assert.equal(touches[0].type,'contact');assert.equal(touches.at(-1).type,'release');assert.ok(touches.at(-1).y<touches[0].y);
    assert.equal(await page.locator('#phone-shell .phone-toolbar').count(),0);
    assert.equal(await page.locator('#phone-shell .phone-status').count(),0);
    await page.evaluate(()=>{window.paneControl=window.originalPaneControl;});
    await require('./remote-controls.cjs')(page);
    await page.screenshot({path:path.join(output,'pane-glass-live-synthetic.png')});

    fs.writeFileSync(path.join(output,'native-ui.json'),JSON.stringify({ok:true,compact,windowsIdentity,resizeEvidence,checks:['Windows application identity and Pane icons','native client dimensions','expand/collapse','iOS 27 guide','AltStore fallback','transport tabs','pin toggle','simulated display aspect','hover window menu','maximize/restore','proportional resize','four-corner anchoring','resize latency and transient desktop pixels','full-frame canvas','wheel-to-touch mapping','no phone overlays','no page errors']},null,2));
    console.log('PASS: native window, drawer, guide/AltStore, tabs, pinning, display aspect, and page errors.');
  } catch(error) {
    console.log('Native preview diagnostics:',logs);
    if(page) console.log(await page.evaluate(()=>({status:document.querySelector('#status-note')?.textContent,devices:document.querySelector('#devices')?.textContent,setup:document.querySelector('#onboarding-note')?.textContent})).catch(()=>({})));
    throw error;
  } finally {
    if(page) await page.evaluate(async()=>{const auth=await fetch('/api/auth').then(r=>r.json());await fetch('/api/window',{method:'POST',headers:{'X-Pane-Token':auth.token,'Content-Type':'application/json'},body:JSON.stringify({action:'close'})});}).catch(()=>{});
    if(browser) await browser.close();
    for(let i=0;i<30&&child.exitCode===null;i++)await sleep(200);
    if(child.exitCode===null)child.kill();
    fs.writeFileSync(path.join(output,'native-ui.log'),logs);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
