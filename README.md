# Advanced Post Builder Bot

Classic post builder (buttons under any message) + Rich Post builder (big headings, boxes, in-bubble buttons),
with premium emoji, multi-channel publishing, templates and post history.

## Files (all in the project root, plus the Procfile)
post_builder.py (start this), rich_flow.py, blocks.py, entities.py, tgapi.py, targets.py, db.py,
config.py, server.py, requirements.txt, .python-version, Procfile

## Render
- Build: `pip install -r requirements.txt`   Start: `python post_builder.py`
- Env: `API_ID`, `API_HASH`, `BOT_TOKEN`, `MONGO_URI`, `ADMIN_IDS` (comma separated), `PYTHON_VERSION=3.11.9`
- Render sets `PORT` itself. Self-ping uses `RENDER_EXTERNAL_URL` (set by Render automatically).

## Menu
- 📝 New Post / 🔗 Edit Post / 💬 Topic Post / ✏️ Edit Topic - classic builder (preview = the real post)
- 🎨 Rich Post - heading, text, quote, table (text + button per row), button rows, divider
- 📚 My Rich Posts - edit, copy or delete rich posts you published
- 📢 Channels / 💬 Topics - saved targets (publish to several at once)

## Premium emoji (important)
- Button name: send a premium emoji with the name = it becomes the button icon.
- Rich Post: premium emoji and Telegram formatting (bold, italic, spoiler, links) work inside any text.
- Send a premium emoji alone (nothing running) = the bot replies with its ID.
- **Telegram's rule:** a bot may use premium emoji (text and button icons) only
  - in private chats, groups and supergroups if the **bot's owner** (the account that made it in BotFather) has Premium, or
  - anywhere, **channels included**, if the bot owns an extra username bought on Fragment.
  So in a normal channel the premium emoji cannot go out - that is Telegram, not a bug.
- How the bot behaves: the post always goes out first with the normal emoji. Then it tries to upgrade the buttons to the
  premium icons and checks what Telegram kept. Kept = icons stay. Refused or silently dropped = the normal emoji stay and the
  bot tells you why. You never end up with a button without any emoji.
- **/emojicheck**: sends 3 silent test messages (deleted after 20 s) to the chat you name and reports for text, button icon and
  rich message what Telegram really does. Run it on your channel, your group and your PM. The result is remembered.
- `TRUST_ICONS=1` (env): only if /emojicheck shows icons work but posts still fall back, because Telegram does not echo the buttons back.

## Also
- In the publish list: 🔕 Silent (no notification) and 📌 Pin.
- Any crash inside the bot is shown to you as a message instead of the bot going silent.
