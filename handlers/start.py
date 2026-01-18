from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database.crud.users import UserCRUD
from database.crud.transactions import TransactionCRUD
from keyboards.main import main_menu, back_button
from core.bot import logger
from core.redis_cache import delete_user_state
import html

router = Router()

class UserStates(StatesGroup):
    """حالات المستخدم العامة"""
    waiting_for_amount = State()
    waiting_for_transaction_id = State()
    waiting_for_account = State()
    waiting_for_gift_code = State()
    waiting_for_message = State()

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext):
    """بدء البوت"""
    user_id = message.from_user.id
    
    # مسح الحالة السابقة
    await state.clear()
    await delete_user_state(user_id)
    
    # التحقق من وجود المستخدم أو إنشاؤه
    user_crud = UserCRUD(session)
    user = await user_crud.get_user(user_id)
    
    if not user:
        user = await user_crud.create_user(user_id)
        welcome_msg = "🎉 أهلاً وسهلاً بك في البوت!\n\n"
    else:
        welcome_msg = "👋 أهلاً بك مجدداً!\n\n"
    
    # عرض الرصيد
    balance_msg = f"💰 <b>رصيدك الحالي:</b> {user.balance:,} ليرة سورية"
    
    # إرسال الرسالة مع القائمة
    await message.answer(
        f"{welcome_msg}{balance_msg}",
        reply_markup=main_menu(user_id),
        parse_mode="HTML"
    )
    
    logger.info(f"User {user_id} started the bot")

@router.message(Command("balance"))
async def cmd_balance(message: Message, session: AsyncSession):
    """عرض الرصيد"""
    user_id = message.from_user.id
    user_crud = UserCRUD(session)
    user = await user_crud.get_user(user_id)
    
    if user:
        balance_msg = f"💰 <b>رصيدك الحالي:</b> {user.balance:,} ليرة سورية"
    else:
        balance_msg = "⚠️ لم يتم العثور على حسابك. استخدم /start للبدء"
    
    await message.answer(balance_msg, parse_mode="HTML")

@router.message(Command("help"))
async def cmd_help(message: Message):
    """مساعدة"""
    help_text = """
<b>🎮 أوامر البوت:</b>

/start - بدء البوت والقائمة الرئيسية
/balance - عرض رصيدك
/help - عرض هذه الرسالة

<b>📞 للدعم:</b>
- استخدام زر "تواصل معنا"
- أو إرسال رسالة مباشرة

<b>⚠️ ملاحظات:</b>
- لا تشارك معلوماتك مع أحد
- تأكد من صحة العمليات قبل التأكيد
"""
    await message.answer(help_text, parse_mode="HTML")

@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """العودة للقائمة الرئيسية"""
    user_id = callback.from_user.id
    
    # مسح الحالة
    await state.clear()
    await delete_user_state(user_id)
    
    # جلب الرصيد الحالي
    user_crud = UserCRUD(session)
    user = await user_crud.get_user(user_id)
    
    if user:
        balance_msg = f"💰 <b>رصيدك الحالي:</b> {user.balance:,} ليرة سورية"
    else:
        balance_msg = "💰 <b>رصيدك الحالي:</b> 0 ليرة سورية"
    
    # تعديل الرسالة
    await callback.message.edit_text(
        f"🏠 <b>القائمة الرئيسية</b>\n\n{balance_msg}",
        reply_markup=main_menu(user_id),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    """إلغاء العملية الحالية"""
    user_id = callback.from_user.id
    
    # مسح الحالة
    await state.clear()
    await delete_user_state(user_id)
    
    await callback.message.edit_text(
        "❌ <b>تم إلغاء العملية</b>\n\nاستخدم /start للعودة للقائمة الرئيسية.",
        parse_mode="HTML"
    )
    
    await callback.answer("تم الإلغاء")

@router.callback_query(F.data.startswith("back_"))
async def handle_back(callback: CallbackQuery, state: FSMContext):
    """معالجة أزرار العودة المختلفة"""
    back_to = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    
    # مسح الحالة المؤقتة
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await delete_user_state(user_id)
    
    # حسب الوجهة
    if back_to == "charge_main":
        from handlers.charge.main import charge_main_menu
        await charge_main_menu(callback, state)
    
    elif back_to == "withdraw_main":
        from handlers.withdraw.main import withdraw_main_menu
        await withdraw_main_menu(callback, state)
    
    else:
        # العودة للقائمة الرئيسية
        await back_to_main(callback, state)
    
    await callback.answer()

@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession):
    """إحصائيات للمستخدم (للأدمن)"""
    user_id = message.from_user.id
    from config import ADMIN_ID
    
    if user_id != ADMIN_ID:
        await message.answer("⛔ هذا الأمر للإدمن فقط.")
        return
    
    from database.crud.transactions import TransactionCRUD
    from database.crud.users import UserCRUD
    
    user_crud = UserCRUD(session)
    tx_crud = TransactionCRUD(session)
    
    # إحصائيات سريعة
    total_users = await session.execute("SELECT COUNT(*) FROM users")
    total_users_count = total_users.scalar()
    
    active_users = await user_crud.get_active_users_count(7)
    
    today = datetime.date.today()
    daily_stats = await tx_crud.get_daily_stats(today)
    
    stats_text = f"""
<b>📊 إحصائيات البوت:</b>

👥 <b>إجمالي المستخدمين:</b> {total_users_count:,}
🔥 <b>المستخدمين النشطين (أسبوع):</b> {active_users:,}

<b>اليوم ({today.strftime('%Y-%m-%d')}):</b>
📥 <b>إجمالي الشحن:</b> {sum(daily_stats['charge'].values()):,} ليرة
📤 <b>إجمالي السحب:</b> {sum(daily_stats['withdraw'].values()):,} ليرة
🔁 <b>عدد المعاملات:</b> {sum(daily_stats['counts'].values()):,}
"""
    
    await message.answer(stats_text, parse_mode="HTML")

# استيراد datetime
import datetime