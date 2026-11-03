(() => {
  const arrow = document.querySelector('#drawer-toggle');
  const drawer = document.querySelector('#connection-drawer');
  let expanded = false;
  let aspect = 390 / 844;
  let native = false;
  let chain = Promise.resolve();
  function render(state) {
    native = state.native;
    document.documentElement.style.setProperty('--rail-scale',state.rail_scale??1);
    document.documentElement.style.setProperty('--rail-top',`${state.rail_top??240}px`);
    expanded = state.expanded;
    document.documentElement.style.setProperty('--phone-width', `${state.phone_width}px`);
    document.documentElement.style.setProperty('--phone-height', `${state.height}px`);
    document.body.classList.toggle('drawer-open', expanded);
    document.body.classList.toggle('browser-mode', !native);
    for (const id of ['pin-window','minimize-window','maximize-window','close-window']) document.querySelector('#'+id).hidden = !native;
    drawer.hidden = !expanded;
    document.querySelector('#phone-screen').inert = expanded;
    if (expanded) window.paneReleaseKeys?.();
    arrow.setAttribute('aria-expanded', String(expanded));
    arrow.setAttribute('aria-label', expanded ? 'Close connection sidebar' : 'Open connection sidebar');
    arrow.title=arrow.getAttribute('aria-label');
    document.querySelector('#maximize-window').setAttribute('aria-label',state.maximized?'Restore window':'Maximize window');
    document.querySelector('#pin-window').setAttribute('aria-pressed', String(state.pinned));
  }
  function command(action, extra = {}) {
    const result = chain.then(() => postJson('/api/window', { action, ...extra }));
    chain = result.catch(error => { document.querySelector('#screen-note').textContent = error.message; });
    return result;
  }
  async function layout(open = expanded) {
    render(await command('layout', { expanded: open, aspect }));
  }
  arrow.addEventListener('click', () => layout(!expanded).catch(() => {}));
  document.querySelector('#welcome-setup').addEventListener('click', async () => {
    await layout(true);
    if (document.querySelector('#run-guide').hidden) document.querySelector('#toggle-guide').click();
  });
  document.querySelectorAll('#drag-handle,[data-window-drag]').forEach(handle => {
    let origin=null, moveBusy=false, wantedMove=null;
    async function flushMove(){
      moveBusy=true;
      try{while(wantedMove){const next=wantedMove;wantedMove=null;await command('move',next);}}
      finally{moveBusy=false;}
    }
    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0 || !native) return;
      event.preventDefault(); origin={x:event.screenX,y:event.screenY};
      handle.setPointerCapture(event.pointerId); command('drag').catch(() => {origin=null;});
    });
    handle.addEventListener('pointermove',event=>{
      if(origin){wantedMove={dx:event.screenX-origin.x,dy:event.screenY-origin.y};if(!moveBusy)flushMove().catch(()=>{});}
    });
    const end=()=>{origin=null;};
    handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);handle.addEventListener('lostpointercapture',end);
  });
  for (const action of ['close', 'minimize', 'maximize', 'pin']) {
    document.querySelector(`#${action}-window`).addEventListener('click', () => command(action).then(render).catch(() => {}));
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== document.querySelector('#screen-view').contentWindow || !['pane-display','pane-stream-status'].includes(event.data?.source)) return;
    if(event.data.source==='pane-stream-status'){document.querySelector('#stream-note').textContent=event.data.tone==='ok'?'':event.data.text;arrow.classList.toggle('has-warning',event.data.tone==='warn');return;}
    const { width, height } = event.data;
    const next = width / height;
    if (!Number.isFinite(next) || next < .35 || next > 2.5 || Math.abs(next - aspect) < .005) return;
    aspect = next;
    layout().catch(() => {});
  });

  const cluster=document.querySelector('.handle-cluster');
  let menuTimer;
  cluster.addEventListener('pointerenter',()=>{clearTimeout(menuTimer);cluster.classList.add('menu-open');command('window-menu',{open:true}).catch(()=>{});});
  cluster.addEventListener('pointerleave',()=>{menuTimer=setTimeout(()=>{cluster.classList.remove('menu-open');command('window-menu',{open:false}).catch(()=>{});},250);});
  cluster.addEventListener('focusin',()=>{cluster.classList.add('menu-open');command('window-menu',{open:true}).catch(()=>{});});
  let resizing=null, resizeBusy=false, wantedHeight=null;
  const resizeGrip=document.querySelector('#resize-window');
  resizeGrip.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();resizing={y:event.screenY,height:parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--phone-height'))};resizeGrip.setPointerCapture(event.pointerId);});
  async function flushResize(){resizeBusy=true;try{while(wantedHeight!==null){const height=wantedHeight;wantedHeight=null;render(await command('resize',{height}));}}finally{resizeBusy=false;}}
  resizeGrip.addEventListener('pointermove',event=>{if(!resizing)return;wantedHeight=Math.max(360,Math.min(10000,resizing.height+event.screenY-resizing.y));if(!resizeBusy)flushResize().catch(()=>{});});
  const endResize=()=>{resizing=null;};
  resizeGrip.addEventListener('pointerup',endResize);resizeGrip.addEventListener('pointercancel',endResize);resizeGrip.addEventListener('lostpointercapture',endResize);

  async function initialize() {
    // The browser can load before the launcher has attached the native shell.
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        const state = await getJson('/api/window');
        if (state.native || attempt === 39) { render(state); return; }
      } catch (_) {}
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
  initialize();
})();
