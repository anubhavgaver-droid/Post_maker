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
from motor.motor_asyncio import AsyncIOMotorClient

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, MONGO_URI, LOG_CHANNEL_ID
from server import start_web_server, self_ping_loop

app = Client("interactive_post_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Global session dictionary
user_sessions = {}

# MongoDB Setup
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["telegram_clone_bot"]
channels_collection = db["saved_channels"]
topics_collection = db["saved_topics"]


# ----------------- CUSTOM REPLY KEYBOARDS -----------------

def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📝 New Post", "🔗 Edit Post"],
            ["💬 Topic Post", "✏️ Edit Topic"],
            ["📢 Channels", "💬 Topics"],
            ["🤖 Create Clone Bot"]
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


async def get_saved_channels_keyboard(user_id: int, for_management: bool = False):
    cursor = channels_collection.find({"user_id": user_id})
    channels = await cursor.to_list(length=None)
    
    keyboard = []
    for ch in channels:
        ch_name = ch.get("name")
        ch_id = ch.get("chat_id")
        db_id = str(ch.get("_id"))
        if for_management:
            keyboard.append([
                InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"ignore_ch"),
                InlineKeyboardButton("❌ Delete", callback_data=f"del_ch_{db_id}")
            ])
        else:
            keyboard.append([InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"sel_ch_{ch_id}")])
    
    if not for_management:
        keyboard.append([InlineKeyboardButton("➕ Add New / Custom Channel", callback_data="sel_ch_custom")])
    else:
        keyboard.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_new_ch_prompt")])
        
    return InlineKeyboardMarkup(keyboard)


async def get_saved_topics_keyboard(user_id: int, for_management: bool = False):
    cursor = topics_collection.find({"user_id": user_id})
    topics = await cursor.to_list(length=None)
    
    keyboard = []
    for tp in topics:
        tp_name = tp.get("name")
        chat_id = tp.get("chat_id")
        thread_id = tp.get("thread_id")
        db_id = str(tp.get("_id"))
        if for_management:
            keyboard.append([
                InlineKeyboardButton(f"💬 {tp_name}", callback_data=f"ignore_tp"),
                InlineKeyboardButton("❌ Delete", callback_data=f"del_tp_{db_id}")
            ])
        else:
            keyboard.append([InlineKeyboardButton(f"💬 {tp_name}", callback_data=f"sel_tp_{chat_id}_{thread_id}")])
            
    if not for_management:
        keyboard.append([InlineKeyboardButton("➕ Add New / Custom Topic", callback_data="sel_tp_custom")])
    else:
        keyboard.append([InlineKeyboardButton("➕ Add New Topic", callback_data="add_new_tp_prompt")])
        
    return InlineKeyboardMarkup(keyboard)


# ----------------- COMMAND & MENU HANDLERS -----------------

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
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


