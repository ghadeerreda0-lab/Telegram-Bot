 from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import re

from keyboards.main import payment_methods_keyboard, back_button, cancel_button, numeric_keyboard
from core.redis_cache import set_user_state, get_user_state, delete_user_state
from core.bot import logger
from database.crud.transactions import TransactionCRUD
from database.crud.syriatel_codes import SyriatelCodeCRUD
from database.crud.users import UserCRUD
from config import MIN_DEPOSIT, MAX_DEPOSIT, SYRIATEL_CODE_LIMIT

router = Router()

class ChargeStates(StatesGroup):
    """حالات عملية الشحن"""
    choose_method = State()
    enter_amount = State()
    enter_transaction_id = State()
    confirm = State()

@router.callback_query(F.data == "charge_main")
async def charge_main_menu(callback: CallbackQuery, state: FSMContext):
    """القائمة الرئيسية للشحن"""
    user_id = callback.from_user.id
    
    # مسح أي حالة سابقة
    await state.clear()
    await delete_user_state(user_id)
    
    # حفظ الحالة
    await set_user_state(user_id, {
        "step": "choose_method",
        "action": "charge"
    })
    
    # عرض طرق الدفع
    await callback.message.edit_text(
        "📥 <b>شحن الرصيد</b>\n\n"
        "اختر طريقة الدفع المناسبة:",
        reply_markup=payment_methods_keyboard("charge"),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.callback_query(F.data.in_(["pay_syr", "pay_sch", "pay_sch_usd"]))
async def choose_payment_method(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """اختيار طريقة الدفع"""
    user_id = callback.from_user.id
    
    # تحديد اسم الطريقة
    method_map = {
        "pay_syr": "سيرياتيل كاش",
        "pay_sch": "شام كاش",
        "pay_sch_usd": "شام كاش دولار"
    }
    
    method_key = callback.data
    method_name = method_map.get(method_key, "غير معروف")
    
    # حفظ في الحالة
    await set_user_state(user_id, {
        "step": "enter_amount",
        "action": "charge",
        "payment_method": method_name,
        "method_key": method_key
    })
    
    # رسالة خاصة لكل طريقة
    if method_key == "pay_syr":
        extra_info = "\n💰 <b>الرقم:</b> 099XXXXXXX"
    elif method_key == "pay_sch":
        extra_info = "\n💰 <b>الرقم:</b> 094YYYYYYY"
    else:  # pay_sch_usd
        extra_info = "\n💰 <b>الرقم:</b> 094ZZZZZZZ\n💵 <b>العملة:</b> دولار أمريكي"
    
    await callback.message.edit_text(
        f"💳 <b>طريقة الدفع:</b> {method_name}\n"
        f"{extra_info}\n\n"
        f"📝 <b>الخطوات:</b>\n"
        f"1. قم بالتحويل للرقم أعلاه\n"
        f"2. أدخل المبلغ المراد شحنه\n"
        f"3. أدخل رقم العملية (Transaction ID)\n\n"
        f"💵 <b>الحد الأدنى:</b> {MIN_DEPOSIT:,} ليرة\n"
        f"💰 <b>الحد الأقصى:</b> {MAX_DEPOSIT:,} ليرة\n\n"
        f"⬇️ <b>أدخل المبلغ:</b>",
        reply_markup=back_button("charge_main"),
        parse_mode="HTML"
    )
    
    await callback.answer()

@router.message(F.text, ChargeStates.enter_amount)
async def enter_amount(message: Message, state: FSMContext, session: AsyncSession):
    """استقبال المبلغ"""
    user_id = message.from_user.id
    
    # التحقق من أن الرسالة من نفس المستخدم
    if message.from_user.id != user_id:
        return
    
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
    
    # التحقق من الحدود
    if amount < MIN_DEPOSIT:
        await message.answer(
            f"❌ <b>المبلغ أقل من الحد الأدنى!</b>\n"
            f"الحد الأدنى: {MIN_DEPOSIT:,} ليرة\n"
            f"⬇️ أعد إدخال المبلغ:",
            parse_mode="HTML"
        )
        return
    
    if amount > MAX_DEPOSIT:
        await message.answer(
            f"❌ <b>المبلغ يتجاوز الحد الأقصى!</b>\n"
            f"الحد الأقصى: {MAX_DEPOSIT:,} ليرة\n"
            f"⬇️ أعد إدخال المبلغ:",
            parse_mode="HTML"
        )
        return
    
    # خاصة لسيرياتيل كاش: التحقق من توفر كود
    if user_state.get("method_key") == "pay_syr":
        syriatel_crud = SyriatelCodeCRUD(session)
        available_code = await syriatel_crud.get_available_code(amount)
        
        if not available_code:
            await message.answer(
                "❌ <b>لا توجد أكواد متاحة حاليًا!</b>\n"
                "الرجاء المحاولة لاحقًا أو استخدام طريقة دفع أخرى.\n"
                "سيتم إعلام الإدمن بهذه المشكلة.",
                reply_markup=back_button("charge_main"),
                parse_mode="HTML"
            )
            
            # إشعار للإدمن
            from core.bot import bot_manager
            bot = await bot_manager.bot
            from config import CHANNEL_ADMIN_LOGS
            
            await bot.send_message(
                CHANNEL_ADMIN_LOGS,
                f"⚠️ <b>نفاد الأكواد!</b>\n"
                f"المستخدم {user_id} حاول شحن {amount:,}\n"
                f"لكن لا توجد أكواد سيرياتيل متاحة.",
                parse_mode="HTML"
            )
            
            return
        
        # حفظ معلومات الكود
        user_state["syriatel_code_id"] = available_code.id
        user_state["syriatel_code"] = available_code.code
    
    # حفظ المبلغ في الحالة
    user_state["amount"] = amount
    user_state["step"] = "enter_transaction_id"
    
    await set_user_state(user_id, user_state)
    
    # طلب رقم العملية
    await message.answer(
        f"✅ <b>تم حفظ المبلغ:</b> {amount:,} ليرة\n\n"
        f"🔑 <b>الآن أدخل رقم العملية (Transaction ID):</b>\n"
        f"• يجب أن يكون الرقم صحيحًا\n"
        f"• تأكد من كتابته بدقة\n"
        f"• يمكن أن يحتوي على أرقام وحروف\n\n"
        f"📝 <b>أدخل رقم العملية:</b>",
        reply_markup=cancel_button(),
        parse_mode="HTML"
    )

@router.message(F.text, ChargeStates.enter_transaction_id)
async def enter_transaction_id(message: Message, state: FSMContext, session: AsyncSession):
    """استقبال رقم العملية"""
    user_id = message.from_user.id
    
    # جلب الحالة
    user_state = await get_user_state(user_id)
    if not user_state or user_state.get("step") != "enter_transaction_id":
        await message.answer("❌ جلسة منتهية. ابدأ من جديد.")
        return
    
    transaction_id = message.text.strip()
    
    if not transaction_id or len(transaction_id) < 4:
        await message.answer(
            "❌ <b>رقم العملية غير صالح!</b>\n"
            "يجب أن يكون على الأقل 4 محارف.\n"
            "⬇️ أعد إدخال رقم العملية:",
            parse_mode="HTML"
        )
        return
    
    # حفظ رقم العملية
    user_state["transaction_id"] = transaction_id
    user_state["step"] = "confirm"
    
    await set_user_state(user_id, user_state)
    
    # عرض تفاصيل الطلب للتأكيد
    amount = user_state.get("amount", 0)
    method = user_state.get("payment_method", "غير معروف")
    
    confirm_text = f"""
✅ <b>تفاصيل طلب الشحن:</b>

💰 <b>المبلغ:</b> {amount:,} ليرة
💳 <b>طريقة الدفع:</b> {method}
🔑 <b>رقم العملية:</b> {transaction_id}
👤 <b>المستخدم:</b> {user_id}

⚠️ <b>تأكد من صحة المعلومات قبل التأكيد</b>
⚠️ <b>التحويلات الخاطئة لا يمكن استرجاعها</b>

<b>هل تريد تأكيد طلب الشحن؟</b>
"""
    
    from keyboards.main import confirmation_buttons
    confirm_kb = confirmation_buttons(
        confirm_data="confirm_charge",
        cancel_data="cancel"
    )
    
    await message.answer(
        confirm_text,
        reply_markup=confirm_kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "confirm_charge")
async def confirm_charge_request(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """تأكيد طلب الشحن"""
    user_id = callback.from_user.id
    
    # جلب الحالة
    user_state = await get_user_state(user_id)
    if not user_state or user_state.get("step") != "confirm":
        await callback.answer("❌ جلسة منتهية", show_alert=True)
        return
    
    # استخراج البيانات
    amount = user_state.get("amount", 0)
    method = user_state.get("payment_method", "غير معروف")
    transaction_id = user_state.get("transaction_id", "")
    method_key = user_state.get("method_key", "")
    
    try:
        # إنشاء المعاملة في قاعدة البيانات
        tx_crud = TransactionCRUD(session)
        
        tx_result = await tx_crud.create_transaction(
            user_id=user_id,
            type_="charge",
            amount=amount,
            payment_method=method,
            transaction_id=transaction_id,
            notes=f"طلب شحن عبر {method}"
        )
        
        # إذا كان سيرياتيل كاش، تحديث الكود
        if method_key == "pay_syr" and "syriatel_code_id" in user_state:
            syriatel_crud = SyriatelCodeCRUD(session)
            await syriatel_crud.update_code_amount(
                user_state["syriatel_code_id"],
                amount
            )
        
        # إرسال طلب الموافقة للقناة المناسبة
        from core.bot import bot_manager
        from config import CHANNEL_SYR_CASH, CHANNEL_SCH_CASH
        from keyboards.main import admin_transaction_buttons
        
        bot = await bot_manager.bot
        
        # تحديد القناة
        if method_key == "pay_syr":
            channel_id = CHANNEL_SYR_CASH
        elif method_key == "pay_sch":
            channel_id = CHANNEL_SCH_CASH
        else:  # pay_sch_usd
            channel_id = CHANNEL_SCH_CASH  # يمكن إنشاء قناة منفصلة
        
        # نص الرسالة للقناة
        order_number = tx_result["order_number"]
        order_time = tx_result["datetime"]
        
        channel_msg = f"""
🔔 <b>طلب شحن جديد!</b>

📋 <b>رقم الطلب الشهري:</b> #{order_number}
💰 <b>المبلغ:</b> {amount:,} ليرة
💳 <b>طريقة الدفع:</b> {method}
🔑 <b>رقم العملية:</b> {transaction_id}
👤 <b>المستخدم:</b> {user_id}
🕒 <b>الوقت:</b> {order_time}

{'🆔 <b>كود سيرياتيل:</b> ' + user_state.get('syriatel_code', '') if method_key == 'pay_syr' else ''}
"""
        
        # إرسال للقناة
        await bot.send_message(
            channel_id,
            channel_msg.strip(),
            reply_markup=admin_transaction_buttons(tx_result["id"]),
            parse_mode="HTML"
        )
        
        # إرسال تأكيد للمستخدم
        await callback.message.edit_text(
            f"✅ <b>تم إرسال طلب الشحن بنجاح!</b>\n\n"
            f"💰 <b>المبلغ:</b> {amount:,} ليرة\n"
            f"💳 <b>الطريقة:</b> {method}\n"
            f"🔑 <b>رقم العملية:</b> {transaction_id}\n"
            f"📋 <b>رقم الطلب:</b> #{order_number}\n\n"
            f"⏳ <b>سيتم مراجعة طلبك قريبًا من قبل الإدمن</b>\n"
            f"📬 <b>ستصلك إشعار عند الموافقة</b>",
            parse_mode="HTML"
        )
        
        # مسح الحالة
        await state.clear()
        await delete_user_state(user_id)
        
        logger.info(f"Charge request created: User {user_id}, Amount {amount}, TX {transaction_id}")
        
    except Exception as e:
        logger.error(f"Error creating charge request: {e}")
        
        await callback.message.edit_text(
            f"❌ <b>حدث خطأ أثناء معالجة طلبك!</b>\n\n"
            f"تفاصيل الخطأ: {str(e)}\n\n"
            f"الرجاء المحاولة مرة أخرى أو التواصل مع الدعم.",
            parse_mode="HTML"
        )
    
    await callback.answer()