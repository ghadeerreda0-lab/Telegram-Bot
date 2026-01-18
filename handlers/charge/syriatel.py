 from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
import datetime

from keyboards.main import back_button, confirmation_buttons
from core.redis_cache import set_user_state, get_user_state
from core.bot import logger
from database.crud.syriatel_codes import SyriatelCodeCRUD
from database.crud.transactions import TransactionCRUD
from config import SYRIATEL_CODE_LIMIT, CHANNEL_ADMIN_LOGS

router = Router()

class SyriatelAdminStates(StatesGroup):
    """حالات إدارة أكواد سيرياتيل"""
    add_code = State()
    delete_code = State()
    toggle_code = State()
    view_stats = State()

# ==================== أدوات مساعدة ====================

async def send_code_alert_to_admin(bot, message: str):
    """إرسال تنبيه للإدمن حول الأكواد"""
    try:
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"⚠️ <b>سيرياتيل كاش - تنبيه</b>\n\n{message}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")

async def get_syriatel_stats(session: AsyncSession) -> Dict[str, Any]:
    """جلب إحصائيات الأكواد"""
    syriatel_crud = SyriatelCodeCRUD(session)
    return await syriatel_crud.get_code_stats()

# ==================== معالجة طلبات الشحن بسيرياتيل ====================

@router.callback_query(F.data == "syriatel_info")
async def show_syriatel_info(callback: CallbackQuery, session: AsyncSession):
    """عرض معلومات نظام سيرياتيل كاش"""
    stats = await get_syriatel_stats(session)
    
    info_text = f"""
<b>ℹ️ نظام سيرياتيل كاش</b>

📊 <b>الإحصائيات:</b>
• إجمالي الأكواد: {stats['total_codes']}
• الأكواد النشطة: {stats['active_codes']}
• الأكواد الممتلئة: {stats['full_codes']}
• متوسط الامتلاء: {stats['avg_usage_percent']:.1f}%
• السعة المستخدمة: {stats['total_used']:,} / {stats['total_capacity']:,}

⚙️ <b>معلومات النظام:</b>
• الحد الأقصى لكل كود: {SYRIATEL_CODE_LIMIT:,} ليرة
• التصفير التلقائي: يوميًا
• البحث التلقائي عن الكود المناسب

🔧 <b>للاستخدام:</b>
1. اختر "شحن رصيد"
2. اختر "سيرياتيل كاش"
3. أدخل المبلغ
4. سيعطيك البوت الكود المناسب تلقائيًا
"""
    
    await callback.message.edit_text(
        info_text,
        reply_markup=back_button("charge_main"),
        parse_mode="HTML"
    )
    
    await callback.answer()

# ==================== إدارة الأكواد (للأدمن) ====================

@router.callback_query(F.data == "admin_syriatel_codes")
async def admin_syriatel_menu(callback: CallbackQuery, session: AsyncSession):
    """قائمة إدارة أكواد سيرياتيل للأدمن"""
    from config import ADMIN_ID
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ صلاحيات غير كافية", show_alert=True)
        return
    
    stats = await get_syriatel_stats(session)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="📝 إضافة كود جديد", callback_data="syriatel_add_code")
    builder.button(text="🗑️ حذف كود", callback_data="syriatel_delete_code")
    builder.button(text="🔁 تفعيل/تعطيل كود", callback_data="syriatel_toggle_code")
    builder.button(text="📊 عرض الإحصائيات", callback_data="syriatel_view_stats")
    builder.button(text="🔄 عرض جميع الأكواد", callback_data="syriatel_list_codes")
    builder.button(text="🧹 تصفير الأكواد يدويًا", callback_data="syriatel_reset_codes")
    builder.button(text="⬅️ رجوع", callback_data="admin_payments")
    
    builder.adjust(2, 2, 2, 1)
    
    menu_text = f"""
<b>🎛 إدارة أكواد سيرياتيل كاش</b>

📈 <b>الإحصائيات الحالية:</b>
• الأكواد: {stats['total_codes']} (نشطة: {stats['active_codes']})
• الممتلئة: {stats['full_codes']}
• السعة: {stats['total_used']:,} / {stats['total_capacity']:,}
• الامتلاء: {stats['avg_usage_percent']:.1f}%

🔧 <b>اختر الإجراء المطلوب:</b>
"""
    
    await callback.message.edit_text(
        menu_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "syriatel_add_code")
