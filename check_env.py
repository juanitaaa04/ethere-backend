from dotenv import load_dotenv
import os

load_dotenv()

cid = os.getenv("PAYPAL_CLIENT_ID")
secret = os.getenv("PAYPAL_SECRET")

print("PAYPAL_CLIENT_ID:", "✅ Loaded" if cid else "❌ Missing")
print("PAYPAL_SECRET:", "✅ Loaded" if secret else "❌ Missing")
