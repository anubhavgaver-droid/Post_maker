from motor.motor_asyncio import AsyncIOMotorClient

from config import DB_NAME, MONGO_URI

client = AsyncIOMotorClient(MONGO_URI)
database = client[DB_NAME]
channels = database["saved_channels"]
topics = database["saved_topics"]
admins = database["saved_admins"]
templates = database["post_templates"]   # {user_id, kind: 'rich' | 'grid', name, data}
rich_posts = database["rich_posts"]       # {user_id, title, blocks, targets: [{chat_id, message_id, thread_id, name}], ts}
