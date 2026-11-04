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
    page.on('response', async response=>{if(response.url().endsWith('/api/window') && response.status()>=400) console.log('Window API error:',await response.text());});
    await page.reload();
    await page.waitForFunction(async () => {
      const auth = await fetch('/api/auth').then(r=>r.json());
      const state = await fetch('/api/window',{headers:{'X-Pane-Token':auth.token}}).then(r=>r.json());
      return state.native && innerWidth === state.width && innerHeight === state.height;
    });
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
    assert.equal(await page.locator('#resize-window').count(),0);
    assert.equal(await page.locator('[data-resize-corner]').count(),4);
    const overlay = await page.locator('#connection-drawer').boundingBox();
    const phone = await page.locator('#phone-shell').boundingBox();
    assert.ok(overlay.x >= phone.x && overlay.x + overlay.width <= phone.x + phone.width);
    await page.route('**/api/screen', route=>route.fulfill({json:{phase:'starting'}}));
    await page.route('**/api/screen/stop', route=>route.fulfill({json:{phase:'idle'}}));
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('button',{name:'Disconnect',exact:true}).click();
    await page.getByRole('button',{name:'Connect',exact:true}).waitFor();
    await page.unroute('**/api/screen');
    await page.unroute('**/api/screen/stop');

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
    await page.waitForFunction(()=>{const css=getComputedStyle(document.documentElement);return (parseFloat(css.getPropertyValue('--phone-width'))-14)/(parseFloat(css.getPropertyValue('--phone-height'))-14)>2;});
    await mirror.evaluate(()=>parent.postMessage({source:'pane-display',width:390,height:844},parent.location.origin));
    await page.waitForFunction(w=>parseInt(getComputedStyle(document.documentElement).getPropertyValue('--phone-width'))===w-60,compact.width);
    await page.screenshot({path:path.join(output,'pane-expanded.png')});
    await page.getByRole('button',{name:'Close connection panel',exact:true}).click();
    await page.locator('#connection-drawer').waitFor({state:'hidden'});
    await page.waitForFunction(w=>innerWidth===w,compact.width);
    const handleBox = await page.locator('.rail-grip').boundingBox();
    await page.locator('.handle-cluster').hover();
    await page.waitForFunction(async ()=>(await getJson('/api/window')).region_test.menu);
    await checkRegion(true);
    const minBox = await page.locator('#minimize-window').boundingBox();
    const maxBox = await page.locator('#maximize-window').boundingBox();
    const closeBox = await page.locator('#close-window').boundingBox();
    assert.ok(minBox.y + minBox.height <= handleBox.y - 3);
    assert.ok(closeBox.y + closeBox.height <= maxBox.y && maxBox.y + maxBox.height <= minBox.y);
    assert.equal(await page.locator('.rail-grip').isVisible(),true);
    await page.getByRole('button',{name:'Maximize window',exact:true}).waitFor({state:'visible'});
    assert.equal(await page.locator('.rail-button[aria-label="Volume up"]').getAttribute('title'),'Volume up');
    await page.getByRole('button',{name:'Maximize window',exact:true}).click();
    await page.getByRole('button',{name:'Restore window',exact:true}).click();
    await page.waitForFunction(h=>innerHeight===h,compact.height);
    await page.waitForFunction(h => document.querySelector('.workspace').getBoundingClientRect().height === h, compact.height);
    const grip=await page.locator('.corner-se').boundingBox();
    await page.mouse.move(grip.x+16,grip.y+16);await page.mouse.down();await page.mouse.move(grip.x+16,grip.y-65,{steps:6});await page.mouse.up();
    await page.waitForFunction(h=>innerHeight<h,compact.height);
    await page.mouse.move(150,200);
    // Native resize may move the window under the OS pointer; verify the
    // region against the current requested menu state, whether open or closed.
    await page.waitForFunction(async ()=>{const s=await getJson('/api/window');return innerWidth===s.width&&innerHeight===s.height;});
    await checkRegion();
    await checkDesktopPixels();
    await page.evaluate(async()=>renderScreen({phase:'idle'}));
    assert.deepEqual(errors,[]);
    // Exercise the real mirror document with synthetic full-size video frames.
    // No stream or touch requests are sent to a phone in this test.
    await page.route('**/api/screen', route=>route.fulfill({json:{phase:'running',udid:'test',transport:'usb'}}));
    await page.route('**/mirror/**', route=>route.fulfill({status:503,body:'Synthetic frame test'}));
    await page.evaluate(()=>renderScreen({phase:'running',udid:'test',transport:'usb'}));
    const picture=await page.waitForEvent('framenavigated', {predicate:f=>f.url().endsWith('/mirror.html')}).catch(()=>page.frames().find(f=>f.url().endsWith('/mirror.html')));
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
    // Synthetic folded/unfolded-like sizes; these are not claimed Duo specs.
    // Every frame passes through the actual canvas -> shell -> native resize path.
    for (const [width,height] of [[1290,2796],[1800,1920],[1920,1800],[2532,1170],[1170,2532]]) {
      console.log('Live display target:',width,height);
      await picture.evaluate(({width,height})=>{
        const source=document.createElement('canvas');source.width=width;source.height=height;
        const brush=source.getContext('2d');brush.fillStyle='#153b64';brush.fillRect(0,0,width,height);
        const frame=new VideoFrame(source,{timestamp:0});drawFrame(frame);
        lastFrame?.close();lastFrame=frame;
      },{width,height});
      await page.waitForFunction(({width,height})=>{
        const screen=document.querySelector('#phone-screen').getBoundingClientRect();
        return Math.abs(screen.width/screen.height-width/height)<.002;
      },{width,height}).catch(async error=>{
        console.log('Display mismatch:', await page.evaluate(async()=>({native:await getJson('/api/window'),screen:document.querySelector('#phone-screen').getBoundingClientRect().toJSON(),note:document.querySelector('#screen-note').textContent})), await picture.evaluate(()=>({width:canvas.width,height:canvas.height})));
        throw error;
      });
      await picture.waitForFunction(({width,height})=>{
        const r=canvas.getBoundingClientRect();
        return Math.abs(innerWidth/innerHeight-width/height)<.002 &&
          Math.abs(r.width/ r.height-width/height)<.0001 &&
          r.left>=-1 && r.top>=-1 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1 &&
          innerWidth-r.width<2 && innerHeight-r.height<2;
      },{width,height});
      assert.deepEqual(await picture.evaluate(()=>{const r=canvas.getBoundingClientRect();return touchCoords({clientX:r.left+r.width/2,clientY:r.top+r.height/2});}),{x:32768,y:32768});
      await checkRegion();
    }
    await checkDesktopPixels();
    const bezel=await page.evaluate(()=>{const outer=document.querySelector('#phone-shell').getBoundingClientRect(),inner=document.querySelector('#phone-screen').getBoundingClientRect();return [inner.left-outer.left,inner.top-outer.top,outer.right-inner.right,outer.bottom-inner.bottom];});
    assert.deepEqual(bezel,[7,7,7,7]);
    await page.screenshot({path:path.join(output,'pane-glass-live-synthetic.png')});

    fs.writeFileSync(path.join(output,'native-ui.json'),JSON.stringify({ok:true,compact,checks:['live display aspect changes including near-square and landscape','actual desktop pixels outside the shape','equal four-sided bezel','actual HWND shape and managed region','upward hover menu geometry','Home hold Siri','single-action panel gestures','usage guide','native client dimensions','expand/collapse','iOS 27 guide','AltStore fallback','transport tabs','pin toggle','simulated display aspect','hover window menu','maximize/restore','proportional resize','full-frame canvas','wheel-to-touch mapping','no phone overlays','no page errors']},null,2));
    console.log('PASS: native window, drawer, guide/AltStore, tabs, pinning, display aspect, and page errors.');
  } finally {
    if(page) await page.evaluate(async()=>{const auth=await fetch('/api/auth').then(r=>r.json());await fetch('/api/window',{method:'POST',headers:{'X-Pane-Token':auth.token,'Content-Type':'application/json'},body:JSON.stringify({action:'close'})});}).catch(()=>{});
    if(browser) await browser.close();
    for(let i=0;i<30&&child.exitCode===null;i++)await sleep(200);
    if(child.exitCode===null)child.kill();
    fs.writeFileSync(path.join(output,'native-ui.log'),logs);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
