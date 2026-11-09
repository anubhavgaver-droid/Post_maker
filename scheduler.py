"""Scheduled posts and auto-delete jobs (stored in MongoDB, so a restart loses nothing)."""
import asyncio
import datetime
import logging
import os
import re
import time

import db
import tgapi

log = logging.getLogger("scheduler")
TZ_MIN = int(os.getenv("TZ_OFFSET_MIN", "330"))  # India = 330
_exec = {}
_MULT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def register(job_type: str, fn):
    """fn(client, job) -> text that is sent to the user after the job ran"""
    _exec[job_type] = fn


def fmt_time(ts: float, tz_min: int = None) -> str:
    return time.strftime("%d %b, %H:%M", time.gmtime(ts + (TZ_MIN if tz_min is None else tz_min) * 60))


def parse_when(text: str, now: float = None, tz_min: int = None):
    """'30m' '2h' '1d 12h' | '18:30' (next time it is 18:30) | 'kal 09:00' / 'tomorrow 09:00' | '25/12 09:00'  ->  epoch or None"""
    now = now or time.time()
    tz = TZ_MIN if tz_min is None else tz_min
    t = (text or "").strip().lower()
    if re.fullmatch(r"(?:\s*\d+\s*[smhd])+", t):
        secs = sum(int(n) * _MULT[u] for n, u in re.findall(r"(\d+)\s*([smhd])", t))
        return now + secs if secs >= 20 else None
    m = re.fullmatch(r"(?:(kal|tomorrow)\s+)?(\d{1,2}):(\d{2})", t)
    if m:
        h, mi = int(m.group(2)), int(m.group(3))
        if h > 23 or mi > 59:
            return None
        local = now + tz * 60
        due = (int(local) // 86400) * 86400 + h * 3600 + mi * 60 + (86400 if m.group(1) else 0)
        if not m.group(1) and due <= local + 20:
            due += 86400
        return due - tz * 60
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})", t)
    if m:
        d, mo, h, mi = map(int, m.groups())
        year = time.gmtime(now + tz * 60).tm_year
        for y in (year, year + 1):
            try:
                ts = datetime.datetime(y, mo, d, h, mi, tzinfo=datetime.timezone.utc).timestamp() - tz * 60
            except ValueError:
                return None
            if ts > now + 20:
                return ts
    return None


# ---------- storage ----------
async def add_job(doc: dict) -> str:
    ins = await db.jobs.insert_one(doc)
    return str(ins.inserted_id)


async def list_jobs(uid: int) -> list:
    return await db.jobs.find({"user_id": uid, "kind": "post"}).sort("due", 1).limit(20).to_list(length=20)


async def cancel_job(job_id, uid: int) -> bool:
    from bson import ObjectId
    r = await db.jobs.delete_one({"_id": ObjectId(str(job_id)), "user_id": uid})
    return bool(r.deleted_count)


async def add_delete(chat_id, message_id: int, delay: int):
    if delay and delay > 0:
        await db.jobs.insert_one({"kind": "delete", "due": time.time() + delay, "chat_id": chat_id, "message_id": message_id, "user_id": 0})


async def due_jobs() -> list:
    return await db.jobs.find({"due": {"$lte": time.time()}}).to_list(length=20)


# ---------- runner ----------
async def _execute(client, job: dict):
    if job["kind"] == "delete":
        await tgapi.call("deleteMessage", {"chat_id": job["chat_id"], "message_id": job["message_id"]})
        return
    fn = _exec.get(job.get("type"))
    if not fn:
        return
    try:
        text = await fn(client, job)
    except Exception as e:
        log.exception("scheduled job failed")
        text = f"❌ <b>Scheduled post fail ho gayi</b>\\n<code>{type(e).__name__}: {str(e)[:150]}</code>"
    await client.send_message(job["user_id"], text)


async def run_once(client):
    for job in await due_jobs():
        await db.jobs.delete_one({"_id": job["_id"]})  # take it first, so it can never run twice
        try:
            await _execute(client, job)
        except Exception:
            log.exception("job error")


async def run(client):
    while True:
        await asyncio.sleep(15)
        try:
            await run_once(client)
        except Exception:
            log.exception("scheduler loop")
