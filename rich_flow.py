"""Rich Post builder: heading / text / quote / table / button rows / divider, premium emoji everywhere,
publish to several channels or topics, save templates, edit or delete published posts."""
import html
import re
import time

from bson import ObjectId

import blocks as B
import db
import scheduler
import targets as T
import templates_builtin as TB
import tgapi
from entities import entities_to_html, plain

esc = html.escape
MAX_BLOCKS = 40


def new_session(blocks=None, edit_post=None) -> dict:
    return {"mode": "RICH", "state": "RICH", "blocks": blocks or [], "await": None, "panel": None, "preview": None,
            "opts": [], "sel": set(), "edit_post": edit_post, "silent": False, "pin": False}


# ---------- tiny rich-html helpers ----------
def cb(text: str, data: str, style: str = "primary") -> str:
    st = f' style="{style}"' if style else ""
    return f'<tg-button type="callback_data"{st} data="{data}">{esc(text)}</tg-button>'


def row(*buttons: str) -> str:
    return "<tg-button-row>" + "".join(buttons) + "</tg-button-row>"


def P(text: str) -> str:
    return f"<p>{text}</p>"


async def show(client, uid: int, s: dict, body: str, rows: list = None, chat_id: int = None):
    """Draw the panel: edit it in place, or send a new one."""
    h = body + "".join(rows or [])
    if s["panel"] and chat_id is None:
        c, m = s["panel"]
        res = await tgapi.call("editMessageText", {"chat_id": c, "message_id": m, "rich_message": {"html": h}})
        if res.get("ok") or "not modified" in tgapi.desc(res).lower():
            return
        chat_id = c
    res = await tgapi.call("sendRichMessage", {"chat_id": chat_id or uid, "rich_message": {"html": h}})
    if res.get("ok"):
        s["panel"] = (chat_id or uid, res["result"]["message_id"])
    else:
        await client.send_message(chat_id or uid, f"❌ Telegram ne rich message refuse kiya:\n<code>{esc(tgapi.desc(res))}</code>")


# ---------- views ----------
def main_view(s: dict, note: str = ""):
    editing = bool(s["edit_post"])
    body = "<h2>🎨 RICH POST MAKER</h2>" + (P(note) if note else "") + P(f"🧱 <b>Blocks:</b> {len(s['blocks'])}")
    if editing:
        body += P("✏️ <i>Published post edit ho raha hai</i>")
    rows = [
        row(cb("🔠 Heading", "rp:add:h"), cb("📝 Text", "rp:add:p"), cb("💬 Quote", "rp:add:q")),
        row(cb("▦ Table", "rp:add:t"), cb("🔘 Buttons", "rp:add:b"), cb("➖ Divider", "rp:add:hr")),
        row(cb("🧱 Edit blocks", "rp:blocks"), cb("👁 Preview", "rp:prev")),
        row(cb("💾 Save template", "rp:tpl_save"), cb("📋 Templates", "rp:tpl_list")),
        row(cb("🔄 Update published" if editing else "🚀 Publish", "rp:upd" if editing else "rp:pub", "success"), cb("🗑 Clear", "rp:clear", "danger")),
        row(cb("✖ Close", "rp:close", "danger")),
    ]
    return body, rows


def summary(b: dict) -> str:
    t = b["t"]
    if t in ("h", "p", "q"):
        extra = re.sub(r"\s+", " ", plain(b["text"]))[:30]
    elif t == "t":
        extra = f"{len(b['rows'])} row(s)"
    elif t == "b":
        extra = f"{sum(len(x) for x in b['lines'])} button(s)"
    else:
        extra = ""
    return f"{B.ICON[t]} {B.NAME[t]}" + (f": {esc(extra)}" if extra else "")


def blocks_view(s: dict):
    body = "<h2>🧱 BLOCKS</h2>" + ("" if s["blocks"] else P("Abhi koi block nahi hai."))
    rows = []
    for i, b in enumerate(s["blocks"]):
        body += P(f"<b>{i + 1}.</b> {summary(b)}")
        rows.append(row(cb(f"✏️ {i + 1}", f"rp:ed:{i}"), cb("⬆️", f"rp:mv:{i}:-1"), cb("⬇️", f"rp:mv:{i}:1"), cb("🗑", f"rp:rm:{i}", "danger")))
    rows.append(row(cb("⬅️ Back", "rp:back")))
    return body, rows


