"""Telegram message entities -> HTML, and premium (custom) emoji helpers. Offsets are UTF-16, like Telegram's."""
import html as _html
import re

_SIMPLE = {"BOLD": "b", "ITALIC": "i", "UNDERLINE": "u", "STRIKETHROUGH": "s", "SPOILER": "tg-spoiler", "CODE": "code", "PRE": "code"}
_TGE = re.compile(r'<tg-emoji emoji-id="(\d+)">(.*?)</tg-emoji>', re.S)
_TAG = re.compile(r"<[^>]+>")


def etype(e) -> str:
    return getattr(e.type, "name", str(e.type)).split(".")[-1].upper()


def custom_emoji_ids(entities) -> list:
    return [str(e.custom_emoji_id) for e in (entities or []) if etype(e) == "CUSTOM_EMOJI" and getattr(e, "custom_emoji_id", None)]


def entities_to_html(text: str, entities) -> str:
    """Text + entities -> escaped HTML (b i u s code spoiler, links, <tg-emoji> for premium emoji).
    Entities that only partly overlap are closed and re-opened so the result is always well-formed."""
    text = text or ""
    u = text.encode("utf-16-le")
    n = len(u) // 2
    spans = []  # (start, end, open tag, close tag)
    for e in entities or []:
        k, start, end = etype(e), e.offset, e.offset + e.length
        if e.length <= 0 or start < 0 or end > n:
            continue
        if k in _SIMPLE:
            t = _SIMPLE[k]
            spans.append((start, end, f"<{t}>", f"</{t}>"))
        elif k == "TEXT_LINK" and getattr(e, "url", None):
            spans.append((start, end, f'<a href="{_html.escape(e.url, quote=True)}">', "</a>"))
        elif k == "CUSTOM_EMOJI" and getattr(e, "custom_emoji_id", None):
            spans.append((start, end, f'<tg-emoji emoji-id="{e.custom_emoji_id}">', "</tg-emoji>"))
    points = sorted({0, n} | {s[0] for s in spans} | {s[1] for s in spans})
    out, stack = [], []
    for idx, p in enumerate(points):
        closing = {i for i in stack if spans[i][1] == p}
        reopen = []
        while closing:  # close what ends here; anything opened later than it is closed and re-opened
            i = stack.pop()
            out.append(spans[i][3])
            if i in closing:
                closing.discard(i)
            else:
                reopen.append(i)
        for i in reversed(reopen):
            out.append(spans[i][2])
            stack.append(i)
        for i in sorted((i for i, s in enumerate(spans) if s[0] == p), key=lambda i: -spans[i][1]):
            out.append(spans[i][2])
            stack.append(i)
        if idx + 1 < len(points):
            out.append(_html.escape(u[2 * p:2 * points[idx + 1]].decode("utf-16-le", errors="ignore"), quote=False))
    return "".join(out)


def plain(h: str) -> str:
    return _html.unescape(_TAG.sub("", h or "")).strip()


def split_icon_html(h: str):
    """'<tg-emoji ..>🔥</tg-emoji> Download' -> ('Download', icon id, '🔥').  First premium emoji = the icon."""
    m = _TGE.search(h or "")
    icon = fb = None
    if m:
        icon, fb = m.group(1), plain(m.group(2)) or "⭐"
        h = h[:m.start()] + h[m.end():]
    h = _TGE.sub(lambda mm: mm.group(2), h)  # any other premium emoji stay as their normal emoji
    return plain(h), icon, fb


def split_lines_balanced(h: str) -> list:
    """Split HTML at newlines, closing and re-opening tags so every line is well-formed."""
    tag = re.compile(r"<(/?)([a-zA-Z-]+)([^>]*)>")
    lines, cur, stack, pos = [], "", [], 0

    def feed(chunk):
        nonlocal cur
        parts = chunk.split("\n")
        for k, part in enumerate(parts):
            cur += part
            if k < len(parts) - 1:
                lines.append(cur + "".join(f"</{t}>" for t, _ in reversed(stack)))
                cur = "".join(f"<{t}{a}>" for t, a in stack)

    for m in tag.finditer(h):
        feed(h[pos:m.start()])
        pos = m.end()
        cur += m.group(0)
        closing, name, attrs = m.group(1), m.group(2), m.group(3)
        if attrs.strip().endswith("/"):
            continue
        if closing:
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    del stack[k]
                    break
        else:
            stack.append((name, attrs))
    feed(h[pos:])
    lines.append(cur)
    return lines
