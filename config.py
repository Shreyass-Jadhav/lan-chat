# config.py - Unified Cloud & Internet Server Configuration
import os
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "chat_database.db"

# Cloud Hosting Port (Railway, Render, Fly.io pass $PORT env variable, default 8000)
PORT = int(os.environ.get("PORT", 8000))
HTTP_PORT = PORT
WS_PORT = int(os.environ.get("WS_PORT", 8001))
HOST = os.environ.get("HOST", "0.0.0.0")

# Security & Size Limits
MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16 MB max for high-res image uploads
DEFAULT_ADMIN_USER = "admin"
# If ADMIN_PASS is not set, a random password is generated on first run and printed to the console.
DEFAULT_ADMIN_PASS = os.environ.get("ADMIN_PASS")


def get_lan_ip() -> str:
    """Best-effort LAN IP discovery. Works offline / on a phone hotspot (no internet needed)."""
    for target in ("8.8.8.8", "10.255.255.255", "192.168.255.255", "172.16.255.255"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 80))  # UDP: no packet is actually sent
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        finally:
            s.close()
    return "127.0.0.1"
