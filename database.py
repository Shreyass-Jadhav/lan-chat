# database.py - Discord-like Hierarchical Data Model (Servers, Channels, DMs, Roles, Messages)
import sqlite3
import hashlib
import secrets
import hmac
from pathlib import Path
from datetime import datetime, timedelta
from config import DB_PATH, DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"pbkdf2${salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2$"):
        _, salt, h = stored.split("$")
        cand = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
        return hmac.compare_digest(cand, h)
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)  # legacy


class Database:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA busy_timeout = 5000")
        except Exception:
            pass
        self.generated_admin_pass = None
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()

        # 1. Users
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                custom_status TEXT,
                avatar_color TEXT DEFAULT '#0084ff',
                avatar_url TEXT,
                bio TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP
            )
        """)

        # 2. Servers (Communities / Guilds)
        c.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                icon_url TEXT,
                banner_url TEXT,
                description TEXT,
                is_public BOOLEAN DEFAULT 1,
                background_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        # Migration for existing databases
        try:
            c.execute("ALTER TABLE servers ADD COLUMN background_url TEXT")
        except sqlite3.OperationalError:
            pass

        # 3. Server Members & Roles
        c.execute("""
            CREATE TABLE IF NOT EXISTS server_members (
                server_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT DEFAULT 'member', -- 'owner', 'admin', 'mod', 'member'
                nickname TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (server_id, user_id),
                FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        # 4. Channel Categories
        c.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                position INTEGER DEFAULT 0,
                FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE
            )
        """)

        # 5. Channels inside Servers
        c.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                category_id INTEGER,
                name TEXT NOT NULL,
                channel_type TEXT DEFAULT 'text', -- 'text', 'announcement', 'voice'
                topic TEXT,
                position INTEGER DEFAULT 0,
                is_private BOOLEAN DEFAULT 0,
                background_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL
            )
        """)

        # 6. Channel Messages
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT DEFAULT 'text', -- 'text', 'image', 'system'
                reply_to_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                edited_at TIMESTAMP,
                is_deleted BOOLEAN DEFAULT 0,
                FOREIGN KEY (channel_id) REFERENCES channels (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (reply_to_id) REFERENCES messages (id) ON DELETE SET NULL
            )
        """)

        # 7. Reactions
        c.execute("""
            CREATE TABLE IF NOT EXISTS reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(message_id, user_id, emoji),
                FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        # 8. Server Invites
        c.execute("""
            CREATE TABLE IF NOT EXISTS server_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                server_id INTEGER NOT NULL,
                created_by INTEGER NOT NULL,
                max_uses INTEGER DEFAULT 0, -- 0 = unlimited
                uses INTEGER DEFAULT 0,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                revoked BOOLEAN DEFAULT 0,
                FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        # 9. Direct Message (DM) Channels
        c.execute("""
            CREATE TABLE IF NOT EXISTS dm_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS dm_recipients (
                dm_channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (dm_channel_id, user_id),
                FOREIGN KEY (dm_channel_id) REFERENCES dm_channels (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS dm_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dm_channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT DEFAULT 'text',
                reply_to_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_deleted BOOLEAN DEFAULT 0,
                FOREIGN KEY (dm_channel_id) REFERENCES dm_channels (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (reply_to_id) REFERENCES dm_messages (id) ON DELETE SET NULL
            )
        """)

        # 10. Banned Users
        c.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                server_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                banned_by INTEGER,
                reason TEXT,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (server_id, user_id),
                FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS dm_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                UNIQUE(message_id, user_id, emoji),
                FOREIGN KEY (message_id) REFERENCES dm_messages (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        self.conn.commit()
        self.bootstrap_defaults()

    def bootstrap_defaults(self):
        c = self.conn.cursor()
        
        # Ensure default bootstrap admin user
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            pw = DEFAULT_ADMIN_PASS
            if not pw:
                pw = self.generated_admin_pass = secrets.token_urlsafe(9)
            self.register_user(DEFAULT_ADMIN_USER, pw)

        # Ensure default community server
        c.execute("SELECT COUNT(*) FROM servers")
        if c.fetchone()[0] == 0:
            admin = self.get_user_by_username(DEFAULT_ADMIN_USER)
            admin_id = admin["id"] if admin else 1
            server = self.create_server(
                name="Main Community",
                owner_id=admin_id,
                description="The default general community server",
                is_public=True
            )
            if server:
                cat1 = self.create_category(server["id"], "TEXT CHANNELS")
                cat2 = self.create_category(server["id"], "COMMUNITY")
                self.create_channel(server["id"], "general", category_id=cat1["id"], topic="General conversations and hangouts")
                self.create_channel(server["id"], "announcements", category_id=cat1["id"], channel_type="announcement", topic="Official news and updates")
                self.create_channel(server["id"], "media-and-photos", category_id=cat2["id"], topic="Share your images and media")

    # ------------------------------------------------------------------
    # USERS & AUTH
    # ------------------------------------------------------------------
    def register_user(self, username: str, password: str):
        password_hash = hash_password(password)
        try:
            c = self.conn.cursor()
            c.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            self.conn.commit()
            user_id = c.lastrowid

            # Auto-join all public servers
            c.execute("SELECT id FROM servers WHERE is_public = 1")
            for (srv_id,) in c.fetchall():
                c.execute(
                    "INSERT OR IGNORE INTO server_members (server_id, user_id, role) VALUES (?, ?, 'member')",
                    (srv_id, user_id),
                )
            self.conn.commit()
            return self.get_user_by_id(user_id)
        except sqlite3.IntegrityError:
            return None

    def authenticate_user(self, username: str, password: str):
        c = self.conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        if row and verify_password(password, row["password_hash"]):
            return dict(row)
        return None

    def get_user_by_id(self, user_id: int):
        c = self.conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str):
        c = self.conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        return dict(row) if row else None

    def update_user_profile(self, user_id: int, avatar_url=None, bio=None, avatar_color=None, custom_status=None):
        c = self.conn.cursor()
        updates = []
        params = []
        if avatar_url is not None:
            updates.append("avatar_url = ?")
            params.append(avatar_url)
        if bio is not None:
            updates.append("bio = ?")
            params.append(bio)
        if avatar_color is not None:
            updates.append("avatar_color = ?")
            params.append(avatar_color)
        if custom_status is not None:
            updates.append("custom_status = ?")
            params.append(custom_status)
        if not updates:
            return False
        params.append(user_id)
        c.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        self.conn.commit()
        return c.rowcount > 0

    def update_user_online(self, user_id: int, is_online: bool):
        c = self.conn.cursor()
        c.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # SERVERS (GUILDS)
    # ------------------------------------------------------------------
    def create_server(self, name: str, owner_id: int, description: str = None, icon_url: str = None, banner_url: str = None, is_public: bool = True):
        c = self.conn.cursor()
        try:
            c.execute("""
                INSERT INTO servers (name, owner_id, description, icon_url, banner_url, is_public)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, owner_id, description, icon_url, banner_url, 1 if is_public else 0))
            self.conn.commit()
            server_id = c.lastrowid

            # Add owner as owner role
            c.execute("""
                INSERT INTO server_members (server_id, user_id, role)
                VALUES (?, ?, 'owner')
            """, (server_id, owner_id))
            self.conn.commit()

            # Create default text channel
            cat = self.create_category(server_id, "TEXT CHANNELS")
            self.create_channel(server_id, "general", category_id=cat["id"] if cat else None)

            return self.get_server_by_id(server_id)
        except sqlite3.Error:
            return None

    def get_server_by_id(self, server_id: int):
        c = self.conn.cursor()
        c.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
        row = c.fetchone()
        return dict(row) if row else None

    def get_servers_for_user(self, user_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT s.*, sm.role as my_role
            FROM servers s
            JOIN server_members sm ON sm.server_id = s.id
            WHERE sm.user_id = ?
            ORDER BY s.created_at
        """, (user_id,))
        return [dict(r) for r in c.fetchall()]

    def is_server_member(self, server_id: int, user_id: int) -> bool:
        c = self.conn.cursor()
        c.execute("SELECT 1 FROM server_members WHERE server_id = ? AND user_id = ?", (server_id, user_id))
        return c.fetchone() is not None

    def get_server_member_role(self, server_id: int, user_id: int):
        c = self.conn.cursor()
        c.execute("SELECT role FROM server_members WHERE server_id = ? AND user_id = ?", (server_id, user_id))
        row = c.fetchone()
        return row["role"] if row else None

    def add_server_member(self, server_id: int, user_id: int, role: str = "member"):
        c = self.conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO server_members (server_id, user_id, role)
            VALUES (?, ?, ?)
        """, (server_id, user_id, role))
        self.conn.commit()

    def remove_server_member(self, server_id: int, user_id: int):
        c = self.conn.cursor()
        c.execute("DELETE FROM server_members WHERE server_id = ? AND user_id = ?", (server_id, user_id))
        self.conn.commit()
        return c.rowcount > 0

    def get_server_members(self, server_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT u.id, u.username, u.avatar_color, u.avatar_url, u.custom_status, u.bio,
                   sm.role, sm.nickname, sm.joined_at, u.last_seen
            FROM server_members sm
            JOIN users u ON u.id = sm.user_id
            WHERE sm.server_id = ?
            ORDER BY
                CASE sm.role
                    WHEN 'owner' THEN 0
                    WHEN 'admin' THEN 1
                    WHEN 'mod' THEN 2
                    ELSE 3
                END,
                u.username
        """, (server_id,))
        return [dict(r) for r in c.fetchall()]

    def update_server(self, server_id: int, name=None, icon_url=None, banner_url=None, description=None, background_url=None, is_public=None):
        c = self.conn.cursor()
        updates, params = [], []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if icon_url is not None:
            updates.append("icon_url = ?")
            params.append(icon_url)
        if banner_url is not None:
            updates.append("banner_url = ?")
            params.append(banner_url)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if background_url is not None:
            if background_url in ("", "reset", "default"):
                updates.append("background_url = NULL")
            else:
                updates.append("background_url = ?")
                params.append(background_url)
        if is_public is not None:
            updates.append("is_public = ?")
            params.append(1 if is_public else 0)
        if not updates:
            return False
        params.append(server_id)
        c.execute(f"UPDATE servers SET {', '.join(updates)} WHERE id = ?", params)
        self.conn.commit()
        return c.rowcount > 0

    # ------------------------------------------------------------------
    # CATEGORIES & CHANNELS
    # ------------------------------------------------------------------
    def create_category(self, server_id: int, name: str, position: int = 0):
        c = self.conn.cursor()
        c.execute("INSERT INTO categories (server_id, name, position) VALUES (?, ?, ?)", (server_id, name, position))
        self.conn.commit()
        return {"id": c.lastrowid, "server_id": server_id, "name": name, "position": position}

    def get_categories_for_server(self, server_id: int):
        c = self.conn.cursor()
        c.execute("SELECT * FROM categories WHERE server_id = ? ORDER BY position, id", (server_id,))
        return [dict(r) for r in c.fetchall()]

    def create_channel(self, server_id: int, name: str, category_id: int = None, channel_type: str = "text", topic: str = None, background_url: str = None):
        c = self.conn.cursor()
        clean_name = name.lower().replace(" ", "-")
        c.execute("""
            INSERT INTO channels (server_id, category_id, name, channel_type, topic, background_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (server_id, category_id, clean_name, channel_type, topic, background_url))
        self.conn.commit()
        return self.get_channel_by_id(c.lastrowid)

    def get_channel_by_id(self, channel_id: int):
        c = self.conn.cursor()
        c.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = c.fetchone()
        return dict(row) if row else None

    def get_channels_for_server(self, server_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM channels WHERE server_id = ?
            ORDER BY position, id
        """, (server_id,))
        return [dict(r) for r in c.fetchall()]

    def update_channel(self, channel_id: int, name=None, topic=None, background_url=None):
        c = self.conn.cursor()
        updates, params = [], []
        if name is not None:
            updates.append("name = ?")
            params.append(name.lower().replace(" ", "-"))
        if topic is not None:
            updates.append("topic = ?")
            params.append(topic)
        if background_url is not None:
            if background_url in ("", "reset", "default"):
                updates.append("background_url = NULL")
            else:
                updates.append("background_url = ?")
                params.append(background_url)
        if not updates:
            return False
        params.append(channel_id)
        c.execute(f"UPDATE channels SET {', '.join(updates)} WHERE id = ?", params)
        self.conn.commit()
        return c.rowcount > 0

    def delete_channel(self, channel_id: int):
        c = self.conn.cursor()
        c.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        self.conn.commit()
        return c.rowcount > 0

    # ------------------------------------------------------------------
    # MESSAGES & REACTIONS
    # ------------------------------------------------------------------
    def save_message(self, channel_id: int, user_id: int, content: str, message_type: str = "text", reply_to_id: int = None):
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO messages (channel_id, user_id, content, message_type, reply_to_id)
            VALUES (?, ?, ?, ?, ?)
        """, (channel_id, user_id, content, message_type, reply_to_id))
        self.conn.commit()
        return self.get_message_by_id(c.lastrowid)

    def get_message_by_id(self, message_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT m.*, u.username, u.avatar_color, u.avatar_url
            FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.id = ?
        """, (message_id,))
        row = c.fetchone()
        if not row:
            return None
        msg = dict(row)
        msg["reactions"] = self.get_reactions_for_messages([message_id]).get(message_id, [])
        return msg

    def get_channel_messages(self, channel_id: int, limit: int = 100):
        c = self.conn.cursor()
        c.execute("""
            SELECT m.*, u.username, u.avatar_color, u.avatar_url
            FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.channel_id = ? AND m.is_deleted = 0
            ORDER BY m.id DESC
            LIMIT ?
        """, (channel_id, limit))
        rows = [dict(r) for r in c.fetchall()]
        rows.reverse()
        if rows:
            ids = [r["id"] for r in rows]
            reactions = self.get_reactions_for_messages(ids)
            for r in rows:
                r["reactions"] = reactions.get(r["id"], [])
        return rows

    def delete_message(self, message_id: int):
        c = self.conn.cursor()
        c.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (message_id,))
        self.conn.commit()
        return c.rowcount > 0

    def add_reaction(self, message_id: int, user_id: int, emoji: str):
        try:
            c = self.conn.cursor()
            c.execute("INSERT OR IGNORE INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)", (message_id, user_id, emoji))
            self.conn.commit()
            return c.rowcount > 0
        except sqlite3.Error:
            return False

    def remove_reaction(self, message_id: int, user_id: int, emoji: str):
        c = self.conn.cursor()
        c.execute("DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?", (message_id, user_id, emoji))
        self.conn.commit()
        return c.rowcount > 0

    def get_reactions_for_messages(self, message_ids):
        if not message_ids:
            return {}
        c = self.conn.cursor()
        placeholders = ",".join("?" * len(message_ids))
        c.execute(f"""
            SELECT r.message_id, r.emoji, r.user_id, u.username
            FROM reactions r
            JOIN users u ON u.id = r.user_id
            WHERE r.message_id IN ({placeholders})
            ORDER BY r.created_at
        """, message_ids)
        result = {}
        for row in c.fetchall():
            result.setdefault(row["message_id"], []).append({
                "emoji": row["emoji"],
                "user_id": row["user_id"],
                "username": row["username"]
            })
        return result

    # ------------------------------------------------------------------
    # DIRECT MESSAGES (DMs)
    # ------------------------------------------------------------------
    def get_or_create_dm_channel(self, user1_id: int, user2_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT r1.dm_channel_id
            FROM dm_recipients r1
            JOIN dm_recipients r2 ON r1.dm_channel_id = r2.dm_channel_id
            WHERE r1.user_id = ? AND r2.user_id = ?
        """, (user1_id, user2_id))
        row = c.fetchone()
        if row:
            return row["dm_channel_id"]

        c.execute("INSERT INTO dm_channels DEFAULT VALUES")
        self.conn.commit()
        dm_id = c.lastrowid
        c.execute("INSERT INTO dm_recipients (dm_channel_id, user_id) VALUES (?, ?), (?, ?)", (dm_id, user1_id, dm_id, user2_id))
        self.conn.commit()
        return dm_id

    def get_dms_for_user(self, user_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT d.id as dm_id, u.id as recipient_id, u.username, u.avatar_color, u.avatar_url, u.custom_status
            FROM dm_recipients r1
            JOIN dm_channels d ON d.id = r1.dm_channel_id
            JOIN dm_recipients r2 ON r2.dm_channel_id = d.id AND r2.user_id != ?
            JOIN users u ON u.id = r2.user_id
            WHERE r1.user_id = ?
        """, (user_id, user_id))
        return [dict(row) for row in c.fetchall()]

    def save_dm_message(self, dm_id: int, user_id: int, content: str, message_type: str = "text", reply_to_id: int = None):
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO dm_messages (dm_channel_id, user_id, content, message_type, reply_to_id)
            VALUES (?, ?, ?, ?, ?)
        """, (dm_id, user_id, content, message_type, reply_to_id))
        self.conn.commit()
        mid = c.lastrowid
        c.execute("""
            SELECT m.*, u.username, u.avatar_color, u.avatar_url
            FROM dm_messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.id = ?
        """, (mid,))
        msg = dict(c.fetchone())
        msg["reactions"] = []
        return msg

    def get_dm_messages(self, dm_id: int, limit: int = 100):
        c = self.conn.cursor()
        c.execute("""
            SELECT m.*, u.username, u.avatar_color, u.avatar_url
            FROM dm_messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.dm_channel_id = ? AND m.is_deleted = 0
            ORDER BY m.id DESC
            LIMIT ?
        """, (dm_id, limit))
        rows = [dict(r) for r in c.fetchall()]
        rows.reverse()
        rx = self.get_dm_reactions([r["id"] for r in rows])
        for r in rows:
            r["reactions"] = rx.get(r["id"], [])
        return rows

    # ------------------------------------------------------------------
    # INVITES & MODERATION
    # ------------------------------------------------------------------
    def create_server_invite(self, server_id: int, created_by: int, max_uses: int = 0, expires_in_hours: int = 168):
        code = secrets.token_urlsafe(8)
        exp = (datetime.utcnow() + timedelta(hours=expires_in_hours)).strftime("%Y-%m-%d %H:%M:%S")
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO server_invites (code, server_id, created_by, max_uses, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (code, server_id, created_by, max_uses, exp))
        self.conn.commit()
        return self.get_invite_by_code(code)

    def get_invite_by_code(self, code: str):
        c = self.conn.cursor()
        c.execute("""
            SELECT i.*, s.name as server_name, s.icon_url as server_icon, s.description as server_description,
                   s.is_public as server_is_public,
                   (SELECT COUNT(*) FROM server_members WHERE server_id = s.id) as member_count,
                   u.username as inviter_name
            FROM server_invites i
            JOIN servers s ON s.id = i.server_id
            JOIN users u ON u.id = i.created_by
            WHERE i.code = ?
        """, (code,))
        row = c.fetchone()
        return dict(row) if row else None

    def validate_and_redeem_invite(self, code: str, user_id: int):
        inv = self.get_invite_by_code(code)
        if not inv:
            return False, "Invalid invite code", None
        if inv["revoked"]:
            return False, "This invite has been revoked", None
        if inv["expires_at"]:
            if datetime.utcnow() > datetime.strptime(inv["expires_at"], "%Y-%m-%d %H:%M:%S"):
                return False, "This invite has expired", None
        if inv["max_uses"] > 0 and inv["uses"] >= inv["max_uses"]:
            return False, "This invite has reached maximum uses", None

        server_id = inv["server_id"]
        if self.is_server_member(server_id, user_id):
            return True, "Already a member", inv

        c = self.conn.cursor()
        c.execute("UPDATE server_invites SET uses = uses + 1 WHERE code = ?", (code,))
        c.execute("INSERT OR IGNORE INTO server_members (server_id, user_id, role) VALUES (?, ?, 'member')", (server_id, user_id))
        self.conn.commit()
        return True, f"Joined {inv['server_name']}", inv

    def ensure_bootstrap_admin(self):
        self.bootstrap_defaults()

    def change_password(self, user_id: int, new_password: str):
        c = self.conn.cursor()
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
        self.conn.commit()
        return c.rowcount > 0

    def delete_user(self, user_id: int):
        c = self.conn.cursor()
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()
        return c.rowcount > 0

    def delete_server(self, server_id: int):
        c = self.conn.cursor()
        c.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        self.conn.commit()
        return c.rowcount > 0

    def set_member_role(self, server_id: int, user_id: int, role: str):
        c = self.conn.cursor()
        c.execute("UPDATE server_members SET role = ? WHERE server_id = ? AND user_id = ?", (role, server_id, user_id))
        self.conn.commit()
        return c.rowcount > 0

    # ---- DM helpers ----
    def is_dm_member(self, dm_id: int, user_id: int) -> bool:
        c = self.conn.cursor()
        c.execute("SELECT 1 FROM dm_recipients WHERE dm_channel_id = ? AND user_id = ?", (dm_id, user_id))
        return c.fetchone() is not None

    def get_dm_message_by_id(self, mid: int):
        c = self.conn.cursor()
        c.execute("SELECT * FROM dm_messages WHERE id = ? AND is_deleted = 0", (mid,))
        row = c.fetchone()
        if not row:
            return None
        msg = dict(row)
        msg["reactions"] = self.get_dm_reactions([mid]).get(mid, [])
        return msg

    def delete_dm_message(self, mid: int):
        c = self.conn.cursor()
        c.execute("UPDATE dm_messages SET is_deleted = 1 WHERE id = ?", (mid,))
        self.conn.commit()
        return c.rowcount > 0

    def add_dm_reaction(self, mid: int, user_id: int, emoji: str):
        c = self.conn.cursor()
        c.execute("INSERT OR IGNORE INTO dm_reactions (message_id, user_id, emoji) VALUES (?, ?, ?)", (mid, user_id, emoji))
        self.conn.commit()

    def remove_dm_reaction(self, mid: int, user_id: int, emoji: str):
        c = self.conn.cursor()
        c.execute("DELETE FROM dm_reactions WHERE message_id = ? AND user_id = ? AND emoji = ?", (mid, user_id, emoji))
        self.conn.commit()

    def get_dm_reactions(self, ids):
        if not ids:
            return {}
        c = self.conn.cursor()
        c.execute(f"""
            SELECT r.message_id, r.emoji, r.user_id, u.username
            FROM dm_reactions r JOIN users u ON u.id = r.user_id
            WHERE r.message_id IN ({",".join("?" * len(ids))}) ORDER BY r.id
        """, ids)
        out = {}
        for row in c.fetchall():
            out.setdefault(row["message_id"], []).append({"emoji": row["emoji"], "user_id": row["user_id"], "username": row["username"]})
        return out

    def close(self):
        self.conn.close()