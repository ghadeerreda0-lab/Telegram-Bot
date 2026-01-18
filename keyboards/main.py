 from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import Optional, List, Dict
from config import ADMIN_ID

def main_menu(user_id: int) -> InlineKeyboardMarkup:
    """القائمة الرئيسية للبوت"""
    builder = InlineKeyboardBuilder()
    
    # الصف الأول: Ichancy
    builder.button(text="⚡ Ichancy", callback_data="ichancy_main")
    
    # الصف الثاني: الشحن والسحب
    builder.button(text="📥 شحن رصيد", callback_data="charge_main")
    builder.button(text="📤 سحب رصيد", callback_data="withdraw_main")
    builder.adjust(2)
    
    # الصف الثالث: الاحالات
    builder.button(text="💰 نظام الاحالات", callback_data="referrals_main")
    
    # الصف الرابع: الهدايا
    builder.button(text="🎁 اهداء رصيد", callback_data="gift_balance")
    builder.button(text="🎁 كود هدية", callback_data="gift_code")
    builder.adjust(2)
    
    # الصف الخامس: التواصل
    builder.button(text="✉️ رسالة للادمن", callback_data="admin_message")
    builder.button(text="✉️ تواصل معنا", callback_data="contact_us")
    builder.adjust(2)
    
    # الصف السادس: السجلات والشروحات
    builder.button(text="🔁 السجل", callback_data="user_logs")
    builder.button(text="☁️ الشروحات", callback_data="tutorials")
    builder.adjust(2)
    
    # الصف السابع: الرهانات والجاكبوت
    builder.button(text="🔁 سجل الرهانات", callback_data="bets_log")
    builder.button(text="🆕 🃏 الجاكبوت", callback_data="jackpot")
    builder.adjust(2)
    
    # الصف الثامن: الروابط الخارجية
    builder.button(text="↗️ Vp لتشغيل كامل اقسام الموقع", callback_data="vp_link")
    builder.button(text="↗️ ichancy apk", callback_data="apk_link")
    builder.adjust(2)
    
    # الصف التاسع: الشروط
    builder.button(text="📌 الشروط والأحكام", callback_data="rules")
    
    # الصف العاشر: لوحة التحكم (للأدمن فقط)
    if user_id == ADMIN_ID:
        builder.button(text="🎛 لوحة التحكم", callback_data="admin_panel")
    
    builder.adjust(1)
    return builder.as_markup()

def back_button(back_to: str = "main") -> InlineKeyboardMarkup:
    """زر العودة"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ رجوع", callback_data=f"back_{back_to}")
    return builder.as_markup()

def cancel_button() -> InlineKeyboardMarkup:
    """زر إلغاء"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="cancel")
    return builder.as_markup()

def confirmation_buttons(confirm_data: str, cancel_data: str = "cancel") -> InlineKeyboardMarkup:
    """أزرار التأكيد"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ نعم", callback_data=confirm_data)
    builder.button(text="❌ لا", callback_data=cancel_data)
    builder.adjust(2)
    return builder.as_markup()

def payment_methods_keyboard(action: str = "charge") -> InlineKeyboardMarkup:
    """لوحة طرق الدفع/السحب"""
    builder = InlineKeyboardBuilder()
    
    if action == "charge":
        builder.button(text="💰 سيرياتيل كاش", callback_data="pay_syr")
        builder.button(text="💰 شام كاش", callback_data="pay_sch")
        builder.button(text="💰 شام كاش دولار", callback_data="pay_sch_usd")
    else:  # withdraw
        builder.button(text="💰 سيرياتيل كاش", callback_data="withdraw_syr")
        builder.button(text="💰 شام كاش", callback_data="withdraw_sch")
        builder.button(text="💰 شام كاش دولار", callback_data="withdraw_sch_usd")
    
    builder.button(text="⬅️ رجوع", callback_data=f"back_{action}_main")
    builder.adjust(1)
    return builder.as_markup()

def admin_transaction_buttons(transaction_id: int) -> InlineKeyboardMarkup:
    """أزرار إدارة المعاملة للأدمن"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="✅ قبول", callback_data=f"approve_{transaction_id}")
    builder.button(text="❌ رفض", callback_data=f"reject_{transaction_id}")
    builder.button(text="🔁 إعادة التحقق", callback_data=f"reverify_{transaction_id}")
    builder.button(text="💵 تم التسليم", callback_data=f"deliver_{transaction_id}")
    builder.button(text="🔄 تصفير الحساب", callback_data=f"reset_user_{transaction_id}")
    
    builder.adjust(2)
    return builder.as_markup()

def logs_filter_keyboard() -> InlineKeyboardMarkup:
    """تصفية السجل"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="📥 الشحن", callback_data="logs_charge")
    builder.button(text="📤 السحب", callback_data="logs_withdraw")
    builder.button(text="🎁 الهدايا", callback_data="logs_gifts")
    builder.button(text="🔁 الكل", callback_data="logs_all")
    builder.button(text="⬅️ رجوع", callback_data="back_main")
    
    builder.adjust(2)
    return builder.as_markup()

def numeric_keyboard() -> ReplyKeyboardMarkup:
    """لوحة أرقام للرسائل النصية"""
    builder = ReplyKeyboardBuilder()
    
    for i in range(1, 10):
        builder.button(text=str(i))
    builder.button(text="0")
    builder.button(text="❌ إلغاء")
    
    builder.adjust(3, 3, 3, 2)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    """لوحة تحكم الأدمن الرئيسية"""
    builder = InlineKeyboardBuilder()
    
    # الصف الأول: الإحصائيات
    builder.button(text="📊 الإحصائيات", callback_data="admin_stats")
    
    # الصف الثاني: إدارة المستخدمين
    builder.button(text="👥 إدارة المستخدمين", callback_data="admin_users")
    builder.button(text="💰 إدارة الرصيد", callback_data="admin_balance")
    builder.adjust(2)
    
    # الصف الثالث: أنظمة الدفع
    builder.button(text="💳 إعدادات الدفع", callback_data="admin_payments")
    builder.button(text="📤 إعدادات السحب", callback_data="admin_withdraws")
    builder.adjust(2)
    
    # الصف الرابع: الأنظمة الفرعية
    builder.button(text="⚡ إدارة Ichancy", callback_data="admin_ichancy")
    builder.button(text="🎁 إدارة الهدايا", callback_data="admin_gifts")
    builder.adjust(2)
    
    # الصف الخامس: الاحالات والتقارير
    builder.button(text="📈 نظام الاحالات", callback_data="admin_referrals")
    builder.button(text="📋 التقارير", callback_data="admin_reports")
    builder.adjust(2)
    
    # الصف السادس: الإعدادات العامة
    builder.button(text="⚙️ الإعدادات العامة", callback_data="admin_settings")
    builder.button(text="🔔 التنبيهات", callback_data="admin_alerts")
    builder.adjust(2)
    
    # الصف السابع: النسخ الاحتياطي
    builder.button(text="💾 النسخ الاحتياطي", callback_data="admin_backup")
    
    # الصف الثامن: العودة
    builder.button(text="⬅️ رجوع للقائمة", callback_data="back_main")
    
    builder.adjust(1)
    return builder.as_markup()