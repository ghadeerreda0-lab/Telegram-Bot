 from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_
from typing import Optional, List, Dict, Any
import datetime
import json
import os

from keyboards.main import back_button, confirmation_buttons, numeric_keyboard
from core.bot import logger
from core.redis_cache import cache
from database.models import User, Transaction, IchancyAccount, Referral
from database.crud.users import UserCRUD
from database.crud.transactions import TransactionCRUD
from config import ADMIN_ID
from utils.generators import generate_password

router = Router()

class UserAdminStates(StatesGroup):
    """حالات إدارة المستخدمين"""
    search_user = State()
    edit_balance = State()
    add_balance = State()
    subtract_balance = State()
    ban_user = State()
    unban_user = State()
    send_message = State()
    send_photo = State()
    broadcast_message = State()

# ==================== أدوات مساعدة ====================

async def get_user_details(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """جلب تفاصيل مستخدم كاملة"""
    user_crud = UserCRUD(session)
    tx_crud = TransactionCRUD(session)
    
    user = await user_crud.get_user_with_details(user_id)
    if not user:
        return None
    
    # جلب آخر 5 معاملات
    recent_txs = await tx_crud.get_user_transactions(user_id, limit=5)
    
    # جلب حساب Ichancy إن وجد
    ichancy_account = None
    if user.ichancy_account:
        ichancy_account = {
            "username": user.ichancy_account.username,
            "balance": user.ichancy_account.balance,
            "is_active": user.ichancy_account.is_active
        }
    
    # إحصائيات المستخدم
    total_charge = 0
    total_withdraw = 0
    
    for tx in user.transactions:
        if tx.type == "charge" and tx.status == "approved":
            total_charge += tx.amount
        elif tx.type == "withdraw" and tx.status == "approved":
            total_withdraw += tx.amount
    
    return {
        "user_id": user.user_id,
        "balance": user.balance,
        "is_banned": user.is_banned,
        "referrals_count": user.referrals_count,
        "active_referrals": user.active_referrals,
        "total_earned": user.total_earned,
        "created_at": user.created_at.strftime("%Y-%m-%d %H:%M"),
        "updated_at": user.updated_at.strftime("%Y-%m-%d %H:%M"),
        "total_charge": total_charge,
        "total_withdraw": total_withdraw,
        "net_balance": total_charge - total_withdraw,
        "ichancy_account": ichancy_account,
        "recent_transactions": [
            {
                "id": tx.id,
                "type": tx.type,
                "amount": tx.amount,
                "status": tx.status,
                "created_at": tx.created_at.strftime("%Y-%m-%d %H:%M")
            }
            for tx in recent_txs
        ]
    }

async def export_user_data(session: AsyncSession, user_id: int) -> Optional[str]:
    """تصدير بيانات المستخدم كملف JSON"""
    user_data = await get_user_details(session, user_id)
    if not user_data:
        return None
    
    # إضافة وقت التصدير
    user_data["export_time"] = datetime.datetime.now().isoformat()
    
    # حفظ في ملف مؤقت
    filename = f"user_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = f"temp/{filename}"
    
    # إنشاء مجلد temp إذا لم يكن موجود
    os.makedirs("temp", exist_ok=True)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2, default=str)
    
    return filepath

# ==================== معالجات القائمة ====================

@router.callback_query(F.data == "admin_search_user")
@admin_required
async def search_user_start(callback: CallbackQuery, state: FSMContext):
    """بدء البحث عن مستخدم"""
    await state.set_state(UserAdminStates.search_user)
    
    await callback.message.edit_text(
        "🔍 <b>البحث عن مستخدم</b>\n\n"
        "⬇️ <b>أدخل أحد الخيارات:</b>\n"
        "• معرف المستخدم (رقم)\n"
        "• اسم مستخدم Ichancy\n"
        "• جزء من المعرف\n\n"
        "أو أرسل ❌ للإلغاء.",
        reply_markup=back_button("admin_users")
    )
    
    await callback.answer()

