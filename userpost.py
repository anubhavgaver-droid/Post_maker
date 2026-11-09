"""Post as your own Premium account (session string), so premium emoji in the post TEXT also work in channels.

How it works
  1. You send the content to the bot from your Premium account (as always).
  2. The Premium account (userbot) copies that very message into the channel - as you, a Premium user,
     so Telegram keeps the premium emoji.
  3. The bot (admin of the channel) then adds the buttons by editing the post.
Limits: a user account cannot attach inline buttons itself, so buttons still come from the bot (premium button icons
follow the bot rule, /emojicheck).  Rich Posts are sent by the bot only.
Safety: the session string is the key to your whole Telegram account. Add it with /setsession (stored encrypted in the
database) or in the host's env var USER_SESSION_STRING - never in code, never on GitHub, never in a chat.
"""
import base64
import hashlib
import html
import logging
import os
import time

from cryptography.fernet import Fernet, InvalidToken
from pyrogram import Client, enums

import db
import tgapi
from config import API_HASH, API_ID, BOT_TOKEN

log = logging.getLogger("userpost")
ENV_SESSION = os.getenv("USER_SESSION_STRING", "").strip()  # optional: the session can also be added from the bot (/setsession)
KEY_ID = "user_session"
user = None
_me = None
_string = ""
source = None  # 'db' | 'env' | None


def enabled() -> bool:
    return user is not None


# ---------- the session is stored ENCRYPTED in MongoDB (key = derived from BOT_TOKEN, which never goes to the DB) ----------
def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("userpost-v1:" + BOT_TOKEN).encode()).digest()))


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def decrypt(token: str):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, AttributeError):
        return None


async def load_saved():
    doc = await db.bot_settings.find_one({"_id": KEY_ID})
    if not doc:
        return None
    s = decrypt(doc.get("data", ""))
    if s is None:
        log.error("Saved session string cannot be decrypted (BOT_TOKEN changed?) - add it again with /setsession")
    return s


async def _launch(string: str):
    c = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=string, in_memory=True)
    await c.start()
    try:
        return c, await c.get_me()
    except Exception:
        await c.stop()
        raise


async def start():
    """Start the userbot from the saved (DB) session, else from USER_SESSION_STRING. A broken session never stops the bot."""
    global user, _me, _string, source
    for src, s in (("db", await load_saved()), ("env", ENV_SESSION)):
        if not s:
            continue
        try:
            user, _me = await _launch(s)
            _string, source = s, src
            log.info("Userbot started from %s as %s (premium=%s)", src, _me.id, getattr(_me, "is_premium", None))
            return _me
        except Exception as e:
            log.error("Userbot session from %s could not start (%s)", src, type(e).__name__)
    return None


async def stop():
    global user, _me, _string, source
    if user:
        try:
            await user.stop()
        except Exception:
            pass
    user, _me, _string, source = None, None, "", None


async def replace(string: str, by: int):
    """Switch to a new session string (from /setsession) and save it. If it is bad, the old one is brought back."""
    global user, _me, _string, source
    prev = _string
    await stop()  # never two live connections on one session
    try:
        user, _me = await _launch(string)
    except Exception:
        if prev:
            try:
                user, _me = await _launch(prev)
                _string, source = prev, "db"
            except Exception:
                pass
        raise
    _string, source = string, "db"
    await db.bot_settings.update_one({"_id": KEY_ID}, {"$set": {"data": encrypt(string), "by": by, "ts": time.time()}}, upsert=True)
    return _me


async def remove():
    """/delsession: forget the saved session (falls back to USER_SESSION_STRING if that is set)."""
    await stop()
    await db.bot_settings.delete_one({"_id": KEY_ID})
    return await start()


async def me():
    return _me


async def find_copy(bot_username: str, meta: dict, limit: int = 30):
    """The Premium account's own copy of the message you sent to the bot (matched by time, text and media)."""
    async for m in user.get_chat_history(bot_username, limit=limit):
        if not getattr(m, "outgoing", True):
            continue
        if abs((m.date - meta["date"]).total_seconds()) > 8:
            continue
        if (m.text or m.caption or "") != meta["text"] or bool(m.media) != meta["media"]:
            continue
        return m
    return None


def _nopreview() -> dict:
    try:
        from pyrogram.types import LinkPreviewOptions
        return {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
    except (ImportError, TypeError):
        return {"disable_web_page_preview": True}


def link_line(b: dict) -> str:
    """A 'button' as a text link: the premium emoji + the name, clickable (works in channels, posted by a Premium account)."""
    return f'<a href="{html.escape(b["url"], quote=True)}"><emoji id="{b["icon"]}">{html.escape(b.get("fb") or "⭐")}</emoji> {html.escape(b["name"])}</a>'


async def post(bot_username: str, user_msg, chat_id, thread_id=None, silent: bool = False, link_lines: list = None):
    """Copy the message into chat_id as the Premium account. link_lines = buttons that become premium-emoji text links
    at the end of the text / caption. Returns the new message."""
    kw = {"disable_notification": bool(silent)}

    async def go(fn, *args, **extra):
        if not thread_id:
            return await fn(*args, **extra, **kw)
        try:
            return await fn(*args, **extra, message_thread_id=int(thread_id), **kw)
        except TypeError:  # older name of the parameter
            return await fn(*args, **extra, reply_to_message_id=int(thread_id), **kw)

    if not link_lines:
        return await go(user.copy_message, chat_id, bot_username, user_msg.id)
    base = user_msg.caption or user_msg.text or ""
    base_html = getattr(base, "html", None) or html.escape(str(base))
    text = (base_html + "\n\n" if base_html else "") + "\n".join(link_line(b) for b in link_lines)
    if user_msg.media:
        return await go(user.copy_message, chat_id, bot_username, user_msg.id, caption=text, parse_mode=enums.ParseMode.HTML)
    return await go(user.send_message, chat_id, text, parse_mode=enums.ParseMode.HTML, **_nopreview())


async def check_chat(chat, bot_id: int) -> str:
    """Can the Premium account post there, and can the bot add buttons to its posts?"""
    lines = []
    try:
        m = await user.get_chat_member(chat, "me")
        st = str(getattr(m.status, "name", m.status)).split(".")[-1]
        priv = getattr(m, "privileges", None)
        can = st == "OWNER" or bool(priv and getattr(priv, "can_post_messages", True))
        lines.append(f"{'✅' if can else '❌'} Premium account: {st}" + ("" if can else " - post karne ka right nahi"))
    except Exception as e:
        lines.append(f"❌ Premium account chat nahi khol paya: <code>{type(e).__name__}</code>")
    r = await tgapi.call("getChatMember", {"chat_id": chat, "user_id": bot_id})
    if r.get("ok"):
        res = r["result"]
        ok = res.get("status") == "creator" or bool(res.get("can_edit_messages"))
        lines.append(f"{'✅' if ok else '❌'} Bot: {res.get('status')}" + ("" if ok else " - <i>Edit messages of others</i> right chahiye (buttons ke liye)"))
    else:
        lines.append(f"❌ Bot: <code>{tgapi.desc(r)[:100]}</code>")
    return "\n".join(lines)
