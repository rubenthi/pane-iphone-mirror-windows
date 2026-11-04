(() => {
  const select=document.querySelector('#audio-device'), checkbox=document.querySelector('#audio-auto'), note=document.querySelector('#audio-note');
  let busy=false;
  function render(state){
    checkbox.checked=state.enabled;
    note.textContent=state.note || 'Waiting for audio.';
    const signature=JSON.stringify(state.devices||[]);
    if(select.dataset.devices!==signature){
      const previous=select.value;
      select.replaceChildren(new Option('Select paired iPhone…',''),...(state.devices||[]).map(d=>new Option(d.name,d.id)));
      if([...select.options].some(o=>o.value===previous))select.value=previous;
      select.dataset.devices=signature;
    }
  }
  async function act(payload){
    if(busy)return; busy=true;note.textContent='Updating audio connection…';
    document.querySelectorAll('.audio-actions button').forEach(b=>b.disabled=true);
    try{render(await postJson('/api/audio',payload));}catch(e){note.textContent=e.message;}
    finally{busy=false;document.querySelectorAll('.audio-actions button').forEach(b=>b.disabled=false);}
  }
  checkbox.addEventListener('change',()=>act({action:'enable',enabled:checkbox.checked}));
  for(const action of ['refresh','settings','retry'])document.querySelector('#audio-'+action).addEventListener('click',()=>act({action}));
  document.querySelector('#audio-select').addEventListener('click',()=>act({action:'select',device:select.value}));
  async function poll(){try{if(!busy)render(await getJson('/api/audio'));}catch(e){note.textContent=e.message;}finally{setTimeout(poll,2500);}}
  poll();
})();
