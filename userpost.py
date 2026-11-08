"""Post as your own Premium account (session string), so premium emoji in the post TEXT also work in channels.

How it works
  1. You send the content to the bot from your Premium account (as always).
  2. The Premium account (userbot) copies that very message into the channel - as you, a Premium user,
     so Telegram keeps the premium emoji.
  3. The bot (admin of the channel) then adds the buttons by editing the post.
Limits: a user account cannot attach inline buttons itself, so buttons still come from the bot (premium button icons
follow the bot rule, /emojicheck).  Rich Posts are sent by the bot only.
Safety: the session string is the key to your whole Telegram account. Keep it ONLY in the host's environment
variable USER_SESSION_STRING - never in code, never on GitHub, never in a chat.
"""
import logging
import os

from pyrogram import Client

import tgapi
from config import API_HASH, API_ID

log = logging.getLogger("userpost")
SESSION = os.getenv("USER_SESSION_STRING", "").strip()
user = None
_me = None


def enabled() -> bool:
    return user is not None


async def start():
    """Start the userbot if USER_SESSION_STRING is set. A broken session must never stop the bot."""
    global user, _me
    if not SESSION:
        return None
    try:
        c = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION, in_memory=True)
        await c.start()
        user, _me = c, await c.get_me()
        log.info("Userbot started as %s (premium=%s)", _me.id, getattr(_me, "is_premium", None))
    except Exception as e:
        user = None
        log.error("Userbot could not start (%s) - posting as the Premium account is OFF", e)
    return _me


async def stop():
    if user:
        try:
            await user.stop()
        except Exception:
            pass


async def me():
    return _me


async def find_copy(bot_username: str, meta: dict):
    """The Premium account's own copy of the message you just sent to the bot (matched by time, text and media)."""
    async for m in user.get_chat_history(bot_username, limit=30):
        if not getattr(m, "outgoing", True):
            continue
        if abs((m.date - meta["date"]).total_seconds()) > 8:
            continue
        if (m.text or m.caption or "") != meta["text"] or bool(m.media) != meta["media"]:
            continue
        return m
    return None


async def post(bot_username: str, user_msg, chat_id, thread_id=None, silent: bool = False):
    """Copy the message into chat_id as the Premium account. Returns the new message."""
    kw = {"disable_notification": bool(silent)}
    if not thread_id:
        return await user.copy_message(chat_id, bot_username, user_msg.id, **kw)
    try:
        return await user.copy_message(chat_id, bot_username, user_msg.id, message_thread_id=int(thread_id), **kw)
    except TypeError:  # older name of the parameter
        return await user.copy_message(chat_id, bot_username, user_msg.id, reply_to_message_id=int(thread_id), **kw)


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
