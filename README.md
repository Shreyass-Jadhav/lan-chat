# LAN Chat — Crystal Glass

A self-hosted, Discord-style messenger for your local network. Pure Python backend (WebSockets + SQLite), no build step, works on phones, tablets and desktops. Installable to the home screen as a web app.

## Features
- Servers, categories and channels, plus direct messages
- Replies, emoji reactions, image sharing (file, paste or drag-and-drop), typing indicators, unread dots
- Online presence, roles (owner / admin / mod / member), invites, kick and role management
- Per-channel wallpapers, profile avatars and bios, six themes, optional notification sounds
- Salted password hashing, login throttling, static file whitelist, optional HTTPS/WSS

## Quick start

**Windows:** double-click `start.bat`. The browser opens automatically.

**Linux / macOS / Termux (Android):**
```bash
chmod +x start.sh stop.sh
./start.sh
```
Termux: `pkg install python` first. Open `http://127.0.0.1:8000` on the same device.

The first run prints the **admin password once** in the console (username `admin`). To choose your own, set `ADMIN_PASS` before the first start. Change it any time under the gear icon next to your name.

## Connect other devices
Use the `LAN Devices` address printed at startup, e.g. `http://192.168.1.20:8000`. All devices must be on the same Wi-Fi or hotspot. On a phone, open the browser menu and choose **Add to Home screen** to install it.

## HTTPS (optional)
Run `make_cert.bat` (Windows) or `pip install -r requirements-tls.txt && python make_cert.py` (needs a C/Rust toolchain on Termux; use `openssl` there instead). Restart the server. On each device, open `https://<ip>:8001` once and accept the self-signed certificate.

## Configuration (environment variables)
| Variable | Default | Purpose |
|---|---|---|
| `PORT` | 8000 | Web client port |
| `WS_PORT` | 8001 | WebSocket port |
| `ADMIN_PASS` | random | Admin password for a fresh database |
| `NO_BROWSER` | unset | Set to `1` to skip opening a browser |

## Files
`server.py` entry point · `ws_handlers.py` realtime events · `database.py` SQLite model · `config.py` settings · `index.html`, `css/`, `js/` web client · `chat_database.db` created on first run (back it up to keep your data).

## Notes
- Built for trusted LANs. Do not expose ports 8000/8001 to the internet without HTTPS and a reverse proxy.
- To reset everything, stop the server and delete `chat_database.db`.
