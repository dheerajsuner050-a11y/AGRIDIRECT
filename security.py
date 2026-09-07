import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User, DeliveryPartner, DeliveryPartnerProfile, OTPVerification, OTPType, KYCStatus

# --- Security Configuration ---
SECRET_KEY = os.getenv("JWT_SECRET", "agridirect_live_production_secret_key_2026_super_secure")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
COOKIE_NAME = "agridirect_access_token"

import bcrypt

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# --- Password Utilities ---
def hash_password(password: str) -> str:
    """Hashes password using bcrypt with 72-byte safe truncation."""
    safe_pwd = password[:72]
    try:
        return pwd_context.hash(safe_pwd)
    except Exception:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(safe_pwd.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies plain password against bcrypt hash, with legacy SHA256 fallback."""
    safe_pwd = plain_password[:72]
    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$"):
        try:
            return pwd_context.verify(safe_pwd, hashed_password)
        except Exception:
            try:
                return bcrypt.checkpw(safe_pwd.encode("utf-8"), hashed_password.encode("utf-8"))
            except Exception:
                return False
    # Legacy SHA-256 fallback
    sha_hash = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
    return sha_hash == hashed_password

# --- JWT Token Utilities ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def set_auth_cookie(response: Response, token: str):
    """Sets secure HttpOnly SameSite cookie for session management."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=False  # Set to True when using HTTPS in production
    )

def clear_auth_cookie(response: Response):
    """Clears the session cookie."""
    response.delete_cookie(key=COOKIE_NAME)

# --- 6-Digit OTP Engine with Rate Limiting & Hashing ---
def generate_numeric_otp(length: int = 6) -> str:
    """Cryptographically secure numeric OTP."""
    range_start = 10 ** (length - 1)
    range_end = (10 ** length) - 1
    return str(secrets.randbelow(range_end - range_start + 1) + range_start)

def hash_otp(plain_otp: str) -> str:
    """Hashes OTP with SHA256 before database persistence."""
    return hashlib.sha256(plain_otp.strip().encode("utf-8")).hexdigest()

def create_db_otp(
    db: Session,
    phone: str,
    otp_type: OTPType,
    order_id: Optional[int] = None,
    user_id: Optional[int] = None,
    expiry_minutes: int = 10
) -> str:
    """Generates 6-digit OTP, stores hash in DB with expiration, and returns the plaintext for dispatch."""
    plain_otp = generate_numeric_otp(6)
    hashed = hash_otp(plain_otp)
    expires_at = datetime.utcnow() + timedelta(minutes=expiry_minutes)

    # Invalidate previous unused OTPs for same phone and type
    db.query(OTPVerification).filter(
        OTPVerification.phone == phone,
        OTPVerification.otp_type == otp_type,
        OTPVerification.is_used == False
    ).update({"is_used": True})

    otp_record = OTPVerification(
        order_id=order_id,
        user_id=user_id,
        phone=phone,
        otp_hash=hashed,
        otp_type=otp_type,
        is_used=False,
        attempts=0,
        max_attempts=3,
        expires_at=expires_at
    )
    db.add(otp_record)
    db.commit()
    return plain_otp

def verify_db_otp(
    db: Session,
    phone: str,
    plain_otp: str,
    otp_type: OTPType,
    order_id: Optional[int] = None
) -> bool:
    """
    Verifies OTP with single-use flag and rate-limiting.
    Returns True if valid, raises HTTPException if invalid, expired, or locked.
    """
    hashed_input = hash_otp(plain_otp)
    query = db.query(OTPVerification).filter(
        OTPVerification.phone == phone,
        OTPVerification.otp_type == otp_type,
        OTPVerification.is_used == False
    )
    if order_id is not None:
        query = query.filter(OTPVerification.order_id == order_id)

    record = query.order_by(OTPVerification.created_at.desc()).first()

    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP code")

    # Check expiration
    if datetime.utcnow() > record.expires_at:
        record.is_used = True
        db.commit()
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    # Check rate limiting attempts
    if record.attempts >= record.max_attempts:
        record.is_used = True
        db.commit()
        raise HTTPException(status_code=429, detail="Too many failed attempts. OTP has been invalidated.")

    if record.otp_hash != hashed_input:
        record.attempts += 1
        db.commit()
        remaining = record.max_attempts - record.attempts
        raise HTTPException(status_code=400, detail=f"Incorrect OTP code. {remaining} attempt(s) remaining.")

    # Mark as successfully used
    record.is_used = True
    db.commit()
    return True

# --- FastAPI Dependencies & RBAC ---
def get_current_user_optional(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Resolves user from HttpOnly Cookie or Bearer header."""
    token = bearer_token
    if not token:
        token = request.cookies.get(COOKIE_NAME)

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    email = payload.get("sub")
    if not email:
        return None

    return db.query(User).filter(User.email == email, User.is_active == True).first()

def get_current_user(
    current_user: Optional[User] = Depends(get_current_user_optional)
) -> User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in."
        )
    return current_user

def require_roles(allowed_roles: List[str]):
    """Role-based access control dependency."""
    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden. Required role: {', '.join(allowed_roles)}"
            )
        return user
    return role_checker

def require_verified_delivery_partner(
    user: User = Depends(require_roles(["delivery", "admin"])),
    db: Session = Depends(get_db)
) -> DeliveryPartner:
    """Enforces RBAC: Delivery partner must exist and have KYC verified."""
    if user.role == "admin":
        partner = db.query(DeliveryPartner).first()
        if partner:
            return partner

    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == user.id).first()
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery partner profile not registered."
        )

    # Check KYC status
    if not partner.is_verified:
        profile = partner.profile
        if profile and profile.kyc_status == KYCStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Delivery account is pending KYC verification. You cannot accept deliveries yet."
            )
        elif profile and profile.kyc_status == KYCStatus.REJECTED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="KYC verification was rejected. Please re-upload documents."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not verified for delivery operations."
            )

    return partner
