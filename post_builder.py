import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
from server import start_web_server, self_ping_loop

app = Client("interactive_post_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_sessions = {}


def parse_post_link(link: str):
    pattern_public = r"https?://t\.me/([^/]+)/(\d+)"
    pattern_private = r"https?://t\.me/c/(\d+)/(\d+)"

    match_priv = re.match(pattern_private, link)
    if match_priv:
        return int(f"-100{match_priv.group(1)}"), int(match_priv.group(2))

    match_pub = re.match(pattern_public, link)
    if match_pub:
        return f"@{match_pub.group(1)}", int(match_pub.group(2))

    return None, None


def parse_channel_input(channel_text: str):
    """
    Cleans and formats channel username or ID:
    - @username -> '@username'
    - -100123456789 -> -100123456789 (int)
    - 123456789 -> -100123456789 (int)
    - https://t.me/username -> '@username'
    """
    text = channel_text.strip()
    if text.startswith("https://t.me/"):
        text = text.replace("https://t.me/", "").split("/")[0]
        if not text.startswith("@"):
            text = f"@{text}"
        return text

    if text.startswith("@"):
        return text

    try:
        clean_id = int(text)
        if not str(clean_id).startswith("-100") and clean_id > 0:
            clean_id = int(f"-100{clean_id}")
        return clean_id
    except ValueError:
        return text


def build_preview_keyboard(grid_data):
    keyboard = []
    for r_idx, row in enumerate(grid_data):
        row_buttons = []
        for c_idx, item in enumerate(row):
            if item is None:
                row_buttons.append(InlineKeyboardButton("➕", callback_data=f"add_{r_idx}_{c_idx}"))
            else:
                row_buttons.append(InlineKeyboardButton(item[0], url=item[1]))
        keyboard.append(row_buttons)

    keyboard.append([
        InlineKeyboardButton("➕ New Row", callback_data="add_row"),
        InlineKeyboardButton("✅ Publish / Update", callback_data="finish_post")
    ])
    return InlineKeyboardMarkup(keyboard)


@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.reply_text(
        "<b>👋 Interactive Post Builder & Editor Bot!</b>\n\n"
        "➡️ /newpost - Nayi post UI builder se banayein\n"
        "➡️ /editpost - Link se post edit karein (auto-refresh)\n"
        "➡️ /cancel - Cancel process"
    )


@app.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
        await message.reply_text("❌ Operation cancelled.")
    else:
        await message.reply_text("Koi active session nahi hai.")


@app.on_message(filters.command("newpost") & filters.private)
async def newpost_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return

    user_sessions[user_id] = {
        "mode": "NEW",
        "text": "",
        "grid": [[None]],
        "state": "WAITING_TITLE",
        "preview_msg_id": None
    }
    await message.reply_text("<b>📝 Post Content / Message bhejein:</b>")


@app.on_message(filters.command("editpost") & filters.private)
async def editpost_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return

    user_sessions[user_id] = {
        "mode": "EDIT",
        "grid": [],
        "state": "WAITING_POST_LINK",
        "preview_msg_id": None
    }
    await message.reply_text("<b>🔗 Channel Post Ka Link Bhejein:</b>\n(e.g. <code>https://t.me/mychannel/123</code>)")


# ---------------- MAIN MESSAGE ROUTER ----------------

@app.on_message(filters.private & ~filters.command(["start", "cancel", "newpost", "editpost"]))
async def message_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_sessions:
        return

    session = user_sessions[user_id]
    state = session.get("state")

    # 1. Post Content
    if state == "WAITING_TITLE":
        session["text"] = message.text or message.caption or "Untitled Post"
        session["content_msg"] = message
        session["state"] = "BUILDING"
        markup = build_preview_keyboard(session["grid"])
        sent = await message.reply_text(f"<b>🔍 Live Preview:</b>\n\n{session['text']}", reply_markup=markup)
        session["preview_msg_id"] = sent.id

    # 2. Edit Post Link
    elif state == "WAITING_POST_LINK":
        chat_id, msg_id = parse_post_link(message.text.strip())
        if not chat_id or not msg_id:
            await message.reply_text("⚠️ Invalid Telegram Post Link!")
            return

        try:
            target_msg = await client.get_messages(chat_id, msg_id)
            if not target_msg or target_msg.empty:
                await message.reply_text("❌ Post fetch nahi ho sakti. Check karein bot admin hai ya nahi.")
                return

            session["target_chat"] = chat_id
            session["target_msg_id"] = msg_id
            session["text"] = target_msg.text or target_msg.caption or "Post Content"

            existing_grid = []
            if target_msg.reply_markup and target_msg.reply_markup.inline_keyboard:
                for row in target_msg.reply_markup.inline_keyboard:
                    row_items = [(b.text, b.url) for b in row if b.url]
                    if row_items:
                        if len(row_items) < 3:
                            row_items.append(None)
                        existing_grid.append(row_items)

            if not existing_grid:
                existing_grid = [[None]]
            else:
                existing_grid.append([None])

            session["grid"] = existing_grid
            session["state"] = "BUILDING"
            markup = build_preview_keyboard(session["grid"])
            sent = await message.reply_text(f"<b>✏️ Live Edit Preview:</b>\n\n{session['text']}", reply_markup=markup)
            session["preview_msg_id"] = sent.id
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")

    # 3. Button Name
    elif state == "WAITING_BTN_NAME":
        session["temp_name"] = message.text.strip()
        session["state"] = "WAITING_BTN_URL"
        await message.reply_text(f"✅ Name: <b>{session['temp_name']}</b>\n🔗 Ab URL Link bhejein:")

    # 4. Button URL
    elif state == "WAITING_BTN_URL":
        url = message.text.strip()
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("t.me/")):
            await message.reply_text("⚠️ Sahi URL link bhejein!")
            return

        r, c = session["target_pos"]
        session["grid"][r][c] = (session["temp_name"], url)
        if len(session["grid"][r]) < 3 and session["grid"][r][-1] is not None:
            session["grid"][r].append(None)

        session["state"] = "BUILDING"
        try:
            await client.edit_message_reply_markup(
                chat_id=message.chat.id,
                message_id=session["preview_msg_id"],
                reply_markup=build_preview_keyboard(session["grid"])
            )
        except Exception:
            pass
        await message.reply_text("✨ Button added!")

    # 5. Final Publishing Step (FIXED!)
    elif state == "WAITING_FINAL_CHANNEL":
        channel_input = parse_channel_input(message.text.strip())

        try:
            content_msg: Message = session["content_msg"]
            sent = await content_msg.copy(
                chat_id=channel_input,
                reply_markup=session["final_markup"]
            )
            await message.reply_text(
                f"🎉 <b>Post Successfully Published!</b>\n\n"
                f"📍 <b>Target:</b> <code>{channel_input}</code>\n"
                f"🆔 <b>Message ID:</b> <code>{(sent.id if sent else 'Sent')}</code>"
            )
        except Exception as e:
            await message.reply_text(
                f"❌ <b>Publishing Failed!</b>\n\n"
                f"<b>Reason:</b> <code>{str(e)}</code>\n\n"
                "<i>Kripya check karein:\n"
                "1. Bot us channel mein Admin hai ya nahi.\n"
                "2. Channel ID / Username sahi hai ya nahi.</i>"
            )

        del user_sessions[user_id]


