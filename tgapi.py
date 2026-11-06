"""Raw Bot API calls: copy a message with buttons (incl. premium-emoji icons), edit buttons, send Rich Messages.
If Telegram refuses premium emoji, the call is retried with the normal emoji instead (and you are told)."""
import logging
import re

import aiohttp

from config import BOT_TOKEN

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
log = logging.getLogger("tgapi")
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
    return any(b.get("icon") for row in grid for b in row if b)


async def _with_icons(method: str, payload: dict, grid: list, allow_empty: bool):
    """-> (response, used the normal-emoji fallback?)"""
    def build(icons):
        rows = markup_rows(grid, icons)
        p = dict(payload)
        if rows or allow_empty:
            p["reply_markup"] = {"inline_keyboard": rows}
        return p

    res = await call(method, build(True))
    if res.get("ok") or "not modified" in desc(res).lower() or not has_icons(grid):
        return res, False
    res2 = await call(method, build(False))  # premium icons refused -> same buttons with the normal emoji
    return res2, bool(res2.get("ok"))


async def copy_message(chat_id, from_chat_id, message_id, grid: list, thread_id=None):
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    return await _with_icons("copyMessage", payload, grid, allow_empty=False)


async def set_markup(chat_id, message_id: int, grid: list):
    return await _with_icons("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id}, grid, allow_empty=True)


# ---------- rich messages ----------
def strip_emoji_tags(h: str) -> str:
    return re.sub(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', r"\1", h, flags=re.S)


async def send_rich(chat_id, html: str, thread_id=None):
    payload = {"chat_id": chat_id, "rich_message": {"html": html}}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
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
