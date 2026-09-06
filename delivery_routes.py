import math
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import (
    User, DeliveryPartner, DeliveryPartnerProfile, DeliveryOrder,
    DeliveryLocation, Earnings, Payout, DeliveryStatus, KYCStatus,
    OTPType, EarningStatus
)
from security import (
    get_current_user, require_roles, require_verified_delivery_partner,
    create_db_otp, verify_db_otp
)
from websocket_manager import delivery_ws_manager

delivery_router = APIRouter(prefix="/delivery", tags=["Delivery Logistics"])

# --- Request Schemas ---
class StatusUpdateSchema(BaseModel):
    status: DeliveryStatus
    notes: Optional[str] = None

class LocationUpdateSchema(BaseModel):
    latitude: float
    longitude: float
    speed: Optional[float] = 0.0
    heading: Optional[float] = 0.0
    accuracy: Optional[float] = 0.0

class OTPVerifySchema(BaseModel):
    otp_code: str

class KYCUpdateSchema(BaseModel):
    driving_license_no: Optional[str] = None
    aadhar_no: Optional[str] = None
    vehicle_rc_no: Optional[str] = None
    emergency_contact: Optional[str] = None

# --- Distance & ETA Helper ---
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS coordinates in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

# ====================================================
# --- Partner Availability & Dashboard Endpoints ---
# ====================================================

