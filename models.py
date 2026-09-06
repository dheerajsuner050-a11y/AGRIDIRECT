import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey,
    Text, Boolean, Enum as SQLEnum, Index
)
from sqlalchemy.orm import relationship
from database import Base

class DeliveryStatus(str, enum.Enum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    GOING_TO_PICKUP = "GOING_TO_PICKUP"
    ARRIVED_AT_PICKUP = "ARRIVED_AT_PICKUP"
    PICKED_UP = "PICKED_UP"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    ARRIVED_AT_DESTINATION = "ARRIVED_AT_DESTINATION"
    OTP_VERIFIED = "OTP_VERIFIED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

class KYCStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"

class OTPType(str, enum.Enum):
    LOGIN = "LOGIN"
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"

class EarningStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    PAID = "PAID"

class PayoutStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

# --- 1. User Model ---
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    phone = Column(String(20), index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), default="seller", index=True)  # seller, buyer, delivery, admin
    district = Column(String(100), default="Indore")
    state = Column(String(100), default="Madhya Pradesh")
    latitude = Column(Float, default=22.7196)
    longitude = Column(Float, default=75.8577)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    listings = relationship("Listing", back_populates="seller")
    delivery_partner = relationship("DeliveryPartner", back_populates="user", uselist=False)
    buyer_orders = relationship("DeliveryOrder", foreign_keys="DeliveryOrder.buyer_id", back_populates="buyer")
    seller_orders = relationship("DeliveryOrder", foreign_keys="DeliveryOrder.seller_id", back_populates="seller")

# --- 2. Listing Model (Marketplace) ---
class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    crop_name = Column(String(100), nullable=False, index=True)
    category = Column(String(50), default="Vegetables")
    quantity = Column(Float, nullable=False)
    available_quantity = Column(Float, nullable=False)
    price_per_kg = Column(Float, nullable=False)
    quality = Column(String(50), default="Good")
    description = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=False)
    status = Column(String(50), default="Active", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    seller = relationship("User", back_populates="listings")

# --- 3. Delivery Partner Model ---
class DeliveryPartner(Base):
    __tablename__ = "delivery_partners"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    vehicle_type = Column(String(50), default="Bike")  # Bike, Van, Truck, Tempo
    vehicle_number = Column(String(50), default="MP09AB1234")
    license_number = Column(String(100), nullable=False)
    is_available = Column(Boolean, default=True, index=True)
    is_verified = Column(Boolean, default=True, index=True)  # Set to True for default seed, new regs need KYC
    current_latitude = Column(Float, default=22.7196)
    current_longitude = Column(Float, default=75.8577)
    rating = Column(Float, default=5.0)
    total_deliveries = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="delivery_partner")
    profile = relationship("DeliveryPartnerProfile", back_populates="partner", uselist=False, cascade="all, delete-orphan")
    orders = relationship("DeliveryOrder", back_populates="partner")
    locations = relationship("DeliveryLocation", back_populates="partner", cascade="all, delete-orphan")
    earnings = relationship("Earnings", back_populates="partner", cascade="all, delete-orphan")
    payouts = relationship("Payout", back_populates="partner", cascade="all, delete-orphan")

# --- 4. Delivery Partner Profile (KYC & Documents) ---
class DeliveryPartnerProfile(Base):
    __tablename__ = "delivery_partner_profiles"

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, ForeignKey("delivery_partners.id"), unique=True, nullable=False)
    driving_license_no = Column(String(100), nullable=True)
    aadhar_no = Column(String(30), nullable=True)
    vehicle_rc_no = Column(String(50), nullable=True)
    kyc_status = Column(SQLEnum(KYCStatus), default=KYCStatus.VERIFIED, index=True)
    kyc_document_url = Column(String(500), nullable=True)
    emergency_contact = Column(String(20), nullable=True)
    bank_account_no = Column(String(50), nullable=True)
    ifsc_code = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    partner = relationship("DeliveryPartner", back_populates="profile")

