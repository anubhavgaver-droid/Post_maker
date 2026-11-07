import asyncio
import functools
import html
import logging
import os
import re

from bson import ObjectId
from pyrogram import Client, filters, enums, idle
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    CallbackQuery,
)

import blocks as B
import db
import emojicheck
import rich_flow
import targets as T
import tgapi
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
from entities import custom_emoji_ids, entities_to_html, first_custom_emoji, split_icon_html
from server import start_web_server, self_ping_loop

app = Client("interactive_post_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN,
             in_memory=True, parse_mode=enums.ParseMode.HTML)

user_sessions = {}  # user id -> session dict (classic builder or rich builder)
esc = html.escape

MENU = {
    "new": "📝 New Post", "edit": "🔗 Edit Post", "topic": "💬 Topic Post", "edittopic": "✏️ Edit Topic",
    "rich": "🎨 Rich Post", "posts": "📚 My Rich Posts", "channels": "📢 Channels", "topics": "💬 Topics",
    "cancel": "❌ Cancel Process",
}
COMMANDS = ["start", "help", "cancel", "newpost", "editpost", "topicpost", "edittopic", "richpost", "emojicheck", "addadmin", "deladmin", "adminlist"]
MENU_RE = filters.regex(r"^(?:" + "|".join(re.escape(v) for v in MENU.values()) + r")$")


def _label(key):
    return filters.regex(r"^" + re.escape(MENU[key]) + r"$")


# ----------------- ADMIN CHECK -----------------
async def check_is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    return await db.admins.find_one({"user_id": user_id}) is not None


# ----------------- KEYBOARDS -----------------
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [MENU["new"], MENU["edit"]],
            [MENU["topic"], MENU["edittopic"]],
            [MENU["rich"], MENU["posts"]],
            [MENU["channels"], MENU["topics"]],
        ],
        resize_keyboard=True,
    )


def cancel_only_keyboard():
    return ReplyKeyboardMarkup([[MENU["cancel"]]], resize_keyboard=True)


def style_selection_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟦 Primary", callback_data="style_primary"), InlineKeyboardButton("🟩 Success", callback_data="style_success")],
        [InlineKeyboardButton("🟥 Danger", callback_data="style_danger"), InlineKeyboardButton("⚪ Normal", callback_data="style_normal")],
    ])


def safe(fn):
    """Any crash inside a handler is shown to the admin (instead of the bot going silent)."""
    @functools.wraps(fn)
    async def wrapper(client, update):
        try:
            return await fn(client, update)
        except Exception as e:
            if os.getenv("DEBUG_RAISE") == "1":
                raise
            logging.exception("handler error")
            try:
                await client.send_message(update.from_user.id, f"⚠️ <b>Error:</b> <code>{esc(type(e).__name__)}: {esc(str(e)[:200])}</code>\nPhir try karein, ya ❌ Cancel Process dabayein.")
                if hasattr(update, "answer"):
                    await update.answer()
            except Exception:
                pass
    return wrapper


def chooser_markup(session):
    return pairs_markup(T.chooser_pairs(session["opts"], session["sel"], session.get("silent", False), session.get("pin", False)))


def pairs_markup(rows):
    """targets.chooser_pairs -> normal inline keyboard (classic builder)"""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=f"tg:{a}") for t, a in r] for r in rows])


# ----------------- HELPERS -----------------
def parse_post_link(link: str):
    """-> (chat, topic id or None, message id). Private 't.me/c/...' links are checked FIRST:
    otherwise 't.me/c/123/45' would be read as a public channel called 'c'."""
    link = link.strip()
    m = re.match(r"https?://t\.me/c/(\d+)/(\d+)/(\d+)", link)
    if m:
        return int(f"-100{m.group(1)}"), int(m.group(2)), int(m.group(3))
    m = re.match(r"https?://t\.me/c/(\d+)/(\d+)", link)
    if m:
        return int(f"-100{m.group(1)}"), None, int(m.group(2))
    m = re.match(r"https?://t\.me/([^/]+)/(\d+)/(\d+)", link)
    if m:
        return f"@{m.group(1)}", int(m.group(2)), int(m.group(3))
    m = re.match(r"https?://t\.me/([^/]+)/(\d+)", link)
    if m:
        return f"@{m.group(1)}", None, int(m.group(2))
    return None, None, None