@router.message(UserAdminStates.search_user)
async def search_user_process(message: Message, state: FSMContext, session: AsyncSession):
    """معالجة بحث المستخدم"""
    query = message.text.strip()
    
    if query == "❌":
        await state.clear()
        await admin_users_menu(message, session)
        return
    
    user_crud = UserCRUD(session)
    
    # البحث
    if query.isdigit():
        # البحث بمعرف المستخدم
        user_id = int(query)
        user = await user_crud.get_user_with_details(user_id)
        
        if user:
            await show_user_details(message, session, user)
            await state.clear()
            return
    else:
        # البحث باسم مستخدم Ichancy
        from sqlalchemy import select
        from database.models import IchancyAccount
        
        stmt = select(IchancyAccount).where(
            IchancyAccount.username.ilike(f"%{query}%")
        ).limit(10)
        
        result = await session.execute(stmt)
        accounts = result.scalars().all()
        
        if accounts:
            if len(accounts) == 1:
                user = await user_crud.get_user_with_details(accounts[0].user_id)
                if user:
                    await show_user_details(message, session, user)
                    await state.clear()
                    return
            else:
                # عرض قائمة النتائج
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                
                builder = InlineKeyboardBuilder()
                
                for account in accounts[:5]:  # أول 5 نتائج
                    builder.button(
                        text=f"👤 {account.username}",
                        callback_data=f"admin_view_user_{account.user_id}"
                    )
                
                builder.button(text="⬅️ رجوع", callback_data="admin_search_user")
                builder.adjust(1)
                
                await message.answer(
                    f"🔍 <b>تم العثور على {len(accounts)} نتيجة</b>\n\n"
                    "اختر المستخدم المطلوب:",
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML"
                )
                return
    
    await message.answer(
        "❌ <b>لم يتم العثور على مستخدم</b>\n\n"
        "⬇️ حاول البحث بـ:\n"
        "• معرف مختلف\n"
        "• جزء من المعرف\n"
        "• اسم مستخدم Ichancy",
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("admin_view_user_"))
@admin_required
async def view_user_details(callback: CallbackQuery, session: AsyncSession):
    """عرض تفاصيل مستخدم"""
    user_id = int(callback.data.split("_")[3])
    
    user_crud = UserCRUD(session)
    user = await user_crud.get_user_with_details(user_id)
    
    if not user:
        await callback.answer("❌ المستخدم غير موجود", show_alert=True)
        return
    
    await show_user_details(callback.message, session, user)
    await callback.answer()

