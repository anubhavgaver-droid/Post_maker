"""Raw Bot API calls: copy a message with buttons (incl. premium-emoji icons), edit buttons, send Rich Messages.

Premium emoji icons on buttons are applied in TWO steps and CHECKED:
  1. the post goes out with the normal emoji in the button text (always safe),
  2. the bot then tries to upgrade the buttons to the premium icons and looks at what Telegram sent back.
     Icons kept -> done.  Refused or silently dropped -> the normal emoji stay and the reason is reported.
"""
import logging
import os
import re

import aiohttp

from config import BOT_TOKEN

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
log = logging.getLogger("tgapi")
TRUST_ICONS = os.getenv("TRUST_ICONS", "0") == "1"  # 1 = if Telegram does not echo the buttons back, assume the icons were kept
CAPS = {}     # chat -> {"body": bool|None, "icon": bool|None}   filled by /emojicheck
_kinds = {}   # chat -> 'private' | 'group' | 'supergroup' | 'channel'
_session = None


async def call(method: str, payload: dict) -> dict:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    try:
        async with _session.post(f"{API}/{method}", json=payload) as r:
            return await r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def desc(res: dict) -> str:
    return str(res.get("description", "unknown error"))


def norm_chat(ref):
    if isinstance(ref, int):
        return ref
    s = str(ref).strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else s


async def chat_kind(chat_id):
    if chat_id not in _kinds:
        res = await call("getChat", {"chat_id": chat_id})
        if not res.get("ok"):
            return None
        _kinds[chat_id] = res["result"].get("type")
    return _kinds[chat_id]


# ---------- classic inline buttons ----------
def button_json(b: dict, icons: bool = True) -> dict:
    if "cb" in b:  # a builder control (➕, New Row ...)
        return {"text": b["text"], "callback_data": b["cb"]}
    d = {"text": b["name"], "url": b["url"]}
    if b.get("style"):
        d["style"] = b["style"]
    if b.get("icon"):
        if icons:
            d["icon_custom_emoji_id"] = str(b["icon"])
        else:
            d["text"] = f'{b.get("fb") or "⭐"} {b["name"]}'
    return d


def markup_rows(grid: list, icons: bool = True) -> list:
    rows = [[button_json(b, icons) for b in row if b] for row in grid]
    return [r for r in rows if r]


def has_icons(grid: list) -> bool:
    return any(b.get("icon") for row in grid for b in row if b and "url" in b)


def _icons_kept(res: dict, grid: list):
    """True / False = the buttons Telegram sent back do / do not carry the icons. None = it did not send them back."""
    want = sum(1 for row in grid for b in row if b and b.get("icon"))
    try:
        kb = res["result"]["reply_markup"]["inline_keyboard"]
    except (KeyError, TypeError):
        return None
    return sum(1 for r in kb for b in r if b.get("icon_custom_emoji_id")) >= want


def _edit_payload(chat_id, message_id, grid, icons):
    return {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": markup_rows(grid, icons)}}


async def _upgrade(chat_id, message_id, grid):
    """Step 2: premium icons on an already published post. -> (kept?, reason)"""
    if CAPS.get(chat_id, {}).get("icon") is False:
        return False, "pichhle /emojicheck test me is chat me button icon allowed nahi tha"
    r = await call("editMessageReplyMarkup", _edit_payload(chat_id, message_id, grid, True))
    if r.get("ok"):
        kept = _icons_kept(r, grid)
        if kept or (kept is None and TRUST_ICONS):
            return True, ""
        await call("editMessageReplyMarkup", _edit_payload(chat_id, message_id, grid, False))  # put the normal emoji back
        return False, "Telegram ne request accept ki par icon chupchap hata diya"
    return False, desc(r)


async def copy_message(chat_id, from_chat_id, message_id, grid: list, thread_id=None, silent=False):
    """-> (response of the copy, {'icons': None | 'icons' | 'fallback', 'reason': str})"""
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    if silent:
        payload["disable_notification"] = True
    rows = markup_rows(grid, icons=False)  # step 1: normal emoji in the text - always accepted
    if rows:
        payload["reply_markup"] = {"inline_keyboard": rows}
    res = await call("copyMessage", payload)
    if not res.get("ok") or not has_icons(grid):
        return res, {"icons": None, "reason": ""}
    kept, reason = await _upgrade(chat_id, res["result"]["message_id"], grid)
    return res, {"icons": "icons" if kept else "fallback", "reason": reason}


async def set_markup(chat_id, message_id: int, grid: list):
    """Replace the buttons of a message. -> (response, {'icons': ..., 'reason': ...})"""
    res = await call("editMessageReplyMarkup", _edit_payload(chat_id, message_id, grid, True))
    if not has_icons(grid):
        return res, {"icons": None, "reason": ""}
    if res.get("ok"):
        kept = _icons_kept(res, grid)
        if kept or (kept is None and TRUST_ICONS):
            return res, {"icons": "icons", "reason": ""}
        reason = "Telegram ne request accept ki par icon chupchap hata diya"
    elif "not modified" in desc(res).lower():
        return res, {"icons": None, "reason": ""}
    else:
        reason = desc(res)
    res2 = await call("editMessageReplyMarkup", _edit_payload(chat_id, message_id, grid, False))
    return res2, {"icons": "fallback" if res2.get("ok") else None, "reason": reason}


async def pin(chat_id, message_id: int):
    return await call("pinChatMessage", {"chat_id": chat_id, "message_id": message_id, "disable_notification": True})


# ---------- rich messages ----------
def strip_emoji_tags(h: str) -> str:
    return re.sub(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', r"\1", h, flags=re.S)


async def send_rich(chat_id, html: str, thread_id=None, silent=False):
    payload = {"chat_id": chat_id, "rich_message": {"html": html}}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    if silent:
        payload["disable_notification"] = True
    res = await call("sendRichMessage", payload)
    if res.get("ok") or "<tg-emoji" not in html:
        return res, False
    res2 = await call("sendRichMessage", dict(payload, rich_message={"html": strip_emoji_tags(html)}))
    return res2, bool(res2.get("ok"))


async def edit_rich(chat_id, message_id: int, html: str):
    payload = {"chat_id": chat_id, "message_id": message_id, "rich_message": {"html": html}}
    res = await call("editMessageText", payload)
    if res.get("ok") or "not modified" in desc(res).lower() or "<tg-emoji" not in html:
        return res, False
    res2 = await call("editMessageText", dict(payload, rich_message={"html": strip_emoji_tags(html)}))
    return res2, bool(res2.get("ok"))