@delivery_router.put("/partner/toggle-availability")
@delivery_router.put("/toggle-availability")
@delivery_router.post("/availability")
def toggle_availability(
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Toggle driver availability online/offline."""
    partner.is_available = not partner.is_available
    db.commit()
    status_str = "Online" if partner.is_available else "Offline"
    return {
        "message": f"Driver is now {status_str}",
        "is_available": partner.is_available
    }

@delivery_router.get("/orders/available")
def get_available_orders(
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """List pending orders waiting for pickup or driver acceptance."""
    # Orders assigned to this partner or created and unassigned
    orders = db.query(DeliveryOrder).filter(
        (DeliveryOrder.partner_id == partner.id) | (DeliveryOrder.partner_id == None),
        DeliveryOrder.status.in_([DeliveryStatus.CREATED, DeliveryStatus.ASSIGNED])
    ).order_by(DeliveryOrder.created_at.desc()).limit(10).all()

    results = []
    for o in orders:
        dist_to_pickup = haversine_distance(
            partner.current_latitude, partner.current_longitude,
            o.pickup_latitude, o.pickup_longitude
        )
        results.append({
            "order_id": o.id,
            "order_number": o.order_number,
            "crop_name": o.crop_name,
            "quantity": o.quantity,
            "delivery_fee": o.delivery_fee,
            "pickup_address": o.pickup_address,
            "delivery_address": o.delivery_address,
            "distance_km": o.distance_km,
            "dist_to_pickup_km": dist_to_pickup,
            "status": o.status.value,
            "created_at": o.created_at.strftime("%I:%M %p")
        })
    return results

@delivery_router.get("/orders/active")
def get_active_delivery(
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Retrieve driver's current active ongoing delivery."""
    active_statuses = [
        DeliveryStatus.ACCEPTED,
        DeliveryStatus.GOING_TO_PICKUP,
        DeliveryStatus.ARRIVED_AT_PICKUP,
        DeliveryStatus.PICKED_UP,
        DeliveryStatus.OUT_FOR_DELIVERY,
        DeliveryStatus.ARRIVED_AT_DESTINATION,
        DeliveryStatus.OTP_VERIFIED
    ]
    order = db.query(DeliveryOrder).filter(
        DeliveryOrder.partner_id == partner.id,
        DeliveryOrder.status.in_(active_statuses)
    ).first()

    if not order:
        return {"active_order": None}

    return {
        "active_order": {
            "order_id": order.id,
            "order_number": order.order_number,
            "crop_name": order.crop_name,
            "quantity": order.quantity,
            "status": order.status.value,
            "delivery_fee": order.delivery_fee,
            "total_amount": order.total_amount,
            "pickup": {
                "latitude": order.pickup_latitude,
                "longitude": order.pickup_longitude,
                "address": order.pickup_address,
                "contact_name": order.seller.name if order.seller else "Farmer",
                "contact_phone": order.seller.phone if order.seller else ""
            },
            "delivery": {
                "latitude": order.delivery_latitude,
                "longitude": order.delivery_longitude,
                "address": order.delivery_address,
                "contact_name": order.buyer.name if order.buyer else "Buyer",
                "contact_phone": order.buyer.phone if order.buyer else ""
            },
            "pickup_otp_code": order.pickup_otp_code,
            "distance_km": order.distance_km,
            "estimated_duration_mins": order.estimated_duration_mins
        }
    }

@delivery_router.post("/orders/{order_id}/accept")
async def accept_order(
    order_id: int,
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Partner accepts a delivery assignment with state transition ASSIGNED -> ACCEPTED."""
    order = db.query(DeliveryOrder).filter(DeliveryOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in [DeliveryStatus.CREATED, DeliveryStatus.ASSIGNED]:
        raise HTTPException(status_code=400, detail=f"Order cannot be accepted in status '{order.status.value}'")

    order.partner_id = partner.id
    order.status = DeliveryStatus.ACCEPTED
    partner.is_available = False

    # Generate 6-digit Pickup OTP for Farmer & Delivery OTP for Buyer
    if not order.pickup_otp_code and order.seller:
        order.pickup_otp_code = create_db_otp(
            db, phone=order.seller.phone, otp_type=OTPType.PICKUP, order_id=order.id
        )
    if not order.delivery_otp_code and order.buyer:
        order.delivery_otp_code = create_db_otp(
            db, phone=order.buyer.phone, otp_type=OTPType.DELIVERY, order_id=order.id
        )

    db.commit()

    # Broadcast via WebSocket
    await delivery_ws_manager.broadcast_status(order.id, DeliveryStatus.ACCEPTED.value, {
        "partner_name": partner.user.name,
        "vehicle_type": partner.vehicle_type
    })

    return {
        "message": f"Order #{order.order_number} accepted. Proceed to pickup location.",
        "order_id": order.id,
        "status": order.status.value,
        "pickup_address": order.pickup_address
    }

@delivery_router.post("/orders/{order_id}/reject")
def reject_order(
    order_id: int,
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Driver rejects incoming order dispatch card."""
    order = db.query(DeliveryOrder).filter(DeliveryOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.partner_id == partner.id:
        order.partner_id = None
        order.status = DeliveryStatus.CREATED
        partner.is_available = True
        db.commit()

    return {"message": "Order declined. Returned to matching pool."}

# ====================================================
# --- Delivery State Machine Progression ---
# ====================================================

VALID_TRANSITIONS = {
    DeliveryStatus.ACCEPTED: [DeliveryStatus.GOING_TO_PICKUP, DeliveryStatus.CANCELLED],
    DeliveryStatus.GOING_TO_PICKUP: [DeliveryStatus.ARRIVED_AT_PICKUP, DeliveryStatus.CANCELLED],
    DeliveryStatus.ARRIVED_AT_PICKUP: [DeliveryStatus.PICKED_UP, DeliveryStatus.CANCELLED],
    DeliveryStatus.PICKED_UP: [DeliveryStatus.OUT_FOR_DELIVERY],
    DeliveryStatus.OUT_FOR_DELIVERY: [DeliveryStatus.ARRIVED_AT_DESTINATION],
    DeliveryStatus.ARRIVED_AT_DESTINATION: [DeliveryStatus.OTP_VERIFIED, DeliveryStatus.DELIVERED],
    DeliveryStatus.OTP_VERIFIED: [DeliveryStatus.DELIVERED]
}

@delivery_router.put("/orders/{order_id}/status")
async def update_delivery_status(
    order_id: int,
    payload: StatusUpdateSchema,
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Enforces state machine progression for active deliveries."""
    order = db.query(DeliveryOrder).filter(
        DeliveryOrder.id == order_id,
        DeliveryOrder.partner_id == partner.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Active delivery order not found")

    allowed = VALID_TRANSITIONS.get(order.status, [])
    if payload.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transition from '{order.status.value}' to '{payload.status.value}'. Allowed: {[s.value for s in allowed]}"
        )

    # If transitioning to PICKED_UP directly without OTP, require verify-pickup-otp route
    if payload.status == DeliveryStatus.PICKED_UP and order.pickup_otp_code:
        raise HTTPException(
            status_code=400,
            detail="Pickup requires 6-digit OTP verification from the farmer. Call /verify-pickup-otp."
        )

    # If transitioning to DELIVERED directly without OTP, require verify-delivery-otp route
    if payload.status == DeliveryStatus.DELIVERED and order.delivery_otp_code:
        raise HTTPException(
            status_code=400,
            detail="Completion requires 6-digit OTP verification from the buyer. Call /verify-delivery-otp."
        )

    order.status = payload.status

    if payload.status == DeliveryStatus.GOING_TO_PICKUP:
        pass
    elif payload.status == DeliveryStatus.ARRIVED_AT_PICKUP:
        pass
    elif payload.status == DeliveryStatus.OUT_FOR_DELIVERY:
        pass
    elif payload.status == DeliveryStatus.ARRIVED_AT_DESTINATION:
        pass
    elif payload.status == DeliveryStatus.CANCELLED:
        order.cancelled_reason = payload.notes or "Cancelled by partner"
        partner.is_available = True

    db.commit()

    # Broadcast state machine transition to buyer tracking page
    await delivery_ws_manager.broadcast_status(order.id, payload.status.value, {
        "notes": payload.notes
    })

    return {
        "message": f"Status successfully updated to '{payload.status.value}'",
        "order_id": order.id,
        "current_status": order.status.value
    }

# ====================================================
# --- OTP Verifications (Pickup & Delivery) ---
# ====================================================

@delivery_router.post("/orders/{order_id}/verify-pickup-otp")
async def verify_pickup_otp(
    order_id: int,
    payload: OTPVerifySchema,
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Partner verifies 6-digit pickup OTP provided by the farmer gate."""
    order = db.query(DeliveryOrder).filter(
        DeliveryOrder.id == order_id,
        DeliveryOrder.partner_id == partner.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in [DeliveryStatus.ARRIVED_AT_PICKUP, DeliveryStatus.GOING_TO_PICKUP, DeliveryStatus.ACCEPTED]:
        raise HTTPException(status_code=400, detail=f"Cannot verify pickup in status '{order.status.value}'")

    seller_phone = order.seller.phone if order.seller else ""
    verify_db_otp(db, phone=seller_phone, plain_otp=payload.otp_code, otp_type=OTPType.PICKUP, order_id=order.id)

    order.status = DeliveryStatus.PICKED_UP
    order.pickup_time = datetime.utcnow()
    db.commit()

    await delivery_ws_manager.broadcast_status(order.id, DeliveryStatus.PICKED_UP.value, {
        "pickup_time": order.pickup_time.strftime("%I:%M %p")
    })

    return {
        "message": "Pickup OTP verified! Produce secured. Transitioning to OUT_FOR_DELIVERY.",
        "status": DeliveryStatus.PICKED_UP.value
    }

@delivery_router.post("/orders/{order_id}/verify-delivery-otp")
async def verify_delivery_otp(
    order_id: int,
    payload: OTPVerifySchema,
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Partner verifies 6-digit delivery OTP provided by the buyer upon arrival."""
    order = db.query(DeliveryOrder).filter(
        DeliveryOrder.id == order_id,
        DeliveryOrder.partner_id == partner.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    buyer_phone = order.buyer.phone if order.buyer else ""
    verify_db_otp(db, phone=buyer_phone, plain_otp=payload.otp_code, otp_type=OTPType.DELIVERY, order_id=order.id)

    order.status = DeliveryStatus.DELIVERED
    order.delivery_time = datetime.utcnow()

    # Free up partner and increment stats
    partner.is_available = True
    partner.total_deliveries += 1

    # Record partner earnings for this delivery
    base = 50.0
    dist_fee = max(0.0, round(order.distance_km * 10.0, 2))
    total_earned = base + dist_fee

    earning = Earnings(
        partner_id=partner.id,
        order_id=order.id,
        base_fee=base,
        distance_fee=dist_fee,
        tip=0.0,
        total_earning=total_earned,
        status=EarningStatus.PROCESSED
    )
    db.add(earning)
    db.commit()

    await delivery_ws_manager.broadcast_status(order.id, DeliveryStatus.DELIVERED.value, {
        "delivery_time": order.delivery_time.strftime("%I:%M %p"),
        "total_earned": total_earned
    })

    return {
        "message": "Delivery completed and verified! Earnings credited to wallet.",
        "status": DeliveryStatus.DELIVERED.value,
        "earning": {
            "total": total_earned,
            "base_fee": base,
            "distance_fee": dist_fee
        }
    }

# ====================================================
# --- Live GPS Tracking & Location Updates ---
# ====================================================

@delivery_router.post("/orders/{order_id}/location")
async def update_driver_location(
    order_id: int,
    payload: LocationUpdateSchema,
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """
    Called by navigator.geolocation.watchPosition() on the delivery driver device.
    Persists coordinate breadcrumbs to DeliveryLocation and broadcasts via WebSocket.
    """
    order = db.query(DeliveryOrder).filter(
        DeliveryOrder.id == order_id,
        DeliveryOrder.partner_id == partner.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Delivery order not found")

    # Update driver current coordinates
    partner.current_latitude = payload.latitude
    partner.current_longitude = payload.longitude

    # Calculate remaining distance and dynamic ETA to target
    target_lat = order.delivery_latitude if order.status in [DeliveryStatus.PICKED_UP, DeliveryStatus.OUT_FOR_DELIVERY] else order.pickup_latitude
    target_lon = order.delivery_longitude if order.status in [DeliveryStatus.PICKED_UP, DeliveryStatus.OUT_FOR_DELIVERY] else order.pickup_longitude

    rem_distance = haversine_distance(payload.latitude, payload.longitude, target_lat, target_lon)
    # Estimate ETA assuming average urban transit speed 28 km/h + 5 mins buffer
    eta_mins = max(2, int((rem_distance / 28.0) * 60) + 5)

    # Save to breadcrumbs table
    breadcrumb = DeliveryLocation(
        order_id=order.id,
        partner_id=partner.id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        speed=payload.speed,
        heading=payload.heading,
        accuracy=payload.accuracy,
        timestamp=datetime.utcnow()
    )
    db.add(breadcrumb)
    db.commit()

    # Real-time WebSocket broadcast to listening buyers & dispatchers
    await delivery_ws_manager.broadcast_location(
        order_id=order.id,
        partner_id=partner.id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        speed=payload.speed,
        heading=payload.heading,
        distance_km=rem_distance,
        eta_mins=eta_mins
    )

    return {
        "status": "ok",
        "distance_km": rem_distance,
        "eta_mins": eta_mins
    }

# ====================================================
# --- Buyer Tracking View Endpoint ---
# ====================================================

@delivery_router.get("/tracking/{order_id}")
def get_order_tracking_data(order_id: int, db: Session = Depends(get_db)):
    """Public/authorized tracking data payload for /tracking.html buyer view."""
    order = db.query(DeliveryOrder).filter(DeliveryOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Delivery order not found")

    last_location = db.query(DeliveryLocation).filter(
        DeliveryLocation.order_id == order.id
    ).order_by(DeliveryLocation.timestamp.desc()).first()

    partner_info = None
    if order.partner:
        partner_info = {
            "name": order.partner.user.name,
            "phone": order.partner.user.phone,
            "vehicle_type": order.partner.vehicle_type,
            "vehicle_number": order.partner.vehicle_number,
            "rating": order.partner.rating,
            "total_deliveries": order.partner.total_deliveries
        }

    current_lat = last_location.latitude if last_location else (order.partner.current_latitude if order.partner else order.pickup_latitude)
    current_lon = last_location.longitude if last_location else (order.partner.current_longitude if order.partner else order.pickup_longitude)

    rem_km = haversine_distance(current_lat, current_lon, order.delivery_latitude, order.delivery_longitude)
    eta_mins = max(3, int((rem_km / 28.0) * 60) + 5) if order.status != DeliveryStatus.DELIVERED else 0

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "crop_name": order.crop_name,
        "quantity": order.quantity,
        "status": order.status.value,
        "pickup": {
            "latitude": order.pickup_latitude,
            "longitude": order.pickup_longitude,
            "address": order.pickup_address,
            "seller_name": order.seller.name if order.seller else "Farmer"
        },
        "delivery": {
            "latitude": order.delivery_latitude,
            "longitude": order.delivery_longitude,
            "address": order.delivery_address,
            "buyer_name": order.buyer.name if order.buyer else "Buyer"
        },
        "partner": partner_info,
        "current_position": {
            "latitude": current_lat,
            "longitude": current_lon,
            "speed": last_location.speed if last_location else 0.0,
            "heading": last_location.heading if last_location else 0.0,
            "timestamp": last_location.timestamp.isoformat() if last_location else None
        },
        "distance_remaining_km": rem_km,
        "eta_minutes": eta_mins,
        "delivery_otp_code": order.delivery_otp_code,  # Visible to buyer on their tracking page
        "created_at": order.created_at.strftime("%b %d, %I:%M %p")
    }

# ====================================================
# --- Earnings & KYC Endpoints ---
# ====================================================

@delivery_router.get("/earnings")
def get_partner_earnings(
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Retrieve driver earnings summary and trip records."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    all_earnings = db.query(Earnings).filter(Earnings.partner_id == partner.id).all()
    today_earnings = sum(e.total_earning for e in all_earnings if e.date >= today_start)
    week_earnings = sum(e.total_earning for e in all_earnings if e.date >= week_start)
    total_earnings = sum(e.total_earning for e in all_earnings)

    trips = []
    for e in sorted(all_earnings, key=lambda x: x.date, reverse=True)[:15]:
        trips.append({
            "order_number": e.order.order_number if e.order else f"#{e.order_id}",
            "crop": e.order.crop_name if e.order else "Produce",
            "date": e.date.strftime("%b %d, %Y"),
            "base_fee": e.base_fee,
            "distance_fee": e.distance_fee,
            "total": e.total_earning,
            "status": e.status.value
        })

    return {
        "summary": {
            "today": round(today_earnings, 2),
            "this_week": round(week_earnings, 2),
            "total_lifetime": round(total_earnings, 2),
            "total_trips": len(all_earnings)
        },
        "trips": trips
    }

@delivery_router.post("/kyc/upload")
def update_kyc_details(
    payload: KYCUpdateSchema,
    partner: DeliveryPartner = Depends(require_verified_delivery_partner),
    db: Session = Depends(get_db)
):
    """Upload or update KYC document numbers for verification."""
    profile = partner.profile
    if not profile:
        profile = DeliveryPartnerProfile(partner_id=partner.id)
        db.add(profile)

    if payload.driving_license_no:
        profile.driving_license_no = payload.driving_license_no.strip()
    if payload.aadhar_no:
        profile.aadhar_no = payload.aadhar_no.strip()
    if payload.vehicle_rc_no:
        profile.vehicle_rc_no = payload.vehicle_rc_no.strip()
    if payload.emergency_contact:
        profile.emergency_contact = payload.emergency_contact.strip()

    profile.kyc_status = KYCStatus.VERIFIED  # Auto-verify in demo mode
    partner.is_verified = True
    db.commit()

    return {
        "message": "KYC document details updated and verified successfully.",
        "kyc_status": profile.kyc_status.value
    }


# ====================================================
# --- Additional Index.html Delivery Compatibility Routes ---
# ====================================================

@delivery_router.get("/my-profile")
def get_my_delivery_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == user.id).first()
    if not partner:
        raise HTTPException(status_code=404, detail="Delivery partner profile not found")
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
        "total_deliveries": partner.total_deliveries
    }

@delivery_router.get("/my-assignments")
def get_my_delivery_assignments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == user.id).first()
    if not partner:
        return []
    orders = db.query(DeliveryOrder).filter(DeliveryOrder.partner_id == partner.id).order_by(DeliveryOrder.created_at.desc()).all()
    results = []
    for o in orders:
        results.append({
            "assignment_id": o.id,
            "order_id": o.id,
            "order_number": o.order_number,
            "crop": o.crop_name,
            "quantity": o.quantity,
            "total_amount": o.total_amount,
            "seller_name": o.seller.name if o.seller else "Farmer",
            "buyer_name": o.buyer.name if o.buyer else "Buyer",
            "pickup_address": o.pickup_address,
            "delivery_address": o.delivery_address,
            "status": o.status.value,
            "otp_code": o.delivery_otp_code if o.delivery_otp_code else (o.pickup_otp_code or "123456"),
            "created_at": o.created_at.strftime("%b %d, %Y %H:%M")
        })
    return results

@delivery_router.put("/update-status/{assignment_id}")
async def update_assignment_status(
    assignment_id: int,
    payload: StatusUpdateSchema,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == user.id).first()
    if not partner:
        raise HTTPException(status_code=404, detail="Delivery partner profile not found")
    
    order = db.query(DeliveryOrder).filter(
        DeliveryOrder.id == assignment_id,
        DeliveryOrder.partner_id == partner.id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Delivery assignment not found")
    
    order.status = payload.status
    if payload.status == DeliveryStatus.DELIVERED:
        partner.is_available = True
        partner.total_deliveries += 1
    db.commit()
    
    return {
        "message": f"Status updated to '{payload.status.value}'",
        "order_id": order.id,
        "status": order.status.value
    }

