"""Rich post blocks: parse what the admin types, render the Rich Message HTML."""
import html
import re

from entities import plain, split_icon_html, split_lines_balanced

COLORS = {"blue": "primary", "primary": "primary", "green": "success", "success": "success",
          "red": "danger", "danger": "danger", "": None, "none": None, "default": None, "-": None}
ICON = {"h": "🔠", "p": "📝", "q": "💬", "t": "▦", "b": "🔘", "hr": "➖"}
NAME = {"h": "Heading", "p": "Text", "q": "Quote", "t": "Table", "b": "Buttons", "hr": "Divider"}
esc = html.escape


def fmt(h: str) -> str:
    """' // ' (with spaces) or a typed \\n = new line inside one line of text."""
    return re.sub(r"\s+//\s+", "<br/>", h.replace("\\n", " // "))


def btn_html(b: dict) -> str:
    st = f' style="{b["style"]}"' if b.get("style") else ""
    icon = f'<tg-emoji emoji-id="{b["icon"]}">{esc(b.get("fb") or "⭐")}</tg-emoji> ' if b.get("icon") else ""
    return f'<tg-button type="url"{st} url="{esc(b["url"], quote=True)}">{icon}{esc(b["name"])}</tg-button>'


def render(blocks: list) -> str:
    """The post, exactly as it is sent."""
    out = []
    for b in blocks:
        t = b["t"]
        if t == "h":
            out.append(f"<h{b['size']}>{fmt(b['text'].replace(chr(10), ' '))}</h{b['size']}>")
        elif t == "p":
            out += [f"<p>{fmt(line)}</p>" for line in split_lines_balanced(b["text"]) if plain(line)]
        elif t == "q":
            out.append("<blockquote>" + "<br/>".join(fmt(x) for x in split_lines_balanced(b["text"]) if plain(x)) + "</blockquote>")
        elif t == "hr":
            out.append("<hr/>")
        elif t == "t":
            rows = ""
            for r in b["rows"]:
                right = btn_html(r["btn"]) if r["btn"] else ""
                rows += f'<tr><td valign="middle">{fmt(r["text"])}</td><td align="center" valign="middle">{right}</td></tr>'
            out.append(f"<table bordered>{rows}</table>")
        elif t == "b":
            for line in b["lines"]:
                out.append("<tg-button-row>" + "".join(btn_html(x) for x in line) + "</tg-button-row>")
    return "".join(out)


def parse_url(u: str):
    u = plain(u)
    if re.match(r"^(https?://|tg://)\S+$", u):
        return u
    if re.match(r"^(t|telegram)\.me/\S+$", u):
        return "https://" + u
    if re.fullmatch(r"@\w{4,}", u):
        return "https://t.me/" + u[1:]
    return None


def parse_button(name_html: str, url_html: str, color: str = ""):
    """-> (button dict, None) or (None, error). A premium emoji in the name becomes the button icon."""
    name, icon, fb = split_icon_html(name_html)
    if not name:
        return None, "A button needs a name."
    link = parse_url(url_html)
    if not link:
        return None, f"“{esc(plain(url_html)[:40])}” is not a valid link. Use https://… or t.me/… or @username."
    c = plain(color).lower()
    if c not in COLORS:
        return None, "Color must be blue, green, red or none."
    return {"name": name[:60], "url": link, "style": COLORS[c], "icon": icon, "fb": fb}, None


def parse_block(kind: str, raw: str):
    """raw = HTML made from the admin's message. -> (block, None) or (None, error text)"""
    raw = raw.strip()
    if not plain(raw):
        return None, "Send some text."
    if kind == "h":
        m = re.match(r"^([1-6]):\s*(.+)$", raw, re.S)
        size, text = (int(m.group(1)), m.group(2).strip()) if m else (1, raw)
        return {"t": "h", "size": size, "text": text, "raw": raw}, None
    if kind in ("p", "q"):
        return {"t": kind, "text": raw, "raw": raw}, None
    if kind == "t":
        rows = []
        for n, line in enumerate([x for x in raw.split("\n") if plain(x)], 1):
            parts = [x.strip() for x in line.split("|")]
            if len(parts) == 1:
                rows.append({"text": parts[0], "btn": None})
                continue
            if len(parts) < 3:
                return None, f"Row {n}: write <code>Text | Button name | Link | color</code> (or only the text)."
            b, err = parse_button(parts[1], parts[2], parts[3] if len(parts) > 3 else "")
            if err:
                return None, f"Row {n}: {err}"
            rows.append({"text": parts[0], "btn": b})
        if len(rows) > 30:
            return None, "A table can have at most 30 rows."
        return {"t": "t", "rows": rows, "raw": raw}, None
    if kind == "b":
        lines = []
        for n, group in enumerate([g for g in re.split(r"\n\s*\n", raw) if plain(g)], 1):
            line = []
            for x in [y for y in group.split("\n") if plain(y)]:
                parts = [p.strip() for p in x.split("|")]
                if len(parts) < 2:
                    return None, f"Row {n}: write <code>Name | Link | color</code>."
                b, err = parse_button(parts[0], parts[1], parts[2] if len(parts) > 2 else "")
                if err:
                    return None, f"Row {n}: {err}"
                line.append(b)
            if len(line) > 8:
                return None, f"Row {n}: at most 8 buttons in one row."
            lines.append(line)
        return {"t": "b", "lines": lines, "raw": raw}, None
    return None, "Unknown block."


def title_of(blocks: list) -> str:
    for b in blocks:
        if b["t"] in ("h", "p", "q"):
            return plain(b["text"].replace("\n", " "))[:40] or "Post"
    return "Post"
