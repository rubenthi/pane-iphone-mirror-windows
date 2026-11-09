const assert = require('node:assert/strict');
const http = require('node:http');
const {once} = require('node:events');

// A real localhost HTTP upstream for Pane's input proxy. Keep the fixture
// restricted to an ephemeral loopback port and never contact phone hardware.
exports.start = async function start() {
  const events = [];
  const server = http.createServer(async (req, res) => {
    if (req.method !== 'POST') { res.writeHead(503).end(); return; }
    if (!/^Basic /.test(req.headers.authorization || '')) { res.writeHead(401).end(); return; }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    events.push({path: req.url, ...JSON.parse(Buffer.concat(chunks).toString())});
    res.writeHead(200, {'Content-Type':'text/plain'}).end('ok');
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return {port:server.address().port, close:()=>server.close(), events};
};

exports.check = async function check(browser, url, upstream) {
  const page = await browser.newPage({viewport:{width:400,height:700}});
  try {
    await page.goto(url + '/mirror.html', {waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>Boolean(window.HandsetKeys));
    const input = events => page.evaluate(async steps => {
      const box=document.querySelector('#c').getBoundingClientRect();
      for(const [type,id,x,y] of steps) {
        document.body.dispatchEvent(new PointerEvent(type,{pointerId:id,button:0,bubbles:true,
          clientX:box.left+x*box.width,clientY:box.top+y*box.height}));
      }
    },events);
    // Wait for the proxy, not merely delivery of the DOM event.
    const until = async condition => {
      const end=Date.now()+3000;
      while(!condition() && Date.now()<end) await new Promise(r=>setTimeout(r,10));
      assert.ok(condition(), 'Expected input never reached the simulated device');
    };
    await input([['pointerdown',1,.5,.5],['pointerdown',2,.9,.2],['pointerup',2,.9,.2],
      ['pointermove',1,.6,.4],['pointercancel',1,0,0]]);
    await until(()=>upstream.events.at(-1)?.type==='release');
    const touch=upstream.events.filter(e=>e.path==='/touch');
    assert.deepEqual(touch.map(e=>e.type), ['contact','contact','release']);
    assert.equal(touch[0].x,32768);
    assert.deepEqual(touch[2], {...touch[1],type:'release'});
    // Cancelling an armed bottom-edge gesture must not inject Home or a tap.
    await input([['pointerdown',3,.5,1],['pointermove',3,.5,.4],['pointercancel',3,.5,.4]]);
    await page.keyboard.down('Shift');await page.keyboard.down('a');await page.keyboard.up('a');
    await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    await until(()=>upstream.events.filter(e=>e.path==='/key').length===4);
    assert.deepEqual(upstream.events.filter(e=>e.path==='/key').map(e=>e.usages),[[225],[225,4],[225],[]]);
    assert.equal(upstream.events.filter(e=>e.path==='/touch').length,3);
    assert.equal(upstream.events.filter(e=>e.path==='/button').length,0);
  } finally { await page.close(); }
};
