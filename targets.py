"""Where to publish: saved channels / topics (tick several), or a custom one."""
import re

import db
from tgapi import norm_chat


async def load_options(uid: int, kinds: str) -> list:
    """kinds: 'c' channels, 't' topics, 'ct' both"""
    opts = []
    if "c" in kinds:
        for ch in await db.channels.find({"user_id": uid}).to_list(length=None):
            opts.append({"key": f"c:{ch['_id']}", "label": ch.get("name", "Channel"), "icon": "📢",
                         "chat_id": norm_chat(ch["chat_id"]), "thread_id": None})
    if "t" in kinds:
        for tp in await db.topics.find({"user_id": uid}).to_list(length=None):
            opts.append({"key": f"t:{tp['_id']}", "label": tp.get("name", "Topic"), "icon": "💬",
                         "chat_id": norm_chat(tp["chat_id"]), "thread_id": tp.get("thread_id")})
    return opts


def chooser_pairs(opts: list, selected: set, silent: bool = False, pin: bool = False, as_user=None) -> list:
    """Rows of (label, action). Actions: 'toggle:<key>' | 'silent' | 'pin' | 'asuser' | 'custom' | 'go' | 'back'
    as_user: None = hide the row, True/False = shown ticked / unticked"""
    rows = [[(("✅ " if o["key"] in selected else "⬜ ") + f"{o['icon']} {o['label']}", f"toggle:{o['key']}")] for o in opts]
    rows.append([("🔕 Silent " + ("✅" if silent else "⬜"), "silent"), ("📌 Pin " + ("✅" if pin else "⬜"), "pin")])
    if as_user is not None:
        rows.append([("👤 Premium account se post " + ("✅" if as_user else "⬜"), "asuser")])
    rows.append([("➕ Custom", "custom"), (f"🚀 Publish ({len(selected)})", "go")])
    rows.append([("⬅️ Back", "back")])
    return rows


def add_custom(opts: list, selected: set, chat_id, thread_id=None, label=None):
    key = f"x:{len(opts)}"
    opts.append({"key": key, "label": label or str(chat_id), "icon": "✍️", "chat_id": chat_id, "thread_id": thread_id})
    selected.add(key)


def post_link(chat_id, message_id: int) -> str:
    if isinstance(chat_id, str):
        return f"https://t.me/{chat_id.lstrip('@')}/{message_id}"
    return f"https://t.me/c/{str(chat_id).replace('-100', '', 1)}/{message_id}"


def parse_custom(text: str):
    """'@chan' | '-100123' | '-100123, 45' | a t.me link -> (chat, thread or None), or None if not understood."""
    t = (text or "").strip()
    m = re.match(r"^(?:https?://)?t\.me/c/(\d+)/(\d+)/(\d+)$", t)  # private topic message link
    if m:
        return int(f"-100{m.group(1)}"), int(m.group(2))
    m = re.match(r"^(?:https?://)?t\.me/c/(\d+)(?:/\d+)?$", t)
    if m:
        return int(f"-100{m.group(1)}"), None
    m = re.match(r"^(?:https?://)?t\.me/([A-Za-z0-9_]{4,})/(\d+)/(\d+)$", t)  # public topic message link
    if m:
        return "@" + m.group(1), int(m.group(2))
    m = re.match(r"^(?:https?://)?t\.me/([A-Za-z0-9_]{4,})(?:/\d+)?$", t)
    if m:
        return "@" + m.group(1), None
    parts = [x.strip() for x in t.split(",")]
    ref = parts[0]
    if re.fullmatch(r"-?\d+", ref):
        chat = int(ref)
        if chat > 0 and not str(chat).startswith("100"):
            chat = int(f"-100{chat}")
        elif chat > 0:
            chat = -chat
    elif re.fullmatch(r"@?[A-Za-z0-9_]{4,}", ref):
        chat = "@" + ref.lstrip("@")
    else:
        return None
    return chat, (int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None)