async def show_user_details(message_or_callback, session: AsyncSession, user):
    """عرض تفاصيل المستخدم (وظيفة مساعدة)"""
    details = await get_user_details(session, user.user_id)
    
    if not details:
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer("❌ خطأ في جلب البيانات")
        else:
            await message_or_callback.message.edit_text("❌ خطأ في جلب البيانات")
        return
    
    # بناء نص التفاصيل
    details_text = f"""
<b>👤 تفاصيل المستخدم</b>

<code>{details['user_id']}</code>

💰 <b>الرصيد الحالي:</b> {details['balance']:,} ليرة
🚫 <b>الحالة:</b> {'محظور ❌' if details['is_banned'] else 'نشط ✅'}
📅 <b>تاريخ التسجيل:</b> {details['created_at']}
🔄 <b>آخر تحديث:</b> {details['updated_at']}

📊 <b>الإحصائيات المالية:</b>
• إجمالي الشحن: {details['total_charge']:,} ليرة
• إجمالي السحب: {details['total_withdraw']:,} ليرة
• صافي الإيداع: {details['net_balance']:,} ليرة

👥 <b>نظام الاحالات:</b>
• عدد الاحالات: {details['referrals_count']}
• الاحالات النشطة: {details['active_referrals']}
• الأرباح من الاحالات: {details['total_earned']:,} ليرة
"""
    
    # إضافة حساب Ichancy إن وجد
    if details['ichancy_account']:
        acc = details['ichancy_account']
        status = "نشط ✅" if acc['is_active'] else "معطل ❌"
        
        details_text += f"""
⚡ <b>حساب Ichancy:</b>
• اسم المستخدم: {acc['username']}
• الرصيد: {acc['balance']:,} ليرة
• الحالة: {status}
"""
    
    # إضافة آخر المعاملات
    if details['recent_transactions']:
        details_text += "\n<b>📝 آخر المعاملات:</b>\n"
        for tx in details['recent_transactions'][:3]:
            arabic_type = {
                "charge": "شحن",
                "withdraw": "سحب",
                "gift": "هدية",
                "bonus": "بونص"
            }.get(tx['type'], tx['type'])
            
            status_icon = "✅" if tx['status'] == "approved" else "⏳" if tx['status'] == "pending" else "❌"
            
            details_text += f"• {arabic_type} {status_icon}: {tx['amount']:,} ليرة ({tx['created_at']})\n"
    
    # أزرار التحكم
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="💰 تعديل الرصيد", callback_data=f"admin_edit_user_balance_{user.user_id}")
    builder.button(text="📤 سحب رصيد", callback_data=f"admin_subtract_balance_{user.user_id}")
    builder.button(text="📥 إضافة رصيد", callback_data=f"admin_add_balance_{user.user_id}")
    
    if details['is_banned']:
        builder.button(text="✅ فك الحظر", callback_data=f"admin_unban_user_{user.user_id}")
    else:
        builder.button(text="🚫 حظر", callback_data=f"admin_ban_user_{user.user_id}")
    
    builder.button(text="📨 إرسال رسالة", callback_data=f"admin_send_message_{user.user_id}")
    builder.button(text="📤 تصدير البيانات", callback_data=f"admin_export_user_{user.user_id}")
    builder.button(text="🗑️ حذف الحساب", callback_data=f"admin_delete_user_{user.user_id}")
    builder.button(text="⬅️ رجوع", callback_data="admin_users")
    
    builder.adjust(2, 2, 2, 2, 1)
    
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(
            details_text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    else:
        await message_or_callback.message.edit_text(
            details_text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("admin_edit_user_balance_"))
@admin_required
async def edit_user_balance_start(callback: CallbackQuery, state: FSMContext):
    """بدء تعديل رصيد مستخدم"""
    user_id = int(callback.data.split("_")[4])
    
    await state.set_state(UserAdminStates.edit_balance)
    await state.update_data(target_user_id=user_id)
    
    await callback.message.edit_text(
        f"💰 <b>تعديل رصيد المستخدم</b>\n\n"
        f"المستخدم: <code>{user_id}</code>\n\n"
        f"⬇️ <b>أدخل الرصيد الجديد:</b>\n"
        f"• أدخل الرقم فقط\n"
        f"• مثال: 50000\n\n"
        f"أو أرسل ❌ للإلغاء.",
        reply_markup=back_button(f"admin_view_user_{user_id}")
    )
    
    await callback.answer()

@router.message(UserAdminStates.edit_balance)
async def edit_user_balance_process(message: Message, state: FSMContext, session: AsyncSession):
    """معالجة تعديل الرصيد"""
    data = await state.get_data()
    user_id = data.get("target_user_id")
    
    if not user_id:
        await message.answer("❌ جلسة منتهية")
        await state.clear()
        return
    
    new_balance_text = message.text.strip()
    
    if new_balance_text == "❌":
        await state.clear()
        await view_user_details_by_id(message, session, user_id)
        return
    
    if not new_balance_text.isdigit():
        await message.answer(
            "❌ <b>قيمة غير صالحة!</b>\n"
            "يجب إدخال أرقام فقط.\n"
            "⬇️ أعد إدخال الرصيد:",
            parse_mode="HTML"
        )
        return
    
    new_balance = int(new_balance_text)
    
    if new_balance < 0:
        await message.answer(
            "❌ <b>القيمة غير صالحة!</b>\n"
            "يجب أن يكون الرصيد موجبًا.\n"
            "⬇️ أعد إدخال الرصيد:",
            parse_mode="HTML"
        )
        return
    
    # تحديث الرصيد
    user_crud = UserCRUD(session)
    old_balance, _ = await user_crud.update_balance(user_id, new_balance, operation="set")
    
    # تسجيل المعاملة الإدارية
    tx_crud = TransactionCRUD(session)
    await tx_crud.create_transaction(
        user_id=user_id,
        type_="admin_adjust",
        amount=new_balance - old_balance,
        payment_method="admin",
        transaction_id=f"ADJ_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        notes=f"تعديل إداري من {old_balance} إلى {new_balance}"
    )
    
    # إرسال إشعار للمستخدم
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            user_id,
            f"🔔 <b>تحديث الرصيد</b>\n\n"
            f"تم تعديل رصيدك من قبل الإدمن:\n"
            f"💰 <b>الرصيد السابق:</b> {old_balance:,} ليرة\n"
            f"💰 <b>الرصيد الجديد:</b> {new_balance:,} ليرة\n"
            f"📊 <b>التغيير:</b> {new_balance - old_balance:+,} ليرة\n\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Could not notify user {user_id}: {e}")
    
    await message.answer(
        f"✅ <b>تم تحديث الرصيد بنجاح!</b>\n\n"
        f"المستخدم: <code>{user_id}</code>\n"
        f"💰 <b>الرصيد السابق:</b> {old_balance:,} ليرة\n"
        f"💰 <b>الرصيد الجديد:</b> {new_balance:,} ليرة\n"
        f"📊 <b>التغيير:</b> {new_balance - old_balance:+,} ليرة",
        parse_mode="HTML"
    )
    
    await state.clear()
    
    # تسجيل في قناة الإدمن
    from config import CHANNEL_ADMIN_LOGS
    
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"💰 <b>تعديل رصيد مستخدم</b>\n\n"
            f"👤 <b>المستخدم:</b> {user_id}\n"
            f"👨‍💼 <b>بواسطة:</b> {message.from_user.id}\n"
            f"💰 <b>من:</b> {old_balance:,} ليرة\n"
            f"💰 <b>إلى:</b> {new_balance:,} ليرة\n"
            f"📊 <b>التغيير:</b> {new_balance - old_balance:+,} ليرة\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not log to admin channel: {e}")

