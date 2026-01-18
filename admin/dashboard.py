from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime, timedelta
import json

from keyboards.main import admin_panel_keyboard, back_button
from core.bot import logger
from database.models import User, Transaction, SyriatelCode, IchancyAccount, Referral
from config import ADMIN_ID

router = Router()

def admin_required(func):
    """مصادقة أن المستخدم هو أدمن"""
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

@router.callback_query(F.data == "admin_panel")
@admin_required
async def admin_dashboard(callback: CallbackQuery, session: AsyncSession):
    """لوحة التحكم الرئيسية"""
    # جلب الإحصائيات السريعة
    stats = await get_quick_stats(session)
    
    dashboard_text = f"""
<b>🎛 لوحة تحكم الأدمن</b>

📊 <b>الإحصائيات الحالية:</b>

👥 <b>المستخدمين:</b> {stats['total_users']:,}
💰 <b>إجمالي الأرصدة:</b> {stats['total_balance']:,} ليرة
📥 <b>طلبات الشحن المعلقة:</b> {stats['pending_charge']:,}
📤 <b>طلبات السحب المعلقة:</b> {stats['pending_withdraw']:,}

📈 <b>اليوم ({stats['today']}):</b>
• الشحن: {stats['today_charge']:,} ليرة
• السحب: {stats['today_withdraw']:,} ليرة
• المعاملات: {stats['today_transactions']:,}

🔧 <b>اختر القسم للإدارة:</b>
"""
    
    await callback.message.edit_text(
        dashboard_text,
        reply_markup=admin_panel_keyboard(),
        parse_mode="HTML"
    )
    
    await callback.answer()

async def get_quick_stats(session: AsyncSession) -> dict:
    """جلب إحصائيات سريعة"""
    # إجمالي المستخدمين
    users_stmt = select(func.count(User.user_id))
    users_result = await session.execute(users_stmt)
    total_users = users_result.scalar() or 0
    
    # إجمالي الأرصدة
    balance_stmt = select(func.sum(User.balance))
    balance_result = await session.execute(balance_stmt)
    total_balance = balance_result.scalar() or 0
    
    # الطلبات المعلقة
    pending_charge_stmt = select(func.count(Transaction.id)).where(
        Transaction.type == "charge",
        Transaction.status == "pending"
    )
    pending_charge_result = await session.execute(pending_charge_stmt)
    pending_charge = pending_charge_result.scalar() or 0
    
    pending_withdraw_stmt = select(func.count(Transaction.id)).where(
        Transaction.type == "withdraw",
        Transaction.status == "pending"
    )
    pending_withdraw_result = await session.execute(pending_withdraw_stmt)
    pending_withdraw = pending_withdraw_result.scalar() or 0
    
    # إحصائيات اليوم
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    today_charge_stmt = select(func.sum(Transaction.amount)).where(
        Transaction.type == "charge",
        Transaction.status == "approved",
        Transaction.created_at.between(today_start, today_end)
    )
    today_charge_result = await session.execute(today_charge_stmt)
    today_charge = today_charge_result.scalar() or 0
    
    today_withdraw_stmt = select(func.sum(Transaction.amount)).where(
        Transaction.type == "withdraw",
        Transaction.status == "approved",
        Transaction.created_at.between(today_start, today_end)
    )
    today_withdraw_result = await session.execute(today_withdraw_stmt)
    today_withdraw = today_withdraw_result.scalar() or 0
    
    today_transactions_stmt = select(func.count(Transaction.id)).where(
        Transaction.created_at.between(today_start, today_end)
    )
    today_transactions_result = await session.execute(today_transactions_stmt)
    today_transactions = today_transactions_result.scalar() or 0
    
    return {
        "total_users": total_users,
        "total_balance": total_balance,
        "pending_charge": pending_charge,
        "pending_withdraw": pending_withdraw,
        "today": today.strftime("%Y-%m-%d"),
        "today_charge": today_charge,
        "today_withdraw": today_withdraw,
        "today_transactions": today_transactions
    }

