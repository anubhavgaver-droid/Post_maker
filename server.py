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
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Web Server running on port {PORT}")


# Self-ping must go to the PUBLIC url - a ping to 0.0.0.0 never counts as traffic for Render's free tier.
async def self_ping_loop():
    url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("BASE_URL")
    if not url:
        print("ℹ️ Self-ping off (no RENDER_EXTERNAL_URL). Use an external pinger if the service sleeps.")
        return
    await asyncio.sleep(10)  # Wait for server startup
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        while True:
            try:
                async with session.get(url):
                    pass
            except Exception as e:
                print(f"Self-ping error: {e}")
            await asyncio.sleep(PING_INTERVAL)
