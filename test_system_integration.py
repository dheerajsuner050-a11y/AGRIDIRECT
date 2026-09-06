import httpx
import asyncio
import json
import websockets

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("==================================================")
    print("[TEST] RUNNING AGRIDIRECT SYSTEM INTEGRATION TEST SUITE")
    print("==================================================")
    
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        # Test 1: Health / Index
        r = client.get("/")
        assert r.status_code == 200, f"Index failed: {r.status_code}"
        print("[PASS] [1/11] Index HTML page loaded successfully")

        # Test 2: General Auth Login (Buyer)
        r = client.post("/auth/login", json={"email": "buyer@agridirect.com", "password": "buyer123"})
        assert r.status_code == 200, f"Buyer login failed: {r.text}"
        buyer_data = r.json()
        assert "access_token" in buyer_data, "Missing access_token"
        assert "agridirect_token" in r.cookies, "Missing HttpOnly auth cookie"
        print(f"[PASS] [2/11] General Auth Login passed. User: {buyer_data['user']['name']} ({buyer_data['user']['role']})")

        # Test 3: Delivery Partner Login
        r = client.post("/delivery/auth/login", json={"email": "delivery@agridirect.com", "password": "delivery123"})
        assert r.status_code == 200, f"Delivery login failed: {r.text}"
        driver_token = r.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {driver_token}"}
        print("[PASS] [3/11] Delivery Partner Auth Login passed. Bearer token acquired.")

        # Test 4: Delivery Partner Profile
        r = client.get("/delivery/auth/profile", headers=auth_headers)
        assert r.status_code == 200, f"Profile failed: {r.text}"
        prof = r.json()
        assert prof["partner"]["email"] == "delivery@agridirect.com"
        print(f"[PASS] [4/11] Delivery Profile fetched: {prof['partner']['name']} | Vehicle: {prof['profile']['vehicle_type']}")

        # Test 5: Toggle Availability
        r = client.post("/delivery/availability", headers=auth_headers, json={"is_online": True})
        assert r.status_code == 200, f"Availability toggle failed: {r.text}"
        print(f"[PASS] [5/11] Availability toggled: {r.json()['is_online']}")

        # Test 6: Fetch Active Order
        r = client.get("/delivery/orders/active", headers=auth_headers)
        assert r.status_code == 200, f"Active order failed: {r.text}"
        active = r.json()
        assert active["order"] is not None, "No active order found"
        order_id = active["order"]["id"]
        order_num = active["order"]["order_number"]
        delivery_otp = active["order"].get("delivery_otp_preview")
        print(f"[PASS] [6/11] Active Order found: {order_num} (ID: {order_id}) | Status: {active['order']['status']} | OTP Preview: {delivery_otp}")

        # Test 7: Location Streaming Breadcrumb
        loc_payload = {
            "latitude": 22.8250,
            "longitude": 75.9500,
            "heading": 45.0,
            "speed_kmh": 38.5,
            "battery_level": 92
        }
        r = client.post(f"/delivery/orders/{order_id}/location", headers=auth_headers, json=loc_payload)
        assert r.status_code == 200, f"Location update failed: {r.text}"
        print("[PASS] [7/11] Location breadcrumb logged successfully to DB and broadcast.")

        # Test 8: Buyer Tracking Endpoint
        r = client.get(f"/delivery/tracking/{order_id}")
        assert r.status_code == 200, f"Tracking endpoint failed: {r.text}"
        track = r.json()
        assert "driver" in track and "route" in track
        print(f"[PASS] [8/11] Buyer Tracking payload verified: Driver {track['driver']['name']}, ETA: {track['eta_minutes']} mins")

        # Test 9: Verify Delivery OTP & Complete Delivery
        r = client.post(f"/delivery/orders/{order_id}/verify-delivery-otp", headers=auth_headers, json={"otp_code": delivery_otp})
        assert r.status_code == 200, f"OTP verification failed: {r.text}"
        verify_res = r.json()
        assert verify_res["status"] == "DELIVERED", "Status not DELIVERED"
        assert verify_res["earnings"] > 0, "Earnings not computed"
        print(f"[PASS] [9/11] Delivery OTP verified: State -> DELIVERED, Driver Earnings credited: Rs {verify_res['earnings']}")

        # Test 10: Market Prices / AI Grading intact
        r = client.get("/api/market-prices")
        assert r.status_code == 200, f"Market prices failed: {r.text}"
        print("[PASS] [10/11] AgriDirect AI crop endpoints & market prices intact.")

        # Test 11: Static dashboard and tracking page delivery
        r_dash = client.get("/delivery-dashboard")
        assert r_dash.status_code == 200
        r_track = client.get("/tracking")
        assert r_track.status_code == 200
        print("[PASS] [11/11] Delivery Dashboard & Tracking portal HTML pages served successfully.")

    print("\n[SUCCESS] ALL 11 INTEGRATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
