import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# إعدادات قاعدة البيانات
DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")

# القنوات
CHANNEL_SYR_CASH = os.getenv("CHANNEL_SYR_CASH", "")
CHANNEL_SCH_CASH = os.getenv("CHANNEL_SCH_CASH", "")
CHANNEL_ADMIN_LOGS = os.getenv("CHANNEL_ADMIN_LOGS", "")
CHANNEL_WITHDRAW = os.getenv("CHANNEL_WITHDRAW", "")
CHANNEL_STATS = os.getenv("CHANNEL_STATS", "")
CHANNEL_SUPPORT = os.getenv("CHANNEL_SUPPORT", "")

# إعدادات الأداء
REDIS_CACHE_TTL = 3600
DB_POOL_SIZE = 10

# حدود النظام
MIN_DEPOSIT = 500
MAX_DEPOSIT = 100000
MIN_WITHDRAW = 1000
MAX_WITHDRAW = 50000
SYRIATEL_CODE_LIMIT = 5400