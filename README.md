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

## Premium emoji
- Button name: send a premium emoji with the name = it becomes the button icon.
- Rich Post: premium emoji and Telegram formatting (bold, italic, spoiler, links) work inside any text.
- Send a premium emoji alone (nothing running) = the bot replies with its ID.
- Telegram only lets bots use premium emoji in some cases (see notes). If it is refused the bot retries
  with the normal emoji and tells you.
