from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete, func, and_, or_
from sqlalchemy.orm import joinedload
from typing import Optional, List, Dict, Any
from database.models import Transaction, MonthlyCounter, User
from core.redis_cache import cache
import datetime

class TransactionCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_transaction(
        self,
        user_id: int,
        type_: str,
        amount: int,
        payment_method: str,
        transaction_id: str,
        account_number: str = "",
        notes: str = ""
    ) -> Dict[str, Any]:
        """إنشاء معاملة جديدة مع عداد شهري"""
        now = datetime.datetime.now()
        month = now.month
        year = now.year
        
        # الحصول على العداد الشهري وتحديثه
        stmt = select(MonthlyCounter).where(
            MonthlyCounter.month == month,
            MonthlyCounter.year == year,
            MonthlyCounter.payment_method == payment_method
        )
        result = await self.db.execute(stmt)
        counter_row = result.scalar_one_or_none()
        
        if counter_row:
            order_number = counter_row.counter + 1
            counter_row.counter = order_number
        else:
            order_number = 1
            counter_row = MonthlyCounter(
                month=month,
                year=year,
                payment_method=payment_method,
                counter=order_number
            )
            self.db.add(counter_row)
        
        # إنشاء المعاملة
        transaction = Transaction(
            user_id=user_id,
            type=type_,
            amount=amount,
            payment_method=payment_method,
            transaction_id=transaction_id,
            account_number=account_number,
            notes=notes,
            created_at=now
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return {
            "id": transaction.id,
            "order_number": order_number,
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    async def get_transaction(self, transaction_id: int) -> Optional[Transaction]:
        """جلب معاملة"""
        stmt = select(Transaction).options(joinedload(Transaction.user)).where(
            Transaction.id == transaction_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def update_transaction_status(
        self,
        transaction_id: int,
        status: str,
        verified_auto: bool = False,
        notes: str = ""
    ) -> bool:
        """تحديث حالة المعاملة"""
        stmt = update(Transaction).where(Transaction.id == transaction_id).values(
            status=status,
            verified_auto=verified_auto,
            notes=notes
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        return result.rowcount > 0
    
    async def get_pending_transactions(
        self,
        type_: Optional[str] = None,
        payment_method: Optional[str] = None,
        limit: int = 100
    ) -> List[Transaction]:
        """جلب المعاملات المعلقة"""
        conditions = [Transaction.status == "pending"]
        
        if type_:
            conditions.append(Transaction.type == type_)
        
        if payment_method:
            conditions.append(Transaction.payment_method == payment_method)
        
        stmt = (
            select(Transaction)
            .options(joinedload(Transaction.user))
            .where(and_(*conditions))
            .order_by(Transaction.created_at.asc())
            .limit(limit)
        )
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_user_transactions(
        self,
        user_id: int,
        type_: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Transaction]:
        """جلب معاملات مستخدم مع تصفية"""
        conditions = [Transaction.user_id == user_id]
        
        if type_:
            conditions.append(Transaction.type == type_)
        
        stmt = (
            select(Transaction)
            .where(and_(*conditions))
            .order_by(Transaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_daily_stats(self, date: datetime.date) -> Dict[str, Any]:
        """إحصائيات يومية"""
        start_date = datetime.datetime.combine(date, datetime.time.min)
        end_date = datetime.datetime.combine(date, datetime.time.max)
        
        # إجمالي الشحن
        charge_stmt = select(
            Transaction.payment_method,
            func.sum(Transaction.amount).label("total")
        ).where(
            and_(
                Transaction.type == "charge",
                Transaction.status == "approved",
                Transaction.created_at.between(start_date, end_date)
            )
        ).group_by(Transaction.payment_method)
        
        charge_result = await self.db.execute(charge_stmt)
        charge_stats = {row[0]: row[1] for row in charge_result.all()}
        
        # إجمالي السحب
        withdraw_stmt = select(
            Transaction.payment_method,
            func.sum(Transaction.amount).label("total")
        ).where(
            and_(
                Transaction.type == "withdraw",
                Transaction.status == "approved",
                Transaction.created_at.between(start_date, end_date)
            )
        ).group_by(Transaction.payment_method)
        
        withdraw_result = await self.db.execute(withdraw_stmt)
        withdraw_stats = {row[0]: row[1] for row in withdraw_result.all()}
        
        # عدد المعاملات
        count_stmt = select(
            Transaction.type,
            func.count(Transaction.id).label("count")
        ).where(
            Transaction.created_at.between(start_date, end_date)
        ).group_by(Transaction.type)
        
        count_result = await self.db.execute(count_stmt)
        count_stats = {row[0]: row[1] for row in count_result.all()}
        
        return {
            "date": date.strftime("%Y-%m-%d"),
            "charge": charge_stats,
            "withdraw": withdraw_stats,
            "counts": count_stats
        }