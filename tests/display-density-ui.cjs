// Real browser rendering at monitor-like scales; disposable state, no phone IO.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const output=path.join(root,'test-results','display-density');
  fs.mkdirSync(output,{recursive:true});
  const child=spawn(process.env.PANE_TEST_PYTHON||'python3',['tests/browser_preview.py'],
    {cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
  let browser,logs='';
  child.stderr.on('data',data=>{logs+=data;});
  try{
    const url=await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error(logs||'Density fixture startup timed out')),10000);
      child.stdout.once('data',data=>{clearTimeout(timer);resolve(data.toString().trim().split(' ').at(-1));});
      child.once('exit',()=>{clearTimeout(timer);reject(Error(logs||'Density fixture exited'));});
    });
    browser=await chromium.launch({executablePath:process.env.PANE_TEST_CHROMIUM||undefined,
      headless:true,args:['--no-sandbox']});
    const results=[];
    const viewport={width:420,height:800};
    for(const density of [1,1.25,1.5,2]){
      const context=await browser.newContext({viewport,deviceScaleFactor:density,reducedMotion:'reduce'});
      try{
        const page=await context.newPage(),errors=[];
        page.on('pageerror',error=>errors.push(error.message));
        await page.route('**/api/setup',route=>route.fulfill({json:{phase:'idle',onboardingRequired:false,boundUdid:'density-fixture'}}));
        await page.route('**/api/window',async route=>{
          const response=await route.fetch();
          await route.fulfill({json:{...(await response.json()),native:true}});
        });
        await page.goto(url);
        await page.evaluate(()=>window.paneExperience.ready);
        await page.waitForFunction(()=>!document.body.classList.contains('browser-mode')&&document.querySelectorAll('.pane-icon svg').length>0);
        await page.evaluate(()=>document.fonts.ready);
        const geometry=await page.evaluate(()=>{
          const phone=document.querySelector('#phone-shell'),screen=document.querySelector('#phone-screen');
          const outer=phone.getBoundingClientRect(),inner=screen.getBoundingClientRect();
          return {density:devicePixelRatio,viewport:{width:innerWidth,height:innerHeight},
            bezel:[inner.left-outer.left,inner.top-outer.top,outer.right-inner.right,outer.bottom-inner.bottom],
            background:getComputedStyle(phone).backgroundColor,
            radius:getComputedStyle(phone).borderTopLeftRadius,
            icons:[...document.querySelectorAll('.pane-icon svg')].map(svg=>({
              tag:svg.tagName.toLowerCase(),width:svg.viewBox.baseVal.width,height:svg.viewBox.baseVal.height,
              imageRendering:getComputedStyle(svg).imageRendering,
              vectorShapes:svg.querySelectorAll('path,circle,rect,line,polyline,polygon,ellipse').length}))};
        });
        assert.equal(geometry.density,density);
        assert.deepEqual(geometry.viewport,viewport,'Monitor density must not change logical viewport dimensions');
        assert.ok(geometry.bezel.every(side=>Math.abs(side-3)<.05),`Unequal bezel at DPR ${density}: ${geometry.bezel}`);
        assert.equal(geometry.background,'rgb(0, 0, 0)');
        assert.equal(geometry.radius,'44px');
        assert.ok(geometry.icons.length>0);
        assert.ok(geometry.icons.every(icon=>icon.tag==='svg'&&icon.width>0&&icon.height>0&&icon.vectorShapes>0
          &&!['pixelated','crisp-edges'].includes(icon.imageRendering)),'UI icons must retain vector shapes and smooth rendering');
        const screenshot=await page.screenshot({path:path.join(output,`ui-${density}.png`),omitBackground:true});
        assert.equal(screenshot.readUInt32BE(16),viewport.width*density,'PNG width must use physical device pixels');
        assert.equal(screenshot.readUInt32BE(20),viewport.height*density,'PNG height must use physical device pixels');
        const edge=await page.evaluate(async({png,density})=>{
          const bytes=Uint8Array.from(atob(png),c=>c.charCodeAt(0));
          const image=await createImageBitmap(new Blob([bytes],{type:'image/png'}));
          try{
            const probe=document.createElement('canvas');probe.width=probe.height=Math.ceil(50*density);
            const ctx=probe.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0);
            const pixels=ctx.getImageData(0,0,probe.width,probe.height).data;
            let transparent=0,opaque=0,antialiased=0;
            for(let i=3;i<pixels.length;i+=4){if(pixels[i]===0)transparent++;else if(pixels[i]===255)opaque++;else antialiased++;}
            return {transparent,opaque,antialiased};
          }finally{image.close();}
        },{png:screenshot.toString('base64'),density});
        assert.ok(edge.transparent>0&&edge.opaque>0&&edge.antialiased>0,
          `CSS rounded edge must include antialiased coverage at DPR ${density}: ${JSON.stringify(edge)}`);

        await page.route('**/api/screen',route=>route.fulfill({json:{phase:'running',udid:'density-fixture',transport:'usb',displaySize:{width:1320,height:2868}}}));
        await page.route('**/mirror/**',route=>route.fulfill({status:503,body:'Synthetic density fixture'}));
        await page.evaluate(()=>renderScreen({phase:'running',udid:'density-fixture',transport:'usb'}));
        const picture=page.frames().find(frame=>frame.parentFrame()===page.mainFrame());
        await picture.waitForURL('**/mirror.html');
        await picture.waitForFunction(()=>typeof drawFrame==='function');
        const frame=await picture.evaluate(()=>{
          const source=document.createElement('canvas');source.width=1328;source.height=2896;
          const brush=source.getContext('2d');brush.fillStyle='#ff00ff';brush.fillRect(0,0,1328,2896);
          brush.fillStyle='#00ff00';brush.fillRect(0,0,1320,2868);
          const image=new VideoFrame(source,{timestamp:0});
          try{
            nativeDisplaySize={width:1320,height:2868};drawFrame(image);
            return {width:canvas.width,height:canvas.height,density:devicePixelRatio,
              edge:Array.from(ctx.getImageData(canvas.width-1,canvas.height-1,1,1).data),
              imageRendering:getComputedStyle(canvas).imageRendering};
          }finally{image.close();}
        });
        assert.deepEqual([frame.width,frame.height],[1320,2868],
          'Mirror backing resolution must preserve the full native aperture regardless of DPR');
        assert.equal(frame.density,density);
        assert.deepEqual(frame.edge,[0,255,0,255]);
        assert.ok(!['pixelated','crisp-edges'].includes(frame.imageRendering));
        const mirrorShot=await page.screenshot({path:path.join(output,`mirror-${density}.png`),omitBackground:true});
        assert.deepEqual([mirrorShot.readUInt32BE(16),mirrorShot.readUInt32BE(20)],
          [viewport.width*density,viewport.height*density]);
        assert.deepEqual(errors,[]);
        results.push({density,geometry,edge,frame});
      }finally{await context.close();}
    }
    fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({ok:true,viewport,results},null,2));
    console.log('PASS: DPR 1, 1.25, 1.5 and 2 retain vector UI, antialiased CSS corners, equal black 3px bezel, physical screenshot density and native-resolution mirror frames.');
  }finally{
    if(browser)await browser.close();
    child.kill();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
