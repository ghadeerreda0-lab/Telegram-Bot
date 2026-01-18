import random
import string
import secrets
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import IchancyAccount

def generate_password(length: int = 12) -> str:
    """توليد كلمة مرور قوية"""
    if length < 8:
        length = 8
    
    # مجموعات المحارف
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    
    # تأكد من احتواء كل نوع
    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(symbols)
    ]
    
    # أكمل الباقي
    all_chars = lowercase + uppercase + digits + symbols
    password += [secrets.choice(all_chars) for _ in range(length - 4)]
    
    # خلط الكلمة
    secrets.SystemRandom().shuffle(password)
    
    return ''.join(password)

async def generate_username(session: AsyncSession, base_name: str) -> str:
    """توليد اسم مستخدم فريد"""
    # تنظيف الاسم الأساسي
    base_name = ''.join(c for c in base_name if c.isalnum()).lower()
    
    if len(base_name) < 3:
        base_name = "user" + base_name
    
    # محاولة بدون إضافات أولاً
    username = base_name
    
    # التحقق من التكرار
    for attempt in range(100):  # 100 محاولة كحد أقصى
        if attempt > 0:
            # إضافة أرقام أو حروف عشوائية
            if attempt < 10:
                suffix = str(attempt)
            elif attempt < 36:
                suffix = string.ascii_lowercase[attempt - 10]
            else:
                suffix = ''.join(secrets.choice(string.digits + string.ascii_lowercase) for _ in range(2))
            
            username = f"{base_name}_{suffix}"
        
        # التحقق من قاعدة البيانات
        stmt = select(IchancyAccount).where(IchancyAccount.username == username)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if not existing:
            return username
    
    # إذا فشلت جميع المحاولات، استخدم timestamp
    import time
    timestamp = int(time.time()) % 10000
    return f"{base_name}_{timestamp}"

def generate_gift_code(length: int = 8) -> str:
    """توليد كود هدية عشوائي"""
    chars = string.ascii_uppercase + string.digits
    # تجنب الأحرف المربكة (0, O, 1, I, L)
    chars = chars.replace('0', '').replace('O', '').replace('1', '').replace('I', '').replace('L', '')
    
    return ''.join(secrets.choice(chars) for _ in range(length))

def generate_transaction_id() -> str:
    """توليد رقم معاملة عشوائي"""
    timestamp = int(time.time() * 1000)
    random_part = ''.join(secrets.choice(string.digits) for _ in range(6))
    return f"TX{timestamp}{random_part}"