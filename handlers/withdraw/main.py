from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
import random

from keyboards.main import payment_methods_keyboard, back_button, cancel_button, confirmation_buttons
from core.redis_cache import set_user_state, get_user_state, delete_user_state
from core.bot import logger
from database.crud.transactions import TransactionCRUD
from database.crud.users import UserCRUD
from config import MIN_WITHDRAW, MAX_WITHDRAW, CHANNEL_WITHDRAW

router = Router()

class WithdrawStates(StatesGroup):
    """حالات عملية السحب"""
    choose_method = State()
    enter_amount = State()
    enter_account = State()
    confirm = State()

@router.callback_query(F.data == "withdraw_main")
async def withdraw_main_menu(callback: CallbackQuery, state: FSMContext):
    """القائمة الرئيسية للسحب"""
    user_id = callback.from_user.id
    
    # مسح أي حالة سابقة
    await state.clear()
    await delete_user_state(user_id)
    
    # التحقق من رصيد المستخدم
    user_crud = UserCRUD(callback.session)
    user = await user_crud.get_user(user_id)
    
    if not user or user.balance < MIN_WITHDRAW:
        await callback.message.edit_text(
            f"⚠️ <b>رصيدك غير كافي للسحب!</b>\n\n"
            f"💰 <b>رصيدك الحالي:</b> {user.balance if user else 0:,} ليرة\n"
            f"📥 <b>الحد الأدنى للسحب:</b> {MIN_WITHDRAW:,} ليرة\n\n"
            f"يجب أن يكون رصيدك على الأقل {MIN_WITHDRAW:,} ليرة لطلب السحب.",
            reply_markup=back_button("main"),
            parse_mode="HTML"
        )
        return
    
    # حفظ الحالة
    await set_user_state(user_id, {
        "step": "choose_method",
        "action": "withdraw"
    })
    
    # عرض طرق السحب
    await callback.message.edit_text(
        f"📤 <b>سحب الرصيد</b>\n\n"
        f"💰 <b>رصيدك المتاح:</b> {user.balance:,} ليرة\n"
        f"📥 <b>الحد الأدنى:</b> {MIN_WITHDRAW:,} ليرة\n"
        f"💰 <b>الحد الأقصى:</b> {MAX_WITHDRAW:,} ليرة\n\n"
        f"اختر طريقة السحب:",
        reply_markup=payment_methods_keyboard("withdraw"),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data.in_(["withdraw_syr", "withdraw_sch", "withdraw_sch_usd"]))
