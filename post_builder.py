import os
import re
import asyncio
from pyrogram import Client, filters, enums, idle
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    CallbackQuery
)

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
from server import start_web_server, self_ping_loop

app = Client("interactive_post_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Global session dictionary
user_sessions = {}


# ----------------- CUSTOM REPLY KEYBOARDS -----------------

def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📝 New Post", "🔗 Edit Post"],
            ["💬 Topic Post", "✏️ Edit Topic"]
        ],
        resize_keyboard=True
    )

def cancel_only_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["❌ Cancel Process"]
        ],
        resize_keyboard=True
    )


# ----------------- HELPER FUNCTIONS -----------------

def parse_post_link(link: str):
    link = link.strip()
    pattern_private_topic = r"https?://t\.me/c/(\d+)/(\d+)/(\d+)"
    pattern_public_topic = r"https?://t\.me/([^/]+)/(\d+)/(\d+)"
    pattern_private_channel = r"https?://t\.me/c/(\d+)/(\d+)"
    pattern_public_channel = r"https?://t\.me/([^/]+)/(\d+)"

    m = re.match(pattern_private_topic, link)
    if m:
        chat_id = int(f"-100{m.group(1)}") if not m.group(1).startswith("-100") else int(m.group(1))
        return chat_id, int(m.group(2)), int(m.group(3))

    m = re.match(pattern_public_topic, link)
    if m:
        return f"@{m.group(1)}", int(m.group(2)), int(m.group(3))

    m = re.match(pattern_private_channel, link)
    if m:
        chat_id = int(f"-100{m.group(1)}") if not m.group(1).startswith("-100") else int(m.group(1))
        return chat_id, None, int(m.group(2))

    m = re.match(pattern_public_channel, link)
    if m:
        return f"@{m.group(1)}", None, int(m.group(2))

    return None, None, None


def parse_channel_input(channel_text: str):
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
        if clean_id > 0 and not str(clean_id).startswith("-100"):
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
                btn_name, btn_url = item[0], item[1]
                btn_style = item[2] if len(item) > 2 else None
                if btn_style:
                    row_buttons.append(InlineKeyboardButton(btn_name, url=btn_url, style=btn_style))
                else:
                    row_buttons.append(InlineKeyboardButton(btn_name, url=btn_url))
        keyboard.append(row_buttons)

    keyboard.append([
        InlineKeyboardButton("➕ New Row", callback_data="add_row"),
        InlineKeyboardButton("✅ Publish / Update", callback_data="finish_post")
    ])
    return InlineKeyboardMarkup(keyboard)


def style_selection_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟦 Primary", callback_data="style_primary"),
            InlineKeyboardButton("🟩 Success", callback_data="style_success"),
        ],
        [
            InlineKeyboardButton("🟥 Danger", callback_data="style_danger"),
            InlineKeyboardButton("⚪ Normal", callback_data="style_normal"),
        ]
    ])


# ----------------- COMMAND & MENU HANDLERS -----------------

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.reply_text(
        "<b>👋 Welcome to Interactive Post Builder Bot!</b>\n\n"
        "Neeche diye gaye buttons se apna action select karein:",
        reply_markup=main_menu_keyboard()
    )


@app.on_message((filters.regex("❌ Cancel Process") | filters.command("cancel")) & filters.private)
async def cancel_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await message.reply_text(
        "❌ Operation cancelled.",
        reply_markup=main_menu_keyboard()
    )


@app.on_message(filters.regex("📝 New Post") & filters.private)
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
        "preview_msg_id": None,
        "is_premium": message.from_user.is_premium
    }
    await message.reply_text(
        "<b>📝 Channel Post Content / Message bhejein:</b>",
        reply_markup=cancel_only_keyboard()
    )


@app.on_message(filters.regex("🔗 Edit Post") & filters.private)
@app.on_message(filters.command("editpost") & filters.private)
async def editpost_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return

    user_sessions[user_id] = {
        "mode": "EDIT",
        "grid": [],
        "state": "WAITING_POST_LINK",
        "preview_msg_id": None,
        "is_premium": message.from_user.is_premium
    }
    await message.reply_text(
        "<b>🔗 Channel Post Ka Link Bhejein:</b>\n(e.g. <code>https://t.me/mychannel/123</code>)",
        reply_markup=cancel_only_keyboard()
    )


@app.on_message(filters.regex("💬 Topic Post") & filters.private)
@app.on_message(filters.command("topicpost") & filters.private)
async def topicpost_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return

    user_sessions[user_id] = {
        "mode": "TOPIC_NEW",
        "text": "",
        "grid": [[None]],
        "state": "WAITING_TITLE",
        "preview_msg_id": None,
        "is_premium": message.from_user.is_premium
    }
    await message.reply_text(
        "<b>💬 Topic Group Post Content / Message bhejein:</b>",
        reply_markup=cancel_only_keyboard()
    )