def parse_channel_input(text: str):
    text = text.strip()
    if text.startswith("https://t.me/"):
        text = "@" + text.replace("https://t.me/", "").split("/")[0].lstrip("@")
    if text.startswith("@"):
        return text
    try:
        n = int(text)
        return int(f"-100{n}") if n > 0 and not str(n).startswith("-100") else n
    except ValueError:
        return text


def forwarded_ref(message):
    """(chat id, message id) of a forwarded channel post - works with old and new Kurigram."""
    chat = getattr(message, "forward_from_chat", None)
    mid = getattr(message, "forward_from_message_id", None)
    if chat and mid:
        return chat.id, mid
    origin = getattr(message, "forward_origin", None)
    chat, mid = getattr(origin, "chat", None), getattr(origin, "message_id", None)
    return (chat.id, mid) if chat and mid else (None, None)


def style_str(st):
    if not st:
        return None
    name = str(getattr(st, "name", st)).split(".")[-1].lower()
    return {"primary": "primary", "success": "success", "positive": "success", "danger": "danger"}.get(name)


async def toast(client, uid, text, secs=2):
    """A short message that removes itself."""
    try:
        m = await client.send_message(uid, text)
        await asyncio.sleep(secs)
        await m.delete()
    except Exception:
        pass


# ----------------- CLASSIC BUILDER: the button grid -----------------
def normalize(grid):
    out = []
    for row in grid:
        items = [x for x in row if x is not None]
        out.append(items + [None] if len(items) < 3 else items)
    return out or [[None]]


def final_grid(grid):
    return [[b for b in row if b] for row in grid if any(row)]


def builder_grid(session):
    rows = []
    for r, row in enumerate(session["grid"]):
        line = []
        for c, item in enumerate(row):
            if item is None:
                line.append({"text": "➕", "cb": f"add_{r}_{c}"})
            elif session.get("rm_mode"):
                line.append({"text": f"❌ {item['name'][:20]}", "cb": f"del_{r}_{c}"})
            else:
                line.append(item)
        rows.append(line)
    rows.append([{"text": "➕ New Row", "cb": "add_row"}, {"text": "✅ Publish / Update", "cb": "finish_post"}])
    rows.append([{"text": "💾 Save Layout", "cb": "lay_save"}, {"text": "📋 Load Layout", "cb": "lay_load"}])
    rows.append([
        {"text": "✅ Remove Mode ON" if session.get("rm_mode") else "🗑 Remove Mode", "cb": "rm_toggle"},
        {"text": "🧹 Clear All", "cb": "clear_btns"},
    ])
    return rows


async def send_preview(client, uid, session, title="🔍 Live Preview"):
    """The preview IS the real post (copied), with the builder buttons under it."""
    src_chat, src_id = session["src"]
    res, info = await tgapi.copy_message(uid, src_chat, src_id, builder_grid(session))
    if not res.get("ok"):
        return await client.send_message(uid, f"❌ <b>Preview fail:</b> <code>{esc(tgapi.desc(res))}</code>", reply_markup=main_menu_keyboard())
    session["preview_id"] = res["result"]["message_id"]
    note = f"\n<i>(Premium icon is chat mein nahi chala: {esc(info['reason'])})</i>" if info["icons"] == "fallback" else ""
    await client.send_message(uid, f"{title} ☝️\n➕ dabakar button add karein.\n✅ <b>Publish / Update</b> se aage badhein." + note)


async def refresh_preview(client, uid, session):
    res, info = await tgapi.set_markup(uid, session["preview_id"], builder_grid(session))
    if not res.get("ok") and "not modified" not in tgapi.desc(res).lower():
        await send_preview(client, uid, session)


