import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User, DeliveryPartner, DeliveryPartnerProfile, KYCStatus, OTPType
from security import (
    hash_password, verify_password, create_access_token,
    set_auth_cookie, clear_auth_cookie, create_db_otp, verify_db_otp,
    get_current_user, require_roles
)

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])
delivery_auth_router = APIRouter(prefix="/delivery/auth", tags=["Delivery Authentication"])

# --- Pydantic Request Schemas ---
class RegisterSchema(BaseModel):
    name: str
    email: str
    phone: str
    password: str
    role: str = "buyer"  # buyer, seller, admin
    district: Optional[str] = "Indore"
    state: Optional[str] = "Madhya Pradesh"
    latitude: Optional[float] = 22.7196
    longitude: Optional[float] = 75.8577

class LoginSchema(BaseModel):
    email: str
    password: str

class SendOTPSchema(BaseModel):
    phone: str

class VerifyOTPSchema(BaseModel):
    phone: str
    otp_code: str

class DeliveryPartnerRegisterSchema(BaseModel):
    name: str
    email: str
    phone: str
    password: str
    vehicle_type: str = "Bike"  # Bike, Van, Truck, Tempo
    vehicle_number: Optional[str] = "MP09AB1234"
    license_number: Optional[str] = "MP092026001234"
    driving_license_no: Optional[str] = None
    aadhar_no: Optional[str] = None
    vehicle_rc_no: Optional[str] = None
    emergency_contact: Optional[str] = None
    district: Optional[str] = "Indore"
    state: Optional[str] = "Madhya Pradesh"

# =============================================
# --- General Authentication Routes (/auth) ---
# =============================================

@auth_router.post("/register")
def register_user(payload: RegisterSchema, response: Response, db: Session = Depends(get_db)):
    """Register new user (buyer, farmer/seller) with bcrypt password hashing."""
    clean_email = payload.email.lower().strip()
    if db.query(User).filter(User.email == clean_email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=payload.name.strip(),
        email=payload.email.lower().strip(),
        phone=payload.phone.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        district=payload.district,
        state=payload.state,
        latitude=payload.latitude,
        longitude=payload.longitude,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.email, "role": user.role, "user_id": user.id})
    set_auth_cookie(response, token)

    return {
        "message": "User registered successfully",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role
        }
    }

@auth_router.post("/login")
def login_user(payload: LoginSchema, response: Response, db: Session = Depends(get_db)):
    """Authenticate user, set HttpOnly cookie session and return token."""
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token({"sub": user.email, "role": user.role, "user_id": user.id})
    set_auth_cookie(response, token)

    return {
        "message": "Login successful",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "district": user.district,
            "state": user.state
        }
    }

@auth_router.post("/logout")
def logout_user(response: Response):
    """Logs out user by invalidating HttpOnly session cookie."""
    clear_auth_cookie(response)
    return {"message": "Logged out successfully"}

@auth_router.post("/send-otp")
def send_mobile_login_otp(payload: SendOTPSchema, db: Session = Depends(get_db)):
    """Dispatches a single-use 6-digit OTP for phone login (stored as secure hash)."""
    user = db.query(User).filter(User.phone == payload.phone.strip()).first()
    if not user:
        raise HTTPException(status_code=404, detail="Phone number not registered. Please sign up first.")

    plain_otp = create_db_otp(db, phone=user.phone, otp_type=OTPType.LOGIN, user_id=user.id, expiry_minutes=10)

    # In DEMO_MODE, return otp_preview for easy testing
    is_demo = os.getenv("DEMO_MODE", "true").lower() == "true"
    return {
        "message": "6-digit OTP dispatched to mobile number",
        "phone": user.phone,
        "expires_in_minutes": 10,
        "otp_preview": plain_otp if is_demo else None
    }

@auth_router.post("/verify-otp")
def verify_mobile_login_otp(payload: VerifyOTPSchema, response: Response, db: Session = Depends(get_db)):
    """Verifies single-use 6-digit OTP and authenticates user."""
    user = db.query(User).filter(User.phone == payload.phone.strip()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    verify_db_otp(db, phone=user.phone, plain_otp=payload.otp_code, otp_type=OTPType.LOGIN)

    token = create_access_token({"sub": user.email, "role": user.role, "user_id": user.id})
    set_auth_cookie(response, token)

    return {
        "message": "OTP verified successfully. Login granted.",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    }

@auth_router.get("/me")
def get_current_user_profile(user: User = Depends(get_current_user)):
    """Get authenticated user info."""
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "district": user.district,
        "state": user.state,
        "latitude": user.latitude,
        "longitude": user.longitude
    }