@app.on_message(filters.regex("✏️ Edit Topic") & filters.private)
@app.on_message(filters.command("edittopic") & filters.private)
async def edittopic_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return

    user_sessions[user_id] = {
        "mode": "TOPIC_EDIT",
        "grid": [],
        "state": "WAITING_POST_LINK",
        "preview_msg_id": None,
        "is_premium": message.from_user.is_premium
    }
    await message.reply_text(
        "<b>🔗 Topic Post Ka Link Bhejein:</b>\n(e.g. <code>https://t.me/c/123456/45/678</code>)",
        reply_markup=cancel_only_keyboard()
    )


# ----------------- MAIN MESSAGE ROUTER -----------------

@app.on_message(filters.private & ~filters.command(["start", "cancel", "newpost", "editpost", "topicpost", "edittopic"]) & ~filters.regex("^(📝 New Post|🔗 Edit Post|💬 Topic Post|✏️ Edit Topic|❌ Cancel Process)$"))
async def message_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_sessions:
        return

    session = user_sessions[user_id]
    state = session.get("state")

    # 1. Post Content Title
    if state == "WAITING_TITLE":
        session["text"] = message.text or message.caption or "Untitled Post"
        session["content_msg"] = message
        session["state"] = "BUILDING"
        markup = build_preview_keyboard(session["grid"])
        sent = await message.reply_text(
            f"<b>🔍 Live Preview:</b>\n\n{session['text']}", 
            reply_markup=markup
        )
        session["preview_msg_id"] = sent.id

    # 2. Fetch Post Link
    elif state == "WAITING_POST_LINK":
        chat_id, thread_id, msg_id = parse_post_link(message.text.strip())
        if not chat_id or not msg_id:
            await message.reply_text("⚠️ Invalid Telegram Post Link! Sahi link bhejein.")
            return

        try:
            target_msg = await client.get_messages(chat_id, msg_id)
            if not target_msg or target_msg.empty:
                await message.reply_text("❌ Post fetch nahi ho sakti.")
                return

            session["target_chat"] = chat_id
            session["message_thread_id"] = thread_id
            session["target_msg_id"] = msg_id
            session["text"] = target_msg.text or target_msg.caption or "Post Content"

            existing_grid = []
            if target_msg.reply_markup and target_msg.reply_markup.inline_keyboard:
                for row in target_msg.reply_markup.inline_keyboard:
                    row_items = []
                    for b in row:
                        if b.url:
                            b_style = getattr(b, "style", None)
                            row_items.append((b.text, b.url, b_style))
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
            sent = await message.reply_text(
                f"<b>✏️ Live Edit Preview:</b>\n\n{session['text']}", 
                reply_markup=markup
            )
            session["preview_msg_id"] = sent.id
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")

    # 3. Button Name
    elif state == "WAITING_BTN_NAME":
        session["temp_name"] = message.text.strip()
        session["state"] = "WAITING_STYLE_CHOICE"
        
        await message.reply_text(
            f"✅ Button Name: <b>{session['temp_name']}</b>\n\n"
            "🎨 **Button ka Style Select Karein:**",
            reply_markup=style_selection_keyboard()
        )

    # 4. Button URL (Ab yahan naya preview message neeche bhejega)
    elif state == "WAITING_BTN_URL":
        url = message.text.strip()
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("t.me/")):
            await message.reply_text("⚠️ Sahi URL link bhejein!")
            return

        r, c = session["target_pos"]
        btn_name = session["temp_name"]
        btn_style = session.get("selected_style", None)

        session["grid"][r][c] = (btn_name, url, btn_style)
        if len(session["grid"][r]) < 3 and session["grid"][r][-1] is not None:
            session["grid"][r].append(None)

        session["state"] = "BUILDING"
        
        # Naya preview message chat ke bilkul neeche send karein
        markup = build_preview_keyboard(session["grid"])
        sent = await message.reply_text(
            f"✨ **Button Added Successfully!**\n\n<b>🔍 Current Live Preview:</b>\n\n{session['text']}",
            reply_markup=markup
        )
        session["preview_msg_id"] = sent.id

    # 5. Final Publishing (Channel)
    elif state == "WAITING_FINAL_CHANNEL":
        channel_input = parse_channel_input(message.text.strip())
        try:
            content_msg: Message = session["content_msg"]
            sent = await client.copy_message(
                chat_id=channel_input,
                from_chat_id=content_msg.chat.id,
                message_id=content_msg.id,
                reply_markup=session["final_markup"]
            )
            await message.reply_text(
                f"🎉 <b>Post Successfully Published!</b>\n\n"
                f"📍 <b>Target:</b> <code>{channel_input}</code>\n"
                f"🆔 <b>Message ID:</b> <code>{(sent.id if sent else 'Sent')}</code>",
                reply_markup=main_menu_keyboard()
            )
        except Exception as e:
            await message.reply_text(
                f"❌ <b>Publishing Failed:</b> <code>{str(e)}</code>",
                reply_markup=main_menu_keyboard()
            )

        del user_sessions[user_id]

    # 6. Final Publishing (Topic Group)
    elif state == "WAITING_TOPIC_INPUT":
        input_text = message.text.strip()
        chat_id, thread_id, _ = parse_post_link(input_text)

        if not chat_id or not thread_id:
            try:
                parts = input_text.split(",")
                chat_id = parse_channel_input(parts[0].strip())
                thread_id = int(parts[1].strip())
            except Exception:
                await message.reply_text("⚠️ Invalid Topic Input! Topic Link ya `GroupID, TopicID` format mein bhejein.")
                return

        try:
            content_msg: Message = session["content_msg"]
            sent = await client.copy_message(
                chat_id=chat_id,
                from_chat_id=content_msg.chat.id,
                message_id=content_msg.id,
                reply_to_message_id=thread_id,
                reply_markup=session["final_markup"]
            )
            await message.reply_text(
                f"🎉 <b>Topic Post Successfully Published!</b>\n\n"
                f"📍 <b>Group:</b> <code>{chat_id}</code>\n"
                f"💬 <b>Topic ID:</b> <code>{thread_id}</code>\n"
                f"🆔 <b>Message ID:</b> <code>{(sent.id if sent else 'Sent')}</code>",
                reply_markup=main_menu_keyboard()
            )
        except Exception as e:
            await message.reply_text(
                f"❌ <b>Topic Publishing Failed:</b> <code>{str(e)}</code>",
                reply_markup=main_menu_keyboard()
            )

        del user_sessions[user_id]


