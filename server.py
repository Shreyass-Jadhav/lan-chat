# server.py
import asyncio
import os
import ssl
import threading
import http.server
import socketserver
import webbrowser
import websockets

from config import HTTP_PORT, WS_PORT, MAX_MESSAGE_SIZE, BASE_DIR, get_lan_ip
from database import Database
from ws_handlers import handle_websocket

CERT, KEY = BASE_DIR / "cert.pem", BASE_DIR / "key.pem"


def tls_context():
    """Enable HTTPS/WSS automatically when cert.pem + key.pem exist (see make_cert.py)."""
    if CERT.exists() and KEY.exists():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(CERT), str(KEY))
        return ctx
    return None


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Static file server limited to the web client (never exposes the DB or .py files)."""
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(BASE_DIR), **kw)

    def _allowed(self):
        p = self.path.split("?")[0]
        return p in ("/", "/index.html", "/manifest.json", "/icon.svg", "/icon-192.png", "/icon-512.png") or p.startswith(("/css/", "/js/"))

    def do_GET(self):
        if not self._allowed():
            return self.send_error(404)
        super().do_GET()

    def do_HEAD(self):
        if not self._allowed():
            return self.send_error(404)
        super().do_HEAD()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, *a):
        pass


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_http_server(ctx):
    try:
        with ReusableTCPServer(("0.0.0.0", HTTP_PORT), QuietHandler) as httpd:
            if ctx:
                httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
            httpd.serve_forever()
    except OSError as exc:
        print(f"[ERROR] HTTP Server failed to start on port {HTTP_PORT}: {exc}")


async def main():
    ip = get_lan_ip()
    db = Database()
    db.ensure_bootstrap_admin()
    admin_pw = db.generated_admin_pass
    db.close()
    ctx = tls_context()
    http_s, ws_s = ("https", "wss") if ctx else ("http", "ws")

    threading.Thread(target=start_http_server, args=(ctx,), daemon=True).start()

    print()
    print("=" * 60)
    print("  LAN CHAT SERVER" + ("  [TLS enabled]" if ctx else ""))
    print("=" * 60)
    print(f"  Local PC:     {http_s}://127.0.0.1:{HTTP_PORT}")
    print(f"  LAN Devices:  {http_s}://{ip}:{HTTP_PORT}")
    print(f"  WebSocket:    {ws_s}://{ip}:{WS_PORT}")
    if ctx:
        print(f"  Self-signed cert: on each device open {http_s}://{ip}:{WS_PORT} once and accept it.")
    if admin_pw:
        print("-" * 60)
        print("  FIRST RUN - admin account created")
        print(f"  Username: admin    Password: {admin_pw}")
        print("  (shown once; change it in the account settings)")
    print("=" * 60)
    print()

    if not os.environ.get("NO_BROWSER"):
        def _open():
            try:
                webbrowser.open(f"{http_s}://127.0.0.1:{HTTP_PORT}")
            except Exception:
                pass
        threading.Timer(1.0, _open).start()

    async with websockets.serve(
        handle_websocket, "0.0.0.0", WS_PORT,
        max_size=MAX_MESSAGE_SIZE, ping_interval=20, ping_timeout=20, ssl=ctx,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Server safely stopped.")
