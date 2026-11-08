const assert = require('node:assert/strict');
module.exports = async function checkRemoteControls(page) {
  // Exercise the real fetch/queue boundary with the pinned service's response.
  const touches = [];
  await page.route('**/mirror/touch', async route => {
    touches.push(route.request().postDataJSON());
    await route.fulfill({contentType: 'text/plain', body: 'ok'});
  });
  await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/mirror/touch') && r.request().postDataJSON().type === 'release'),
    page.locator('[data-gesture="control"]').click(),
  ]);
  assert.equal(touches.filter(e => e.type === 'contact').length, 13);
  await page.unroute('**/mirror/touch');
  await page.evaluate(()=>{
    window.controlEvents=[];
    window.paneControl=async(path,payload)=>window.controlEvents.push({path,...payload});
  });
  const home=page.locator('[data-gesture="home"]');
  await home.click();
  await page.waitForFunction(()=>window.controlEvents.length===1);
  assert.deepEqual(await page.evaluate(()=>window.controlEvents),[{path:'/button',name:'home',state:'press'}]);
  await page.evaluate(()=>window.controlEvents=[]);
  await home.hover(); await page.mouse.down(); await page.waitForTimeout(750); await page.mouse.up();
  await page.waitForTimeout(100);
  assert.deepEqual(await page.evaluate(()=>window.controlEvents),[{path:'/button',name:'siri',state:'press'}]);
  // Leaving the Home target cancels a hold, including its eventual click.
  await page.evaluate(()=>window.controlEvents=[]);
  await home.hover(); await page.mouse.down(); await page.mouse.move(150,200); await page.waitForTimeout(700); await page.mouse.up();
  assert.deepEqual(await page.evaluate(()=>window.controlEvents),[]);
  for(const panel of ['notifications','control']) {
    await page.evaluate(()=>window.controlEvents=[]);
    await page.locator(`[data-gesture="${panel}"]`).dblclick({delay:30});
    await page.waitForFunction(()=>window.controlEvents.filter(e=>e.type==='release').length===2);
    const events=await page.evaluate(()=>window.controlEvents);
    assert.equal(events[0].type,'contact');
    assert.equal(events[0].y,0);
    assert.equal(events[0].x,panel==='notifications'?16000:58000);
    assert.equal(events.filter(e=>e.type==='release').length,2);
    assert.ok(events.every(e=>e.path==='/touch'));
  }
  // App switcher opens with two Home taps; each press sends its own pair.
  await home.click(); await page.evaluate(()=>window.controlEvents=[]);
  await page.locator('[data-gesture="switcher"]').dblclick({delay:30});
  await page.waitForFunction(()=>window.controlEvents.length===4);
  assert.ok((await page.evaluate(()=>window.controlEvents)).every(e=>e.name==='home'));
  // Another button breaks the repeat chain; changing panels must not send Home.
  await page.evaluate(()=>window.controlEvents=[]);
  await page.locator('[data-gesture="notifications"]').click();
  await page.waitForFunction(()=>window.controlEvents.at(-1)?.type==='release');
  await page.locator('.rail-button[data-btn="volume-up"]').click();
  await page.locator('[data-gesture="notifications"]').click();
  await page.locator('[data-gesture="control"]').click();
  await page.waitForFunction(()=>window.controlEvents.filter(e=>e.type==='release').length===3);
  assert.equal(await page.evaluate(()=>window.controlEvents.some(e=>e.name==='home')),false);
  await home.click();
  // A failed opening attempt must not make the next click dismiss an unopened panel.
  await page.evaluate(()=>{
    let fail=true;
    window.controlEvents=[];
    window.paneControl=async(path,payload)=>{
      window.controlEvents.push({path,...payload});
      if(fail){fail=false;throw new Error('Synthetic disconnect');}
    };
  });
  await page.locator('[data-gesture="notifications"]').click();
  await page.waitForFunction(()=>document.querySelector('#screen-note').textContent==='Phone not connected. Unlock it and reconnect.');
  await page.evaluate(()=>window.controlEvents=[]);
  await page.locator('[data-gesture="notifications"]').click();
  await page.waitForFunction(()=>window.controlEvents.at(-1)?.type==='release');
  assert.equal(await page.evaluate(()=>window.controlEvents.some(e=>e.name==='home')),false);
  await home.click();
  assert.match(await page.locator('.usage-guide').textContent(),/How to use Pane/);
  console.log('PASS: Home click/hold/cancel, panel toggles, failed gesture recovery and usage guide');
};
