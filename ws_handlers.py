# ws_handlers.py - Discord-like Realtime WebSocket Engine & Event Handlers
import asyncio
import json
import re
import traceback
from database import Database

# Connected client sessions: {user_id: set(web.WebSocketResponse)}
CLIENTS = {}
CONN_USER = {}


async def send_json(ws, payload):
    try:
        await ws.send(json.dumps(payload))
    except Exception:
        pass


async def broadcast_to_server_members(server_id: int, payload: dict, exclude_user_id: int = None):
    db = Database()
    members = db.get_server_members(server_id)
    member_ids = {m["id"] for m in members}
    db.close()

    for uid in member_ids:
        if exclude_user_id and uid == exclude_user_id:
            continue
        for ws in list(CLIENTS.get(uid, set())):
            await send_json(ws, payload)


async def broadcast_to_channel(channel_id: int, payload: dict, exclude_user_id: int = None):
    db = Database()
    channel = db.get_channel_by_id(channel_id)
    db.close()
    if channel:
        await broadcast_to_server_members(channel["server_id"], payload, exclude_user_id)


def safe_img(v, allow=()):
    if isinstance(v, str) and (v in allow or v.startswith("data:image/")):
        return v
    return None


async def broadcast_dm(db, dm_id, payload, exclude=None):
    rows = db.conn.execute("SELECT user_id FROM dm_recipients WHERE dm_channel_id = ?", (dm_id,)).fetchall()
    for r in rows:
        if r[0] == exclude:
            continue
        for w_ in list(CLIENTS.get(r[0], set())):
            await send_json(w_, payload)


async def notify_users(user_ids, payload):
    for uid in user_ids:
        for w_ in list(CLIENTS.get(uid, set())):
            await send_json(w_, payload)


def with_presence(members):
    for m in members:
        m["online"] = m["id"] in CLIENTS
    return members


async def broadcast_presence(user_id, online):
    payload = {"type": "presence", "user_id": user_id, "online": online}
    for conns in list(CLIENTS.values()):
        for w_ in list(conns):
            await send_json(w_, payload)


def public_user(u):
    if not u:
        return None
    return {
        "id": u["id"],
        "username": u["username"],
        "custom_status": u.get("custom_status"),
        "avatar_color": u.get("avatar_color", "#0084ff"),
        "avatar_url": u.get("avatar_url"),
        "bio": u.get("bio"),
    }


