import redis.asyncio as redis
import json
from typing import Optional, Any
from config.settings import REDIS_URL, REDIS_CACHE_TTL

class RedisCache:
    def __init__(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """حفظ قيمة في الكاش"""
        if not self.redis:
            return
        if ttl is None:
            ttl = REDIS_CACHE_TTL
        await self.redis.set(key, json.dumps(value), ex=ttl)
    
    async def get(self, key: str) -> Optional[Any]:
        """جلب قيمة من الكاش"""
        if not self.redis:
            return None
        data = await self.redis.get(key)
        return json.loads(data) if data else None
    
    async def delete(self, key: str):
        """حذف قيمة من الكاش"""
        if self.redis:
            await self.redis.delete(key)
    
    async def exists(self, key: str) -> bool:
        """التحقق من وجود المفتاح"""
        if not self.redis:
            return False
        return await self.redis.exists(key) == 1
    
    async def incr(self, key: str, amount: int = 1) -> int:
        """زيادة قيمة رقمية"""
        if not self.redis:
            return 0
        return await self.redis.incrby(key, amount)
    
    async def decr(self, key: str, amount: int = 1) -> int:
        """تقليل قيمة رقمية"""
        if not self.redis:
            return 0
        return await self.redis.decrby(key, amount)

# Instance
cache = RedisCache()

# Helper functions
async def get_user_state(user_id: int) -> Optional[dict]:
    return await cache.get(f"user_state:{user_id}")

async def set_user_state(user_id: int, state: dict, ttl: int = 300):
    await cache.set(f"user_state:{user_id}", state, ttl)

async def delete_user_state(user_id: int):
    await cache.delete(f"user_state:{user_id}")