async def choose_withdraw_method(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """اختيار طريقة السحب"""
    user_id = callback.from_user.id
    
    # تحديد اسم الطريقة
    method_map = {
        "withdraw_syr": "سيرياتيل كاش",
        "withdraw_sch": "شام كاش",
        "withdraw_sch_usd": "شام كاش دولار"
    }
    
    method_key = callback.data
    method_name = method_map.get(method_key, "غير معروف")
    
    # جلب رصيد المستخدم
    user_crud = UserCRUD(session)
    user = await user_crud.get_user(user_id)
    
    if not user or user.balance < MIN_WITHDRAW:
        await callback.answer("❌ رصيد غير كافي", show_alert=True)
        return
    
    # حفظ في الحالة
    await set_user_state(user_id, {
        "step": "enter_amount",
        "action": "withdraw",
        "payment_method": method_name,
        "method_key": method_key,
        "current_balance": user.balance
    })
    
    # رسالة خاصة لكل طريقة
    info_text = f"""
📤 <b>سحب عبر {method_name}</b>

💰 <b>رصيدك الحالي:</b> {user.balance:,} ليرة
📥 <b>الحد الأدنى:</b> {MIN_WITHDRAW:,} ليرة
💰 <b>الحد الأقصى:</b> {MAX_WITHDRAW:,} ليرة

📝 <b>الخطوات:</b>
1. أدخل المبلغ المراد سحبه
2. أدخل رقم الحساب/الهاتف
3. انتظر موافقة الإدمن
4. استلم الحوالة

⬇️ <b>أدخل المبلغ:</b>
"""
    
    await callback.message.edit_text(
        info_text,
        reply_markup=back_button("withdraw_main"),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.message(F.text, WithdrawStates.enter_amount)
async def withdraw_enter_amount(message: Message, state: FSMContext, session: AsyncSession):
    """استقبال مبلغ السحب"""
    user_id = message.from_user.id
    
    # جلب الحالة
    user_state = await get_user_state(user_id)
    if not user_state or user_state.get("step") != "enter_amount":
        await message.answer("❌ جلسة منتهية. ابدأ من جديد.")
        return
    
    # التحقق من صحة المبلغ
    amount_text = message.text.strip()
    
    if not amount_text.isdigit():
        await message.answer(
            "❌ <b>المبلغ غير صالح!</b>\n"
            "يجب إدخال أرقام فقط.\n"
            "⬇️ أعد إدخال المبلغ:",
            parse_mode="HTML"
        )
        return
    
    amount = int(amount_text)
    current_balance = user_state.get("current_balance", 0)
    
    # التحقق من الحدود والرصيد
    if amount < MIN_WITHDRAW:
        await message.answer(
            f"❌ <b>المبلغ أقل من الحد الأدنى!</b>\n"
            f"الحد الأدنى: {MIN_WITHDRAW:,} ليرة\n"
            f"⬇️ أعد إدخال المبلغ:",
            parse_mode="HTML"
        )
        return
    
    if amount > MAX_WITHDRAW:
        await message.answer(
            f"❌ <b>المبلغ يتجاوز الحد الأقصى!</b>\n"
            f"الحد الأقصى: {MAX_WITHDRAW:,} ليرة\n"
            f"⬇️ أعد إدخال المبلغ:",
            parse_mode="HTML"
        )
        return
    
    if amount > current_balance:
        await message.answer(
            f"❌ <b>المبلغ يتجاوز رصيدك!</b>\n"
            f"رصيدك الحالي: {current_balance:,} ليرة\n"
            f"المبلغ المدخل: {amount:,} ليرة\n"
            f"⬇️ أعد إدخال مبلغ أقل:",
            parse_mode="HTML"
        )
        return
    
    # تطبيق نسبة السحب إن وجدت
    # (سيتم تطبيقها من إعدادات الأدمن لاحقًا)
    user_state["amount"] = amount
    user_state["step"] = "enter_account"
    
    await set_user_state(user_id, user_state)
    
    # طلب رقم الحساب
    method_name = user_state.get("payment_method", "السحب")
    
    account_prompt = f"""
✅ <b>تم حفظ المبلغ:</b> {amount:,} ليرة

💳 <b>الآن أدخل رقم الحساب لاستلام المبلغ:</b>

<b>لـ {method_name}:</b>
"""
    
    # توجيهات حسب طريقة السحب
    if user_state.get("method_key") == "withdraw_syr":
        account_prompt += "• أدخل رقم هاتف سيرياتيل كاش\n• مثال: 0993123456"
    elif user_state.get("method_key") == "withdraw_sch":
        account_prompt += "• أدخل رقم هاتف شام كاش\n• مثال: 0944123456"
    else:  # withdraw_sch_usd
        account_prompt += "• أدخل رقم حساب بنكي\n• أو رقم هاتف\n• تأكد من صحة التفاصيل"
    
    account_prompt += "\n\n📝 <b>أدخل رقم الحساب:</b>"
    
    await message.answer(
        account_prompt,
        reply_markup=cancel_button(),
        parse_mode="HTML"
    )

@router.message(F.text, WithdrawStates.enter_account)
async def withdraw_enter_account(message: Message, state: FSMContext, session: AsyncSession):
    """استقبال رقم الحساب"""
    user_id = message.from_user.id
    
    # جلب الحالة
    user_state = await get_user_state(user_id)
    if not user_state or user_state.get("step") != "enter_account":
        await message.answer("❌ جلسة منتهية. ابدأ من جديد.")
        return
    
    account_number = message.text.strip()
    
    if not account_number or len(account_number) < 5:
        await message.answer(
            "❌ <b>رقم الحساب غير صالح!</b>\n"
            "يجب أن يكون على الأقل 5 محارف.\n"
            "⬇️ أعد إدخال رقم الحساب:",
            parse_mode="HTML"
        )
        return
    
    # حفظ رقم الحساب
    user_state["account_number"] = account_number
    user_state["step"] = "confirm"
    
    await set_user_state(user_id, user_state)
    
    # عرض تفاصيل الطلب للتأكيد
    amount = user_state.get("amount", 0)
    method = user_state.get("payment_method", "غير معروف")
    current_balance = user_state.get("current_balance", 0)
    new_balance = current_balance - amount
    
    confirm_text = f"""
✅ <b>تفاصيل طلب السحب:</b>

💰 <b>المبلغ:</b> {amount:,} ليرة
💳 <b>طريقة السحب:</b> {method}
📱 <b>رقم الحساب:</b> {account_number}
👤 <b>المستخدم:</b> {user_id}

💰 <b>الرصيد الحالي:</b> {current_balance:,} ليرة
💰 <b>الرصيد بعد السحب:</b> {new_balance:,} ليرة

⚠️ <b>ملاحظات هامة:</b>
• السحب يدوي من قبل الإدمن
• قد تستغرق العملية بعض الوقت
• تأكد من صحة رقم الحساب
• لا يمكن إلغاء الطلب بعد الموافقة

<b>هل تريد تأكيد طلب السحب؟</b>
"""
    
    confirm_kb = confirmation_buttons(
        confirm_data="confirm_withdraw",
        cancel_data="cancel"
    )
    
    await message.answer(
        confirm_text,
        reply_markup=confirm_kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "confirm_withdraw")
async def confirm_withdraw_request(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """تأكيد طلب السحب"""
    user_id = callback.from_user.id
    
    # جلب الحالة
    user_state = await get_user_state(user_id)
    if not user_state or user_state.get("step") != "confirm":
        await callback.answer("❌ جلسة منتهية", show_alert=True)
        return
    
    # استخراج البيانات
    amount = user_state.get("amount", 0)
    method = user_state.get("payment_method", "غير معروف")
    account_number = user_state.get("account_number", "")
    method_key = user_state.get("method_key", "")
    
    try:
        # إنشاء رقم عملية عشوائي للسحب
        transaction_id = str(random.randint(100000, 999999))
        
        # إنشاء المعاملة في قاعدة البيانات
        tx_crud = TransactionCRUD(session)
        
        tx_result = await tx_crud.create_transaction(
            user_id=user_id,
            type_="withdraw",
            amount=amount,
            payment_method=method,
            transaction_id=transaction_id,
            account_number=account_number,
            notes=f"طلب سحب عبر {method}"
        )
        
        # خصم المبلغ من رصيد المستخدم (معلق حتى الموافقة)
        user_crud = UserCRUD(session)
        old_balance, new_balance = await user_crud.update_balance(
            user_id, 
            amount, 
            operation="subtract"
        )
        
        # إرسال طلب الموافقة للقناة
        from core.bot import bot_manager
        from keyboards.main import admin_transaction_buttons
        
        bot = await bot_manager.bot
        
        # نص الرسالة للقناة
        order_number = tx_result["order_number"]
        order_time = tx_result["datetime"]
        
        channel_msg = f"""
🔔 <b>طلب سحب جديد!</b>

📋 <b>رقم الطلب:</b> #{transaction_id}
💰 <b>المبلغ:</b> {amount:,} ليرة
💳 <b>طريقة السحب:</b> {method}
📱 <b>رقم الحساب:</b> {account_number}
👤 <b>المستخدم:</b> {user_id}
💰 <b>رصيده قبل:</b> {old_balance:,} ليرة
💰 <b>رصيده بعد:</b> {new_balance:,} ليرة
🕒 <b>الوقت:</b> {order_time}
"""
        
        # إرسال للقناة
        await bot.send_message(
            CHANNEL_WITHDRAW,
            channel_msg.strip(),
            reply_markup=admin_transaction_buttons(tx_result["id"]),
            parse_mode="HTML"
        )
        
        # إرسال تأكيد للمستخدم
        await callback.message.edit_text(
            f"✅ <b>تم إرسال طلب السحب بنجاح!</b>\n\n"
            f"💰 <b>المبلغ:</b> {amount:,} ليرة\n"
            f"💳 <b>الطريقة:</b> {method}\n"
            f"📱 <b>رقم الحساب:</b> {account_number}\n"
            f"🔢 <b>رقم الطلب:</b> #{transaction_id}\n"
            f"💰 <b>رصيدك الجديد:</b> {new_balance:,} ليرة\n\n"
            f"⏳ <b>سيتم مراجعة طلبك قريبًا من قبل الإدمن</b>\n"
            f"📬 <b>ستصلك إشعار عند الموافقة والتسليم</b>",
            parse_mode="HTML"
        )
        
        # مسح الحالة
        await state.clear()
        await delete_user_state(user_id)
        
        logger.info(f"Withdraw request created: User {user_id}, Amount {amount}, Account {account_number}")
        
    except Exception as e:
        logger.error(f"Error creating withdraw request: {e}")
        
        await callback.message.edit_text(
            f"❌ <b>حدث خطأ أثناء معالجة طلبك!</b>\n\n"
            f"تفاصيل الخطأ: {str(e)}\n\n"
            f"الرجاء المحاولة مرة أخرى أو التواصل مع الدعم.",
            parse_mode="HTML"
        )
    
    await callback.answer()