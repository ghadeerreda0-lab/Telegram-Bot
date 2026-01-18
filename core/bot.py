from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.storage.memory import MemoryStorage
from redis.asyncio import Redis
import logging
from config import BOT_TOKEN, REDIS_HOST, REDIS_PORT, REDIS_DB

# إعدادات التسجيل
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class BotManager:
    _instance = None
    _bot = None
    _dp = None
    _redis = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def init(self):
        """تهيئة البوت والتخزين"""
        if self._bot is None:
            # إنشاء كائن Redis للتخزين
            self._redis = Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True
            )
            
            # استخدام Redis لتخزين FSM (للتوسع)
            storage = RedisStorage(redis=self._redis)
            
            # إنشاء البوت مع إعدادات افتراضية
            self._bot = Bot(
                token=BOT_TOKEN,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
            
            # إنشاء Dispatcher
            self._dp = Dispatcher(storage=storage)
            
            logger.info("✅ Bot initialized successfully")
    
    @property
    def bot(self) -> Bot:
        if self._bot is None:
            raise RuntimeError("Bot not initialized. Call init() first.")
        return self._bot
    
    @property
    def dp(self) -> Dispatcher:
        if self._dp is None:
            raise RuntimeError("Dispatcher not initialized. Call init() first.")
        return self._dp
    
    @property
    def redis(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("Redis not initialized. Call init() first.")
        return self._redis
    
    async def close(self):
        """إغلاق الاتصالات"""
        if self._bot:
            await self._bot.session.close()
        if self._redis:
            await self._redis.close()
        
        logger.info("✅ Bot connections closed")

# Global instance
bot_manager = BotManager()

# اختصارات للاستخدام السهل
async def get_bot() -> Bot:
    await bot_manager.init()
    return bot_manager.bot

async def get_dispatcher() -> Dispatcher:
    await bot_manager.init()
    return bot_manager.dp