async def view_user_details_by_id(message, session, user_id):
    """عرض تفاصيل مستخدم بالمعرف"""
    user_crud = UserCRUD(session)
    user = await user_crud.get_user_with_details(user_id)
    
    if user:
        await show_user_details(message, session, user)
    else:
        await message.answer("❌ المستخدم غير موجود")

@router.callback_query(F.data.startswith("admin_add_balance_"))
@admin_required
async def add_balance_start(callback: CallbackQuery, state: FSMContext):
    """بدء إضافة رصيد لمستخدم"""
    user_id = int(callback.data.split("_")[3])
    
    await state.set_state(UserAdminStates.add_balance)
    await state.update_data(target_user_id=user_id)
    
    await callback.message.edit_text(
        f"📥 <b>إضافة رصيد للمستخدم</b>\n\n"
        f"المستخدم: <code>{user_id}</code>\n\n"
        f"⬇️ <b>أدخل المبلغ للإضافة:</b>\n"
        f"• أدخل الرقم فقط\n"
        f"• مثال: 5000\n\n"
        f"أو أرسل ❌ للإلغاء.",
        reply_markup=back_button(f"admin_view_user_{user_id}")
    )
    
    await callback.answer()

@router.message(UserAdminStates.add_balance)
async def add_balance_process(message: Message, state: FSMContext, session: AsyncSession):
    """معالجة إضافة الرصيد"""
    data = await state.get_data()
    user_id = data.get("target_user_id")
    
    if not user_id:
        await message.answer("❌ جلسة منتهية")
        await state.clear()
        return
    
    amount_text = message.text.strip()
    
    if amount_text == "❌":
        await state.clear()
        await view_user_details_by_id(message, session, user_id)
        return
    
    if not amount_text.isdigit():
        await message.answer(
            "❌ <b>قيمة غير صالحة!</b>\n"
            "يجب إدخال أرقام فقط.\n"
            "⬇️ أعد إدخال المبلغ:",
            parse_mode="HTML"
        )
        return
    
    amount = int(amount_text)
    
    if amount <= 0:
        await message.answer(
            "❌ <b>القيمة غير صالحة!</b>\n"
            "يجب أن يكون المبلغ موجبًا.\n"
            "⬇️ أعد إدخال المبلغ:",
            parse_mode="HTML"
        )
        return
    
    # إضافة الرصيد
    user_crud = UserCRUD(session)
    old_balance, new_balance = await user_crud.update_balance(user_id, amount, operation="add")
    
    # تسجيل المعاملة
    tx_crud = TransactionCRUD(session)
    await tx_crud.create_transaction(
        user_id=user_id,
        type_="admin_deposit",
        amount=amount,
        payment_method="admin",
        transaction_id=f"ADD_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        notes=f"إضافة إدارية بواسطة {message.from_user.id}"
    )
    
    # إرسال إشعار للمستخدم
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            user_id,
            f"🎁 <b>إضافة رصيد</b>\n\n"
            f"تمت إضافة رصيد لحسابك من قبل الإدمن:\n"
            f"💰 <b>المبلغ المضاف:</b> {amount:,} ليرة\n"
            f"💰 <b>الرصيد السابق:</b> {old_balance:,} ليرة\n"
            f"💰 <b>الرصيد الجديد:</b> {new_balance:,} ليرة\n\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Could not notify user {user_id}: {e}")
    
    await message.answer(
        f"✅ <b>تمت إضافة الرصيد بنجاح!</b>\n\n"
        f"المستخدم: <code>{user_id}</code>\n"
        f"💰 <b>المبلغ المضاف:</b> {amount:,} ليرة\n"
        f"💰 <b>الرصيد السابق:</b> {old_balance:,} ليرة\n"
        f"💰 <b>الرصيد الجديد:</b> {new_balance:,} ليرة",
        parse_mode="HTML"
    )
    
    await state.clear()