@router.callback_query(F.data == "admin_stats")
@admin_required
async def detailed_stats(callback: CallbackQuery, session: AsyncSession):
    """إحصائيات مفصلة"""
    # إحصائيات المستخدمين
    users_stmt = select(
        func.count(User.user_id).label("total"),
        func.count(User.user_id).filter(User.is_banned == True).label("banned"),
        func.sum(User.balance).label("total_balance"),
        func.avg(User.balance).label("avg_balance")
    )
    users_result = await session.execute(users_stmt)
    users_stats = users_result.first()
    
    # إحصائيات المعاملات
    tx_stmt = select(
        Transaction.type,
        func.count(Transaction.id).label("count"),
        func.sum(Transaction.amount).label("total")
    ).group_by(Transaction.type)
    
    tx_result = await session.execute(tx_stmt)
    tx_stats = {row[0]: {"count": row[1], "total": row[2] or 0} for row in tx_result}
    
    # إحصائيات الشهر
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    month_charge_stmt = select(func.sum(Transaction.amount)).where(
        Transaction.type == "charge",
        Transaction.status == "approved",
        Transaction.created_at >= month_start
    )
    month_charge_result = await session.execute(month_charge_stmt)
    month_charge = month_charge_result.scalar() or 0
    
    month_withdraw_stmt = select(func.sum(Transaction.amount)).where(
        Transaction.type == "withdraw",
        Transaction.status == "approved",
        Transaction.created_at >= month_start
    )
    month_withdraw_result = await session.execute(month_withdraw_stmt)
    month_withdraw = month_withdraw_result.scalar() or 0
    
    # أكثر المستخدمين رصيدًا
    top_users_stmt = select(User.user_id, User.balance).order_by(
        User.balance.desc()
    ).limit(10)
    
    top_users_result = await session.execute(top_users_stmt)
    top_users = list(top_users_result)
    
    # تجميع النص
    stats_text = f"""
<b>📊 إحصائيات مفصلة</b>

<b>👥 المستخدمين:</b>
• الإجمالي: {users_stats.total:,}
• المحظورين: {users_stats.banned:,}
• إجمالي الأرصدة: {users_stats.total_balance or 0:,} ليرة
• متوسط الرصيد: {int(users_stats.avg_balance or 0):,} ليرة

<b>📈 المعاملات:</b>
"""
    
    # إضافة إحصائيات كل نوع
    for tx_type, data in tx_stats.items():
        arabic_type = {
            "charge": "الشحن",
            "withdraw": "السحب",
            "gift": "الهدايا",
            "bonus": "البونص"
        }.get(tx_type, tx_type)
        
        stats_text += f"• {arabic_type}: {data['count']:,} معاملة ({data['total']:,} ليرة)\n"
    
    stats_text += f"""
<b>📅 هذا الشهر (من {month_start.strftime('%Y-%m-%d')}):</b>
• إجمالي الشحن: {month_charge:,} ليرة
• إجمالي السحب: {month_withdraw:,} ليرة
• صافي الربح: {month_charge - month_withdraw:,} ليرة

<b>🏆 أعلى 10 أرصدة:</b>
"""
    
    # إضافة أعلى المستخدمين
    for i, (user_id, balance) in enumerate(top_users, 1):
        stats_text += f"{i}. <code>{user_id}</code> - {balance:,} ليرة\n"
    
    stats_text += "\n<b>🔄 آخر تحديث:</b> " + datetime.now().strftime("%Y-%m-%d %H:%M")
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 تحديث", callback_data="admin_stats")
    builder.button(text="📤 تصدير كـ JSON", callback_data="export_stats_json")
    builder.button(text="⬅️ رجوع", callback_data="admin_panel")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "export_stats_json")
@admin_required
async def export_stats_json(callback: CallbackQuery, session: AsyncSession):
    """تصدير الإحصائيات كـ JSON"""
    stats = await get_quick_stats(session)
    
    # إضافة وقت التصدير
    stats["export_time"] = datetime.now().isoformat()
    stats["exported_by"] = callback.from_user.id
    
    # تحويل لـ JSON
    stats_json = json.dumps(stats, ensure_ascii=False, indent=2)
    
    # تقطيع إذا كان طويلاً
    if len(stats_json) > 4000:
        stats_json = json.dumps({"error": "البيانات طويلة جدًا، استخدم النسخة الكاملة"}, ensure_ascii=False)
    
    await callback.message.answer(
        f"<b>📤 إحصائيات البوت (JSON)</b>\n\n"
        f"<code>{stats_json}</code>",
        parse_mode="HTML"
    )
    
    await callback.answer("✅ تم إرسال الإحصائيات")