# ----------------- CALLBACK QUERY HANDLER -----------------

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

    elif data.startswith("style_"):
        await query.answer()

        if data == "style_primary":
            session["selected_style"] = enums.ButtonStyle.PRIMARY
        elif data == "style_success":
            session["selected_style"] = getattr(enums.ButtonStyle, "SUCCESS", getattr(enums.ButtonStyle, "POSITIVE", None))
        elif data == "style_danger":
            session["selected_style"] = enums.ButtonStyle.DANGER
        else:
            session["selected_style"] = None

        session["state"] = "WAITING_BTN_URL"
        await query.message.edit_text("✅ Style selected!\n\n🔗 **Ab URL Link bhejein:**")

    elif data == "add_row":
        session["grid"].append([None])
        await query.answer("New Row added!")
        
        # Nayi row add hone par bhi naya preview message neeche bhej dega
        markup = build_preview_keyboard(session["grid"])
        sent = await query.message.reply_text(
            f"➕ **New Row Added!**\n\n<b>🔍 Current Live Preview:</b>\n\n{session['text']}",
            reply_markup=markup
        )
        session["preview_msg_id"] = sent.id

    elif data == "finish_post":
        await query.answer()
        final_grid = []
        for row in session["grid"]:
            valid_row = [btn for btn in row if btn is not None]
            if valid_row:
                row_btns = []
                for b in valid_row:
                    b_name, b_url = b[0], b[1]
                    b_style = b[2] if len(b) > 2 else None
                    if b_style:
                        row_btns.append(InlineKeyboardButton(b_name, url=b_url, style=b_style))
                    else:
                        row_btns.append(InlineKeyboardButton(b_name, url=b_url))
                final_grid.append(row_btns)

        final_markup = InlineKeyboardMarkup(final_grid) if final_grid else None
        session["final_markup"] = final_markup

        mode = session["mode"]

        if mode == "NEW":
            session["state"] = "WAITING_FINAL_CHANNEL"
            await query.message.reply_text("📢 <b>Channel Username ya ID Bhejein:</b>\n(e.g. <code>@mychannel</code> ya <code>-100123456789</code>)")

        elif mode == "TOPIC_NEW":
            session["state"] = "WAITING_TOPIC_INPUT"
            await query.message.reply_text(
                "💬 <b>Topic Details Bhejein:</b>\n\n"
                "• Topic Message ka Direct Link (e.g. <code>https://t.me/c/123456/45/678</code>)\n"
                "• Ya Group ID, Topic ID (e.g. <code>-100123456789, 45</code>)"
            )

        elif mode in ["EDIT", "TOPIC_EDIT"]:
            try:
                await client.edit_message_reply_markup(
                    chat_id=session["target_chat"],
                    message_id=session["target_msg_id"],
                    reply_markup=final_markup
                )
                await query.message.reply_text(
                    "🎉 **Post / Topic Post Live Refreshed & Updated!**",
                    reply_markup=main_menu_keyboard()
                )
            except Exception as e:
                await query.message.reply_text(
                    f"❌ Failed to edit post: {str(e)}",
                    reply_markup=main_menu_keyboard()
                )
            del user_sessions[user_id]


async def main():
    await start_web_server()
    asyncio.create_task(self_ping_loop())
    print("Bot Starting...")
    await app.start()
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
