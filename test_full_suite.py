import httpx
import os

BASE_URL = "http://127.0.0.1:8000"

def test_all():
    print("==================================================")
    print("   AGRIDIRECT AI — FULL SYSTEM COMPREHENSIVE TEST  ")
    print("==================================================")
    
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # 1. GET Homepage (Receives CSRF Token Cookie)
        r = client.get("/")
        print(f"[1] GET / -> Status {r.status_code}")
        assert r.status_code == 200

        csrf_token = client.cookies.get("agridirect_csrf_token", "")
        csrf_headers = {"x-csrf-token": csrf_token} if csrf_token else {}
        print(f"    [CSRF Token Acquired]: {csrf_token[:10]}...")

        # 2. Mandi Prices API
        r = client.get("/api/market-prices")
        print(f"[2] GET /api/market-prices -> Status {r.status_code}, Items: {len(r.json())}")
        assert r.status_code == 200

        # 3. Register New Farmer
        farmer_email = f"farmer_test_{os.urandom(3).hex()}@test.com"
        reg_payload = {
            "name": "Test Farmer",
            "email": farmer_email,
            "phone": "9876500111",
            "password": "password123",
            "role": "seller"
        }
        r = client.post("/auth/register", json=reg_payload)
        print(f"[3] POST /auth/register (Farmer) -> Status {r.status_code}")
        assert r.status_code == 200
        farmer_token = r.json()["access_token"]

        # 4. Register New Buyer
        buyer_email = f"buyer_test_{os.urandom(3).hex()}@test.com"
        reg_buyer = {
            "name": "Test Buyer",
            "email": buyer_email,
            "phone": "9876500222",
            "password": "password123",
            "role": "buyer"
        }
        r = client.post("/auth/register", json=reg_buyer)
        print(f"[4] POST /auth/register (Buyer) -> Status {r.status_code}")
        assert r.status_code == 200
        buyer_token = r.json()["access_token"]

        # 5. Register Delivery Partner
        deliv_email = f"delivery_test_{os.urandom(3).hex()}@test.com"
        reg_deliv = {
            "name": "Test Driver",
            "email": deliv_email,
            "phone": "9876500333",
            "password": "password123",
            "vehicle_type": "Bike",
            "vehicle_number": "MP09XY9999",
            "license_number": "MP0920260099"
        }
        r = client.post("/delivery/auth/register", json=reg_deliv)
        print(f"[5] POST /delivery/auth/register -> Status {r.status_code}")
        assert r.status_code == 200

        # 6. Login Existing User
        r = client.post("/auth/login", json={"email": farmer_email, "password": "password123"})
        print(f"[6] POST /auth/login -> Status {r.status_code}, User: {r.json()['user']['name']}")
        assert r.status_code == 200

        # 7. Mobile OTP Login Flow
        r = client.post("/auth/send-otp", json={"phone": "9876500111"})
        print(f"[7a] POST /auth/send-otp -> Status {r.status_code}")
        assert r.status_code == 200
        otp = r.json().get("otp_preview")
        
        if otp:
            r = client.post("/auth/verify-otp", json={"phone": "9876500111", "otp_code": otp})
            print(f"[7b] POST /auth/verify-otp -> Status {r.status_code}, Verified!")
            assert r.status_code == 200

        # Refresh CSRF Cookie after auth operations
        csrf_token = client.cookies.get("agridirect_csrf_token", "")
        csrf_headers = {"x-csrf-token": csrf_token} if csrf_token else {}

        # 8. Create Listing as Farmer
        farmer_headers = {"Authorization": f"Bearer {farmer_token}", **csrf_headers}
        listing_payload = {
            "crop_name": "Tomato",
            "category": "Vegetables",
            "quantity": 300,
            "price_per_kg": 35.0,
            "quality": "Good",
            "description": "Fresh red tomatoes"
        }
        r = client.post("/api/seller/listings", headers=farmer_headers, json=listing_payload)
        print(f"[8] POST /api/seller/listings -> Status {r.status_code}, Response: {r.json()}")
        assert r.status_code == 200
        listing_id = r.json()["listing_id"]

        # 9. View Marketplace
        r = client.get("/api/marketplace")
        print(f"[9] GET /api/marketplace -> Status {r.status_code}, Total Listings: {len(r.json())}")
        assert r.status_code == 200

        # 10. Multi-item Cart Checkout as Buyer
        buyer_headers = {"Authorization": f"Bearer {buyer_token}", **csrf_headers}
        cart_payload = {
            "items": [{"listing_id": listing_id, "quantity": 50}],
            "delivery_address": "Indore Warehouse Sector 9"
        }
        r = client.post("/api/orders/place-cart", headers=buyer_headers, json=cart_payload)
        print(f"[10] POST /api/orders/place-cart -> Status {r.status_code}, Orders: {len(r.json().get('orders', []))}")
        assert r.status_code == 200

        # 11. My Orders
        r = client.get("/api/orders/my-orders", headers=buyer_headers)
        print(f"[11] GET /api/orders/my-orders -> Status {r.status_code}, Total Orders: {len(r.json())}")
        assert r.status_code == 200

    print("\n==================================================")
    print("  SUCCESS: ALL COMPREHENSIVE ENDPOINTS ARE WORKING!")
    print("==================================================")

if __name__ == "__main__":
    test_all()
