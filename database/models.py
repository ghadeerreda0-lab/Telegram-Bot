 from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, Float, ForeignKey, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import datetime

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(BigInteger, primary_key=True)
    balance = Column(Integer, default=0, nullable=False)
    referrals_count = Column(Integer, default=0)
    active_referrals = Column(Integer, default=0)
    total_earned = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    transactions = relationship("Transaction", back_populates="user")
    referrals = relationship("Referral", foreign_keys="Referral.referred_by", back_populates="referrer")
    ichancy_account = relationship("IchancyAccount", back_populates="user", uselist=False)

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    type = Column(String(20), nullable=False)  # charge, withdraw, gift, bonus
    amount = Column(Integer, nullable=False)
    payment_method = Column(String(50))
    transaction_id = Column(String(100))
    account_number = Column(String(100))
    status = Column(String(20), default="pending")  # pending, approved, rejected, completed
    verified_auto = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="transactions")
    
    __table_args__ = (
        Index('idx_transactions_user_status', 'user_id', 'status'),
        Index('idx_transactions_created', 'created_at'),
    )

class MonthlyCounter(Base):
    __tablename__ = "monthly_counter"
    
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    payment_method = Column(String(50), nullable=False)
    counter = Column(Integer, default=0)
    
    __table_args__ = (
        PrimaryKeyConstraint('month', 'year', 'payment_method'),
    )

class SyriatelCode(Base):
    __tablename__ = "syriatel_codes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False)
    current_amount = Column(Integer, default=0)
    max_amount = Column(Integer, default=5400)
    is_active = Column(Boolean, default=True)
    daily_reset = Column(Boolean, default=True)
    last_used = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    
    __table_args__ = (
        CheckConstraint('current_amount <= max_amount', name='check_amount_limit'),
        Index('idx_syriatel_active', 'is_active'),
    )

class IchancyAccount(Base):
    __tablename__ = "ichancy_accounts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), unique=True, nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    password = Column(String(200), nullable=False)
    account_id = Column(String(100))  # ID في المنصة الخارجية
    balance = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    deleted_at = Column(DateTime)
    
    # Relationships
    user = relationship("User", back_populates="ichancy_account")

class Referral(Base):
    __tablename__ = "referrals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    referred_id = Column(BigInteger, ForeignKey("users.user_id"), unique=True, nullable=False)
    is_active = Column(Boolean, default=False)
    earned_amount = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    referrer = relationship("User", foreign_keys=[referrer_id], back_populates="referrals")
    referred = relationship("User", foreign_keys=[referred_id])

class GiftCode(Base):
    __tablename__ = "gift_codes"
    
    code = Column(String(20), primary_key=True)
    amount = Column(Integer, nullable=False)
    max_uses = Column(Integer, nullable=False)
    used_count = Column(Integer, default=0)
    created_by = Column(BigInteger)  # admin id
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    __table_args__ = (
        Index('idx_gift_code_expires', 'expires_at'),
    )

class GiftCodeUsage(Base):
    __tablename__ = "gift_code_usages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), ForeignKey("gift_codes.code"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    used_at = Column(DateTime, default=func.now())
    
    __table_args__ = (
        UniqueConstraint('code', 'user_id', name='unique_code_user'),
    )

# جدول الإعدادات العامة
class Setting(Base):
    __tablename__ = "settings"
    
    key = Column(String(100), primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())