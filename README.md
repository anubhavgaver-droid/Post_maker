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

## Post as your Premium account (premium emoji in channel posts)
Add the session string from the bot: `/setsession` (super admins only). The bot deletes your message at once, checks the session,
and saves it **encrypted** in MongoDB (key derived from BOT_TOKEN, which is never stored). `/delsession` removes it. You can still use the env var
`USER_SESSION_STRING` instead. Make the string with `python gen_session.py` on your own computer/Termux, never on Render.
- In the publish list a row appears: `👤 Premium account se post`. Your Premium account copies the post into the channel (the premium emoji
  in the text stay), then the bot adds the buttons by editing the post. Send the content to the bot **from that same account**.
- Needs: the account is an admin of the channel with the right to post; the bot is an admin with **Edit messages of others**.
  `/userbot @channel` checks both.
- **Premium icons on buttons in a channel are impossible** for any bot unless the bot owns a Fragment username (Telegram's rule). The
  option `🔗 Premium emoji wale buttons text-links bane` is the working alternative: those buttons become clickable text links
  (premium emoji + name) at the end of the post text/caption, the other buttons stay normal buttons.
- Rich Posts are sent by the bot only.
- **Safety:** the session string controls your whole Telegram account. Super admins only; never in code/GitHub/chat. If it leaks:
  Telegram > Settings > Devices > end that session. Use your own channels and human speed.

## Schedule, auto-delete, templates
- Publish list: `📅 Schedule` (30m, 2h, 18:30, kal 09:00, 25/12 09:00 - timezone from env `TZ_OFFSET_MIN`, default 330 = India)
  and `🗑 Auto-delete` (off / 1h / 24h / 7d after posting). Both work for classic and rich posts and survive restarts (MongoDB).
  Menu `📅 Scheduled` lists and cancels them. Keep the content message in the bot chat until the scheduled post has gone out.
- 🎨 Rich Post > Templates > `🎁 Ready-made templates`: Announcement, New Release, Chats Board, Giveaway, Links Hub.

## Also
- In the publish list: 🔕 Silent (no notification) and 📌 Pin.
- Any crash inside the bot is shown to you as a message instead of the bot going silent.