@router.callback_query(F.data == "admin_users")
@admin_required
async def admin_users_menu(callback: CallbackQuery):
    """قائمة إدارة المستخدمين"""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🔍 بحث عن مستخدم", callback_data="admin_search_user")
    builder.button(text="📋 قائمة المستخدمين", callback_data="admin_list_users")
    builder.button(text="💰 تعديل رصيد", callback_data="admin_edit_balance")
    builder.button(text="📊 أعلى الرصيد", callback_data="admin_top_balance")
    builder.button(text="🚫 حظر مستخدم", callback_data="admin_ban_user")
    builder.button(text="✅ فك حظر", callback_data="admin_unban_user")
    builder.button(text="📨 رسالة جماعية", callback_data="admin_broadcast")
    builder.button(text="🧹 تصفير جميع الأرصدة", callback_data="admin_reset_all_balances")
    builder.button(text="⬅️ رجوع", callback_data="admin_panel")
    
    builder.adjust(2, 2, 2, 2, 1)
    
    await callback.message.edit_text(
        "<b>👥 إدارة المستخدمين</b>\n\n"
        "🔧 <b>اختر الإجراء المطلوب:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "admin_payments")
@admin_required
async def admin_payments_menu(callback: CallbackQuery, session: AsyncSession):
    """قائمة إدارة الدفع"""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    # جلب عدد الطلبات المعلقة لكل طريقة
    pending_stmt = select(
        Transaction.payment_method,
        func.count(Transaction.id).label("count")
    ).where(
        Transaction.type == "charge",
        Transaction.status == "pending"
    ).group_by(Transaction.payment_method)
    
    pending_result = await session.execute(pending_stmt)
    pending_counts = {row[0]: row[1] for row in pending_result}
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="📋 طلبات الشحن المعلقة", callback_data="admin_pending_charges")
    builder.button(text="🔄 جميع طلبات الشحن", callback_data="admin_all_charges")
    builder.button(text="⚙️ إعدادات الدفع", callback_data="admin_payment_settings")
    builder.button(text="💰 سيرياتيل كاش", callback_data="admin_syriatel_codes")
    builder.button(text="🎁 نظام البونص", callback_data="admin_bonus_system")
    builder.button(text="➕ إضافة طريقة دفع", callback_data="admin_add_payment_method")
    builder.button(text="⬅️ رجوع", callback_data="admin_panel")
    
    builder.adjust(2, 2, 2, 1)
    
    # بناء نص الطلبات المعلقة
    pending_text = ""
    for method, count in pending_counts.items():
        pending_text += f"• {method}: {count} طلب\n"
    
    if not pending_text:
        pending_text = "• لا توجد طلبات معلقة\n"
    
    menu_text = f"""
<b>💳 إدارة نظام الدفع</b>

📥 <b>طلبات الشحن المعلقة:</b>
{pending_text}

🔧 <b>اختر القسم للإدارة:</b>
"""
    
    await callback.message.edit_text(
        menu_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "admin_pending_charges")
