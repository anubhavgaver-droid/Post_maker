"""Ready-made rich post templates. Load one, then change the texts and links to yours."""
import blocks as B

SPEC = [
    ("📢 Announcement", [
        ("h", "1: 📢 Announcement"),
        ("p", "Yahan apna message likhein.\nHar nayi line ek naya paragraph banegi."),
        ("hr", ""),
        ("b", "Join Channel | https://t.me/yourchannel | green"),
    ]),
    ("🎬 New Release", [
        ("h", "2: 🎬 Movie / Story Name"),
        ("q", "Chhota sa description yahan likhein."),
        ("t", "Quality: 1080p // Size: 1.5 GB | DOWNLOAD | https://t.me/yourchannel | green\nQuality: 720p // Size: 900 MB | DOWNLOAD | https://t.me/yourchannel | blue\nQuality: 480p // Size: 450 MB | DOWNLOAD | https://t.me/yourchannel | blue"),
        ("b", "Join | https://t.me/yourchannel | green\nRequest | https://t.me/yourgroup | blue"),
    ]),
    ("📋 Chats Board", [
        ("h", "1: 📁 CHATS LIST"),
        ("t", "1. Chat A // ID -1001234567890 | OPEN | https://t.me/chat_a | green\n2. Chat B // ID -1009876543210 | OPEN | https://t.me/chat_b | green"),
        ("b", "Refresh | https://t.me/yourbot | blue"),
    ]),
    ("🎁 Giveaway", [
        ("h", "1: 🎁 GIVEAWAY"),
        ("p", "Prize: <b>apna prize likhein</b>\nLast date: DD/MM"),
        ("t", "Step 1 // Channel join karein | JOIN | https://t.me/yourchannel | green\nStep 2 // Post share karein | SHARE | https://t.me/share/url?url=https://t.me/yourchannel | blue"),
        ("q", "Winner random chuna jayega."),
    ]),
    ("🔗 Links Hub", [
        ("h", "1: 🔗 Hamare Links"),
        ("b", "Channel | https://t.me/yourchannel | green\nGroup | https://t.me/yourgroup | blue\n\nSupport | https://t.me/yoursupport | red"),
    ]),
]
NAMES = [n for n, _ in SPEC]


def build(i: int) -> list:
    out = []
    for kind, raw in SPEC[i][1]:
        if kind == "hr":
            out.append({"t": "hr", "raw": ""})
            continue
        block, err = B.parse_block(kind, raw)
        assert not err, f"{SPEC[i][0]}: {err}"
        out.append(block)
    return out
