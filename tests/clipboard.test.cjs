const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup(fail=false) {
  const sent = [], note = {}, button = {addEventListener(){}};
  const context = {window:{paneSetTyping(){}},TextEncoder,
    document:{querySelector:s=>s==='#paste-note'?note:s==='#paste-iphone'?button:{classList:{contains:()=>true}}}};
  vm.runInNewContext(fs.readFileSync('handset/web/controls.js','utf8'),context);
  context.window.paneControl=context.window.createPaneControlQueue(async(path,payload)=>{
    sent.push({path,payload});
    if(fail && path==='/clipboard')throw Error('Phone clipboard unavailable');
  });
  vm.runInNewContext(fs.readFileSync('handset/web/clipboard.js','utf8'),context);
  return {paste:context.window.panePaste,sent,note};
}
test('Unicode and multiline clipboard is written before Cmd+V and modifiers release',async()=>{
  const s=setup();await s.paste({text:'你好 🌍\nline two'});
  assert.deepEqual(s.sent.map(x=>x.path),['/key','/clipboard','/key','/key']);
  assert.equal(s.sent[1].payload.text,'你好 🌍\nline two');
  assert.deepEqual([...s.sent[2].payload.usages],[227,25]);
  assert.deepEqual([...s.sent[3].payload.usages],[]);
});
test('clipboard failure never pastes stale iPhone clipboard',async()=>{
  const s=setup(true);await assert.rejects(s.paste({text:'new text'}));
  assert.equal(s.sent.some(x=>x.payload.usages?.includes(25)),false);
});
test('empty, oversized and unsupported clipboard content is rejected before sending',async()=>{
  const s=setup();
  await assert.rejects(s.paste({text:''}));
  await assert.rejects(s.paste({text:'x'.repeat(1024*1024)}));
  await assert.rejects(s.paste({image:{type:'image/jpeg',size:10}}));
  assert.deepEqual(s.sent,[]);
});
