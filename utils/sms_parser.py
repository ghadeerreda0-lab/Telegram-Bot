 import re
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.transactions import TransactionCRUD
from database.crud.syriatel_codes import SyriatelCodeCRUD
from core.bot import logger
from config import CHANNEL_ADMIN_LOGS

class SMSParser:
    """محلل رسائل SMS للتحقق التلقائي"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.tx_crud = TransactionCRUD(session)
        self.syriatel_crud = SyriatelCodeCRUD(session)
    
    async def parse_syriatel_sms(self, sms_text: str, sender: str, timestamp: datetime) -> Dict[str, Any]:
        """
        تحليل رسالة سيرياتيل كاش
        العائد: {
            "success": bool,
            "transaction_id": str,
            "amount": int,
            "from_number": str,
            "balance": int,
            "message": str
        }
        """
        # تنظيف النص
        sms_text = sms_text.strip()
        
        # أنماط رسائل سيرياتيل كاش
        patterns = [
            # النمط 1: "تم استلام مبلغ X ليرة من رقم. رقم العملية: Y. الرصيد الجديد: Z"
            r'تم استلام مبلغ (\d+(?:,\d+)*) ليرة من (\d+).*?رقم العملية[:\s]*(\d+).*?الرصيد الجديد[:\s]*(\d+(?:,\d+)*)',
            
            # النمط 2: "تم تحويل مبلغ X ليرة إلى حسابك. رقم العملية: Y"
            r'تم تحويل مبلغ (\d+(?:,\d+)*) ليرة إلى حسابك.*?رقم العملية[:\s]*(\d+)',
            
            # النمط 3: "Syriatel Cash: You received X SP from X. Transaction ID: Y. New balance: Z"
            r'received (\d+(?:,\d+)*) SP from (\d+).*?Transaction ID[:\s]*(\d+).*?New balance[:\s]*(\d+(?:,\d+)*)',
            
            # النمط 4: "عملية إيداع: X ليرة. رقم العملية: Y"
            r'عملية إيداع[:\s]*(\d+(?:,\d+)*) ليرة.*?رقم العملية[:\s]*(\d+)',
            
            # النمط 5: "تم إيداع X ليرة. رقم العملية: Y. الرصيد: Z"
            r'تم إيداع (\d+(?:,\d+)*) ليرة.*?رقم العملية[:\s]*(\d+).*?الرصيد[:\s]*(\d+(?:,\d+)*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    # استخراج البيانات حسب النمط
                    if len(match.groups()) == 4:
                        # النمط 1 أو 3
                        amount_str = match.group(1).replace(',', '')
                        from_number = match.group(2)
                        transaction_id = match.group(3)
                        balance_str = match.group(4).replace(',', '') if match.group(4) else None
                    elif len(match.groups()) == 3:
                        # النمط 5
                        amount_str = match.group(1).replace(',', '')
                        transaction_id = match.group(2)
                        balance_str = match.group(3).replace(',', '')
                        from_number = sender
                    else:
                        # النمط 2 أو 4
                        amount_str = match.group(1).replace(',', '')
                        transaction_id = match.group(2)
                        from_number = sender
                        balance_str = None
                    
                    amount = int(amount_str)
                    balance = int(balance_str) if balance_str else None
                    
                    return {
                        "success": True,
                        "transaction_id": transaction_id.strip(),
                        "amount": amount,
                        "from_number": from_number.strip(),
                        "balance": balance,
                        "message": "تم تحليل الرسالة بنجاح"
                    }
                    
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing SMS with pattern: {e}")
                    continue
        
        # إذا لم يتطابق مع أي نمط
        return {
            "success": False,
            "transaction_id": None,
            "amount": 0,
            "from_number": None,
            "balance": None,
            "message": "لم يتم التعرف على تنسيق الرسالة"
        }
    
    async def verify_transaction(self, transaction_id: str, amount: int) -> Tuple[bool, Optional[int]]:
        """
        التحقق من وجود معاملة بهذا الرقم والمبلغ
        العائد: (موجود, معرف_المعاملة)
        """
        try:
            # البحث عن معاملة معلقة بنفس رقم العملية
            from sqlalchemy import select
            from database.models import Transaction
            
            stmt = select(Transaction).where(
                Transaction.transaction_id == transaction_id,
                Transaction.type == "charge",
                Transaction.status == "pending"
            ).order_by(Transaction.created_at.desc()).limit(1)
            
            result = await self.session.execute(stmt)
            transaction = result.scalar_one_or_none()
            
            if not transaction:
                # البحث عن أي معاملة بنفس الرقم (حتى المكتملة)
                stmt = select(Transaction).where(
                    Transaction.transaction_id == transaction_id,
                    Transaction.type == "charge"
                ).order_by(Transaction.created_at.desc()).limit(1)
                
                result = await self.session.execute(stmt)
                transaction = result.scalar_one_or_none()
                
                if transaction:
                    return False, None  # موجودة ولكنها مكتملة أو مرفوضة
            
            if transaction and transaction.amount == amount:
                return True, transaction.id
            else:
                return False, None
                
        except Exception as e:
            logger.error(f"Error verifying transaction: {e}")
            return False, None
    
    async def auto_approve_transaction(self, transaction_id: int, sms_data: Dict[str, Any]) -> bool:
        """الموافقة التلقائية على المعاملة"""
        try:
            # تحديث حالة المعاملة
            success = await self.tx_crud.update_transaction_status(
                transaction_id,
                "approved",
                verified_auto=True,
                notes=f"تم التحقق تلقائياً via SMS. الراسل: {sms_data['from_number']}"
            )
            
            if not success:
                return False
            
            # جلب المعاملة للمستخدم
            from sqlalchemy import select
            from database.models import Transaction, User
            
            stmt = select(Transaction, User.balance).join(
                User, Transaction.user_id == User.user_id
            ).where(Transaction.id == transaction_id)
            
            result = await self.session.execute(stmt)
            row = result.first()
            
            if not row:
                return False
            
            transaction, user_balance = row
            
            # إضافة الرصيد للمستخدم
            from database.crud.users import UserCRUD
            user_crud = UserCRUD(self.session)
            old_balance, new_balance = await user_crud.update_balance(
                transaction.user_id,
                transaction.amount,
                operation="add"
            )
            
            # إرسال إشعار للمستخدم
            await self._notify_user_auto_approval(
                transaction.user_id,
                transaction.amount,
                new_balance
            )
            
            # تسجيل في قناة الإدمن
            await self._log_auto_approval(
                transaction.id,
                transaction.user_id,
                transaction.amount,
                sms_data['from_number']
            )
            
            logger.info(f"Auto-approved transaction {transaction_id} for user {transaction.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error auto-approving transaction: {e}")
            return False
    
    async def _notify_user_auto_approval(self, user_id: int, amount: int, new_balance: int):
        """إرسال إشعار للمستخدم بالتحقق التلقائي"""
        try:
            from core.bot import bot_manager
            bot = await bot_manager.bot
            
            await bot.send_message(
                user_id,
                f"✅ <b>تم التحقق تلقائياً من شحنتك!</b>\n\n"
                f"💰 <b>المبلغ:</b> {amount:,} ليرة\n"
                f"💰 <b>رصيدك الجديد:</b> {new_balance:,} ليرة\n"
                f"🤖 <b>النظام:</b> التحقق التلقائي\n"
                f"🕒 <b>الوقت:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"شكراً لاستخدامك خدماتنا! 🎉",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not notify user {user_id}: {e}")
    
    async def _log_auto_approval(self, tx_id: int, user_id: int, amount: int, from_number: str):
        """تسجيل الموافقة التلقائية في قناة الإدمن"""
        try:
            from core.bot import bot_manager
            bot = await bot_manager.bot
            
            await bot.send_message(
                CHANNEL_ADMIN_LOGS,
                f"🤖 <b>تحقق تلقائي ناجح</b>\n\n"
                f"📋 <b>رقم المعاملة:</b> {tx_id}\n"
                f"👤 <b>المستخدم:</b> {user_id}\n"
                f"💰 <b>المبلغ:</b> {amount:,} ليرة\n"
                f"📱 <b>من رقم:</b> {from_number}\n"
                f"🕒 <b>الوقت:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not log auto-approval: {e}")
    
    async def process_sms_webhook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        معالجة طلب Webhook من تطبيق SMS
        البيانات المتوقعة: {
            "sender": "رقم المرسل",
            "message": "نص الرسالة",
            "timestamp": "2024-01-15 14:30:00"
        }
        """
        try:
            sender = data.get("sender", "")
            message = data.get("message", "")
            timestamp_str = data.get("timestamp", "")
            
            if not all([sender, message]):
                return {"success": False, "error": "بيانات غير كاملة"}
            
            # تحويل timestamp
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except:
                timestamp = datetime.now()
            
            # تحليل الرسالة
            result = await self.parse_syriatel_sms(message, sender, timestamp)
            
            if not result["success"]:
                return {
                    "success": False,
                    "error": result["message"],
                    "parsed_data": result
                }
            
            # التحقق من وجود معاملة مطابقة
            transaction_id = result["transaction_id"]
            amount = result["amount"]
            
            exists, tx_id = await self.verify_transaction(transaction_id, amount)
            
            if not exists:
                return {
                    "success": False,
                    "error": "لا توجد معاملة معلقة مطابقة",
                    "parsed_data": result,
                    "transaction_exists": False
                }
            
            # الموافقة التلقائية
            approval_success = await self.auto_approve_transaction(tx_id, result)
            
            if approval_success:
                return {
                    "success": True,
                    "message": "تم التحقق والموافقة تلقائياً",
                    "transaction_id": tx_id,
                    "parsed_data": result
                }
            else:
                return {
                    "success": False,
                    "error": "فشل الموافقة التلقائية",
                    "transaction_id": tx_id,
                    "parsed_data": result
                }
            
        except Exception as e:
            logger.error(f"Error processing SMS webhook: {e}")
            return {
                "success": False,
                "error": f"خطأ داخلي: {str(e)}"
            }