@admin_required
async def admin_pending_charges(callback: CallbackQuery, session: AsyncSession):
    """عرض طلبات الشحن المعلقة"""
    from database.crud.transactions import TransactionCRUD
    from keyboards.main import admin_transaction_buttons
    
    tx_crud = TransactionCRUD(session)
    pending_txs = await tx_crud.get_pending_transactions(type_="charge", limit=20)
    
    if not pending_txs:
        await callback.message.edit_text(
            "✅ <b>لا توجد طلبات شحن معلقة حالياً</b>",
            reply_markup=back_button("admin_payments"),
            parse_mode="HTML"
        )
        return
    
    # عرض أول طلب مع أزرار التحكم
    first_tx = pending_txs[0]
    
    tx_text = f"""
<b>📥 طلبات الشحن المعلقة ({len(pending_txs)})</b>

<b>الطلب الحالي ({1}/{len(pending_txs)}):</b>
🔢 <b>رقم المعاملة:</b> {first_tx.id}
💰 <b>المبلغ:</b> {first_tx.amount:,} ليرة
💳 <b>الطريقة:</b> {first_tx.payment_method}
🔑 <b>رقم العملية:</b> {first_tx.transaction_id}
👤 <b>المستخدم:</b> {first_tx.user_id}
🕒 <b>الوقت:</b> {first_tx.created_at.strftime('%Y-%m-%d %H:%M')}
📝 <b>الحالة:</b> {first_tx.status}
"""
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    # أزرار التحكم بالمعاملة الحالية
    builder.button(text="✅ قبول", callback_data=f"approve_{first_tx.id}")
    builder.button(text="❌ رفض", callback_data=f"reject_{first_tx.id}")
    builder.button(text="🔁 إعادة التحقق", callback_data=f"reverify_{first_tx.id}")
    
    # أزرار التنقل
    if len(pending_txs) > 1:
        builder.button(text="➡️ التالي", callback_data=f"admin_pending_next_{first_tx.id}")
    
    builder.button(text="🔄 تحديث", callback_data="admin_pending_charges")
    builder.button(text="⬅️ رجوع", callback_data="admin_payments")
    
    builder.adjust(3, 1, 1, 1)
    
    await callback.message.edit_text(
        tx_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data.startswith("admin_pending_next_"))
@admin_required
async def admin_pending_next(callback: CallbackQuery, session: AsyncSession):
    """الانتقال للطلب التالي"""
    current_id = int(callback.data.split("_")[3])
    
    from database.crud.transactions import TransactionCRUD
    
    tx_crud = TransactionCRUD(session)
    pending_txs = await tx_crud.get_pending_transactions(type_="charge", limit=20)
    
    if not pending_txs:
        await callback.answer("❌ لا توجد طلبات", show_alert=True)
        return
    
    # البحث عن الموضع الحالي
    current_index = next((i for i, tx in enumerate(pending_txs) if tx.id == current_id), -1)
    
    if current_index == -1 or current_index + 1 >= len(pending_txs):
        await callback.answer("❌ لا يوجد طلب تالي", show_alert=True)
        return
    
    # الطلب التالي
    next_tx = pending_txs[current_index + 1]
    
    tx_text = f"""
<b>📥 طلبات الشحن المعلقة ({len(pending_txs)})</b>

<b>الطلب الحالي ({current_index + 2}/{len(pending_txs)}):</b>
🔢 <b>رقم المعاملة:</b> {next_tx.id}
💰 <b>المبلغ:</b> {next_tx.amount:,} ليرة
💳 <b>الطريقة:</b> {next_tx.payment_method}
🔑 <b>رقم العملية:</b> {next_tx.transaction_id}
👤 <b>المستخدم:</b> {next_tx.user_id}
🕒 <b>الوقت:</b> {next_tx.created_at.strftime('%Y-%m-%d %H:%M')}
📝 <b>الحالة:</b> {next_tx.status}
"""
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    # أزرار التحكم
    builder.button(text="✅ قبول", callback_data=f"approve_{next_tx.id}")
    builder.button(text="❌ رفض", callback_data=f"reject_{next_tx.id}")
    builder.button(text="🔁 إعادة التحقق", callback_data=f"reverify_{next_tx.id}")
    
    # أزرار التنقل
    builder.button(text="⬅️ السابق", callback_data=f"admin_pending_prev_{next_tx.id}")
    
    if current_index + 2 < len(pending_txs):
        builder.button(text="➡️ التالي", callback_data=f"admin_pending_next_{next_tx.id}")
    
    builder.button(text="🔄 تحديث", callback_data="admin_pending_charges")
    builder.button(text="⬅️ رجوع", callback_data="admin_payments")
    
    builder.adjust(3, 2, 1, 1)
    
    await callback.message.edit_text(
        tx_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()