from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, and_, or_, desc
from typing import Optional, List, Dict, Any
import datetime
import csv
import os
import io

from keyboards.main import back_button, confirmation_buttons, admin_transaction_buttons
from core.bot import logger
from database.models import Transaction, User
from database.crud.transactions import TransactionCRUD
from database.crud.users import UserCRUD
from config import ADMIN_ID, CHANNEL_ADMIN_LOGS

router = Router()

class TransactionAdminStates(StatesGroup):
    """حالات إدارة المعاملات"""
    filter_transactions = State()
    search_transaction = State()

# ==================== أدوات مساعدة ====================

async def process_transaction_approval(
    callback: CallbackQuery,
    session: AsyncSession,
    transaction_id: int,
    action: str,  # approve, reject, deliver
    admin_id: int
) -> bool:
    """معالجة موافقة/رفض/تسليم معاملة"""
    tx_crud = TransactionCRUD(session)
    
    # جلب المعاملة
    transaction = await tx_crud.get_transaction(transaction_id)
    if not transaction:
        await callback.answer("❌ المعاملة غير موجودة", show_alert=True)
        return False
    
    # التحقق من حالة المعاملة
    if transaction.status != "pending" and action in ["approve", "reject"]:
        await callback.answer(f"⚠️ تمت معالجتها مسبقاً ({transaction.status})", show_alert=True)
        return False
    
    user_crud = UserCRUD(session)
    user = await user_crud.get_user(transaction.user_id)
    
    if not user:
        await callback.answer("❌ المستخدم غير موجود", show_alert=True)
        return False
    
    try:
        if action == "approve":
            # الموافقة على المعاملة
            if transaction.type == "charge":
                # إضافة الرصيد للمستخدم
                old_balance, new_balance = await user_crud.update_balance(
                    transaction.user_id,
                    transaction.amount,
                    operation="add"
                )
                
                # تحديث حالة المعاملة
                await tx_crud.update_transaction_status(
                    transaction_id,
                    "approved",
                    notes=f"تمت الموافقة بواسطة {admin_id}"
                )
                
                # إرسال إشعار للمستخدم
                await notify_user(
                    transaction.user_id,
                    f"✅ <b>تم قبول طلب الشحن</b>\n\n"
                    f"💰 <b>المبلغ:</b> {transaction.amount:,} ليرة\n"
                    f"💳 <b>الطريقة:</b> {transaction.payment_method}\n"
                    f"💰 <b>رصيدك السابق:</b> {old_balance:,} ليرة\n"
                    f"💰 <b>رصيدك الجديد:</b> {new_balance:,} ليرة\n"
                    f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
                )
                
                # تحديث رسالة القناة
                await update_channel_message(
                    callback,
                    transaction,
                    f"\n\n✅ <b>تم الموافقة</b>\n"
                    f"💰 <b>الرصيد قبل:</b> {old_balance:,} ليرة\n"
                    f"💰 <b>الرصيد بعد:</b> {new_balance:,} ليرة"
                )
                
            elif transaction.type == "withdraw":
                # السحب تم خصمه مسبقاً عند الطلب، فقط نقوم بالموافقة
                await tx_crud.update_transaction_status(
                    transaction_id,
                    "approved",
                    notes=f"تمت الموافقة على السحب بواسطة {admin_id}"
                )
                
                # إرسال إشعار للمستخدم
                await notify_user(
                    transaction.user_id,
                    f"✅ <b>تم قبول طلب السحب</b>\n\n"
                    f"💰 <b>المبلغ:</b> {transaction.amount:,} ليرة\n"
                    f"💳 <b>الطريقة:</b> {transaction.payment_method}\n"
                    f"📱 <b>رقم الحساب:</b> {transaction.account_number}\n"
                    f"⏳ <b>جاري تحويل المبلغ...</b>\n"
                    f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
                )
                
                # تحديث رسالة القناة
                await update_channel_message(
                    callback,
                    transaction,
                    "\n\n✅ <b>تم الموافقة على السحب</b>\n"
                    f"⏳ <b>جاري التحويل إلى:</b> {transaction.account_number}"
                )
            
            logger.info(f"Transaction {transaction_id} approved by {admin_id}")
            
        elif action == "reject":
            # رفض المعاملة
            if transaction.type == "charge":
                # لا نضيف رصيد (لأنه لم يضاف أصلاً)
                pass
            elif transaction.type == "withdraw":
                # إعادة الرصيد للمستخدم
                old_balance, new_balance = await user_crud.update_balance(
                    transaction.user_id,
                    transaction.amount,
                    operation="add"
                )
            
            await tx_crud.update_transaction_status(
                transaction_id,
                "rejected",
                notes=f"تم الرفض بواسطة {admin_id}"
            )
            
            # إرسال إشعار للمستخدم
            await notify_user(
                transaction.user_id,
                f"❌ <b>تم رفض طلبك</b>\n\n"
                f"📋 <b>نوع الطلب:</b> {transaction.type}\n"
                f"💰 <b>المبلغ:</b> {transaction.amount:,} ليرة\n"
                f"💡 <b>ملاحظة:</b> يمكنك التواصل مع الدعم للاستفسار\n"
                f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            
            # تحديث رسالة القناة
            await update_channel_message(
                callback,
                transaction,
                "\n\n❌ <b>تم رفض الطلب</b>"
            )
            
            logger.info(f"Transaction {transaction_id} rejected by {admin_id}")
        
        elif action == "deliver":
            # تأكيد تسليم الحوالة (للسحب فقط)
            if transaction.type != "withdraw":
                await callback.answer("❌ هذا الزر للسحب فقط", show_alert=True)
                return False
            
            await tx_crud.update_transaction_status(
                transaction_id,
                "completed",
                notes=f"تم التسليم بواسطة {admin_id}"
            )
            
            # إرسال إشعار للمستخدم
            await notify_user(
                transaction.user_id,
                f"💵 <b>تم تسليم الحوالة</b>\n\n"
                f"💰 <b>المبلغ:</b> {transaction.amount:,} ليرة\n"
                f"💳 <b>الطريقة:</b> {transaction.payment_method}\n"
                f"📱 <b>رقم الحساب:</b> {transaction.account_number}\n"
                f"✅ <b>تم التحويل بنجاح</b>\n"
                f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            
            # تحديث رسالة القناة
            await update_channel_message(
                callback,
                transaction,
                "\n\n💵 <b>تم تسليم الحوالة</b>"
            )
            
            logger.info(f"Transaction {transaction_id} delivered by {admin_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing transaction {transaction_id}: {e}")
        await callback.answer(f"❌ خطأ: {str(e)}", show_alert=True)
        return False

async def notify_user(user_id: int, message: str):
    """إرسال إشعار للمستخدم"""
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        await bot.send_message(user_id, message, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Could not notify user {user_id}: {e}")

async def update_channel_message(callback: CallbackQuery, transaction: Transaction, additional_text: str):
    """تحديث رسالة القناة"""
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        # الحصول على النص الأصلي
        original_text = callback.message.text or callback.message.caption or ""
        
        # إضافة النص الجديد
        new_text = original_text + additional_text
        
        # تحديث الرسالة
        await bot.edit_message_text(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=new_text,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error updating channel message: {e}")

# ==================== معالجات أزرار المعاملات ====================

@router.callback_query(F.data.startswith("approve_"))
async def approve_transaction(callback: CallbackQuery, session: AsyncSession):
    """معالجة زر الموافقة"""
    transaction_id = int(callback.data.split("_")[1])
    
    success = await process_transaction_approval(
        callback, session, transaction_id, "approve", callback.from_user.id
    )
    
    if success:
        await callback.answer("✅ تمت الموافقة")
    else:
        await callback.answer()

@router.callback_query(F.data.startswith("reject_"))
async def reject_transaction(callback: CallbackQuery, session: AsyncSession):
    """معالجة زر الرفض"""
    transaction_id = int(callback.data.split("_")[1])
    
    success = await process_transaction_approval(
        callback, session, transaction_id, "reject", callback.from_user.id
    )
    
    if success:
        await callback.answer("❌ تم الرفض")
    else:
        await callback.answer()

@router.callback_query(F.data.startswith("deliver_"))
async def deliver_transaction(callback: CallbackQuery, session: AsyncSession):
    """معالجة زر تم التسليم"""
    transaction_id = int(callback.data.split("_")[1])
    
    success = await process_transaction_approval(
        callback, session, transaction_id, "deliver", callback.from_user.id
    )
    
    if success:
        await callback.answer("💵 تم تسليم الحوالة")
    else:
        await callback.answer()

@router.callback_query(F.data.startswith("reset_user_"))
async def reset_user_balance(callback: CallbackQuery, session: AsyncSession):
    """زر تصفير حساب المستخدم"""
    transaction_id = int(callback.data.split("_")[2])
    
    # جلب المعاملة والمستخدم
    tx_crud = TransactionCRUD(session)
    transaction = await tx_crud.get_transaction(transaction_id)
    
    if not transaction:
        await callback.answer("❌ المعاملة غير موجودة", show_alert=True)
        return
    
    user_id = transaction.user_id
    
    # تأكيد العملية
    await callback.message.edit_text(
        f"🔄 <b>تصفير حساب مستخدم</b>\n\n"
        f"👤 <b>المستخدم:</b> {user_id}\n"
        f"📋 <b>المعاملة:</b> {transaction_id}\n"
        f"💰 <b>المبلغ:</b> {transaction.amount:,} ليرة\n\n"
        f"<b>هل تريد تصفير رصيد هذا المستخدم؟</b>\n"
        f"سيتم وضع رصيده على 0.",
        reply_markup=confirmation_buttons(
            f"confirm_reset_{user_id}_{transaction_id}",
            f"cancel_reset_{transaction_id}"
        ),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_reset_"))
async def confirm_reset_user_balance(callback: CallbackQuery, session: AsyncSession):
    """تأكيد تصفير حساب المستخدم"""
    parts = callback.data.split("_")
    user_id = int(parts[2])
    transaction_id = int(parts[3])
    
    user_crud = UserCRUD(session)
    
    # جلب الرصيد الحالي
    user = await user_crud.get_user(user_id)
    if not user:
        await callback.answer("❌ المستخدم غير موجود", show_alert=True)
        return
    
    old_balance = user.balance
    
    # تصفير الرصيد
    await user_crud.update_balance(user_id, 0, operation="set")
    
    # تسجيل المعاملة الإدارية
    tx_crud = TransactionCRUD(session)
    await tx_crud.create_transaction(
        user_id=user_id,
        type_="admin_reset",
        amount=old_balance,
        payment_method="admin",
        transaction_id=f"RESET_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        notes=f"تصفير رصيد من {old_balance} إلى 0، مرتبط بمعاملة {transaction_id}"
    )
    
    # تحديث رسالة القناة
    from core.bot import bot_manager
    bot = await bot_manager.bot
    
    original_text = callback.message.text or ""
    new_text = original_text + f"\n\n🔄 <b>تم تصفير الحساب</b>\n💰 <b>الرصيد السابق:</b> {old_balance:,} ليرة"
    
    await bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=new_text,
        parse_mode="HTML"
    )
    
    # تسجيل في قناة الإدمن
    try:
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"🔄 <b>تصفير حساب مستخدم</b>\n\n"
            f"👤 <b>المستخدم:</b> {user_id}\n"
            f"📋 <b>المعاملة:</b> {transaction_id}\n"
            f"💰 <b>الرصيد السابق:</b> {old_balance:,} ليرة\n"
            f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not log reset to admin channel: {e}")
    
    await callback.answer("✅ تم تصفير الحساب")

# ==================== إدارة المعاملات من لوحة التحكم ====================

@router.callback_query(F.data == "admin_all_charges")
@admin_required
async def show_all_charges(callback: CallbackQuery, session: AsyncSession):
    """عرض جميع طلبات الشحن"""
    await show_filtered_transactions(callback, session, "charge")

@router.callback_query(F.data == "admin_all_withdraws")
async def show_all_withdraws(callback: CallbackQuery, session: AsyncSession):
    """عرض جميع طلبات السحب"""
    await show_filtered_transactions(callback, session, "withdraw")

async def show_filtered_transactions(callback: CallbackQuery, session: AsyncSession, tx_type: str = None):
    """عرض معاملات مصفاة"""
    from sqlalchemy import select
    
    arabic_type = {
        "charge": "الشحن",
        "withdraw": "السحب",
        None: "الجميع"
    }.get(tx_type, tx_type)
    
    # بناء الاستعلام
    conditions = []
    if tx_type:
        conditions.append(Transaction.type == tx_type)
    
    stmt = select(Transaction).where(*conditions).order_by(
        Transaction.created_at.desc()
    ).limit(50)
    
    result = await session.execute(stmt)
    transactions = result.scalars().all()
    
    if not transactions:
        await callback.message.edit_text(
            f"📭 <b>لا توجد معاملات {arabic_type}</b>",
            reply_markup=back_button("admin_payments" if tx_type == "charge" else "admin_withdraws"),
            parse_mode="HTML"
        )
        return
    
    # إحصائيات سريعة
    total_amount = sum(tx.amount for tx in transactions)
    pending_count = sum(1 for tx in transactions if tx.status == "pending")
    approved_count = sum(1 for tx in transactions if tx.status == "approved")
    
    # النص الرئيسي
    text = f"""
<b>📋 معاملات {arabic_type}</b>

📊 <b>الإحصائيات:</b>
• العدد: {len(transactions):,}
• المبلغ الإجمالي: {total_amount:,} ليرة
• المعلقة: {pending_count:,}
• المنجزة: {approved_count:,}

<b>آخر {min(10, len(transactions))} معاملة:</b>
"""
    
    # عرض آخر 10 معاملات
    for i, tx in enumerate(transactions[:10], 1):
        status_icon = "✅" if tx.status == "approved" else "⏳" if tx.status == "pending" else "❌"
        text += f"{i}. {status_icon} {tx.amount:,} ليرة - {tx.payment_method} - {tx.created_at.strftime('%m-%d %H:%M')}\n"
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="📤 تصدير كـ CSV", callback_data=f"export_{tx_type or 'all'}_csv")
    builder.button(text="🔍 بحث متقدم", callback_data=f"search_{tx_type or 'all'}")
    
    if tx_type == "charge":
        builder.button(text="📥 المعلقة فقط", callback_data="admin_pending_charges")
        builder.button(text="⬅️ رجوع", callback_data="admin_payments")
    elif tx_type == "withdraw":
        builder.button(text="📤 المعلقة فقط", callback_data="admin_pending_withdraws")
        builder.button(text="⬅️ رجوع", callback_data="admin_withdraws")
    else:
        builder.button(text="⬅️ رجوع", callback_data="admin_panel")
    
    builder.adjust(2, 1, 1)
    
    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data.startswith("export_") and F.data.endswith("_csv"))
@admin_required
async def export_transactions_csv(callback: CallbackQuery, session: AsyncSession):
    """تصدير المعاملات كملف CSV"""
    tx_type = callback.data.split("_")[1]  # charge, withdraw, all
    
    if tx_type == "all":
        tx_type = None
    
    # جلب المعاملات
    from sqlalchemy import select
    
    conditions = []
    if tx_type:
        conditions.append(Transaction.type == tx_type)
    
    stmt = select(Transaction).where(*conditions).order_by(Transaction.created_at.desc())
    result = await session.execute(stmt)
    transactions = result.scalars().all()
    
    if not transactions:
        await callback.answer("❌ لا توجد معاملات للتصدير", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⏳ <b>جاري تجهيز ملف التصدير...</b>",
        parse_mode="HTML"
    )
    
    # إنشاء CSV في الذاكرة
    output = io.StringIO()
    writer = csv.writer(output)
    
    # كتابة الرأس
    writer.writerow([
        "ID", "User ID", "Type", "Amount", "Payment Method",
        "Transaction ID", "Account Number", "Status", "Created At", "Notes"
    ])
    
    # كتابة البيانات
    for tx in transactions:
        writer.writerow([
            tx.id,
            tx.user_id,
            tx.type,
            tx.amount,
            tx.payment_method or "",
            tx.transaction_id or "",
            tx.account_number or "",
            tx.status,
            tx.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            tx.notes or ""
        ])
    
    # إرسال الملف
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        # حفظ في ملف مؤقت
        filename = f"transactions_{tx_type or 'all'}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = f"temp/{filename}"
        
        os.makedirs("temp", exist_ok=True)
        with open(filepath, "w", encoding="utf-8-sig") as f:
            f.write(output.getvalue())
        
        file = FSInputFile(filepath)
        
        arabic_type = {
            "charge": "الشحن",
            "withdraw": "السحب",
            None: "الجميع"
        }.get(tx_type, tx_type)
        
        await bot.send_document(
            callback.from_user.id,
            file,
            caption=f"📤 <b>تصدير معاملات {arabic_type}</b>\n\n"
                   f"📅 <b>التاريخ:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                   f"📊 <b>عدد المعاملات:</b> {len(transactions):,}",
            parse_mode="HTML"
        )
        
        # حذف الملف المؤقت
        os.remove(filepath)
        await callback.message.delete()
        
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        await callback.message.edit_text(
            f"❌ <b>خطأ في التصدير:</b> {str(e)}",
            parse_mode="HTML"
        )
    
    await callback.answer()

def admin_required(func):
    """مصادقة الأدمن"""
    async def wrapper(*args, **kwargs):
        callback_or_message = args[0]
        user_id = callback_or_message.from_user.id
        
        if user_id != ADMIN_ID:
            if isinstance(callback_or_message, CallbackQuery):
                await callback_or_message.answer("⛔ صلاحيات غير كافية", show_alert=True)
            else:
                await callback_or_message.answer("⛔ هذا الأمر للإدمن فقط.")
            return
        
        return await func(*args, **kwargs)
    
    return wrapper