async def add_syriatel_code_start(callback: CallbackQuery, state: FSMContext):
    """بدء إضافة كود سيرياتيل"""
    from config import ADMIN_ID
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ صلاحيات غير كافية", show_alert=True)
        return
    
    await state.set_state(SyriatelAdminStates.add_code)
    
    await callback.message.edit_text(
        "<b>📝 إضافة كود سيرياتيل جديد</b>\n\n"
        "⬇️ <b>أدخل رقم الكود (رقم الهاتف):</b>\n"
        "• يجب أن يبدأ بـ 099\n"
        "• 10 أرقام\n"
        "• مثال: 0993123456\n\n"
        "أو أرسل ❌ لإلغاء العملية.",
        reply_markup=back_button("admin_syriatel_codes")
    )
    
    await callback.answer()

@router.message(SyriatelAdminStates.add_code)
async def add_syriatel_code_process(message: Message, state: FSMContext, session: AsyncSession):
    """معالجة إضافة كود سيرياتيل"""
    from config import ADMIN_ID
    
    if message.from_user.id != ADMIN_ID:
        return
    
    code = message.text.strip()
    
    # التحقق من صحة الرقم
    if code == "❌":
        await state.clear()
        await admin_syriatel_menu(message, session)
        return
    
    if not code.startswith("099") or len(code) != 10 or not code.isdigit():
        await message.answer(
            "❌ <b>رقم غير صالح!</b>\n"
            "يجب أن يبدأ بـ 099 ويتكون من 10 أرقام.\n"
            "⬇️ أعد إدخال الرقم:",
            parse_mode="HTML"
        )
        return
    
    # التحقق من عدم تكرار الرقم
    syriatel_crud = SyriatelCodeCRUD(session)
    
    # البحث عن الكود الموجود
    from sqlalchemy import select
    from database.models import SyriatelCode
    
    stmt = select(SyriatelCode).where(SyriatelCode.code == code)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        status = "نشط" if existing.is_active else "معطل"
        await message.answer(
            f"⚠️ <b>الكود موجود مسبقًا!</b>\n\n"
            f"الكود: {code}\n"
            f"الحالة: {status}\n"
            f"المبلغ الحالي: {existing.current_amount:,}\n"
            f"آخر استخدام: {existing.last_used or 'لم يستخدم'}\n\n"
            f"هل تريد تفعيله إذا كان معطلًا؟",
            reply_markup=confirmation_buttons(
                f"syriatel_activate_{existing.id}",
                "admin_syriatel_codes"
            ),
            parse_mode="HTML"
        )
        return
    
    try:
        # إضافة الكود الجديد
        new_code = await syriatel_crud.add_code(code)
        
        await message.answer(
            f"✅ <b>تم إضافة الكود بنجاح!</b>\n\n"
            f"الكود: {new_code.code}\n"
            f"الحد الأقصى: {new_code.max_amount:,} ليرة\n"
            f"الحالة: نشط ✓\n"
            f"التصفير اليومي: مفعل ✓\n\n"
            f"تمت الإضافة في: {new_code.created_at.strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
        
        # إشعار في قناة الإدمن
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"✅ <b>تم إضافة كود سيرياتيل جديد</b>\n\n"
            f"الكود: {new_code.code}\n"
            f"بواسطة: {message.from_user.id}\n"
            f"الوقت: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error adding syriatel code: {e}")
        await message.answer(
            f"❌ <b>خطأ في إضافة الكود!</b>\n\n"
            f"الخطأ: {str(e)}",
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("syriatel_activate_"))
async def activate_existing_code(callback: CallbackQuery, session: AsyncSession):
    """تفعيل كود موجود"""
    from config import ADMIN_ID
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ صلاحيات غير كافية", show_alert=True)
        return
    
    code_id = int(callback.data.split("_")[2])
    
    from sqlalchemy import update
    from database.models import SyriatelCode
    
    stmt = update(SyriatelCode).where(
        SyriatelCode.id == code_id
    ).values(is_active=True)
    
    await session.execute(stmt)
    await session.commit()
    
    await callback.message.edit_text(
        "✅ <b>تم تفعيل الكود بنجاح!</b>\n\n"
        "يمكن الآن استخدامه في عمليات الشحن.",
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "syriatel_list_codes")
async def list_all_syriatel_codes(callback: CallbackQuery, session: AsyncSession):
    """عرض جميع أكواد سيرياتيل"""
    from config import ADMIN_ID
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ صلاحيات غير كافية", show_alert=True)
        return
    
    from sqlalchemy import select
    from database.models import SyriatelCode
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    # جلب الأكواد مع ترتيب
    stmt = select(SyriatelCode).order_by(
        SyriatelCode.is_active.desc(),
        SyriatelCode.current_amount.asc()
    ).limit(50)  # حد 50 كود في الصفحة
    
    result = await session.execute(stmt)
    codes = result.scalars().all()
    
    if not codes:
        await callback.message.edit_text(
            "📭 <b>لا توجد أكواد مسجلة!</b>\n\n"
            "استخدم زر 'إضافة كود جديد' لإضافة أول كود.",
            reply_markup=back_button("admin_syriatel_codes"),
            parse_mode="HTML"
        )
        return
    
    # تجميع النص
    lines = []
    for code in codes:
        status = "🟢" if code.is_active else "🔴"
        percent = (code.current_amount / code.max_amount * 100) if code.max_amount > 0 else 0
        bars = "█" * int(percent / 10)
        
        lines.append(
            f"{status} <code>{code.code}</code>\n"
            f"   ↳ {code.current_amount:,}/{code.max_amount:,} ليرة\n"
            f"   ↳ {percent:.1f}% {bars}\n"
            f"   ↳ آخر استخدام: {code.last_used.strftime('%H:%M') if code.last_used else '---'}\n"
        )
    
    # لوحة المفاتيح للتحكم
    builder = InlineKeyboardBuilder()
    
    for code in codes[:10]:  # أزرار لأول 10 أكواد
        builder.button(
            text=f"{'✅' if code.is_active else '❌'} {code.code[:6]}...",
            callback_data=f"syriatel_code_{code.id}"
        )
    
    builder.button(text="⬅️ رجوع", callback_data="admin_syriatel_codes")
    builder.adjust(3, 3, 3, 1)
    
    await callback.message.edit_text(
        f"📋 <b>قائمة أكواد سيرياتيل</b>\n\n" + "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data.startswith("syriatel_code_"))
async def manage_single_code(callback: CallbackQuery, session: AsyncSession):
    """إدارة كود فردي"""
    from config import ADMIN_ID
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ صلاحيات غير كافية", show_alert=True)
        return
    
    code_id = int(callback.data.split("_")[2])
    
    from sqlalchemy import select
    from database.models import SyriatelCode
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    stmt = select(SyriatelCode).where(SyriatelCode.id == code_id)
    result = await session.execute(stmt)
    code = result.scalar_one_or_none()
    
    if not code:
        await callback.answer("❌ الكود غير موجود", show_alert=True)
        return
    
    percent = (code.current_amount / code.max_amount * 100) if code.max_amount > 0 else 0
    bars = "█" * int(percent / 10)
    
    # تفاصيل الكود
    code_info = f"""
<b>📱 كود سيرياتيل</b>

<code>{code.code}</code>

📊 <b>الحالة:</b> {'🟢 نشط' if code.is_active else '🔴 معطل'}
💰 <b>المبلغ الحالي:</b> {code.current_amount:,} ليرة
🎯 <b>الحد الأقصى:</b> {code.max_amount:,} ليرة
📈 <b>نسبة الامتلاء:</b> {percent:.1f}%
{bars} ({code.current_amount:,}/{code.max_amount:,})

🔄 <b>التصفير اليومي:</b> {'مفعل ✓' if code.daily_reset else 'معطل ✗'}
⏰ <b>آخر استخدام:</b> {code.last_used.strftime('%Y-%m-%d %H:%M') if code.last_used else 'لم يستخدم'}
📅 <b>تاريخ الإضافة:</b> {code.created_at.strftime('%Y-%m-%d')}
"""
    
    # أزرار التحكم
    builder = InlineKeyboardBuilder()
    
    if code.is_active:
        builder.button(text="⏸️ تعطيل الكود", callback_data=f"syriatel_disable_{code.id}")
    else:
        builder.button(text="▶️ تفعيل الكود", callback_data=f"syriatel_enable_{code.id}")
    
    builder.button(text="🗑️ حذف الكود", callback_data=f"syriatel_remove_{code.id}")
    builder.button(text="🔄 تصفير الكود", callback_data=f"syriatel_zero_{code.id}")
    builder.button(text="📝 تعديل الحد", callback_data=f"syriatel_edit_{code.id}")
    builder.button(text="⬅️ رجوع للقائمة", callback_data="syriatel_list_codes")
    
    builder.adjust(2, 2, 1, 1)
    
    await callback.message.edit_text(
        code_info,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "syriatel_reset_codes")
async def reset_syriatel_codes(callback: CallbackQuery, session: AsyncSession):
    """تصفير جميع الأكواد يدويًا"""
    from config import ADMIN_ID
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ صلاحيات غير كافية", show_alert=True)
        return
    
    # تأكيد العملية
    await callback.message.edit_text(
        "⚠️ <b>تصفير جميع أكواد سيرياتيل</b>\n\n"
        "هذا الإجراء سوف:\n"
        "• يضع جميع الأكواد على 0 ليرة\n"
        "• لا يحذف الأكواد\n"
        "• يؤثر على الأكواد النشطة فقط\n\n"
        "<b>هل أنت متأكد؟</b>",
        reply_markup=confirmation_buttons(
            "confirm_syriatel_reset",
            "admin_syriatel_codes"
        ),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "confirm_syriatel_reset")
async def confirm_reset_syriatel_codes(callback: CallbackQuery, session: AsyncSession):
    """تأكيد تصفير الأكواد"""
    from config import ADMIN_ID
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ صلاحيات غير كافية", show_alert=True)
        return
    
    try:
        syriatel_crud = SyriatelCodeCRUD(session)
        await syriatel_crud.reset_daily_codes()
        
        # إشعار في قناة الإدمن
        from core.bot import bot_manager
        bot = await bot_manager.bot
        
        await bot.send_message(
            CHANNEL_ADMIN_LOGS,
            f"🔄 <b>تم تصفير أكواد سيرياتيل</b>\n\n"
            f"بواسطة: {callback.from_user.id}\n"
            f"الوقت: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
        
        await callback.message.edit_text(
            "✅ <b>تم تصفير جميع أكواد سيرياتيل بنجاح!</b>\n\n"
            "جميع الأكواد الآن جاهزة للاستخدام من جديد.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error resetting syriatel codes: {e}")
        await callback.message.edit_text(
            f"❌ <b>خطأ في تصفير الأكواد!</b>\n\n"
            f"الخطأ: {str(e)}",
            parse_mode="HTML"
        )
    
    await callback.answer()