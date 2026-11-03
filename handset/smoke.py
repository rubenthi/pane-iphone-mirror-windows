"""Packaged dependency and local HTTP smoke check; never connects to a phone."""
import http.client
import json
from pathlib import Path
import threading


def run(output):
    result = {'ok': False}
    try:
        from pymobiledevice3.remote.core_device.screen_stream import ScreenStreamServer
        from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
        from pymobiledevice3.remote import userspace_tunnel
        from pymobiledevice3 import bonjour
        from handset.server import Handler, SingleServer
        from handset.version import VERSION
        import webview
        assert hasattr(ScreenStreamServer, '_ensure_fresh_stream')
        assert hasattr(userspace_tunnel.UserspaceRsdTunnel, '_aopen_locked')
        assert hasattr(bonjour, '_bind_ipv4') and hasattr(bonjour, '_send_query_all')
        assert Path(__file__).with_name('install_update.ps1').is_file()
        server = SingleServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                conn.request('GET', '/')
                response = conn.getresponse()
                assert response.status == 200 and b'Pane' in response.read()
            finally:
                conn.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(5)
        verify_native_window()
        result = {'ok': True, 'version': VERSION, 'checks': ['dependency imports', 'bundled updater', 'HTTP UI', 'WebView2 renderer', 'native window region', 'drawer sizing', 'WebCodecs API']}
    except Exception as error:
        import traceback
        result['error'] = str(error)
        result['traceback'] = traceback.format_exc()
    Path(output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


def verify_native_window():
    """Exercise the real packaged WinForms/WebView2 renderer without any phone API."""
    import ctypes
    from ctypes import wintypes as W
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import os
    import tempfile
    import time
    import webview
    from handset.window import FloatingWindow
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            body=b'<!doctype html><title>Pane smoke test</title><body style="margin:0;background:#101617;color:white">Pane runtime check</body>'
            self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Page)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    window=webview.create_window('Pane runtime check',f'http://127.0.0.1:{server.server_port}',width=388,height=760,frameless=True,easy_drag=False,resizable=False)
    errors=[]
    def verify():
        try:
            shell=FloatingWindow()
            assert shell.attach(os.getpid()), 'Native window did not attach'
            for expanded in (False,True,False):
                state=shell.layout(expanded,390/844)
                time.sleep(.2)
                viewport=window.evaluate_js('({width:innerWidth,height:innerHeight,decoder:typeof VideoDecoder})')
                assert viewport['width']==state['width'] and viewport['height']==state['height'], (viewport,state)
                assert viewport['decoder']=='function', 'WebCodecs VideoDecoder unavailable'
            shell.u.GetWindowRgn.argtypes=[W.HWND,W.HRGN]
            shell.g.PtInRegion.argtypes=[W.HRGN,ctypes.c_int,ctypes.c_int]
            region=shell.g.CreateRoundRectRgn(0,0,1,1,0,0)
            try:
                assert shell.u.GetWindowRgn(shell.handle,region)>0
                assert not shell.g.PtInRegion(region,0,0), 'Corner should be outside shaped window'
                assert shell.g.PtInRegion(region,100,100), 'Phone body missing from region'
                assert not shell.g.PtInRegion(region,state['phone_width']+3,100), 'Gap outside phone must not capture input'
                assert not shell.g.PtInRegion(region,state['width']-1,1), 'Blank rectangular corner must not capture input'
            finally:
                shell.g.DeleteObject(region)
        except Exception as error:
            errors.append(repr(error))
        finally:
            window.destroy()
    window.events.loaded += verify
    try:
        webview.start(gui='edgechromium',storage_path=tempfile.mkdtemp(prefix='Pane-smoke-view-'))
    finally:
        server.shutdown();server.server_close();thread.join(5)
    if errors:
        raise RuntimeError('; '.join(errors))