@router.callback_query(F.data == "admin_top_balance")
@admin_required
async def show_top_balances(callback: CallbackQuery, session: AsyncSession):
    """عرض أعلى الأرصدة"""
    user_crud = UserCRUD(session)
    top_users = await user_crud.get_top_users_by_balance(limit=20)
    
    if not top_users:
        await callback.message.edit_text(
            "📭 <b>لا توجد بيانات</b>",
            reply_markup=back_button("admin_users"),
            parse_mode="HTML"
        )
        return
    
    # بناء النص
    text_lines = ["<b>🏆 أعلى 20 رصيد في البوت</b>\n"]
    
    for i, user in enumerate(top_users, 1):
        text_lines.append(
            f"{i}. <code>{user.user_id}</code> - {user.balance:,} ليرة"
        )
    
    # إجمالي الأرصدة
    total_balance = sum(user.balance for user in top_users)
    text_lines.append(f"\n<b>💰 الإجمالي:</b> {total_balance:,} ليرة")
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 تصدير كـ CSV", callback_data="admin_export_top_balances")
    builder.button(text="⬅️ رجوع", callback_data="admin_users")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
@admin_required
async def broadcast_message_start(callback: CallbackQuery, state: FSMContext):
    """بدء إرسال رسالة جماعية"""
    await state.set_state(UserAdminStates.broadcast_message)
    
    await callback.message.edit_text(
        "📨 <b>إرسال رسالة جماعية</b>\n\n"
        "⬇️ <b>أدخل نص الرسالة:</b>\n"
        "• يمكنك استخدام HTML للتنسيق\n"
        "• سيتم إرسالها لجميع المستخدمين\n"
        "• قد تستغرق بعض الوقت\n\n"
        "أو أرسل ❌ للإلغاء.",
        reply_markup=back_button("admin_users")
    )
    
    await callback.answer()

@router.message(UserAdminStates.broadcast_message)
async def broadcast_message_process(message: Message, state: FSMContext, session: AsyncSession):
    """معالجة الرسالة الجماعية"""
    if message.text.strip() == "❌":
        await state.clear()
        await admin_users_menu(message, session)
        return
    
    message_text = message.text
    
    # تأكيد الإرسال
    from keyboards.main import confirmation_buttons
    
    confirm_kb = confirmation_buttons(
        confirm_data=f"confirm_broadcast:{message.message_id}",
        cancel_data="cancel_broadcast"
    )
    
    await message.answer(
        f"⚠️ <b>تأكيد الإرسال الجماعي</b>\n\n"
        f"<b>نص الرسالة:</b>\n{message_text[:500]}...\n\n"
        f"<b>سيتم إرسال هذه الرسالة لجميع مستخدمي البوت.</b>\n"
        f"هل تريد المتابعة؟",
        reply_markup=confirm_kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("confirm_broadcast:"))
@admin_required
async def confirm_broadcast(callback: CallbackQuery, session: AsyncSession):
    """تأكيد وإرسال الرسالة الجماعية"""
    message_id = int(callback.data.split(":")[1])
    
    # جلب الرسالة الأصلية
    from core.bot import bot_manager
    bot = await bot_manager.bot
    
    try:
        original_message = await bot.forward_message(
            chat_id=callback.from_user.id,
            from_chat_id=callback.from_user.id,
            message_id=message_id
        )
        
        message_text = original_message.text
        
    except Exception as e:
        await callback.answer("❌ لم أتمكن من جلب الرسالة", show_alert=True)
        return
    
    # جلب جميع مستخدمي البوت
    from sqlalchemy import select
    from database.models import User
    
    stmt = select(User.user_id).where(User.is_banned == False)
    result = await session.execute(stmt)
    user_ids = [row[0] for row in result.all()]
    
    total_users = len(user_ids)
    
    await callback.message.edit_text(
        f"⏳ <b>جاري إرسال الرسالة الجماعية...</b>\n\n"
        f"👥 <b>عدد المستخدمين:</b> {total_users:,}\n"
        f"📝 <b>حالة الإرسال:</b> يبدأ...",
        parse_mode="HTML"
    )
    
    # إرسال للمستخدمين
    success_count = 0
    fail_count = 0
    
    for i, user_id in enumerate(user_ids, 1):
        try:
            await bot.send_message(
                user_id,
                f"🔔 <b>إشعار من الإدارة</b>\n\n{message_text}",
                parse_mode="HTML"
            )
            success_count += 1
            
            # تحديث حالة الإرسال كل 50 مستخدم
            if i % 50 == 0 or i == total_users:
                await callback.message.edit_text(
                    f"⏳ <b>جاري إرسال الرسالة الجماعية...</b>\n\n"
                    f"👥 <b>عدد المستخدمين:</b> {total_users:,}\n"
                    f"✅ <b>تم بنجاح:</b> {success_count:,}\n"
                    f"❌ <b>فشل:</b> {fail_count:,}\n"
                    f"📊 <b>النسبة:</b> {success_count/total_users*100:.1f}%",
                    parse_mode="HTML"
                )
                
        except Exception as e:
            fail_count += 1
            logger.warning(f"Failed to send broadcast to {user_id}: {e}")
    
    # النتيجة النهائية
    await callback.message.edit_text(
        f"✅ <b>تم الانتهاء من الإرسال الجماعي</b>\n\n"
        f"👥 <b>إجمالي المستخدمين:</b> {total_users:,}\n"
        f"✅ <b>تم بنجاح:</b> {success_count:,}\n"
        f"❌ <b>فشل:</b> {fail_count:,}\n"
        f"📊 <b>نسبة النجاح:</b> {success_count/total_users*100:.1f}%\n\n"
        f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        parse_mode="HTML"
    )
    
    # تسجيل في قناة الإدمن
    from config import CHANNEL_ADMIN_LOGS
    
    try:
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"📨 <b>إرسال جماعي</b>\n\n"
            f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}\n"
            f"👥 <b>المستخدمين:</b> {total_users:,}\n"
            f"✅ <b>النجاح:</b> {success_count:,}\n"
            f"❌ <b>الفشل:</b> {fail_count:,}\n"
            f"📊 <b>النسبة:</b> {success_count/total_users*100:.1f}%\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"<b>نص الرسالة:</b>\n{message_text[:300]}...",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not log broadcast: {e}")
    
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