# ---------------- CALLBACK HANDLER ----------------

@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.answer("Session Expired!", show_alert=True)
        return

    session = user_sessions[user_id]
    data = query.data

    if data.startswith("add_") and data != "add_row":
        _, r, c = data.split("_")
        session["target_pos"] = (int(r), int(c))
        session["state"] = "WAITING_BTN_NAME"
        await query.answer()
        await query.message.reply_text(f"➕ Button Name (Row {int(r)+1}, Col {int(c)+1}) bhejein:")

    elif data == "add_row":
        session["grid"].append([None])
        await query.message.edit_reply_markup(reply_markup=build_preview_keyboard(session["grid"]))
        await query.answer("New Row added!")

    elif data == "finish_post":
        await query.answer()
        final_grid = []
        for row in session["grid"]:
            valid_row = [btn for btn in row if btn is not None]
            if valid_row:
                final_grid.append([InlineKeyboardButton(b[0], url=b[1]) for b in valid_row])
        final_markup = InlineKeyboardMarkup(final_grid) if final_grid else None

        if session["mode"] == "NEW":
            session["state"] = "WAITING_FINAL_CHANNEL"
            session["final_markup"] = final_markup
            await query.message.reply_text(
                "📢 <b>Channel Username ya ID Bhejein:</b>\n\n"
                "Examples:\n"
                "• <code>@mychannel</code>\n"
                "• <code>-100123456789</code>\n"
                "• <code>https://t.me/mychannel</code>"
            )

        elif session["mode"] == "EDIT":
            try:
                await client.edit_message_reply_markup(
                    chat_id=session["target_chat"],
                    message_id=session["target_msg_id"],
                    reply_markup=final_markup
                )
                await query.message.reply_text("🎉 **Channel Post Successfully Refreshed & Updated!**")
            except Exception as e:
                await query.message.reply_text(f"❌ Failed to edit: {str(e)}")
            del user_sessions[user_id]


async def main():
    await start_web_server()
    asyncio.create_task(self_ping_loop())
    print("Bot Starting...")
    await app.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
