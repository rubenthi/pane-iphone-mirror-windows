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
        result = {'ok': True, 'version': VERSION, 'checks': ['dependency imports', 'bundled updater', 'HTTP UI']}
    except Exception as error:
        import traceback
        result['error'] = str(error)
        result['traceback'] = traceback.format_exc()
    Path(output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