# --- MANAGE CHANNELS SEPARATE ---
@app.on_message(filters.regex("📢 Channels") & filters.private)
async def manage_channels_menu(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    keyboard = await get_saved_channels_keyboard(user_id, for_management=True)
    await message.reply_text(
        "📢 **Manage Saved Channels:**\n\nNeeche aapke saved channels ki list hai. Delete button se hata sakte hain:",
        reply_markup=keyboard
    )


# --- MANAGE TOPICS SEPARATE ---
@app.on_message(filters.regex("💬 Topics") & filters.private)
async def manage_topics_menu(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    keyboard = await get_saved_topics_keyboard(user_id, for_management=True)
    await message.reply_text(
        "💬 **Manage Saved Group Topics:**\n\nNeeche aapke saved topics ki list hai. Delete button se hata sakte hain:",
        reply_markup=keyboard
    )


# --- CLONE BOT INITIATION ---
@app.on_message((filters.regex("🤖 Create Clone Bot") | filters.command("clone")) & filters.private)
async def clone_init_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    
    existing = await channels_collection.database["clones"].find_one({"user_id": user_id, "status": "approved"})
    if existing:
        await message.reply_text(
            f"⚠️ **Aapka Clone Bot Already Active Hai!**\n\n🤖 Username: @{existing.get('bot_username')}",
            reply_markup=main_menu_keyboard()
        )
        return

    user_sessions[user_id] = {"state": "WAITING_CLONE_TOKEN"}
    await message.reply_text(
        "🤖 **Create Your Own Clone Bot:**\n\n"
        "1. @BotFather par jaayein aur naya bot banayein.\n"
        "2. Wahan se mila hua **Bot Token** copy karein.\n"
        "3. Us Bot Token ko yahan bhejein:",
        reply_markup=cancel_only_keyboard()
    )


# ----------------- MAIN MESSAGE ROUTER -----------------

@app.on_message(filters.private & ~filters.command(["start", "cancel", "newpost", "editpost", "topicpost", "edittopic", "clone"]) & ~filters.regex("^(📝 New Post|🔗 Edit Post|💬 Topic Post|✏️ Edit Topic|📢 Channels|💬 Topics|🤖 Create Clone Bot|❌ Cancel Process)$"))
async def message_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_sessions:
        return

    session = user_sessions[user_id]
    state = session.get("state")

    # Add New Channel Details Handler
    if state == "WAITING_NEW_CHANNEL":
        try:
            parts = message.text.split(",")
            ch_name = parts[0].strip()
            ch_input = parse_channel_input(parts[1].strip())

            await channels_collection.update_one(
                {"user_id": user_id, "chat_id": str(ch_input)},
                {"$set": {"name": ch_name, "chat_id": str(ch_input)}},
                upsert=True
            )
            await message.reply_text(
                f"✅ **Channel Saved Successfully!**\n📢 Name: {ch_name}",
                reply_markup=main_menu_keyboard()
            )
        except Exception:
            await message.reply_text("⚠️ Sahi format mein bhejein: `Channel Name, @username`")
        del user_sessions[user_id]
        return

    # Add New Topic Details Handler
    if state == "WAITING_NEW_TOPIC":
        try:
            parts = message.text.split(",")
            tp_name = parts[0].strip()
            input_link_or_ids = parts[1].strip()
            
            chat_id, thread_id, _ = parse_post_link(input_link_or_ids)
            if not chat_id or not thread_id:
                subparts = input_link_or_ids.split("-") # or comma
                chat_id = parse_channel_input(parts[1].strip())
                thread_id = int(parts[2].strip())

            await topics_collection.update_one(
                {"user_id": user_id, "chat_id": str(chat_id), "thread_id": thread_id},
                {"$set": {"name": tp_name, "chat_id": str(chat_id), "thread_id": thread_id}},
                upsert=True
            )
            await message.reply_text(
                f"✅ **Topic Saved Successfully!**\n💬 Name: {tp_name}",
                reply_markup=main_menu_keyboard()
            )
        except Exception:
            await message.reply_text("⚠️ Sahi format mein bhejein: `Topic Name, Link` ya `Topic Name, GroupID, ThreadID`")
        del user_sessions[user_id]
        return

    # Cloned Bot Token Submission
    if state == "WAITING_CLONE_TOKEN":
        token = message.text.strip()
        try:
            test_client = Client(f"test_{user_id}", api_id=API_ID, api_hash=API_HASH, bot_token=token)
            await test_client.start()
            me = await test_client.get_me()
            await test_client.stop()

            await channels_collection.database["pending_clones"].update_one(
                {"user_id": user_id},
                {"$set": {"bot_token": token, "bot_username": me.username, "bot_name": me.first_name, "status": "pending"}},
                upsert=True
            )

            log_text = (
                f"🔔 **New Clone Bot Request Pending!**\n\n"
                f"👤 **User:** {message.from_user.mention} (<code>{user_id}</code>)\n"
                f"🤖 **Bot Name:** {me.first_name}\n"
                f"🔗 **Username:** @{me.username}"
            )
            approval_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_clone_{user_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_clone_{user_id}")
                ]
            ])
            await client.send_message(LOG_CHANNEL_ID, log_text, reply_markup=approval_markup)
            await message.reply_text("⏳ **Token submitted!** Admin approval ke baad activate ho jayega.", reply_markup=main_menu_keyboard())
        except Exception as e:
            await message.reply_text(f"❌ **Invalid Token!** Error: {str(e)}")
        del user_sessions[user_id]
        return

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
            await message.reply_text("⚠️ Invalid Telegram Post Link!")
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
            f"✅ Button Name: <b>{session['temp_name']}</b>\n\n🎨 **Style Select Karein:**",
            reply_markup=style_selection_keyboard()
        )

    # 4. Button URL
    elif state == "WAITING_BTN_URL":
        url = message.text.strip()
        r, c = session["target_pos"]
        btn_name = session["temp_name"]
        btn_style = session.get("selected_style", None)

        session["grid"][r][c] = (btn_name, url, btn_style)
        if len(session["grid"][r]) < 3 and session["grid"][r][-1] is not None:
            session["grid"][r].append(None)

        session["state"] = "BUILDING"
        markup = build_preview_keyboard(session["grid"])
        sent = await message.reply_text(
            f"✨ **Button Added!**\n\n<b>🔍 Current Preview:</b>\n\n{session['text']}",
            reply_markup=markup
        )
        session["preview_msg_id"] = sent.id

    # 5. Final Custom Channel Input
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
            await message.reply_text(f"🎉 <b>Published Successfully! ID:</b> <code>{sent.id}</code>", reply_markup=main_menu_keyboard())
        except Exception as e:
            await message.reply_text(f"❌ <b>Failed:</b> {str(e)}", reply_markup=main_menu_keyboard())
        del user_sessions[user_id]

    # 6. Final Custom Topic Input
    elif state == "WAITING_TOPIC_INPUT":
        input_text = message.text.strip()
        chat_id, thread_id, _ = parse_post_link(input_text)
        try:
            content_msg: Message = session["content_msg"]
            sent = await client.copy_message(
                chat_id=chat_id,
                from_chat_id=content_msg.chat.id,
                message_id=content_msg.id,
                reply_to_message_id=thread_id,
                reply_markup=session["final_markup"]
            )
            await message.reply_text(f"🎉 <b>Topic Published Successfully! ID:</b> <code>{sent.id}</code>", reply_markup=main_menu_keyboard())
        except Exception as e:
            await message.reply_text(f"❌ <b>Failed:</b> {str(e)}", reply_markup=main_menu_keyboard())
        del user_sessions[user_id]