# ----------------- COMMAND & MENU HANDLERS -----------------
HELP_TEXT = (
    "<b>🤖 Advanced Post Builder</b>\n\n"
    "📝 <b>New Post</b> – koi bhi message (text/photo/video) bhejo, uske neeche URL buttons lagao, channel par publish karo.\n"
    "🔗 <b>Edit Post</b> – purani post ke buttons badlo.\n"
    "💬 <b>Topic Post / Edit Topic</b> – group ke topic ke liye.\n"
    "🎨 <b>Rich Post</b> – bade headings, text, quote, table-boxes aur rich buttons wali post.\n"
    "📚 <b>My Rich Posts</b> – publish ki hui rich posts edit / delete karo.\n\n"
    "✨ <b>Premium emoji:</b> button ke naam ke saath premium emoji bhejo = button icon. Rich post ke text mein bhi chalta hai.\n"
    "🔎 Koi premium emoji akele bhejo (jab koi process na chal raha ho) – main uski ID bata dunga.\n"
    "🧪 /emojicheck – asli test: kis chat mein premium emoji chalta hai, kis mein nahi."
)


@app.on_message(filters.command(["start", "help"]) & filters.private)
async def start_cmd(client: Client, message: Message):
    if not await check_is_admin(message.from_user.id):
        return
    await message.reply_text(HELP_TEXT, reply_markup=main_menu_keyboard())


@app.on_message(filters.command("addadmin") & filters.private)
async def add_admin_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.reply_text("❌ Aapke paas yeh command chalane ki permission nahi hai!")
    try:
        new_admin_id = int(message.text.split()[1])
        await db.admins.update_one({"user_id": new_admin_id}, {"$set": {"user_id": new_admin_id, "added_by": message.from_user.id}}, upsert=True)
        await message.reply_text(f"✅ User ID <code>{new_admin_id}</code> ko successfully Admin bana diya gaya hai!")
    except Exception:
        await message.reply_text("⚠️ Sahi format use karein:\n<code>/addadmin USER_ID</code>")


@app.on_message(filters.command("deladmin") & filters.private)
async def del_admin_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.reply_text("❌ Aapke paas yeh command chalane ki permission nahi hai!")
    try:
        target = int(message.text.split()[1])
        result = await db.admins.delete_one({"user_id": target})
        await message.reply_text(f"✅ User ID <code>{target}</code> ko Admin list se hata diya gaya hai." if result.deleted_count else "⚠️ Yeh User ID database mein admin ke roop mein nahi mili.")
    except Exception:
        await message.reply_text("⚠️ Sahi format use karein:\n<code>/deladmin USER_ID</code>")


@app.on_message(filters.command("adminlist") & filters.private)
async def admin_list_cmd(client: Client, message: Message):
    if not await check_is_admin(message.from_user.id):
        return
    db_admins = await db.admins.find({}).to_list(length=None)
    text = "👥 <b>Admins List:</b>\n\n" + f"👑 <b>Super Admins:</b> {ADMIN_IDS}\n\n" + "📋 <b>Dynamic Admins:</b>\n"
    text += "".join(f"• <code>{a.get('user_id')}</code>\n" for a in db_admins) or "<i>Koi dynamic admin added nahi hai.</i>"
    await message.reply_text(text)


@app.on_message((_label("cancel") | filters.command("cancel")) & filters.private)
async def cancel_cmd(client: Client, message: Message):
    user_sessions.pop(message.from_user.id, None)
    await message.reply_text("❌ Operation cancelled.", reply_markup=main_menu_keyboard())


async def _start_classic(message, mode, prompt):
    uid = message.from_user.id
    if not await check_is_admin(uid):
        return
    editing = mode in ("EDIT", "TOPIC_EDIT")
    user_sessions[uid] = {"mode": mode, "grid": [] if editing else [[None]], "state": "WAITING_POST_LINK" if editing else "WAITING_TITLE",
                          "src": None, "preview_id": None, "rm_mode": False}
    await message.reply_text(prompt, reply_markup=cancel_only_keyboard())


@app.on_message(_label("new") & filters.private)
@app.on_message(filters.command("newpost") & filters.private)
async def newpost_cmd(client, message):
    await _start_classic(message, "NEW", "<b>📝 Channel Post Content / Message bhejein:</b>\n<i>(text, photo, video - kuch bhi; premium emoji aur formatting jaisi hai waisi rahegi)</i>")


