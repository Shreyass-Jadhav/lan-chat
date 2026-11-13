#!/usr/bin/env bash
# Start LAN Chat on Linux / macOS / Termux (Android)
cd "$(dirname "$0")"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
python3 -m pip install -q -r requirements.txt || { echo "pip install failed"; exit 1; }
export NO_BROWSER=1
exec python3 server.py