# ----------------- CALLBACK QUERY HANDLER -----------------

@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    data = query.data

    # Channel Delete Handler
    if data.startswith("del_ch_"):
        from bson import ObjectId
        ch_db_id = data.replace("del_ch_", "")
        await channels_collection.delete_one({"_id": ObjectId(ch_db_id)})
        await query.answer("Channel Deleted!", show_alert=True)
        keyboard = await get_saved_channels_keyboard(query.from_user.id, for_management=True)
        await query.message.edit_reply_markup(reply_markup=keyboard)
        return

    # Topic Delete Handler
    if data.startswith("del_tp_"):
        from bson import ObjectId
        tp_db_id = data.replace("del_tp_", "")
        await topics_collection.delete_one({"_id": ObjectId(tp_db_id)})
        await query.answer("Topic Deleted!", show_alert=True)
        keyboard = await get_saved_topics_keyboard(query.from_user.id, for_management=True)
        await query.message.edit_reply_markup(reply_markup=keyboard)
        return

    if data == "add_new_ch_prompt":
        user_id = query.from_user.id
        user_sessions[user_id] = {"state": "WAITING_NEW_CHANNEL"}
        await query.message.reply_text("📢 Naya Channel bhejein (`Name, @username` format mein):", reply_markup=cancel_only_keyboard())
        await query.answer()
        return

    if data == "add_new_tp_prompt":
        user_id = query.from_user.id
        user_sessions[user_id] = {"state": "WAITING_NEW_TOPIC"}
        await query.message.reply_text("💬 Naya Topic bhejein (`Name, Link` format mein):", reply_markup=cancel_only_keyboard())
        await query.answer()
        return

    if data == "ignore_ch" or data == "ignore_tp":
        await query.answer("Yeh sirf naam hai, delete karne ke liye side wale ❌ Delete button par click karein.")
        return

    # Session check
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.answer("Session Expired!", show_alert=True)
        return

    session = user_sessions[user_id]

    if data.startswith("sel_ch_"):
        await query.answer()
        target_ch = data.replace("sel_ch_", "")
        content_msg = session["content_msg"]
        final_markup = session["final_markup"]

        if target_ch == "custom":
            session["state"] = "WAITING_FINAL_CHANNEL"
            await query.message.reply_text("📢 Custom Channel ID ya Username bhejein:")
        else:
            try:
                sent = await client.copy_message(
                    chat_id=int(target_ch) if target_ch.startswith("-") or target_ch.isdigit() else target_ch,
                    from_chat_id=content_msg.chat.id,
                    message_id=content_msg.id,
                    reply_markup=final_markup
                )
                await query.message.reply_text(f"🎉 <b>Published! ID:</b> <code>{sent.id}</code>", reply_markup=main_menu_keyboard())
            except Exception as e:
                await query.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu_keyboard())
            del user_sessions[user_id]

    elif data.startswith("sel_tp_"):
        await query.answer()
        parts = data.split("_")
        chat_id = parts[2]
        thread_id = int(parts[3])
        content_msg = session["content_msg"]
        final_markup = session["final_markup"]

        try:
            sent = await client.copy_message(
                chat_id=int(chat_id) if chat_id.startswith("-") or chat_id.isdigit() else chat_id,
                from_chat_id=content_msg.chat.id,
                message_id=content_msg.id,
                reply_to_message_id=thread_id,
                reply_markup=final_markup
            )
            await query.message.reply_text(f"🎉 <b>Topic Published! ID:</b> <code>{sent.id}</code>", reply_markup=main_menu_keyboard())
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu_keyboard())
        del user_sessions[user_id]

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

        session["final_markup"] = InlineKeyboardMarkup(final_grid) if final_grid else None
        mode = session["mode"]

        if mode == "NEW":
            ch_keyboard = await get_saved_channels_keyboard(user_id, for_management=False)
            await query.message.reply_text("📢 **Channel Select Karein:**", reply_markup=ch_keyboard)
        elif mode == "TOPIC_NEW":
            tp_keyboard = await get_saved_topics_keyboard(user_id, for_management=False)
            await query.message.reply_text("💬 **Topic Select Karein:**", reply_markup=tp_keyboard)


async def main():
    await start_web_server()
    asyncio.create_task(self_ping_loop())
    print("Main Bot Starting...")
    await app.start()
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