@app.on_message(_label("edit") & filters.private)
@app.on_message(filters.command("editpost") & filters.private)
async def editpost_cmd(client, message):
    await _start_classic(message, "EDIT", "<b>🔗 Channel Post Ka Link Bhejein ya Private Channel ki post yahan Forward karein:</b>\n(e.g. <code>https://t.me/mychannel/123</code>)")


@app.on_message(_label("topic") & filters.private)
@app.on_message(filters.command("topicpost") & filters.private)
async def topicpost_cmd(client, message):
    await _start_classic(message, "TOPIC_NEW", "<b>💬 Topic Group Post Content / Message bhejein:</b>")


@app.on_message(_label("edittopic") & filters.private)
@app.on_message(filters.command("edittopic") & filters.private)
async def edittopic_cmd(client, message):
    await _start_classic(message, "TOPIC_EDIT", "<b>🔗 Topic Post Ka Link Bhejein:</b>\n(e.g. <code>https://t.me/c/123456/45/678</code>)")


@app.on_message(_label("rich") & filters.private)
@app.on_message(filters.command("richpost") & filters.private)
async def richpost_cmd(client, message):
    uid = message.from_user.id
    if not await check_is_admin(uid):
        return
    s = rich_flow.new_session()
    user_sessions[uid] = s
    await message.reply_text("🎨 <b>Rich Post Builder</b> khul gaya.", reply_markup=cancel_only_keyboard())
    await rich_flow.open_panel(client, uid, message.chat.id, s)


@app.on_message(filters.command("emojicheck") & filters.private)
async def emojicheck_cmd(client, message):
    uid = message.from_user.id
    if not await check_is_admin(uid):
        return
    user_sessions[uid] = {"state": "EMO_ID"}
    await message.reply_text(
        "🧪 <b>Premium Emoji Test</b>\nEk <b>premium emoji</b> bhejein. Phir bataunga ki kis chat mein test karna hai.\n"
        "Bot dekhega ki Telegram wahan text, button-icon aur rich message mein premium emoji rakhta hai ya nahi.",
        reply_markup=cancel_only_keyboard())


@app.on_message(_label("posts") & filters.private)
async def myposts_cmd(client, message):
    uid = message.from_user.id
    if not await check_is_admin(uid):
        return
    s = rich_flow.new_session()
    user_sessions[uid] = s
    await rich_flow.open_posts(client, uid, message.chat.id, s)


@app.on_message(_label("channels") & filters.private)
async def manage_channels_menu(client, message):
    uid = message.from_user.id
    if not await check_is_admin(uid):
        return
    channels = await db.channels.find({"user_id": uid}).to_list(length=None)
    kb = [[InlineKeyboardButton(f"📢 {c.get('name')}", callback_data="ignore_ch"), InlineKeyboardButton("❌ Delete", callback_data=f"del_ch_{c['_id']}")] for c in channels]
    kb.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_new_ch_prompt")])
    await message.reply_text("📢 <b>Manage Saved Channels:</b>", reply_markup=InlineKeyboardMarkup(kb))


@app.on_message(_label("topics") & filters.private)
async def manage_topics_menu(client, message):
    uid = message.from_user.id
    if not await check_is_admin(uid):
        return
    topics = await db.topics.find({"user_id": uid}).to_list(length=None)
    kb = [[InlineKeyboardButton(f"💬 {t.get('name')}", callback_data="ignore_tp"), InlineKeyboardButton("❌ Delete", callback_data=f"del_tp_{t['_id']}")] for t in topics]
    kb.append([InlineKeyboardButton("➕ Add New Topic", callback_data="add_new_tp_prompt")])
    await message.reply_text("💬 <b>Manage Saved Group Topics:</b>", reply_markup=InlineKeyboardMarkup(kb))


