"""/emojicheck - find out, with real test messages, what Telegram lets THIS bot do with premium emoji in a chat."""
import asyncio

import tgapi


def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


async def probe(chat_id, emoji_id: str, fb: str) -> dict:
    """Sends 3 short silent test messages. -> {'body', 'icon', 'rich', 'errors', 'ids'}"""
    out = {"body": None, "icon": None, "rich": None, "errors": [], "ids": []}
    ent = [{"type": "custom_emoji", "offset": 0, "length": _u16(fb), "custom_emoji_id": emoji_id}]
    r = await tgapi.call("sendMessage", {"chat_id": chat_id, "text": f"{fb} premium emoji in text (test)", "entities": ent, "disable_notification": True})
    if r.get("ok"):
        out["ids"].append(r["result"]["message_id"])
        out["body"] = any(e.get("type") == "custom_emoji" and str(e.get("custom_emoji_id")) == emoji_id for e in (r["result"].get("entities") or []))
    else:
        out["body"] = False
        out["errors"].append("text: " + tgapi.desc(r))

    btn = {"text": "Icon test", "url": "https://t.me/", "icon_custom_emoji_id": emoji_id}
    r = await tgapi.call("sendMessage", {"chat_id": chat_id, "text": "🔘 premium icon on a button (test)", "reply_markup": {"inline_keyboard": [[btn]]}, "disable_notification": True})
    if r.get("ok"):
        out["ids"].append(r["result"]["message_id"])
        kb = (r["result"].get("reply_markup") or {}).get("inline_keyboard")
        out["icon"] = None if kb is None else any(b.get("icon_custom_emoji_id") for row in kb for b in row)
    else:
        out["icon"] = False
        out["errors"].append("button: " + tgapi.desc(r))

    h = (f'<p>Rich message test <tg-emoji emoji-id="{emoji_id}">{fb}</tg-emoji></p><tg-button-row>'
         f'<tg-button type="url" url="https://t.me/"><tg-emoji emoji-id="{emoji_id}">{fb}</tg-emoji> Rich button</tg-button></tg-button-row>')
    r = await tgapi.call("sendRichMessage", {"chat_id": chat_id, "rich_message": {"html": h}, "disable_notification": True})
    if r.get("ok"):
        out["ids"].append(r["result"]["message_id"])
        out["rich"] = "sent"
    else:
        out["rich"] = "error"
        out["errors"].append("rich: " + tgapi.desc(r))

    caps = {k: out[k] for k in ("body", "icon") if out[k] is not None}
    info = await tgapi.call("getChat", {"chat_id": chat_id})
    keys = {chat_id}
    if info.get("ok"):
        keys.add(info["result"]["id"])
        if info["result"].get("username"):
            keys.add("@" + info["result"]["username"])
    for k in keys:
        tgapi.CAPS.setdefault(k, {}).update(caps)
    return out


async def cleanup(chat_id, ids: list, delay: int = 20):
    await asyncio.sleep(delay)
    for i in ids:
        await tgapi.call("deleteMessage", {"chat_id": chat_id, "message_id": i})


def report(out: dict, where: str) -> str:
    def mark(v):
        return "✅" if v else ("❌" if v is False else "❓")
    lines = [
        f"🧪 <b>Emoji test: {where}</b>",
        f"{mark(out['body'])} Text mein premium emoji",
        f"{mark(out['icon'])} Button par premium icon" + ("" if out["icon"] is not None else " (Telegram ne wapas nahi bataya)"),
        f"{'👀' if out['rich'] == 'sent' else '❌'} Rich message " + ("bhej diya - upar jaake dekhein, emoji premium dikh raha hai ya normal?" if out["rich"] == "sent" else "bhejna fail"),
    ]
    if out["errors"]:
        lines.append("\n<b>Telegram ke errors:</b>\n" + "\n".join(f"<code>{e[:160]}</code>" for e in out["errors"]))
    if out["body"] is False or out["icon"] is False:
        lines.append(
            "\n💡 <b>Matlab:</b> Telegram is chat mein bot ko premium emoji bhejne nahi deta.\n"
            "◉ Bot ka <b>owner</b> (jis account se BotFather mein bot bana) Premium hona chahiye.\n"
            "◉ Owner ka Premium sirf <b>private chat, group, supergroup</b> mein kaam karta hai - <b>channel mein nahi</b>.\n"
            "◉ Channel ke liye bot ke paas <b>Fragment se kharida hua extra username</b> chahiye."
        )
    lines.append("\n🗑 Test messages 20 second mein delete ho jayenge.")
    return "\n".join(lines)