HELP = {
    "h": "Heading ka text bhejein.\nSize 1 (sabse bada) se 6 tak: number aur colon se shuru karein, jaise <code>2: Mera title</code>. Default 1 hai.\nTelegram ki apni formatting aur <b>premium emoji</b> seedha use kar sakte hain.",
    "p": "Text bhejein. Har nayi line ek naya paragraph banegi.\nTelegram ki apni formatting (bold, italic, spoiler, link...) aur <b>premium emoji</b> seedha chalte hain.",
    "q": "Quote ka text bhejein (formatting aur premium emoji chalte hain).",
    "t": "Har line ek row: left = text, right = button:\n<code>Text | Button name | Link | color</code>\n◉ <code> // </code> (spaces ke saath) = text ke andar nayi line\n◉ color: blue, green, red (optional)\n◉ Sirf text chahiye? bas text likhein\n◉ Button name ke saath <b>premium emoji</b> bhejo = button icon\nExample:\n<code>1. My Channel // ID -100123 | 🔥 OPEN | https://t.me/mychannel | green</code>",
    "b": "Har line ek button: <code>Name | Link | color</code>\n◉ Ek row mein 8 tak\n◉ Khali line = nayi row\n◉ Name ke saath <b>premium emoji</b> bhejo = button icon\nExample:\n<code>🔥 Join | https://t.me/mychannel | green\nHelp | https://t.me/helpbot</code>",
    "custom": "Channel/topic bhejein: <code>@channel</code> ya <code>-1001234567890</code>.\nTopic ke liye: <code>-1001234567890, 45</code> ya topic ka link.",
    "tpl": "Template ka naam bhejein.",
    "sched": "Kab post karni hai? Aise likhein:\n<code>30m</code> / <code>2h</code> / <code>1d 6h</code> = itni der baad\n<code>18:30</code> = aaj (ya agle din) 18:30 par\n<code>kal 09:00</code> = kal subah 9 baje\n<code>25/12 09:00</code> = us tareekh par\nTime zone: UTC{tz}.",
}


def prompt_view(kind: str, current: str = ""):
    title = {"custom": "✍️ Custom target", "tpl": "💾 Save template", "sched": "📅 Schedule"}.get(kind, f"{B.ICON.get(kind, '')} {B.NAME.get(kind, '')}")
    tz = f"{scheduler.TZ_MIN // 60:+d}:{abs(scheduler.TZ_MIN) % 60:02d}"
    body = f"<h2>{title}</h2>" + "".join(P(x) for x in HELP[kind].replace("{tz}", tz).split("\n"))
    if current:
        body += P("<b>Current:</b>") + f"<pre>{esc(plain(current))}</pre>"
    return body + P("👇 <i>Ab bhejein</i>"), [row(cb("❌ Cancel", "rp:cancel", "danger"))]


def chooser_view(s: dict):
    body = "<h2>🚀 PUBLISH</h2>" + P("Jahan post karni hai unhe ✅ karein, phir <b>Publish</b> dabayein.")
    if "<tg-emoji" in B.render(s["blocks"]):
        body += P("✨ <i>Is post mein premium emoji hain. Channel mein Telegram bots ko ye tabhi allow karta hai jab bot ke paas Fragment username ho - warna normal emoji dikhega. Pakka test: /emojicheck</i>")
    if not s["opts"]:
        body += P("<i>Koi saved channel/topic nahi. ➕ Custom use karein ya main menu se 📢 Channels mein add karein.</i>")
    rows = [row(*[cb(label, f"rp:tg:{action}", "success" if action == "go" else ("danger" if action == "back" else "primary")) for label, action in r])
            for r in T.chooser_pairs(s["opts"], s["sel"], {"silent": s["silent"], "pin": s["pin"], "autodel": s.get("autodel", 0)})]
    return body, rows


# ---------- entry points ----------
async def open_panel(client, uid: int, chat_id: int, s: dict, note: str = ""):
    if s["panel"]:
        try:
            await client.delete_messages(*s["panel"])
        except Exception:
            pass
        s["panel"] = None
    body, rows = main_view(s, note)
    await show(client, uid, s, body, rows, chat_id=chat_id)


