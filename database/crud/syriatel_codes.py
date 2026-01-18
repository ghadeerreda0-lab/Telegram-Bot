from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, and_, or_, text
from typing import Optional, List, Tuple, Dict
from database.models import SyriatelCode, Transaction
from core.redis_cache import cache
import datetime

class SyriatelCodeCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_available_code(self, amount: int) -> Optional[SyriatelCode]:
        """الحصول على كود متاح يتسع للمبلغ"""
        cache_key = f"syriatel_available:{amount}"
        cached = await cache.get(cache_key)
        
        if cached:
            stmt = select(SyriatelCode).where(SyriatelCode.id == cached["id"])
            result = await self.db.execute(stmt)
            return result.scalar_one_or_none()
        
        # البحث عن كود يتسع للمبلغ
        stmt = select(SyriatelCode).where(
            and_(
                SyriatelCode.is_active == True,
                SyriatelCode.current_amount + amount <= SyriatelCode.max_amount
            )
        ).order_by(
            SyriatelCode.current_amount.asc()  # نبدأ بالأقل امتلاءً
        ).limit(1)
        
        result = await self.db.execute(stmt)
        code = result.scalar_one_or_none()
        
        if code:
            await cache.set(cache_key, {"id": code.id}, ttl=60)
        
        return code
    
    async def update_code_amount(self, code_id: int, amount: int) -> Tuple[int, int]:
        """تحديث المبلغ في الكود"""
        stmt = select(SyriatelCode).where(SyriatelCode.id == code_id)
        result = await self.db.execute(stmt)
        code = result.scalar_one_or_none()
        
        if not code:
            return 0, 0
        
        old_amount = code.current_amount
        new_amount = min(code.max_amount, old_amount + amount)
        
        update_stmt = update(SyriatelCode).where(
            SyriatelCode.id == code_id
        ).values(
            current_amount=new_amount,
            last_used=datetime.datetime.now()
        )
        
        await self.db.execute(update_stmt)
        await self.db.commit()
        
        # تنظيف الكاش
        await cache.delete("syriatel_available:*")
        
        return old_amount, new_amount
    
    async def reset_daily_codes(self):
        """تصفير الأكواد اليومي"""
        stmt = update(SyriatelCode).where(
            SyriatelCode.daily_reset == True
        ).values(current_amount=0)
        
        await self.db.execute(stmt)
        await self.db.commit()
        
        # تنظيف الكاش
        await cache.delete("syriatel_available:*")
    
    async def add_code(self, code: str, max_amount: int = 5400) -> SyriatelCode:
        """إضافة كود جديد"""
        syriatel_code = SyriatelCode(
            code=code,
            max_amount=max_amount,
            current_amount=0,
            is_active=True,
            daily_reset=True
        )
        
        self.db.add(syriatel_code)
        await self.db.commit()
        await self.db.refresh(syriatel_code)
        
        return syriatel_code
    
    async def get_code_stats(self) -> Dict[str, Any]:
        """إحصائيات الأكواد"""
        # إجمالي الأكواد
        total_stmt = select(func.count(SyriatelCode.id))
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar_one()
        
        # الأكواد النشطة
        active_stmt = select(func.count(SyriatelCode.id)).where(
            SyriatelCode.is_active == True
        )
        active_result = await self.db.execute(active_stmt)
        active = active_result.scalar_one()
        
        # متوسط الامتلاء
        usage_stmt = select(
            func.avg(SyriatelCode.current_amount).label("avg_used"),
            func.sum(SyriatelCode.current_amount).label("total_used"),
            func.sum(SyriatelCode.max_amount).label("total_capacity")
        )
        usage_result = await self.db.execute(usage_stmt)
        usage = usage_result.one()
        
        # الأكواد الممتلئة
        full_stmt = select(func.count(SyriatelCode.id)).where(
            SyriatelCode.current_amount >= SyriatelCode.max_amount
        )
        full_result = await self.db.execute(full_stmt)
        full = full_result.scalar_one()
        
        return {
            "total_codes": total,
            "active_codes": active,
            "avg_usage_percent": (usage.avg_used / 5400 * 100) if usage.avg_used else 0,
            "total_used": usage.total_used or 0,
            "total_capacity": usage.total_capacity or 0,
            "full_codes": full
        }