import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from core.bot import bot_manager, BotManager, logger
from core.database import engine, Base, create_pool
from core.redis_cache import cache
from config import BOT_TOKEN, ADMIN_ID, DB_NAME
from utils.sms_parser import background_sms_checker

# استيراد جميع الـ routers
from handlers.start import router as start_router
from handlers.charge.main import router as charge_router
from handlers.charge.syriatel import router as syriatel_router
from handlers.withdraw.main import router as withdraw_router
from handlers.ichancy.main import router as ichancy_router
from admin.dashboard import router as admin_dashboard_router
from admin.users import router as admin_users_router
from admin.transactions import router as admin_transactions_router
from utils.sms_parser import sms_router

# إعداد FastAPI للـ webhooks
app = FastAPI(title="Telegram Bot API")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """إدارة دورة حياة التطبيق"""
    # بداية التشغيل
    logger.info("🚀 Starting bot application...")
    
    # تهيئة قاعدة البيانات
    try:
        async with engine.begin() as conn:
            # إنشاء جميع الجداول
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"✅ Database '{DB_NAME}' initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise
    
    # تهيئة Redis
    try:
        await cache.redis.ping()
        logger.info("✅ Redis connected")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise
    
    # تهيئة البوت
    await bot_manager.init()
    
    # إعداد الـ dispatcher
    dp = bot_manager.dp
    
    # تضمين جميع الـ routers
    dp.include_router(start_router)
    dp.include_router(charge_router)
    dp.include_router(syriatel_router)
    dp.include_router(withdraw_router)
    dp.include_router(ichancy_router)
    dp.include_router(admin_dashboard_router)
    dp.include_router(admin_users_router)
    dp.include_router(admin_transactions_router)
    dp.include_router(sms_router)
    
    # بدء المهام الخلفية
    from database.crud.syriatel_codes import SyriatelCodeCRUD
    from sqlalchemy.ext.asyncio import AsyncSession
    
    async def start_background_tasks():
        """بدء المهام الخلفية"""
        # مهمة تصفير أكواد سيرياتيل اليومي
        async def reset_syriatel_codes_daily():
            while True:
                try:
                    # الانتظار حتى منتصف الليل
                    now = datetime.datetime.now()
                    next_midnight = (now + datetime.timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    sleep_seconds = (next_midnight - now).total_seconds()
                    
                    logger.info(f"⏰ Next syriatel codes reset in {sleep_seconds/3600:.1f} hours")
                    await asyncio.sleep(sleep_seconds)
                    
                    # التصفير
                    async with AsyncSession(engine) as session:
                        syriatel_crud = SyriatelCodeCRUD(session)
                        await syriatel_crud.reset_daily_codes()
                    
                    logger.info("✅ Daily syriatel codes reset completed")
                    
                except Exception as e:
                    logger.error(f"Error in daily reset task: {e}")
                    await asyncio.sleep(3600)  # انتظار ساعة عند الخطأ
        
        # بدء المهام
        asyncio.create_task(reset_syriatel_codes_daily())
        # asyncio.create_task(background_sms_checker())  # تفعيل إذا كان هناك نظام SMS
        
        logger.info("✅ Background tasks started")
    
    await start_background_tasks()
    
    logger.info("✅ Bot is ready and running!")
    
    yield  # التطبيق يعمل هنا
    
    # إغلاق التشغيل
    logger.info("🛑 Shutting down bot application...")
    await bot_manager.close()
    await engine.dispose()
    await cache.redis.close()
    logger.info("✅ Bot shutdown completed")

app = FastAPI(lifespan=lifespan)

# ==================== واجهات API للمراقبة ====================

@app.get("/")
async def root():
    """الصفحة الرئيسية للـ API"""
    return {
        "status": "online",
        "service": "Telegram Bot",
        "version": "1.0.0",
        "endpoints": [
            "/health",
            "/stats",
            "/admin/stats"
        ]
    }

@app.get("/health")
async def health_check():
    """فحص صحة النظام"""
    try:
        # فحص قاعدة البيانات
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        
        # فحص Redis
        await cache.redis.ping()
        
        # فحص البوت
        await bot_manager.bot.get_me()
        
        return {
            "status": "healthy",
            "database": "connected",
            "redis": "connected",
            "bot": "connected",
            "timestamp": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@app.get("/stats")
async def get_stats():
    """إحصائيات النظام (للأدمن فقط)"""
    # يمكن إضافة مصادقة هنا
    try:
        from sqlalchemy import select, func
        from sqlalchemy.ext.asyncio import AsyncSession
        from database.models import User, Transaction
        
        async with AsyncSession(engine) as session:
            # إحصائيات المستخدمين
            users_stmt = select(func.count(User.user_id))
            users_result = await session.execute(users_stmt)
            total_users = users_result.scalar()
            
            # إحصائيات المعاملات
            tx_stmt = select(
                func.count(Transaction.id),
                func.sum(Transaction.amount).filter(Transaction.type == "charge", Transaction.status == "approved"),
                func.sum(Transaction.amount).filter(Transaction.type == "withdraw", Transaction.status == "approved")
            )
            tx_result = await session.execute(tx_stmt)
            tx_count, total_charge, total_withdraw = tx_result.one()
            
            return {
                "users": {
                    "total": total_users or 0
                },
                "transactions": {
                    "total": tx_count or 0,
                    "total_charge": total_charge or 0,
                    "total_withdraw": total_withdraw or 0,
                    "net": (total_charge or 0) - (total_withdraw or 0)
                },
                "system": {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "uptime": "N/A"  # يمكن حساب وقت التشغيل
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

# ==================== Webhook endpoints ====================

@app.post("/webhook/sms")
async def sms_webhook_endpoint(data: dict):
    """نقطة نهاية لاستقبال رسائل SMS"""
    try:
        from utils.sms_parser import SMSParser
        from sqlalchemy.ext.asyncio import AsyncSession
        
        async with AsyncSession(engine) as session:
            parser = SMSParser(session)
            result = await parser.process_sms_webhook(data)
            
            if result["success"]:
                return {"status": "success", "data": result}
            else:
                return {"status": "error", "error": result.get("error")}
                
    except Exception as e:
        logger.error(f"SMS webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== تشغيل البوت ====================

async def on_startup():
    """عمليات بدء التشغيل"""
    logger.info("🟢 Bot starting up...")
    
    # تعيين webhook (إذا كان في وضع الإنتاج)
    import os
    webhook_url = os.getenv("WEBHOOK_URL")
    
    if webhook_url:
        from aiogram.methods import SetWebhook
        bot = await bot_manager.bot
        
        await bot(SetWebhook(
            url=f"{webhook_url}/webhook/bot",
            drop_pending_updates=True
        ))
        logger.info(f"✅ Webhook set to: {webhook_url}/webhook/bot")
    else:
        logger.info("✅ Using polling mode")

async def on_shutdown():
    """عمليات إيقاف التشغيل"""
    logger.info("🔴 Bot shutting down...")
    await bot_manager.close()

async def main():
    """الدالة الرئيسية لتشغيل البوت"""
    # إعدادات التسجيل
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("bot.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    
    # تعطيل تسجيل aiogram المزعج
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    
    logger.info("=" * 50)
    logger.info("🤖 BOT STARTING")
    logger.info("=" * 50)
    
    try:
        # بدء البوت في وضع polling
        dp = bot_manager.dp
        
        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)
        
        # حذف التحديثات القديمة والبدء
        bot = await bot_manager.bot
        await bot.delete_webhook(drop_pending_updates=True)
        
        logger.info("✅ Starting bot in polling mode...")
        
        # بدء الـ dispatcher
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        
    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}")
        raise
    finally:
        logger.info("=" * 50)
        logger.info("🛑 BOT STOPPED")
        logger.info("=" * 50)

if __name__ == "__main__":
    import sys
    import datetime  # إضافة استيراد datetime
    
    # التحقق من وجود التوكن
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN is not set in environment variables")
        sys.exit(1)
    
    # تشغيل البوت
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)