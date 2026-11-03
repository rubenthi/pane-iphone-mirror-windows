const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const events = {};
  const docEvents = {};
  const context = {window:{addEventListener:(name,fn)=>{events[name]=fn;}},
    document:{addEventListener:(name,fn)=>{docEvents[name]=fn;},visibilityState:'visible'}};
  vm.runInNewContext(fs.readFileSync('handset/web/keys.js','utf8'), context);
  const sent=[], pastes=[]; let homes=0, typing=false, enabled=true;
  context.window.HandsetKeys.attach({
    post: async value => sent.push(JSON.parse(JSON.stringify(value))),
    enabled: () => enabled, home: async () => {homes++;},
    typing: () => typing, setTyping:value => {typing=value;},
    paste: async payload => pastes.push(payload)
  });
  const key = (code, props={}) => {
    const event={code,key:code === 'KeyA'?'a':code === 'Space'?' ':code,
      target:{tagName:'CANVAS'},preventDefault(){this.prevented=true;},
      stopPropagation(){},...props};
    events.keydown(event);return event;
  };
  return {key, events, docEvents, sent,pastes,get homes(){return homes;},get typing(){return typing;},disable(){enabled=false;}};
}
test('Space is Home only in navigation, never repeats or replaces typed spaces', async () => {
  const s=setup();
  s.key('Space');s.key('Space',{repeat:true});await tick();
  assert.equal(s.homes,1);assert.deepEqual(s.sent,[]);
  s.key('KeyA');s.key('Space');await tick();
  assert.equal(s.typing,true);
  assert.ok(s.sent.at(-1).usages.includes(0x2c));assert.equal(s.homes,1);
  s.key('F2');await tick();s.key('Space');await tick();
  assert.equal(s.homes,2);
});
test('local fields, IME composition and focused buttons keep normal keyboard behavior', async () => {
  const s=setup();
  assert.equal(s.key('Space',{target:{tagName:'TEXTAREA'}}).prevented,undefined);
  assert.equal(s.key('Space',{isComposing:true}).prevented,undefined);
  assert.equal(s.key('Space',{target:{tagName:'BUTTON',closest:()=>true}}).prevented,undefined);
  s.disable();s.key('Space');await tick();assert.equal(s.homes,0);
});
test('Ctrl+V uses clipboard data rather than sending a premature phone paste', async () => {
  const s=setup();
  assert.equal(s.key('KeyV',{ctrlKey:true}).prevented,undefined);
  s.docEvents.paste({target:{tagName:'CANVAS'},preventDefault(){},
    clipboardData:{files:[],getData:()=> 'hello 🌍\nsecond line'}});
  await tick();
  assert.equal(s.pastes[0].text,'hello 🌍\nsecond line');
  assert.equal(s.sent.length,0);
  assert.equal(s.typing,true);
});
test('blur releases held HID keys', async () => {
  const s=setup();s.key('KeyA');s.events.blur();await tick();
  assert.deepEqual(s.sent,[{usages:[4]},{usages:[]}]);
});