def posts_view(posts: list):
    body = "<h2>📚 MY RICH POSTS</h2>" + (P("Edit karne ke liye post chunein.") if posts else P("Abhi koi rich post publish nahi hui."))
    rows = [row(cb(f"🕒 {time.strftime('%d %b', time.gmtime(p['ts']))} • {p.get('title', 'Post')[:26]}", f"rp:post:{p['_id']}")) for p in posts]
    rows.append(row(cb("✖ Close", "rp:close", "danger")))
    return body, rows


async def open_posts(client, uid: int, chat_id: int, s: dict):
    posts = await db.rich_posts.find({"user_id": uid}).sort("ts", -1).limit(8).to_list(length=8)
    body, rows = posts_view(posts)
    await show(client, uid, s, body, rows, chat_id=chat_id)


# ---------- text typed by the admin ----------
async def on_text(client, message, s: dict):
    uid = message.from_user.id
    aw = s["await"]
    if not aw or not message.text:
        return
    raw = entities_to_html(message.text, message.entities)
    try:
        await message.delete()
    except Exception:
        pass
    kind = aw["kind"]

    if kind == "tpl":
        name = plain(raw)[:40]
        await db.templates.update_one({"user_id": uid, "kind": "rich", "name": name},
                                      {"$set": {"data": s["blocks"], "ts": time.time()}}, upsert=True)
        s["await"] = None
        return await show(client, uid, s, *main_view(s, f"✅ Template saved: <b>{esc(name)}</b>"))

    if kind == "sched":
        due = scheduler.parse_when(plain(raw))
        if not due:
            body, rows = prompt_view("sched")
            return await show(client, uid, s, P("❌ Time samajh nahi aaya.") + body, rows)
        chosen = [o for o in s["opts"] if o["key"] in s["sel"]]
        await scheduler.add_job({"kind": "post", "type": "rich", "user_id": uid, "due": due, "blocks": s["blocks"],
                                 "targets": [{"chat_id": o["chat_id"], "thread_id": o.get("thread_id"), "label": o["label"]} for o in chosen],
                                 "silent": s["silent"], "pin": s["pin"], "autodel": s.get("autodel", 0), "title": B.title_of(s["blocks"])})
        s["await"] = None
        return await show(client, uid, s, *main_view(s, f"📅 <b>Schedule ho gaya:</b> {scheduler.fmt_time(due)} ({len(chosen)} jagah). Dekhne/cancel: <b>📅 Scheduled</b> menu."))

    if kind == "custom":
        parsed = T.parse_custom(plain(raw))
        if not parsed:
            body, rows = prompt_view("custom")
            return await show(client, uid, s, P("❌ Samajh nahi aaya.") + body, rows)
        chat, thread = parsed
        T.add_custom(s["opts"], s["sel"], chat, thread, f"{chat}" + (f" / {thread}" if thread else ""))
        s["await"] = None
        return await show(client, uid, s, *chooser_view(s))

    block, err = B.parse_block(kind, raw)
    if err:
        body, rows = prompt_view(kind, aw.get("current", ""))
        return await show(client, uid, s, P(f"❌ {err}") + body, rows)
    if aw.get("replace") is not None and aw["replace"] < len(s["blocks"]):
        s["blocks"][aw["replace"]] = block
        note = "✅ Block update ho gaya"
    else:
        s["blocks"].append(block)
        note = f"✅ {B.NAME[block['t']]} add ho gaya"
    s["await"] = None
    await show(client, uid, s, *main_view(s, note))


# ---------- publish / update ----------
def _line(label: str, link: str, fb: bool) -> str:
    return f'✅ {esc(label)} — <a href="{esc(link, quote=True)}">open</a>' + (" <i>(normal emoji use hua)</i>" if fb else "")