async def handle_websocket(ws):

    user_id = None
    db = Database()

    try:
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        continue

                    t = data.get("type")

                    # ========================================================
                    # AUTHENTICATION
                    # ========================================================
                    if t == "login":
                        user = db.authenticate_user(data.get("username", ""), data.get("password", ""))
                        if not user:
                            await send_json(ws, {"type": "auth_error", "message": "Invalid username or password"})
                            await asyncio.sleep(1)
                            continue
                        user_id = user["id"]
                        first = user_id not in CLIENTS
                        CLIENTS.setdefault(user_id, set()).add(ws)
                        if first:
                            await broadcast_presence(user_id, True)
                        CONN_USER[ws] = user_id
                        db.update_user_online(user_id, True)

                        # Return full initial Discord payload
                        servers = db.get_servers_for_user(user_id)
                        dms = db.get_dms_for_user(user_id)
                        await send_json(ws, {
                            "type": "auth_success",
                            "user": public_user(user),
                            "servers": servers,
                            "dms": dms,
                        })

                    elif t == "register":
                        username = data.get("username", "").strip()
                        password = data.get("password", "")
                        if not (2 <= len(username) <= 24) or len(password) < 4:
                            await send_json(ws, {"type": "auth_error", "message": "Username 2-24 chars, password 4+ chars"})
                            continue
                        user = db.register_user(username, password)
                        if not user:
                            await send_json(ws, {"type": "auth_error", "message": "Username already taken"})
                            continue
                        user_id = user["id"]
                        first = user_id not in CLIENTS
                        CLIENTS.setdefault(user_id, set()).add(ws)
                        if first:
                            await broadcast_presence(user_id, True)
                        CONN_USER[ws] = user_id
                        db.update_user_online(user_id, True)

                        # Redeem server invite if provided during registration
                        invite_code = data.get("invite", "").strip()
                        if invite_code:
                            db.validate_and_redeem_invite(invite_code, user_id)

                        servers = db.get_servers_for_user(user_id)
                        dms = db.get_dms_for_user(user_id)
                        await send_json(ws, {
                            "type": "auth_success",
                            "user": public_user(user),
                            "servers": servers,
                            "dms": dms,
                        })

                    # Check authenticated for all remaining operations
                    if not user_id:
                        continue

                    # ========================================================
                    # INITIAL DATA & SERVERS (GUILDS)
                    # ========================================================
                    if t == "get_initial_data":
                        servers = db.get_servers_for_user(user_id)
                        dms = db.get_dms_for_user(user_id)
                        await send_json(ws, {
                            "type": "initial_data",
                            "servers": servers,
                            "dms": dms,
                        })

                    elif t == "get_server_details":
                        server_id = data.get("server_id")
                        if not db.is_server_member(server_id, user_id):
                            await send_json(ws, {"type": "error", "message": "Not a member of this server"})
                            continue
                        server = db.get_server_by_id(server_id)
                        categories = db.get_categories_for_server(server_id)
                        channels = db.get_channels_for_server(server_id)
                        members = with_presence(db.get_server_members(server_id))
                        my_role = db.get_server_member_role(server_id, user_id)

                        await send_json(ws, {
                            "type": "server_details",
                            "server": server,
                            "categories": categories,
                            "channels": channels,
                            "members": members,
                            "my_role": my_role,
                        })

                    elif t == "create_server":
                        name = data.get("name", "").strip()
                        if not name:
                            await send_json(ws, {"type": "error", "message": "Server name required"})
                            continue
                        desc = data.get("description")
                        icon_url = safe_img(data.get("icon_url"))
                        # is_public: false for hidden private rooms, true for public
                        is_pub = bool(data.get("is_public", False))
                        server = db.create_server(name=name, owner_id=user_id, description=desc, icon_url=icon_url, is_public=is_pub)
                        if server:
                            inv = db.create_server_invite(server["id"], created_by=user_id, max_uses=0, expires_in_hours=720)
                            await send_json(ws, {"type": "server_created", "server": server, "invite": inv})

                    elif t == "update_server":
                        server_id = data.get("server_id")
                        role = db.get_server_member_role(server_id, user_id)
                        if role not in ("owner", "admin"):
                            await send_json(ws, {"type": "error", "message": "Only owner/admin can modify server"})
                            continue
                        db.update_server(
                            server_id,
                            name=data.get("name"),
                            icon_url=safe_img(data.get("icon_url")),
                            banner_url=safe_img(data.get("banner_url")),
                            description=data.get("description"),
                            background_url=safe_img(data.get("background_url"), ("reset", "")),
                            is_public=(bool(data.get("is_public")) if "is_public" in data else None)
                        )
                        server = db.get_server_by_id(server_id)
                        await broadcast_to_server_members(server_id, {"type": "server_updated", "server": server})

                    elif t == "leave_server":
                        server_id = data.get("server_id")
                        role = db.get_server_member_role(server_id, user_id)
                        if role == "owner":
                            await send_json(ws, {"type": "error", "message": "Server owner cannot leave without deleting"})
                            continue
                        db.remove_server_member(server_id, user_id)
                        await send_json(ws, {"type": "server_left", "server_id": server_id})
                        await broadcast_to_server_members(server_id, {
                            "type": "member_left",
                            "server_id": server_id,
                            "user_id": user_id,
                        })

                    # ========================================================
                    # CATEGORIES & CHANNELS
                    # ========================================================
                    elif t == "create_category":
                        server_id = data.get("server_id")
                        name = data.get("name", "").strip()
                        role = db.get_server_member_role(server_id, user_id)
                        if role not in ("owner", "admin"):
                            continue
                        cat = db.create_category(server_id, name)
                        await broadcast_to_server_members(server_id, {"type": "category_created", "category": cat})

                    elif t == "create_channel":
                        server_id = data.get("server_id")
                        name = data.get("name", "").strip()
                        cat_id = data.get("category_id")
                        topic = data.get("topic")
                        role = db.get_server_member_role(server_id, user_id)
                        if role is None or not name:
                            continue
                        ch = db.create_channel(server_id, name, category_id=cat_id, topic=topic)
                        if ch:
                            await broadcast_to_server_members(server_id, {"type": "channel_created", "channel": ch})

                    elif t == "update_channel":
                        channel_id = data.get("channel_id")
                        ch = db.get_channel_by_id(channel_id)
                        if not ch:
                            continue
                        role = db.get_server_member_role(ch["server_id"], user_id)
                        if role not in ("owner", "admin"):
                            continue
                        db.update_channel(
                            channel_id,
                            name=data.get("name"),
                            topic=data.get("topic"),
                            background_url=safe_img(data.get("background_url"), ("reset", "")),
                        )
                        updated_ch = db.get_channel_by_id(channel_id)
                        await broadcast_to_server_members(ch["server_id"], {"type": "channel_updated", "channel": updated_ch})

                    elif t == "delete_channel":
                        channel_id = data.get("channel_id")
                        ch = db.get_channel_by_id(channel_id)
                        if not ch:
                            continue
                        role = db.get_server_member_role(ch["server_id"], user_id)
                        if role not in ("owner", "admin"):
                            continue
                        db.delete_channel(channel_id)
                        await broadcast_to_server_members(ch["server_id"], {
                            "type": "channel_deleted",
                            "server_id": ch["server_id"],
                            "channel_id": channel_id,
                        })

                    # ========================================================
                    # CHANNEL MESSAGING
                    # ========================================================
                    elif t == "join_channel":
                        channel_id = data.get("channel_id")
                        ch = db.get_channel_by_id(channel_id)
                        if not ch or not db.is_server_member(ch["server_id"], user_id):
                            await send_json(ws, {"type": "error", "message": "Access denied"})
                            continue
                        messages = db.get_channel_messages(channel_id, 100)
                        members = with_presence(db.get_server_members(ch["server_id"]))
                        await send_json(ws, {
                            "type": "channel_history",
                            "channel": ch,
                            "messages": messages,
                            "members": members,
                        })

                    elif t == "send_message":
                        channel_id = data.get("channel_id")
                        content = data.get("content", "")
                        mtype = data.get("message_type", "text")
                        reply_to = data.get("reply_to_id")
                        if not content.strip() or (mtype != "image" and len(content) > 4000):
                            continue
                        ch = db.get_channel_by_id(channel_id)
                        if not ch or not db.is_server_member(ch["server_id"], user_id):
                            continue
                        saved = db.save_message(channel_id, user_id, content, mtype, reply_to)
                        if saved:
                            await broadcast_to_channel(channel_id, {
                                "type": "new_message",
                                "channel_id": channel_id,
                                "message": saved,
                            })

                    elif t == "delete_message":
                        message_id = data.get("message_id")
                        existing = db.get_message_by_id(message_id)
                        if not existing:
                            continue
                        ch = db.get_channel_by_id(existing["channel_id"])
                        role = db.get_server_member_role(ch["server_id"], user_id)
                        if existing["user_id"] == user_id or role in ("owner", "admin", "mod"):
                            db.delete_message(message_id)
                            await broadcast_to_channel(existing["channel_id"], {
                                "type": "message_deleted",
                                "channel_id": existing["channel_id"],
                                "message_id": message_id,
                            })

                    elif t == "typing":
                        channel_id = data.get("channel_id")
                        user = db.get_user_by_id(user_id)
                        await broadcast_to_channel(channel_id, {
                            "type": "user_typing",
                            "channel_id": channel_id,
                            "username": user["username"],
                            "is_typing": data.get("is_typing", False),
                        }, exclude_user_id=user_id)

                    # ========================================================
                    # REACTIONS
                    # ========================================================
                    elif t == "add_reaction":
                        message_id = data.get("message_id")
                        emoji = data.get("emoji", "").strip()
                        if emoji:
                            db.add_reaction(message_id, user_id, emoji)
                            msg_item = db.get_message_by_id(message_id)
                            if msg_item:
                                await broadcast_to_channel(msg_item["channel_id"], {
                                    "type": "reactions_updated",
                                    "channel_id": msg_item["channel_id"],
                                    "message_id": message_id,
                                    "reactions": msg_item["reactions"],
                                })

                    elif t == "remove_reaction":
                        message_id = data.get("message_id")
                        emoji = data.get("emoji", "").strip()
                        if emoji:
                            db.remove_reaction(message_id, user_id, emoji)
                            msg_item = db.get_message_by_id(message_id)
                            if msg_item:
                                await broadcast_to_channel(msg_item["channel_id"], {
                                    "type": "reactions_updated",
                                    "channel_id": msg_item["channel_id"],
                                    "message_id": message_id,
                                    "reactions": msg_item["reactions"],
                                })

                    # ========================================================
                    # DIRECT MESSAGES (DMs)
                    # ========================================================
                    elif t == "open_dm":
                        target_id = data.get("recipient_id")
                        if target_id == user_id or not db.get_user_by_id(target_id):
                            continue
                        dm_id = db.get_or_create_dm_channel(user_id, target_id)
                        messages = db.get_dm_messages(dm_id)
                        recipient = db.get_user_by_id(target_id)
                        await send_json(ws, {
                            "type": "dm_history",
                            "dm_id": dm_id,
                            "recipient": public_user(recipient),
                            "messages": messages,
                        })

                    elif t == "send_dm_message":
                        dm_id = data.get("dm_id")
                        content = data.get("content", "")
                        mtype = data.get("message_type", "text")
                        if not str(content).strip():
                            continue
                        chk = db.conn.execute("SELECT 1 FROM dm_recipients WHERE dm_channel_id = ? AND user_id = ?", (dm_id, user_id)).fetchone()
                        if not chk:
                            continue
                        saved = db.save_dm_message(dm_id, user_id, content, mtype, data.get("reply_to_id"))
                    
                        # Send to both DM recipients
                        c = db.conn.cursor()
                        c.execute("SELECT user_id FROM dm_recipients WHERE dm_channel_id = ?", (dm_id,))
                        recipient_ids = [r[0] for r in c.fetchall()]
                        for r_uid in recipient_ids:
                            for target_ws in list(CLIENTS.get(r_uid, set())):
                                await send_json(target_ws, {
                                    "type": "new_dm_message",
                                    "dm_id": dm_id,
                                    "message": saved,
                                })

                    # ========================================================
                    # SERVER INVITES & DISCORD-STYLE JOIN
                    # ========================================================
                    elif t == "create_server_invite":
                        server_id = data.get("server_id")
                        if not db.is_server_member(server_id, user_id):
                            continue
                        inv = db.create_server_invite(
                            server_id,
                            created_by=user_id,
                            max_uses=int(data.get("max_uses", 0)),
                            expires_in_hours=int(data.get("expires_in_hours", 168)),
                        )
                        await send_json(ws, {"type": "server_invite_created", "invite": inv})

                    elif t == "inspect_invite":
                        code = data.get("code", "").strip()
                        inv = db.get_invite_by_code(code)
                        if not inv:
                            await send_json(ws, {"type": "invite_info", "valid": False, "message": "Invalid or expired invite link"})
                        elif inv.get("revoked"):
                            await send_json(ws, {"type": "invite_info", "valid": False, "message": "This invite has been revoked"})
                        else:
                            is_member = db.is_server_member(inv["server_id"], user_id)
                            await send_json(ws, {
                                "type": "invite_info",
                                "valid": True,
                                "is_member": is_member,
                                "invite": {
                                    "code": inv["code"],
                                    "server_id": inv["server_id"],
                                    "server_name": inv["server_name"],
                                    "server_icon": inv.get("server_icon"),
                                    "server_description": inv.get("server_description"),
                                    "server_is_public": inv.get("server_is_public", 1),
                                    "member_count": inv.get("member_count", 1),
                                    "inviter_name": inv.get("inviter_name", "A member")
                                }
                            })

                    elif t == "redeem_server_invite":
                        code = data.get("code", "").strip()
                        ok, reason, inv = db.validate_and_redeem_invite(code, user_id)
                        if not ok:
                            await send_json(ws, {"type": "error", "message": reason})
                        else:
                            server = db.get_server_by_id(inv["server_id"])
                            await send_json(ws, {
                                "type": "invite_redeemed",
                                "message": reason,
                                "server": server,
                            })

                    # ========================================================
                    # USER PROFILE & STATUS
                    # ========================================================
                    elif t in ("dm_add_reaction", "dm_remove_reaction"):
                        dm_id, mid, emoji = data.get("dm_id"), data.get("message_id"), str(data.get("emoji", "")).strip()
                        m = db.get_dm_message_by_id(mid)
                        if not emoji or not m or m["dm_channel_id"] != dm_id or not db.is_dm_member(dm_id, user_id):
                            continue
                        (db.add_dm_reaction if t == "dm_add_reaction" else db.remove_dm_reaction)(mid, user_id, emoji)
                        m = db.get_dm_message_by_id(mid)
                        await broadcast_dm(db, dm_id, {"type": "dm_reactions_updated", "dm_id": dm_id, "message_id": mid, "reactions": m["reactions"]})

                    elif t == "dm_delete_message":
                        dm_id, mid = data.get("dm_id"), data.get("message_id")
                        m = db.get_dm_message_by_id(mid)
                        if m and m["dm_channel_id"] == dm_id and m["user_id"] == user_id:
                            db.delete_dm_message(mid)
                            await broadcast_dm(db, dm_id, {"type": "dm_message_deleted", "dm_id": dm_id, "message_id": mid})

                    elif t == "dm_typing":
                        dm_id = data.get("dm_id")
                        if db.is_dm_member(dm_id, user_id):
                            await broadcast_dm(db, dm_id, {"type": "dm_user_typing", "dm_id": dm_id,
                                                           "username": db.get_user_by_id(user_id)["username"],
                                                           "is_typing": bool(data.get("is_typing"))}, exclude=user_id)

                    elif t == "delete_server":
                        server_id = data.get("server_id")
                        if db.get_server_member_role(server_id, user_id) == "owner":
                            ids = [m["id"] for m in db.get_server_members(server_id)]
                            db.delete_server(server_id)
                            await notify_users(ids, {"type": "server_left", "server_id": server_id})

                    elif t == "set_member_role":
                        server_id, target = data.get("server_id"), data.get("user_id")
                        role = data.get("role")
                        if db.get_server_member_role(server_id, user_id) != "owner" or target == user_id or role not in ("admin", "mod", "member"):
                            await send_json(ws, {"type": "error", "message": "Only the owner can change roles"})
                            continue
                        if db.get_server_member_role(server_id, target) and db.set_member_role(server_id, target, role):
                            await broadcast_to_server_members(server_id, {"type": "member_updated", "server_id": server_id, "user_id": target, "role": role})

                    elif t == "kick_member":
                        server_id, target = data.get("server_id"), data.get("user_id")
                        mine, theirs = db.get_server_member_role(server_id, user_id), db.get_server_member_role(server_id, target)
                        if mine not in ("owner", "admin") or not theirs or target == user_id or theirs == "owner" or (mine == "admin" and theirs == "admin"):
                            await send_json(ws, {"type": "error", "message": "You cannot remove that member"})
                            continue
                        db.remove_server_member(server_id, target)
                        await notify_users([target], {"type": "server_left", "server_id": server_id})
                        await broadcast_to_server_members(server_id, {"type": "member_left", "server_id": server_id, "user_id": target})

                    elif t == "change_password":
                        me_row = db.get_user_by_id(user_id)
                        new_pw = data.get("new_password", "")
                        if not db.authenticate_user(me_row["username"], data.get("old_password", "")):
                            await send_json(ws, {"type": "error", "message": "Current password is incorrect"})
                        elif len(new_pw) < 4:
                            await send_json(ws, {"type": "error", "message": "New password must be 4+ characters"})
                        else:
                            db.change_password(user_id, new_pw)
                            await send_json(ws, {"type": "password_changed"})

                    elif t == "delete_account":
                        me_row = db.get_user_by_id(user_id)
                        if not db.authenticate_user(me_row["username"], data.get("password", "")):
                            await send_json(ws, {"type": "error", "message": "Password is incorrect"})
                            continue
                        for s in [s for s in db.get_servers_for_user(user_id) if s["my_role"] == "owner"]:
                            ids = [m["id"] for m in db.get_server_members(s["id"]) if m["id"] != user_id]
                            db.delete_server(s["id"])
                            await notify_users(ids, {"type": "server_left", "server_id": s["id"]})
                        db.delete_user(user_id)
                        await send_json(ws, {"type": "account_deleted"})
                        await ws.close()
                        break

                    elif t == "update_profile":
                        db.update_user_profile(
                            user_id,
                            avatar_url=safe_img(data.get("avatar_url")),
                            bio=(str(data["bio"])[:200] if data.get("bio") is not None else None),
                            avatar_color=(data["avatar_color"] if re.fullmatch(r"#[0-9a-fA-F]{6}", str(data.get("avatar_color") or "")) else None),
                            custom_status=(str(data["custom_status"])[:60] if data.get("custom_status") is not None else None),
                        )
                        fresh = db.get_user_by_id(user_id)
                        await send_json(ws, {"type": "profile_updated", "user": public_user(fresh)})

                    elif t == "get_user_profile":
                        target_id = data.get("user_id")
                        target = db.get_user_by_id(target_id)
                        if target:
                            p = public_user(target)
                            srv_id = data.get("server_id")
                            if srv_id:
                                p["role"] = db.get_server_member_role(srv_id, target_id)
                            p["online"] = target_id in CLIENTS
                            await send_json(ws, {"type": "user_profile", "user": p, "server_id": srv_id})

                except Exception:
                    traceback.print_exc()
                    db.conn.rollback()
    except Exception:
        traceback.print_exc()
    finally:
        if user_id:
            if user_id in CLIENTS:
                CLIENTS[user_id].discard(ws)
                if not CLIENTS[user_id]:
                    del CLIENTS[user_id]
                    await broadcast_presence(user_id, False)
            db.update_user_online(user_id, False)
        CONN_USER.pop(ws, None)
        db.close()