# ==================== API Endpoint للـ Webhook ====================

from aiogram import Router
from aiogram.types import Message
import asyncio

sms_router = Router()

@sms_router.message()
async def sms_webhook_handler(message: Message, session: AsyncSession):
    """
    معالجة رسائل SMS الواردة عبر Telegram (للتطبيق على الهاتف)
    يمكن استخدام هذه الوظيفة إذا كان تطبيق SMS يرسل الرسائل لـ Telegram بدلاً من HTTP
    """
    # هذا مثال، يحتاج لتخصيص حسب تطبيق SMS المستخدم
    
    user_id = message.from_user.id
    
    # التحقق إذا كان الراسل هو تطبيق SMS (يجب تحديد معرفه)
    SMS_APP_USER_ID = 123456789  # يجب تغييره
    
    if user_id != SMS_APP_USER_ID:
        return
    
    # تحليل الرسالة
    parser = SMSParser(session)
    
    # افتراض أن الرسالة تحتوي على JSON
    try:
        data = json.loads(message.text)
        result = await parser.process_sms_webhook(data)
        
        # إرسال النتيجة للتطبيق
        await message.reply(json.dumps(result, ensure_ascii=False))
        
    except json.JSONDecodeError:
        # إذا كانت نص عادي، حاول تحليله مباشرة
        result = await parser.parse_syriatel_sms(
            message.text,
            "unknown",
            datetime.now()
        )
        
        await message.reply(
            f"📱 <b>نتيجة تحليل SMS:</b>\n\n"
            f"✅ <b>الحالة:</b> {'ناجح' if result['success'] else 'فاشل'}\n"
            f"🔢 <b>رقم العملية:</b> {result['transaction_id'] or 'غير معروف'}\n"
            f"💰 <b>المبلغ:</b> {result['amount']:,} ليرة\n"
            f"📱 <b>من رقم:</b> {result['from_number'] or 'غير معروف'}\n"
            f"💬 <b>الرسالة:</b> {result['message']}",
            parse_mode="HTML"
        )

# ==================== وظيفة الخلفية للتحقق الدوري ====================

async def background_sms_checker(session: AsyncSession):
    """التحقق الدوري عن رسائل SMS الجديدة"""
    import time
    
    while True:
        try:
            # هنا يمكن جلب رسائل SMS من مصدر خارجي
            # مثل قاعدة بيانات مشتركة مع تطبيق الهاتف
            # أو من API خارجي
            
            logger.info("Background SMS checker running...")
            
            # انتظر 30 ثانية قبل التحقق التالي
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Error in background SMS checker: {e}")
            await asyncio.sleep(60)  # انتظار أطول عند الخطأ