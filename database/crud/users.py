from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import joinedload
from typing import Optional, List, Tuple
from database.models import User, Transaction, IchancyAccount, Referral
from core.redis_cache import cache
import datetime

class UserCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user(self, user_id: int) -> Optional[User]:
        """جلب مستخدم بالكاش"""
        cache_key = f"user:{user_id}"
        cached = await cache.get(cache_key)
        if cached:
            return User(**cached)
        
        stmt = select(User).where(User.user_id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            await cache.set(cache_key, {
                "user_id": user.user_id,
                "balance": user.balance,
                "is_banned": user.is_banned,
                "referrals_count": user.referrals_count,
                "active_referrals": user.active_referrals
            }, ttl=600)
        
        return user
    
    async def create_user(self, user_id: int) -> User:
        """إنشاء مستخدم جديد"""
        user = User(user_id=user_id, balance=0)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        # تحديث الكاش
        await cache.delete(f"user:{user_id}")
        
        return user
    
    async def update_balance(self, user_id: int, amount: int, operation: str = "add") -> Tuple[int, int]:
        """تحديث رصيد المستخدم"""
        user = await self.get_user(user_id)
        if not user:
            user = await self.create_user(user_id)
        
        old_balance = user.balance
        
        if operation == "add":
            new_balance = old_balance + amount
        elif operation == "subtract":
            new_balance = max(0, old_balance - amount)
        else:
            new_balance = amount  # set مباشر
        
        stmt = update(User).where(User.user_id == user_id).values(balance=new_balance)
        await self.db.execute(stmt)
        await self.db.commit()
        
        # تحديث الكاش
        await cache.delete(f"user:{user_id}")
        
        return old_balance, new_balance
    
    async def get_user_with_details(self, user_id: int) -> Optional[User]:
        """جلب مستخدم مع جميع تفاصيله"""
        stmt = (
            select(User)
            .options(joinedload(User.transactions))
            .options(joinedload(User.ichancy_account))
            .where(User.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_top_users_by_balance(self, limit: int = 20) -> List[User]:
        """أعلى المستخدمين حسب الرصيد"""
        stmt = select(User).order_by(User.balance.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_active_users_count(self, days: int = 7) -> int:
        """عدد المستخدمين النشطين (لديهم معاملة في آخر X يوم)"""
        date_threshold = datetime.datetime.now() - datetime.timedelta(days=days)
        
        stmt = select(func.count(func.distinct(Transaction.user_id))).where(
            Transaction.created_at >= date_threshold
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()
    
    async def search_users(self, query: str, limit: int = 50) -> List[User]:
        """بحث عن مستخدمين"""
        stmt = select(User).where(
            (User.user_id.cast(String).ilike(f"%{query}%")) |
            (User.ichancy_account.has(username=query))
        ).limit(limit)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()