# ----------------- MAIN MESSAGE ROUTER -----------------
@app.on_message(filters.private & ~filters.command(COMMANDS) & ~MENU_RE)
@safe
async def message_handler(client: Client, message: Message):
    uid = message.from_user.id
    if not await check_is_admin(uid):
        return
    session = user_sessions.get(uid)

    if not session:  # nothing running: a premium emoji sent alone -> tell its ID
        ids = custom_emoji_ids(message.entities)
        if ids:
            await message.reply_text("🔎 <b>Premium emoji ID:</b>\n" + "\n".join(f"<code>{i}</code>" for i in dict.fromkeys(ids)))
        return

    state = session.get("state")
    text = message.text or ""

    if state == "RICH":
        return await rich_flow.on_text(client, message, session)

    if state == "EMO_ID":
        eid, fb = first_custom_emoji(text, message.entities)
        if not eid:
            return await message.reply_text("⚠️ Ek premium emoji bhejein (jo aapke Premium account se dikhta ho).")
        session.update(emo_id=eid, emo_fb=fb, state="EMO_CHAT")
        return await message.reply_text(
            "✅ Emoji mil gaya.\n\nAb batayein kis chat par test karna hai:\n"
            "◉ <code>here</code> = ye chat (PM)\n◉ <code>@channel</code> ya <code>-100123…</code>\n"
            "\n<i>⚠️ Us chat mein 20 second ke liye 3 chhote silent test messages aayenge, phir delete ho jayenge.</i>")

    if state == "EMO_CHAT":
        if text.strip().lower() in ("here", "pm", "me"):
            chat, where = uid, "Private chat (PM)"
        else:
            parsed = T.parse_custom(text)
            if not parsed:
                return await message.reply_text("⚠️ Samajh nahi aaya. <code>here</code>, <code>@channel</code> ya <code>-100123…</code> bhejein.")
            chat, where = parsed[0], str(parsed[0])
        await message.reply_text("🧪 Test chal raha hai…")
        out = await emojicheck.probe(chat, session["emo_id"], session["emo_fb"])
        user_sessions.pop(uid, None)
        asyncio.create_task(emojicheck.cleanup(chat, out["ids"]))
        return await message.reply_text(emojicheck.report(out, where), reply_markup=main_menu_keyboard())

    if state == "WAITING_NEW_CHANNEL":
        try:
            name, ref = [x.strip() for x in text.split(",", 1)]
            ch = T.parse_custom(ref)[0]
            await db.channels.update_one({"user_id": uid, "chat_id": str(ch)}, {"$set": {"name": name, "chat_id": str(ch)}}, upsert=True)
            await message.reply_text(f"✅ <b>Channel Saved:</b> {esc(name)}", reply_markup=main_menu_keyboard())
        except Exception:
            return await message.reply_text("⚠️ Sahi format mein bhejein: <code>Channel Name, @username</code>")
        user_sessions.pop(uid, None)

    elif state == "WAITING_NEW_TOPIC":
        try:
            name, rest = [x.strip() for x in text.split(",", 1)]
            parsed = T.parse_custom(rest)
            chat, thread = parsed
            if not thread:
                raise ValueError
            await db.topics.update_one({"user_id": uid, "chat_id": str(chat), "thread_id": thread},
                                       {"$set": {"name": name, "chat_id": str(chat), "thread_id": thread}}, upsert=True)
            await message.reply_text(f"✅ <b>Topic Saved:</b> {esc(name)}", reply_markup=main_menu_keyboard())
        except Exception:
            return await message.reply_text("⚠️ Sahi format mein bhejein: <code>Topic Name, Link</code> ya <code>Topic Name, -100123, 45</code>")
        user_sessions.pop(uid, None)

    elif state == "WAITING_TITLE":
        session["src"] = (message.chat.id, message.id)
        session["premium_body"] = bool(custom_emoji_ids(message.entities) or custom_emoji_ids(getattr(message, "caption_entities", None)))
        session["state"] = "BUILDING"
        await send_preview(client, uid, session)

    elif state == "WAITING_POST_LINK":
        chat_id, mid = forwarded_ref(message)
        thread_id = None
        if not chat_id:
            chat_id, thread_id, mid = parse_post_link(text)
            if not chat_id or not mid:
                return await message.reply_text("⚠️ Invalid link! Ya toh public link bhejein ya phir private channel ki post yahan forward karein.")
        try:
            target = await client.get_messages(chat_id, mid)
            if not target or target.empty:
                return await message.reply_text("❌ Post fetch nahi ho sakti. Check karein ki bot channel mein admin hai.")
            grid = []
            if target.reply_markup and getattr(target.reply_markup, "inline_keyboard", None):
                for row in target.reply_markup.inline_keyboard:
                    items = []
                    for b in row:
                        if b.url:
                            name, icon, fb = b.text, getattr(b, "icon_custom_emoji_id", None), None
                            items.append({"name": name, "url": b.url, "style": style_str(getattr(b, "style", None)),
                                          "icon": str(icon) if icon else None, "fb": fb})
                    if items:
                        grid.append(items)
            session.update(target_chat=chat_id, message_thread_id=thread_id, target_msg_id=mid, src=(chat_id, mid),
                           grid=normalize(grid + [[None]]), state="BUILDING")
            await send_preview(client, uid, session, "✏️ Live Edit Preview")
        except Exception as e:
            await message.reply_text(f"❌ Error: {esc(str(e))}")

    elif state == "WAITING_BTN_NAME":
        if not text:
            return await message.reply_text("⚠️ Button ka naam text mein bhejein.")
        name, icon, fb = split_icon_html(entities_to_html(text, message.entities))
        if not name:
            return await message.reply_text("⚠️ Sirf emoji nahi - naam bhi likhein (emoji ke saath).")
        session.update(temp_name=name[:60], temp_icon=icon, temp_fb=fb, state="WAITING_STYLE_CHOICE")
        await message.reply_text(
            f"✅ Button Name: <b>{esc(name)}</b>" + (" ✨ <i>(premium icon ke saath)</i>" if icon else "") + "\n\n🎨 <b>Button ka Style Select Karein:</b>",
            reply_markup=style_selection_keyboard(),
        )

    elif state == "WAITING_BTN_URL":
        url = B.parse_url(text)
        if not url:
            return await message.reply_text("⚠️ Sahi URL link bhejein! (https://… ya t.me/… ya @username)")
        r, c = session["target_pos"]
        session["grid"][r][c] = {"name": session["temp_name"], "url": url, "style": session.get("selected_style"),
                                 "icon": session.get("temp_icon"), "fb": session.get("temp_fb")}
        session["grid"] = normalize(session["grid"])
        session["state"] = "BUILDING"
        await refresh_preview(client, uid, session)
        asyncio.create_task(toast(client, uid, "✨ Button add ho gaya! ☝️ Preview dekhein."))

    elif state == "WAITING_LAYOUT_NAME":
        name = text.strip()[:40]
        if not name:
            return await message.reply_text("⚠️ Naam bhejein.")
        await db.templates.update_one({"user_id": uid, "kind": "grid", "name": name}, {"$set": {"data": final_grid(session["grid"])}}, upsert=True)
        session["state"] = "BUILDING"
        await message.reply_text(f"💾 Layout saved: <b>{esc(name)}</b>")

    elif state == "WAITING_CUSTOM_TARGET":
        parsed = T.parse_custom(text)
        if not parsed:
            return await message.reply_text("⚠️ Samajh nahi aaya. <code>@channel</code> ya <code>-100123</code> ya <code>-100123, 45</code> (topic) bhejein.")
        chat, thread = parsed
        T.add_custom(session["opts"], session["sel"], chat, thread, f"{chat}" + (f" / {thread}" if thread else ""))
        session["state"] = "BUILDING"
        await client.send_message(uid, "📢 <b>Select karein, phir Publish:</b>", reply_markup=chooser_markup(session))


