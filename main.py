from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os, httpx
from typing import List
import razorpay  # ✅ Added Razorpay

load_dotenv()

app = FastAPI()

# Allow your dev origins (keep "*" only while testing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ethere.in/", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PAYPAL_BASE = "https://api-m.sandbox.paypal.com"
CURRENCY = "USD"
INR_TO_USD = 83.0  # Replace with your own rate or pricing logic

# ======== PAYPAL FUNCTIONS (unchanged) ========

def inr_to_usd(amount_in_inr: float) -> float:
    return round(float(amount_in_inr) / INR_TO_USD, 2)

async def get_paypal_access_token() -> str:
    cid = os.getenv("PAYPAL_CLIENT_ID", "")
    secret = os.getenv("PAYPAL_SECRET", "")
    if not cid or not secret:
        raise HTTPException(500, "Missing PAYPAL_CLIENT_ID or PAYPAL_SECRET in .env")

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{PAYPAL_BASE}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(cid, secret),
        )
        if r.status_code != 200:
            print("❌ PayPal Auth Error:", r.text)
            raise HTTPException(500, f"PayPal auth failed: {r.text}")
        return r.json()["access_token"]

@app.get("/api/config")
async def get_config():
    cid = os.getenv("PAYPAL_CLIENT_ID")
    if not cid:
        raise HTTPException(500, "PAYPAL_CLIENT_ID not set in .env")
    return {"client_id": cid, "currency": CURRENCY, "env": "sandbox"}

@app.post("/api/orders")
async def create_order(payload: dict):
    cart: List[dict] = payload.get("items", [])

    if not cart:
        raise HTTPException(400, "Cart is empty")

    print("\n🛒 Frontend cart received:", cart)

    paypal_items = []
    total_usd = 0.0
    for item in cart:
        qty = int(item.get("quantity", 1))
        price_inr = float(item.get("price", 0))
        unit_usd = inr_to_usd(price_inr)
        total_usd += unit_usd * qty

        paypal_items.append({
            "name": item.get("name", "Item"),
            "quantity": str(qty),
            "unit_amount": {
                "currency_code": CURRENCY,
                "value": f"{unit_usd:.2f}"
            }
        })

    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {
                "currency_code": CURRENCY,
                "value": f"{total_usd:.2f}",
                "breakdown": {
                    "item_total": {
                        "currency_code": CURRENCY,
                        "value": f"{total_usd:.2f}"
                    }
                }
            },
            "items": paypal_items
        }]
    }

    print("📦 Payload to PayPal:", body)

    access_token = await get_paypal_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{PAYPAL_BASE}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=body,
        )

        print("💬 PayPal response status:", r.status_code)
        print("💬 PayPal raw response:", r.text)

        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"error": r.text}

        if r.status_code not in (200, 201):
            return {
                "error": True,
                "status_code": r.status_code,
                "paypal_error": resp_json
            }

        return resp_json


@app.post("/api/orders/{order_id}/capture")
async def capture_order(order_id: str):
    access_token = await get_paypal_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )
        if r.status_code not in (200, 201):
            print("❌ Capture error:", r.text)
            try:
                return {"error": True, "status_code": r.status_code, "paypal_error": r.json()}
            except Exception:
                return {"error": True, "status_code": r.status_code, "paypal_error": r.text}
        return r.json()
    
@app.post("/api/orders/notify")
async def notify_owner(payload: dict):
    print("📢 NEW PAID ORDER RECEIVED")
    print("Customer:", payload.get("name"))
    print("Email:", payload.get("email"))
    print("Phone:", payload.get("phone"))
    print("Address:", payload.get("address"))
    print("Delivery:", payload.get("delivery"))
    print("Payment ID:", payload.get("payment_id"))

    for item in payload.get("items", []):
        print(f"{item['name']} x{item['quantity']} - ₹{item['price']}")

    return {"message": "Owner notified"}


# ======== RAZORPAY FUNCTIONS (added) ========

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    print("⚠️ Razorpay keys missing in .env")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

@app.get("/api/razorpay/config")
async def get_razorpay_config():
    """Send Razorpay Key ID to frontend."""
    if not RAZORPAY_KEY_ID:
        raise HTTPException(500, "RAZORPAY_KEY_ID not set in .env")
    return {"key": RAZORPAY_KEY_ID, "currency": "INR"}

@app.post("/api/razorpay/create-order")
async def razorpay_create_order(payload: dict):
    cart: List[dict] = payload.get("items", [])
    if not cart:
        raise HTTPException(400, "Cart is empty")

    total_inr = 0
    for item in cart:
        qty = int(item.get("quantity", 1))
        price_inr = float(item.get("price", 0))
        total_inr += price_inr * qty

    amount_paise = int(total_inr * 100)  # Razorpay needs paise
    order = razorpay_client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "payment_capture": 1
    })

    return {"order": order}

@app.post("/api/razorpay/verify")
async def razorpay_verify(payload: dict):
    """
    Verify payment signature sent from frontend after success.
    """
    try:
        razorpay_client.utility.verify_payment_signature(payload)
        return {"status": "success"}
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(400, "Invalid Razorpay signature")
