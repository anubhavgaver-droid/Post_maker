import os
import asyncio
import aiohttp
from aiohttp import web
from config import PORT, PING_INTERVAL

# Simple Keep-Alive HTTP Health Check Server
async def handle_ping(request):
    return web.Response(text="Bot is alive!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Web Server running on port {PORT}")

# Self-Ping Loop to keep Render free tier awake
async def self_ping_loop():
    await asyncio.sleep(10)  # Wait for server startup
    url = f"http://0.0.0.0:{PORT}/"
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url) as resp:
                    pass
            except Exception as e:
                print(f"Self-ping error: {e}")
            await asyncio.sleep(PING_INTERVAL)