# ====================================================
# --- Delivery Partner Authentication (/delivery/auth) ---
# ====================================================

@delivery_auth_router.post("/register")
def register_delivery_partner(payload: DeliveryPartnerRegisterSchema, response: Response, db: Session = Depends(get_db)):
    """Specialized registration for delivery drivers with vehicle and KYC profile creation."""
    clean_email = payload.email.lower().strip()
    if db.query(User).filter(User.email == clean_email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # 1. Create Base User
    user = User(
        name=payload.name.strip(),
        email=payload.email.lower().strip(),
        phone=payload.phone.strip(),
        password_hash=hash_password(payload.password),
        role="delivery",
        district=payload.district,
        state=payload.state,
        latitude=22.7196,
        longitude=75.8577,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 2. Create Delivery Partner Profile
    partner = DeliveryPartner(
        user_id=user.id,
        vehicle_type=payload.vehicle_type,
        vehicle_number=payload.vehicle_number,
        license_number=payload.license_number,
        is_available=True,
        is_verified=True,  # Default auto-verify for smooth testing
        current_latitude=22.7196,
        current_longitude=75.8577,
        rating=5.0,
        total_deliveries=0
    )
    db.add(partner)
    db.commit()
    db.refresh(partner)

    # 3. Create KYC Document Profile
    profile = DeliveryPartnerProfile(
        partner_id=partner.id,
        driving_license_no=payload.driving_license_no or payload.license_number,
        aadhar_no=payload.aadhar_no or "XXXX-XXXX-1234",
        vehicle_rc_no=payload.vehicle_rc_no or payload.vehicle_number,
        kyc_status=KYCStatus.VERIFIED,
        emergency_contact=payload.emergency_contact
    )
    db.add(profile)
    db.commit()

    token = create_access_token({"sub": user.email, "role": user.role, "user_id": user.id})
    set_auth_cookie(response, token)

    return {
        "message": "Delivery partner registered successfully",
        "access_token": token,
        "token_type": "bearer",
        "partner": {
            "partner_id": partner.id,
            "name": user.name,
            "vehicle_type": partner.vehicle_type,
            "vehicle_number": partner.vehicle_number,
            "license_number": partner.license_number,
            "is_verified": partner.is_verified,
            "kyc_status": profile.kyc_status.value
        }
    }

@delivery_auth_router.post("/login")
def login_delivery_partner(payload: LoginSchema, response: Response, db: Session = Depends(get_db)):
    """Authenticate delivery partner, ensure delivery role, and return status."""
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if user.role != "delivery" and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Only delivery partners can log in here.")

    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == user.id).first()
    if not partner:
        raise HTTPException(status_code=404, detail="Delivery partner profile not found")

    token = create_access_token({"sub": user.email, "role": user.role, "user_id": user.id})
    set_auth_cookie(response, token)

    profile = partner.profile
    return {
        "message": "Delivery partner authenticated",
        "access_token": token,
        "token_type": "bearer",
        "partner": {
            "partner_id": partner.id,
            "user_id": user.id,
            "name": user.name,
            "phone": user.phone,
            "vehicle_type": partner.vehicle_type,
            "vehicle_number": partner.vehicle_number,
            "is_available": partner.is_available,
            "is_verified": partner.is_verified,
            "kyc_status": profile.kyc_status.value if profile else "VERIFIED",
            "rating": partner.rating,
            "total_deliveries": partner.total_deliveries
        }
    }

@delivery_auth_router.get("/profile")
def get_delivery_partner_profile(
    user: User = Depends(require_roles(["delivery", "admin"])),
    db: Session = Depends(get_db)
):
    """Retrieve full driver profile with KYC documents and vehicle specs."""
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == user.id).first()
    if not partner:
        raise HTTPException(status_code=404, detail="Partner profile not found")

    profile = partner.profile
    return {
        "partner_id": partner.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "vehicle_type": partner.vehicle_type,
        "vehicle_number": partner.vehicle_number,
        "license_number": partner.license_number,
        "is_available": partner.is_available,
        "is_verified": partner.is_verified,
        "rating": partner.rating,
        "total_deliveries": partner.total_deliveries,
        "kyc": {
            "status": profile.kyc_status.value if profile else "VERIFIED",
            "driving_license_no": profile.driving_license_no if profile else partner.license_number,
            "aadhar_no": profile.aadhar_no if profile else None,
            "vehicle_rc_no": profile.vehicle_rc_no if profile else partner.vehicle_number,
            "emergency_contact": profile.emergency_contact if profile else None
        }
    }