# --- 5. Delivery Order Model ---
class DeliveryOrder(Base):
    __tablename__ = "delivery_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(50), unique=True, index=True, nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True, index=True)
    partner_id = Column(Integer, ForeignKey("delivery_partners.id"), nullable=True, index=True)

    crop_name = Column(String(100), nullable=False)
    quantity = Column(Float, nullable=False)
    price_per_kg = Column(Float, nullable=False)
    subtotal = Column(Float, nullable=False)
    delivery_fee = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)

    status = Column(SQLEnum(DeliveryStatus), default=DeliveryStatus.CREATED, index=True, nullable=False)

    # Route & Geolocation Coordinates
    pickup_latitude = Column(Float, nullable=False, default=22.7196)
    pickup_longitude = Column(Float, nullable=False, default=75.8577)
    pickup_address = Column(String(255), nullable=False)

    delivery_latitude = Column(Float, nullable=False, default=22.9676)
    delivery_longitude = Column(Float, nullable=False, default=76.0534)
    delivery_address = Column(String(255), nullable=False)

    distance_km = Column(Float, default=0.0)
    estimated_duration_mins = Column(Integer, default=0)

    # Single-use OTP tracking codes
    pickup_otp_code = Column(String(10), nullable=True)
    delivery_otp_code = Column(String(10), nullable=True)

    pickup_time = Column(DateTime, nullable=True)
    delivery_time = Column(DateTime, nullable=True)
    cancelled_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    buyer = relationship("User", foreign_keys=[buyer_id], back_populates="buyer_orders")
    seller = relationship("User", foreign_keys=[seller_id], back_populates="seller_orders")
    listing = relationship("Listing")
    partner = relationship("DeliveryPartner", back_populates="orders")
    locations = relationship("DeliveryLocation", back_populates="order", cascade="all, delete-orphan")
    earnings = relationship("Earnings", back_populates="order", cascade="all, delete-orphan")

# --- 6. Delivery Location (GPS Tracking Breadcrumbs) ---
class DeliveryLocation(Base):
    __tablename__ = "delivery_locations"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("delivery_orders.id"), nullable=False, index=True)
    partner_id = Column(Integer, ForeignKey("delivery_partners.id"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    speed = Column(Float, default=0.0)
    heading = Column(Float, default=0.0)
    accuracy = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)

    order = relationship("DeliveryOrder", back_populates="locations")
    partner = relationship("DeliveryPartner", back_populates="locations")

    __table_args__ = (
        Index("idx_order_timestamp", "order_id", "timestamp"),
        Index("idx_partner_timestamp", "partner_id", "timestamp"),
    )

# --- 7. OTP Verification Model ---
class OTPVerification(Base):
    __tablename__ = "otp_verifications"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("delivery_orders.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    phone = Column(String(20), index=True, nullable=False)
    otp_hash = Column(String(255), nullable=False)
    otp_type = Column(SQLEnum(OTPType), nullable=False, index=True)
    is_used = Column(Boolean, default=False, index=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# --- 8. Earnings Model ---
class Earnings(Base):
    __tablename__ = "earnings"

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, ForeignKey("delivery_partners.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("delivery_orders.id"), nullable=False, index=True)
    base_fee = Column(Float, default=50.0)
    distance_fee = Column(Float, default=0.0)
    tip = Column(Float, default=0.0)
    total_earning = Column(Float, default=50.0)
    status = Column(SQLEnum(EarningStatus), default=EarningStatus.PROCESSED, index=True)
    date = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    partner = relationship("DeliveryPartner", back_populates="earnings")
    order = relationship("DeliveryOrder", back_populates="earnings")

# --- 9. Payout Model ---
class Payout(Base):
    __tablename__ = "payouts"

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, ForeignKey("delivery_partners.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    payout_method = Column(String(50), default="BANK_TRANSFER")
    transaction_ref = Column(String(100), nullable=True, index=True)
    status = Column(SQLEnum(PayoutStatus), default=PayoutStatus.REQUESTED, index=True)
    requested_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    partner = relationship("DeliveryPartner", back_populates="payouts")