# ----------------- PUBLISH (classic) -----------------
async def publish_classic(client, uid, session):
    chosen = [o for o in session["opts"] if o["key"] in session["sel"]]
    if not chosen:
        return await client.send_message(uid, "⚠️ Kam se kam ek channel/topic ✅ karein.")
    src_chat, src_id = session["src"]
    grid = final_grid(session["grid"])
    lines, tip = [], False
    for o in chosen:
        res, info = await tgapi.copy_message(o["chat_id"], src_chat, src_id, grid, o.get("thread_id"), silent=session.get("silent", False))
        if not res.get("ok"):
            lines.append(f"❌ {esc(o['label'])}: <code>{esc(tgapi.desc(res))}</code>")
            continue
        mid = res["result"]["message_id"]
        line = f'✅ {esc(o["label"])} — <a href="{esc(T.post_link(o["chat_id"], mid), quote=True)}">open</a>'
        if info["icons"] == "icons":
            line += " ✨ premium icon laga"
        elif info["icons"] == "fallback":
            line += f"\n⚠️ Premium icon nahi laga, normal emoji use hua.\n<code>{esc(info['reason'][:120])}</code>"
            tip = True
        if session.get("pin"):
            pr = await tgapi.pin(o["chat_id"], mid)
            line += " 📌" if pr.get("ok") else f"\n⚠️ Pin fail: <code>{esc(tgapi.desc(pr))}</code>"
        if session.get("premium_body") and tgapi.CAPS.get(o["chat_id"], {}).get("body") is not True and await tgapi.chat_kind(o["chat_id"]) == "channel":
            line += "\n⚠️ Post ke text ke premium emoji channel mein shayad normal dikhein."
            tip = True
        lines.append(line)
    if tip:
        lines.append("\nℹ️ Pakka pata karne ke liye /emojicheck chalayein - wo asli test karke batata hai.")
    await client.send_message(uid, "🎉 <b>Publish result</b>\n\n" + "\n".join(lines), reply_markup=main_menu_keyboard(), disable_web_page_preview=True)
    user_sessions.pop(uid, None)