async def publish_core(uid: int, blocks: list, chosen: list, silent: bool, pin: bool, autodel: int):
    """Send a rich post to every chosen target. -> (result lines, id of the saved post or None)"""
    h = B.render(blocks)
    uses_emoji = "<tg-emoji" in h
    lines, done, warned = [], [], False
    for o in chosen:
        res, fb = await tgapi.send_rich(o["chat_id"], h, o.get("thread_id"), silent=silent)
        if res.get("ok"):
            mid = res["result"]["message_id"]
            done.append({"chat_id": o["chat_id"], "message_id": mid, "thread_id": o.get("thread_id"), "name": o["label"]})
            line = _line(o["label"], T.post_link(o["chat_id"], mid), fb)
            if pin:
                pr = await tgapi.pin(o["chat_id"], mid)
                line += " 📌" if pr.get("ok") else f" ⚠️ pin fail: <code>{esc(tgapi.desc(pr))}</code>"
            if autodel:
                await scheduler.add_delete(o["chat_id"], mid, autodel)
                line += f" 🗑 {T.autodel_label(autodel)} baad delete"
            if uses_emoji:  # say it loudly when the premium emoji probably did not make it
                cap = tgapi.CAPS.get(o["chat_id"], {}).get("body")
                kind = await tgapi.chat_kind(o["chat_id"])
                if fb or cap is False:
                    line += "<br/>⚠️ Premium emoji nahi gaye - normal emoji se post hui."
                    warned = True
                elif cap is None and kind == "channel":
                    line += "<br/>⚠️ Channel mein premium emoji shayad normal dikhein (Telegram rule)."
                    warned = True
            lines.append(line)
        else:
            lines.append(f"❌ {esc(o['label'])}: <code>{esc(tgapi.desc(res))}</code>")
    if warned:
        lines.append("ℹ️ Pakka pata karne ke liye /emojicheck chalayein - wo asli test karke batata hai.")
    doc_id = None
    if done:
        ins = await db.rich_posts.insert_one({"user_id": uid, "title": B.title_of(blocks), "blocks": blocks, "targets": done, "ts": time.time()})
        doc_id = str(ins.inserted_id)
    return lines, doc_id


async def publish(client, uid: int, s: dict):
    chosen = [o for o in s["opts"] if o["key"] in s["sel"]]
    if not chosen:
        return await show(client, uid, s, *chooser_view(s))
    lines, doc_id = await publish_core(uid, s["blocks"], chosen, s["silent"], s["pin"], s.get("autodel", 0))
    if doc_id:
        s["edit_post"] = doc_id
    await show(client, uid, s, *main_view(s, "<b>Publish result</b>" + "".join(P(x) for x in lines)))


async def exec_rich(client, job: dict) -> str:
    """Runs a scheduled rich post (called by scheduler.py)."""
    chosen = [{"chat_id": t["chat_id"], "thread_id": t.get("thread_id"), "label": t["label"]} for t in job["targets"]]
    lines, _ = await publish_core(job["user_id"], job["blocks"], chosen, job["silent"], job["pin"], job.get("autodel", 0))
    return "📅 <b>Scheduled post ka result</b>\n\n" + "\n".join(x.replace("<br/>", "\n") for x in lines)


async def update_published(client, uid: int, s: dict):
    doc = await db.rich_posts.find_one({"_id": ObjectId(s["edit_post"])})
    if not doc:
        return await show(client, uid, s, *main_view(s, "❌ Post database mein nahi mili"))
    h = B.render(s["blocks"])
    lines = []
    for t in doc["targets"]:
        res, fb = await tgapi.edit_rich(t["chat_id"], t["message_id"], h)
        if res.get("ok") or "not modified" in tgapi.desc(res).lower():
            lines.append(_line(t["name"], T.post_link(t["chat_id"], t["message_id"]), fb))
        else:
            lines.append(f"❌ {esc(t['name'])}: <code>{esc(tgapi.desc(res))}</code>")
    await db.rich_posts.update_one({"_id": doc["_id"]}, {"$set": {"blocks": s["blocks"], "title": B.title_of(s["blocks"])}})
    await show(client, uid, s, *main_view(s, "<b>Update result</b>" + "".join(P(x) for x in lines)))