# ==================== الحظر وفك الحظر ====================

@router.callback_query(F.data.startswith("admin_ban_user_"))
@admin_required
async def ban_user_start(callback: CallbackQuery, state: FSMContext):
    """بدء حظر مستخدم"""
    user_id = int(callback.data.split("_")[3])
    
    await state.set_state(UserAdminStates.ban_user)
    await state.update_data(target_user_id=user_id)
    
    await callback.message.edit_text(
        f"🚫 <b>حظر مستخدم</b>\n\n"
        f"المستخدم: <code>{user_id}</code>\n\n"
        f"⬇️ <b>أدخل سبب الحظر (اختياري):</b>\n"
        f"• سيتم إرساله للمستخدم\n"
        f"• اتركه فارغًا إذا لم يكن هناك سبب\n\n"
        f"أو أرسل ❌ للإلغاء.",
        reply_markup=back_button(f"admin_view_user_{user_id}")
    )
    
    await callback.answer()

@router.message(UserAdminStates.ban_user)
async def ban_user_process(message: Message, state: FSMContext, session: AsyncSession):
    """معالجة حظر المستخدم"""
    data = await state.get_data()
    user_id = data.get("target_user_id")
    
    if not user_id:
        await message.answer("❌ جلسة منتهية")
        await state.clear()
        return
    
    reason = message.text.strip() if message.text.strip() != "❌" else ""
    
    if message.text.strip() == "❌":
        await state.clear()
        await view_user_details_by_id(message, session, user_id)
        return
    
    # تحديث حالة الحظر
    from sqlalchemy import update
    
    stmt = update(User).where(User.user_id == user_id).values(is_banned=True)
    await session.execute(stmt)
    await session.commit()
    
    # إرسال إشعار للمستخدم
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        ban_message = f"🚫 <b>تم حظر حسابك</b>\n\n"
        if reason:
            ban_message += f"<b>السبب:</b> {reason}\n\n"
        ban_message += f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        ban_message += f"📞 <b>للتواصل مع الدعم:</b> استخدم زر 'تواصل معنا'"
        
        await bot.send_message(user_id, ban_message, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Could not notify banned user {user_id}: {e}")
    
    await message.answer(
        f"✅ <b>تم حظر المستخدم بنجاح!</b>\n\n"
        f"المستخدم: <code>{user_id}</code>\n"
        f"📝 <b>السبب:</b> {reason if reason else 'غير محدد'}\n"
        f"👨‍💼 <b>بواسطة:</b> {message.from_user.id}",
        parse_mode="HTML"
    )
    
    # تسجيل في قناة الإدمن
    from config import CHANNEL_ADMIN_LOGS
    
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"🚫 <b>حظر مستخدم</b>\n\n"
            f"👤 <b>المستخدم:</b> {user_id}\n"
            f"👨‍💼 <b>بواسطة:</b> {message.from_user.id}\n"
            f"📝 <b>السبب:</b> {reason if reason else 'غير محدد'}\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not log ban to admin channel: {e}")
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_unban_user_"))
@admin_required
async def unban_user(callback: CallbackQuery, session: AsyncSession):
    """فك حظر مستخدم"""
    user_id = int(callback.data.split("_")[3])
    
    # التحقق أن المستخدم محظور
    from sqlalchemy import select
    
    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("❌ المستخدم غير موجود", show_alert=True)
        return
    
    if not user.is_banned:
        await callback.answer("✅ المستخدم غير محظور أصلاً", show_alert=True)
        return
    
    # فك الحظر
    from sqlalchemy import update
    
    stmt = update(User).where(User.user_id == user_id).values(is_banned=False)
    await session.execute(stmt)
    await session.commit()
    
    # إرسال إشعار للمستخدم
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            user_id,
            f"✅ <b>تم فك حظر حسابك</b>\n\n"
            f"يمكنك الآن استخدام البوت بشكل طبيعي.\n\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Could not notify unbanned user {user_id}: {e}")
    
    await callback.message.edit_text(
        f"✅ <b>تم فك حظر المستخدم بنجاح!</b>\n\n"
        f"المستخدم: <code>{user_id}</code>\n"
        f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}",
        parse_mode="HTML"
    )
    
    # تسجيل في قناة الإدمن
    from config import CHANNEL_ADMIN_LOGS
    
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"✅ <b>فك حظر مستخدم</b>\n\n"
            f"👤 <b>المستخدم:</b> {user_id}\n"
            f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not log unban to admin channel: {e}")
    
    await callback.answer()

