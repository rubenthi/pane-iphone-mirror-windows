(() => {
  const arrow = document.querySelector('#drawer-toggle');
  const drawer = document.querySelector('#connection-drawer');
  const fpsSelect = document.querySelector('#fps-target');
  const saved = localStorage.getItem('pane-display-fps');
  if (['15','30','60'].includes(saved)) fpsSelect.value = saved;
  fpsSelect.addEventListener('change', () => localStorage.setItem('pane-display-fps', fpsSelect.value));
  let expanded = false;
  let aspect = 390 / 844;
  let native = false;
  function render(state) {
    native = state.native;
    const height=native?innerHeight:state.height;
    const railScale=native?Math.min(1,Math.max(.15,(height-174)/292)):(state.rail_scale??1);
    document.documentElement.style.setProperty('--rail-scale',railScale);
    document.documentElement.style.setProperty('--rail-top',`${native?Math.max(166,(height-288*railScale)/2):(state.rail_top??240)}px`);
    expanded = state.expanded;
    // Bridge replies can arrive after another resize. The native viewport is
    // authoritative; never repaint an earlier reply's dimensions over it.
    document.documentElement.style.setProperty('--phone-width', `${native?innerWidth-60:state.phone_width}px`);
    document.documentElement.style.setProperty('--phone-height', `${height}px`);
    document.body.classList.toggle('drawer-open', expanded);
    document.body.classList.toggle('browser-mode', !native);
    for (const id of ['pin-window','minimize-window','maximize-window','close-window']) document.querySelector('#'+id).hidden = !native;
    drawer.hidden = !expanded;
    if (expanded) keyboard.releaseAll();
    arrow.setAttribute('aria-expanded', String(expanded));
    arrow.setAttribute('aria-label', expanded ? 'Close connection panel' : 'Open connection panel');
    arrow.title=arrow.getAttribute('aria-label');
    document.querySelector('#maximize-window').setAttribute('aria-label',state.maximized?'Restore window':'Maximize window');
    document.querySelector('#pin-window').setAttribute('aria-pressed', String(state.pinned));
  }
  function command(action, extra = {}) {
    const payload={action,...extra};
    return window.pywebview?.api?.window_command ? window.pywebview.api.window_command(payload).then(result => {if(result.error)throw new Error(result.error);return result;}) : postJson('/api/window',payload);
  }
  let dragReady=Promise.resolve();
  const move=window.createPaneLatestQueue(async payload=>{await dragReady;return command('move',payload);});
  async function layout(open = expanded) {
    render(await command('layout', { expanded: open, aspect }));
  }
  window.paneOpenDrawer = () => layout(true);
  arrow.addEventListener('click', () => layout(!expanded).catch(() => {}));
  window.addEventListener('resize', () => {
    if (!native) return;
    // Follow the viewport in the same paint; don't wait for the bridge reply.
    const height=innerHeight, scale=Math.min(1,Math.max(.15,(height-174)/292));
    document.documentElement.style.setProperty('--phone-width',`${innerWidth-60}px`);
    document.documentElement.style.setProperty('--phone-height',`${height}px`);
    document.documentElement.style.setProperty('--rail-scale',scale);
    document.documentElement.style.setProperty('--rail-top',`${Math.max(166,(height-288*scale)/2)}px`);
  });
  document.querySelectorAll('#drag-handle,[data-window-drag]').forEach(handle => {
    let origin=null;
    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0 || !native) return;
      event.preventDefault(); origin={x:event.screenX,y:event.screenY};
      handle.setPointerCapture(event.pointerId); dragReady=command('drag'); dragReady.catch(() => {origin=null;});
    });
    handle.addEventListener('pointermove',event=>{
      if(origin) move({dx:event.screenX-origin.x,dy:event.screenY-origin.y}).catch(()=>{});
    });
    const end=()=>{origin=null;};
    handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);handle.addEventListener('lostpointercapture',end);
  });
  for (const action of ['close', 'minimize', 'maximize', 'pin']) {
    document.querySelector(`#${action}-window`).addEventListener('click', () => command(action).then(render).catch(() => {}));
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== document.querySelector('#screen-view').contentWindow || !['pane-display','pane-stream-status','pane-video-stats'].includes(event.data?.source)) return;
    if(event.data.source==='pane-video-stats'){
      const s=event.data;
      if([s.width,s.height,s.received,s.presented].every(Number.isFinite)) document.querySelector('#video-performance').textContent=`${s.width} × ${s.height} · received ${s.received.toFixed(1)} FPS · displayed ${s.presented.toFixed(1)} FPS · target ${fpsSelect.value}`;
      return;
    }
    if(event.data.source==='pane-stream-status'){document.querySelector('#stream-note').textContent=event.data.tone==='ok'?'':window.paneNotice(event.data.text);arrow.classList.toggle('has-warning',event.data.tone==='warn');return;}
    const { width, height } = event.data;
    if (![width, height].every(value => Number.isInteger(value) && value > 0 && value <= 16384)) return;
    const next = width / height;
    if (!Number.isFinite(next) || next < .35 || next > 2.5 || Math.abs(next - aspect) < .000001) return;
    aspect = next;
    layout().catch(() => {});
  });

  const cluster=document.querySelector('.handle-cluster');
  let menuTimer;
  cluster.addEventListener('pointerenter',()=>{clearTimeout(menuTimer);cluster.classList.add('menu-open');command('window-menu',{open:true}).catch(()=>{});});
  cluster.addEventListener('pointerleave',()=>{menuTimer=setTimeout(()=>{cluster.classList.remove('menu-open');command('window-menu',{open:false}).catch(()=>{});},250);});
  cluster.addEventListener('focusout',()=>{menuTimer=setTimeout(()=>{if(!cluster.contains(document.activeElement)&&!cluster.matches(':hover')){cluster.classList.remove('menu-open');command('window-menu',{open:false}).catch(()=>{});}},180);});
  cluster.addEventListener('focusin',()=>{cluster.classList.add('menu-open');command('window-menu',{open:true}).catch(()=>{});});
  let resizing=null;
  const resize=window.createPaneLatestQueue(payload=>command('resize',payload),render,true);
  document.querySelectorAll('[data-resize-corner]').forEach(corner=>{
    corner.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;
      event.preventDefault();
      resizing={x:event.screenX,y:event.screenY,height:parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--phone-height')),corner:corner.dataset.resizeCorner};
      corner.setPointerCapture(event.pointerId);
    });
    corner.addEventListener('pointermove',event=>{
      if(!resizing)return;
      const size={corner:resizing.corner,height:window.paneResizeHeight(resizing,event.screenX,event.screenY,aspect)};
      resize(size).catch(error=>{document.querySelector("#screen-note").textContent=window.paneNotice(error.message,'window');});
    });
    const end=()=>{resizing=null;};
    corner.addEventListener('pointerup',end);corner.addEventListener('pointercancel',end);corner.addEventListener('lostpointercapture',end);
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&expanded)layout(false).catch(()=>{});});

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
