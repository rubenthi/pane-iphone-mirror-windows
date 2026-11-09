// Small, consistent outline icons; inline SVG avoids font-dependent glyphs.
window.paneIcon = function(name) {
  const paths = {
    play: '<path d="m7 4 9 6-9 6z"/>',
    chevron: '<path d="m8 5 5 5-5 5"/>',
    settings: '<path d="m8 2 4 0 1 3 3 1 2 4-2 3-3 1-1 4H8l-1-4-3-1-2-3 2-4 3-1z"/><circle cx="10" cy="10" r="3"/>',
    bell: '<path d="M4 14h12l-2-3V7a4 4 0 0 0-8 0v4zM8 17h4"/>',
    volume: '<path d="M2 7h4l4-4v14l-4-4H2zM13 7a4 4 0 0 1 0 6m2-9a8 8 0 0 1 0 12"/>',
    'arrow-right': '<path d="M4 10h12m-5-5 5 5-5 5"/>',
    phone: '<rect x="5.5" y="2" width="9" height="16" rx="2.5"/><path d="M8 15.5h4"/>',
    folder: '<path d="M2 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z"/>',
    upload: '<path d="M10 13V3M6 7l4-4 4 4M3 13v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3"/>',
    download: '<path d="M10 3v10m-4-4 4 4 4-4M3 13v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3"/>',
    bluetooth: '<path d="m5 5 10 10-5 3V2l5 3L5 15"/>',
    refresh: '<path d="M16 7a6 6 0 1 0 0 6M16 3v4h-4"/>',
    pin: '<path d="m7 3 7 0-1 5 3 3H4l3-3zM10 11v6"/>',
    usb: '<path d="M10 17V3m-2 2 2-2 2 2M10 13l-5-3V7M10 10l5-3V4"/><circle cx="5" cy="6" r="1"/><rect x="14" y="2" width="2" height="2"/>',
    wifi: '<path d="M2 7a12 12 0 0 1 16 0M5 10a8 8 0 0 1 10 0m-7 3a3 3 0 0 1 4 0"/><circle cx="10" cy="16" r=".5"/>',
    file: '<path d="M5 2h6l4 4v12H5zM11 2v5h4M8 11h4m-4 3h4"/>',
    image: '<rect x="2" y="2" width="16" height="16" rx="3"/><circle cx="7" cy="7" r="1.5"/><path d="m2 15 5-4 3 2 4-5 4 4"/>',
    check: '<path d="m4 10 4 4 8-8"/>',
    close: '<path d="m5 5 10 10M5 15 15 5"/>',
    alert: '<circle cx="10" cy="10" r="8"/><path d="M10 5v6m0 3h.01"/>'
  };
  const span=document.createElement('span');span.className='pane-icon';span.setAttribute('aria-hidden','true');
  span.innerHTML=`<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.file}</svg>`;
  return span;
};
document.querySelectorAll('[data-icon]').forEach(element=>element.replaceWith(window.paneIcon(element.dataset.icon)));