# ----------------- CALLBACK QUERY HANDLER -----------------
@app.on_callback_query()
@safe
async def callback_handler(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if not await check_is_admin(uid):
        return await query.answer("Access Denied!", show_alert=True)
    data = query.data or ""

    if data.startswith("rp:"):
        return await rich_flow.callback(client, query, user_sessions)

    if data.startswith("del_ch_"):
        await db.channels.delete_one({"_id": ObjectId(data[7:])})
        await query.answer("Channel Deleted!", show_alert=True)
        return await query.message.delete()
    if data.startswith("del_tp_"):
        await db.topics.delete_one({"_id": ObjectId(data[7:])})
        await query.answer("Topic Deleted!", show_alert=True)
        return await query.message.delete()
    if data == "add_new_ch_prompt":
        user_sessions[uid] = {"state": "WAITING_NEW_CHANNEL"}
        await query.message.reply_text("📢 Naya Channel bhejein (<code>Name, @username</code> format mein):", reply_markup=cancel_only_keyboard())
        return await query.answer()
    if data == "add_new_tp_prompt":
        user_sessions[uid] = {"state": "WAITING_NEW_TOPIC"}
        await query.message.reply_text("💬 Naya Topic bhejein (<code>Name, Link</code> ya <code>Name, -100123, 45</code>):", reply_markup=cancel_only_keyboard())
        return await query.answer()
    if data in ("ignore_ch", "ignore_tp"):
        return await query.answer("Delete karne ke liye side wale ❌ Delete button par click karein.")

    session = user_sessions.get(uid)
    if not session or session.get("state") == "RICH":
        return await query.answer("Session Expired!", show_alert=True)

    if data.startswith("add_") and data != "add_row":
        _, r, c = data.split("_")
        session["target_pos"] = (int(r), int(c))
        session["state"] = "WAITING_BTN_NAME"
        await query.answer()
        await client.send_message(uid, f"➕ <b>Row {int(r) + 1}, Col {int(c) + 1}</b> ke liye Button Name bhejein:\n<i>✨ Premium emoji ke saath bhejoge to wo button ka icon ban jayega.</i>")

    elif data == "add_row":
        session["grid"].append([None])
        await query.answer("New Row added!")
        await refresh_preview(client, uid, session)

    elif data.startswith("del_") and not data.startswith(("del_ch_", "del_tp_")):
        _, r, c = data.split("_")
        r, c = int(r), int(c)
        if r < len(session["grid"]) and c < len(session["grid"][r]):
            session["grid"][r][c] = None
            session["grid"] = normalize(session["grid"])
        await query.answer("Button removed")
        await refresh_preview(client, uid, session)

    elif data == "rm_toggle":
        session["rm_mode"] = not session.get("rm_mode")
        await query.answer("Remove mode ON - button par tap = hata do" if session["rm_mode"] else "Remove mode OFF")
        await refresh_preview(client, uid, session)

    elif data == "clear_btns":
        session["grid"], session["rm_mode"] = [[None]], False
        await query.answer("Saare buttons hata diye")
        await refresh_preview(client, uid, session)

    elif data.startswith("style_"):
        await query.answer()
        session["selected_style"] = {"style_primary": "primary", "style_success": "success", "style_danger": "danger"}.get(data)
        session["state"] = "WAITING_BTN_URL"
        await query.message.edit_text("✅ Style selected!\n\n🔗 <b>Ab URL Link bhejein:</b>")

    elif data == "lay_save":
        if not final_grid(session["grid"]):
            return await query.answer("Pehle koi button add karein", show_alert=True)
        session["state"] = "WAITING_LAYOUT_NAME"
        await query.answer()
        await client.send_message(uid, "💾 Layout ka naam bhejein:")

    elif data == "lay_load":
        lays = await db.templates.find({"user_id": uid, "kind": "grid"}).to_list(length=None)
        await query.answer()
        if not lays:
            return await client.send_message(uid, "📋 Abhi koi saved layout nahi hai.")
        kb = [[InlineKeyboardButton(f"📋 {l['name']}", callback_data=f"lay_use_{l['_id']}"), InlineKeyboardButton("🗑", callback_data=f"lay_del_{l['_id']}")] for l in lays]
        await client.send_message(uid, "📋 <b>Layout chunein:</b>", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("lay_use_"):
        lay = await db.templates.find_one({"_id": ObjectId(data[8:])})
        if lay:
            session["grid"] = normalize([list(r) for r in lay["data"]] + [[None]])
            await query.answer("Layout load ho gaya")
            await refresh_preview(client, uid, session)
            await query.message.delete()

    elif data.startswith("lay_del_"):
        await db.templates.delete_one({"_id": ObjectId(data[8:])})
        await query.answer("Layout delete ho gaya", show_alert=True)
        await query.message.delete()

    elif data == "finish_post":
        await query.answer()
        mode, grid = session["mode"], final_grid(session["grid"])
        if mode in ("NEW", "TOPIC_NEW"):
            session["opts"], session["sel"] = await T.load_options(uid, "c" if mode == "NEW" else "t"), set()
            await client.send_message(uid, ("📢 <b>Channel" if mode == "NEW" else "💬 <b>Topic") + " select karein (✅ tick), phir Publish:</b>",
                                      reply_markup=chooser_markup(session))
        else:
            res, info = await tgapi.set_markup(session["target_chat"], session["target_msg_id"], grid)
            if res.get("ok") or "not modified" in tgapi.desc(res).lower():
                note = f"\n⚠️ Premium icon nahi laga, normal emoji use hua.\n<code>{esc(info['reason'][:120])}</code>\nℹ️ Pakka test: /emojicheck" if info["icons"] == "fallback" else ""
                await client.send_message(uid, "🎉 <b>Post / Topic Live Updated!</b>" + note, reply_markup=main_menu_keyboard())
            else:
                await client.send_message(uid, f"❌ Error: <code>{esc(tgapi.desc(res))}</code>", reply_markup=main_menu_keyboard())
            user_sessions.pop(uid, None)

    elif data.startswith("tg:"):
        action = data[3:]
        if action == "go":
            await query.answer()
            await publish_classic(client, uid, session)
        elif action == "back":
            await query.answer()
            await query.message.delete()
        elif action == "custom":
            session["state"] = "WAITING_CUSTOM_TARGET"
            await query.answer()
            await client.send_message(uid, "✍️ Channel/topic bhejein: <code>@channel</code>, <code>-100123</code>, ya topic ke liye <code>-100123, 45</code>:")
        elif action in ("silent", "pin"):
            session[action] = not session.get(action, False)
            await query.answer()
            await query.message.edit_reply_markup(chooser_markup(session))
        elif action.startswith("toggle:"):
            session["sel"] ^= {action[7:]}
            await query.answer()
            await query.message.edit_reply_markup(chooser_markup(session))


async def main():
    await start_web_server()  # port first, so Render sees it open quickly
    asyncio.create_task(self_ping_loop())
    print("Main Bot Starting...")
    await app.start()
    me = await app.get_me()
    print(f"✅ Bot started as @{me.username}")
    await idle()
    await app.stop()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