# ---------- buttons ----------
async def callback(client, query, sessions: dict):
    uid = query.from_user.id
    s = sessions.get(uid)
    d = query.data[3:]  # after 'rp:'
    toast = None
    if not s or s.get("mode") != "RICH":
        s = sessions[uid] = new_session()
    s["panel"] = (query.message.chat.id, query.message.id)

    if d.startswith("add:"):
        kind = d[4:]
        if kind == "hr":
            if len(s["blocks"]) >= MAX_BLOCKS:
                toast = "Bahut zyada blocks"
            else:
                s["blocks"].append({"t": "hr", "raw": ""})
                await show(client, uid, s, *main_view(s, "✅ Divider add ho gaya"))
        else:
            s["await"] = {"kind": kind, "replace": None}
            await show(client, uid, s, *prompt_view(kind))
    elif d in ("back", "cancel"):
        s["await"] = None
        await show(client, uid, s, *main_view(s))
    elif d == "close":
        sessions.pop(uid, None)
        try:
            await query.message.delete()
        except Exception:
            pass
    elif d == "blocks":
        await show(client, uid, s, *blocks_view(s))
    elif d.startswith("ed:"):
        i = int(d[3:])
        b = s["blocks"][i] if i < len(s["blocks"]) else None
        if not b:
            toast = "Block nahi mila"
        elif b["t"] == "hr":
            toast = "Divider mein edit karne ko kuch nahi"
        else:
            s["await"] = {"kind": b["t"], "replace": i, "current": b["raw"]}
            await show(client, uid, s, *prompt_view(b["t"], b["raw"]))
    elif d.startswith("mv:"):
        _, i, step = d.split(":")
        i, j = int(i), int(i) + int(step)
        if 0 <= i < len(s["blocks"]) and 0 <= j < len(s["blocks"]):
            s["blocks"][i], s["blocks"][j] = s["blocks"][j], s["blocks"][i]
        await show(client, uid, s, *blocks_view(s))
    elif d.startswith("rm:"):
        i = int(d[3:])
        if i < len(s["blocks"]):
            s["blocks"].pop(i)
        await show(client, uid, s, *blocks_view(s))
    elif d == "clear":
        await show(client, uid, s, "<h2>🗑 Sab hata dein?</h2>" + P("Draft ke saare blocks hat jayenge."),
                   [row(cb("✅ Haan", "rp:clear_yes", "danger"), cb("❌ Nahi", "rp:back"))])
    elif d == "clear_yes":
        s["blocks"], s["edit_post"] = [], None
        await show(client, uid, s, *main_view(s, "🗑 Clear ho gaya"))
    elif d == "prev":
        if not s["blocks"]:
            toast = "Pehle koi block add karein"
        else:
            if s["preview"]:
                try:
                    await client.delete_messages(*s["preview"])
                except Exception:
                    pass
            res, fb = await tgapi.send_rich(query.message.chat.id, B.render(s["blocks"]))
            if res.get("ok"):
                s["preview"] = (query.message.chat.id, res["result"]["message_id"])
                toast = "Preview bhej diya ⬆️" + (" (normal emoji)" if fb else "")
            else:
                await show(client, uid, s, *main_view(s, f"❌ Preview fail: <code>{esc(tgapi.desc(res))}</code>"))
    elif d == "pub":
        if not s["blocks"]:
            await show(client, uid, s, *main_view(s, "⚠️ Pehle koi block add karein"))
        else:
            s["opts"], s["sel"] = await T.load_options(uid, "ct"), set()
            await show(client, uid, s, *chooser_view(s))
    elif d.startswith("tg:"):
        action = d[3:]
        if action == "go":
            await publish(client, uid, s)
        elif action == "back":
            await show(client, uid, s, *main_view(s))
        elif action == "custom":
            s["await"] = {"kind": "custom"}
            await show(client, uid, s, *prompt_view("custom"))
        elif action in ("silent", "pin"):
            s[action] = not s[action]
            await show(client, uid, s, *chooser_view(s))
        elif action == "autodel":
            s["autodel"] = T.next_autodel(s.get("autodel", 0))
            await show(client, uid, s, *chooser_view(s))
        elif action == "sched":
            if not s["sel"]:
                toast = "Pehle kam se kam ek jagah ✅ karein"
            else:
                s["await"] = {"kind": "sched"}
                await show(client, uid, s, *prompt_view("sched"))
        elif action.startswith("toggle:"):
            key = action[7:]
            s["sel"] ^= {key}
            await show(client, uid, s, *chooser_view(s))
    elif d == "upd":
        await update_published(client, uid, s)
    elif d == "tpl_save":
        if not s["blocks"]:
            toast = "Pehle koi block add karein"
        else:
            s["await"] = {"kind": "tpl"}
            await show(client, uid, s, *prompt_view("tpl"))
    elif d == "tpl_list":
        tpls = await db.templates.find({"user_id": uid, "kind": "rich"}).to_list(length=None)
        body = "<h2>📋 TEMPLATES</h2>" + (P("Load karne ke liye chunein.") if tpls else P("Abhi koi template nahi."))
        rows = [row(cb("🎁 Ready-made templates", "rp:gal", "success"))]
        rows += [row(cb(f"📋 {t['name'][:28]}", f"rp:tpl_use:{t['_id']}"), cb("🗑", f"rp:tpl_del:{t['_id']}", "danger")) for t in tpls]
        rows.append(row(cb("⬅️ Back", "rp:back")))
        await show(client, uid, s, body, rows)
    elif d == "gal":
        rows = [row(cb(name, f"rp:gal_use:{i}")) for i, name in enumerate(TB.NAMES)] + [row(cb("⬅️ Back", "rp:tpl_list"))]
        await show(client, uid, s, "<h2>🎁 READY-MADE</h2>" + P("Ek chunein - phir apne text aur links se badal dein (✏️ Edit blocks)."), rows)
    elif d.startswith("gal_use:"):
        i = int(d[8:])
        s["blocks"], s["edit_post"] = TB.build(i), None
        await show(client, uid, s, *main_view(s, f"✅ Template load hua: <b>{esc(TB.NAMES[i])}</b> - ab text/links badlein"))
    elif d.startswith("tpl_use:"):
        t = await db.templates.find_one({"_id": ObjectId(d[8:])})
        if t:
            s["blocks"], s["edit_post"] = t["data"], None
            await show(client, uid, s, *main_view(s, f"✅ Template load hua: <b>{esc(t['name'])}</b>"))
    elif d.startswith("tpl_del:"):
        await db.templates.delete_one({"_id": ObjectId(d[8:])})
        toast = "Template delete ho gaya"
        tpls = await db.templates.find({"user_id": uid, "kind": "rich"}).to_list(length=None)
        rows = [row(cb(f"📋 {t['name'][:28]}", f"rp:tpl_use:{t['_id']}"), cb("🗑", f"rp:tpl_del:{t['_id']}", "danger")) for t in tpls]
        rows.append(row(cb("⬅️ Back", "rp:back")))
        await show(client, uid, s, "<h2>📋 TEMPLATES</h2>", rows)
    elif d.startswith("post:"):
        doc = await db.rich_posts.find_one({"_id": ObjectId(d[5:])})
        if not doc:
            toast = "Post nahi mili"
        else:
            body = f"<h2>📌 {esc(doc.get('title', 'Post'))}</h2>" + "".join(
                P(f'• <a href="{esc(T.post_link(t["chat_id"], t["message_id"]), quote=True)}">{esc(t["name"])}</a>') for t in doc["targets"])
            rows = [row(cb("✏️ Edit", f"rp:pedit:{doc['_id']}", "success"), cb("📋 Copy as new", f"rp:pcopy:{doc['_id']}")),
                    row(cb("🗑 Delete from channels", f"rp:pdel:{doc['_id']}", "danger")),
                    row(cb("⬅️ Back", "rp:posts"))]
            await show(client, uid, s, body, rows)
    elif d == "posts":
        posts = await db.rich_posts.find({"user_id": uid}).sort("ts", -1).limit(8).to_list(length=8)
        await show(client, uid, s, *posts_view(posts))
    elif d.startswith(("pedit:", "pcopy:")):
        doc = await db.rich_posts.find_one({"_id": ObjectId(d.split(":")[1])})
        if doc:
            ns = new_session(doc["blocks"], str(doc["_id"]) if d.startswith("pedit:") else None)
            ns["panel"] = s["panel"]
            sessions[uid] = ns
            await show(client, uid, ns, *main_view(ns, "✏️ Post load hui" if d.startswith("pedit:") else "📋 Copy load hui"))
    elif d.startswith("pdel:"):
        doc = await db.rich_posts.find_one({"_id": ObjectId(d[5:])})
        if doc:
            gone = 0
            for t in doc["targets"]:
                r = await tgapi.call("deleteMessage", {"chat_id": t["chat_id"], "message_id": t["message_id"]})
                gone += 1 if r.get("ok") else 0
            await db.rich_posts.delete_one({"_id": doc["_id"]})
            posts = await db.rich_posts.find({"user_id": uid}).sort("ts", -1).limit(8).to_list(length=8)
            body, rows = posts_view(posts)
            await show(client, uid, s, P(f"🗑 {gone}/{len(doc['targets'])} message delete hue") + body, rows)
    await (query.answer(toast) if toast else query.answer())
