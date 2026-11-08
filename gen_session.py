"""Run this on YOUR OWN computer / phone (Termux), NOT on Render:   python gen_session.py
It logs in to your Premium account and prints a session string. Put it into the host's environment variable
USER_SESSION_STRING. Anyone who has the string controls your account - never share it, never commit it.
(Use the same API_ID / API_HASH as the bot.)"""
import asyncio

from pyrogram import Client


async def main():
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    async with Client("gen", api_id=api_id, api_hash=api_hash, in_memory=True) as app:  # asks phone, code, 2FA password
        me = await app.get_me()
        print(f"\nLogged in as {me.first_name} (premium={getattr(me, 'is_premium', None)})")
        print("\nSESSION STRING (keep it secret):\n")
        print(await app.export_session_string())


asyncio.get_event_loop().run_until_complete(main())