# ==================== التصدير والحذف ====================

@router.callback_query(F.data.startswith("admin_export_user_"))
@admin_required
async def export_user_data_handler(callback: CallbackQuery, session: AsyncSession):
    """تصدير بيانات مستخدم"""
    user_id = int(callback.data.split("_")[3])
    
    await callback.message.edit_text(
        "⏳ <b>جاري تجهيز بيانات التصدير...</b>",
        parse_mode="HTML"
    )
    
    filepath = await export_user_data(session, user_id)
    
    if not filepath:
        await callback.message.edit_text(
            "❌ <b>خطأ في تصدير البيانات</b>",
            parse_mode="HTML"
        )
        return
    
    # إرسال الملف
    try:
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        file = FSInputFile(filepath)
        await bot.send_document(
            callback.from_user.id,
            file,
            caption=f"📤 <b>بيانات المستخدم</b>\n\nالمستخدم: <code>{user_id}</code>\nالتاريخ: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
        
        # حذف الملف المؤقت
        import os
        os.remove(filepath)
        
        await callback.message.delete()
        
    except Exception as e:
        logger.error(f"Error sending exported file: {e}")
        await callback.message.edit_text(
            f"❌ <b>خطأ في إرسال الملف:</b> {str(e)}",
            parse_mode="HTML"
        )
    
    await callback.answer()

@router.callback_query(F.data.startswith("admin_delete_user_"))
@admin_required
async def delete_user_confirmation(callback: CallbackQuery):
    """تأكيد حذف مستخدم"""
    user_id = int(callback.data.split("_")[3])
    
    await callback.message.edit_text(
        f"⚠️ <b>حذف حساب مستخدم</b>\n\n"
        f"👤 <b>المستخدم:</b> <code>{user_id}</code>\n\n"
        f"<b>هذا الإجراء سوف:</b>\n"
        f"• حذف المستخدم من قاعدة البيانات\n"
        f"• حذف جميع معاملاته\n"
        f"• حذف حسابه في Ichancy\n"
        f"• لا يمكن التراجع عنه\n\n"
        f"<b>هل أنت متأكد تمامًا؟</b>",
        reply_markup=confirmation_buttons(
            f"confirm_delete_user_{user_id}",
            f"admin_view_user_{user_id}"
        ),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_user_"))
@admin_required
async def delete_user_execute(callback: CallbackQuery, session: AsyncSession):
    """تنفيذ حذف المستخدم"""
    user_id = int(callback.data.split("_")[3])
    
    try:
        # بداية معاملة
        async with session.begin():
            # حذف معاملات المستخدم
            from sqlalchemy import delete
            from database.models import Transaction, IchancyAccount, Referral, GiftCodeUsage
            
            await session.execute(delete(Transaction).where(Transaction.user_id == user_id))
            await session.execute(delete(IchancyAccount).where(IchancyAccount.user_id == user_id))
            await session.execute(delete(Referral).where(Referral.referrer_id == user_id))
            await session.execute(delete(Referral).where(Referral.referred_id == user_id))
            await session.execute(delete(GiftCodeUsage).where(GiftCodeUsage.user_id == user_id))
            
            # حذف المستخدم نفسه
            await session.execute(delete(User).where(User.user_id == user_id))
        
        # تنظيف الكاش
        await cache.delete(f"user:{user_id}")
        
        await callback.message.edit_text(
            f"✅ <b>تم حذف المستخدم بنجاح!</b>\n\n"
            f"👤 <b>المستخدم:</b> <code>{user_id}</code>\n"
            f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
        
        # تسجيل في قناة الإدمن
        from config import CHANNEL_ADMIN_LOGS
        
        try:
            from core.bot import bot_manager
            bot = await bot_manager.bot
            
            await bot.send_message(
                CHANNEL_ADMIN_LOGS,
                f"🗑️ <b>حذف مستخدم</b>\n\n"
                f"👤 <b>المستخدم:</b> {user_id}\n"
                f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}\n"
                f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not log deletion to admin channel: {e}")
        
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        await callback.message.edit_text(
            f"❌ <b>خطأ في حذف المستخدم!</b>\n\n"
            f"الخطأ: {str(e)}",
            parse_mode="HTML"
        )
    
    await callback.answer()

# ==================== التصفير الجماعي ====================

@router.callback_query(F.data == "admin_reset_all_balances")
@admin_required
async def reset_all_balances_confirmation(callback: CallbackQuery):
    """تأكيد تصفير جميع الأرصدة"""
    await callback.message.edit_text(
        "⚠️ <b>تصفير جميع أرصدة المستخدمين</b>\n\n"
        "<b>هذا الإجراء سوف:</b>\n"
        "• وضع جميع أرصدة المستخدمين على 0\n"
        "• لا يحذف المستخدمين\n"
        "• لا يؤثر على المعاملات المسجلة\n"
        "• لا يمكن التراجع عنه\n\n"
        "<b>هل أنت متأكد تمامًا؟</b>\n"
        "<i>هذا الإجراء قد يستغرق بعض الوقت...</i>",
        reply_markup=confirmation_buttons(
            "confirm_reset_all_balances",
            "admin_users"
        ),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "confirm_reset_all_balances")
@admin_required
async def reset_all_balances_execute(callback: CallbackQuery, session: AsyncSession):
    """تنفيذ تصفير جميع الأرصدة"""
    await callback.message.edit_text(
        "⏳ <b>جاري تصفير جميع الأرصدة...</b>\n\n"
        "هذه العملية قد تستغرق دقيقة.",
        parse_mode="HTML"
    )
    
    try:
        # جلب جميع المستخدمين
        from sqlalchemy import select
        
        stmt = select(User.user_id, User.balance).where(User.balance > 0)
        result = await session.execute(stmt)
        users = result.all()
        
        total_users = len(users)
        total_amount = sum(balance for _, balance in users)
        
        if total_users == 0:
            await callback.message.edit_text(
                "✅ <b>لا توجد أرصدة لتصفيرها</b>\n\n"
                "جميع المستخدمين لديهم رصيد 0.",
                parse_mode="HTML"
            )
            return
        
        # تصفير الأرصدة
        from sqlalchemy import update
        
        reset_stmt = update(User).values(balance=0)
        await session.execute(reset_stmt)
        await session.commit()
        
        # تنظيف الكاش
        for user_id, _ in users:
            await cache.delete(f"user:{user_id}")
        
        await callback.message.edit_text(
            f"✅ <b>تم تصفير جميع الأرصدة بنجاح!</b>\n\n"
            f"👥 <b>عدد المستخدمين المتأثرين:</b> {total_users:,}\n"
            f"💰 <b>إجمالي المبالغ المصفرة:</b> {total_amount:,} ليرة\n"
            f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}\n"
            f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
        
        # تسجيل في قناة الإدمن
        from config import CHANNEL_ADMIN_LOGS
        
        try:
            from core.bot import bot_manager
            bot = await bot_manager.bot
            
            await bot.send_message(
                CHANNEL_ADMIN_LOGS,
                f"🔄 <b>تصفير جميع الأرصدة</b>\n\n"
                f"👥 <b>المستخدمين المتأثرين:</b> {total_users:,}\n"
                f"💰 <b>المبالغ المصفرة:</b> {total_amount:,} ليرة\n"
                f"👨‍💼 <b>بواسطة:</b> {callback.from_user.id}\n"
                f"🕒 <b>الوقت:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not log reset to admin channel: {e}")
        
    except Exception as e:
        logger.error(f"Error resetting all balances: {e}")
        await callback.message.edit_text(
            f"❌ <b>خطأ في تصفير الأرصدة!</b>\n\n"
            f"الخطأ: {str(e)}",
            parse_mode="HTML"
        )
    
    await callback.answer()