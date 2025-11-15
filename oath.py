import os
import json
import time
import threading  # <-- Added for file-write safety
from urllib.parse import urlencode

from flask import Flask, redirect, request, jsonify
import requests
import boto3

app = Flask(__name__)

# === CONFIG ===
CLIENT_ID = int(os.getenv("ZID_CLIENT_ID", "5410"))
CLIENT_SECRET = os.getenv("ZID_CLIENT_SECRET", "1ACdU5lGCsCCw0iOPPEKkWfLyMVaIcbopDOjaahO")
REDIRECT_URI = os.getenv("ZID_REDIRECT_URI", "https://m5dzci.zid.store")

OAUTH_BASE = "https://oauth.zid.sa"
AUTHORIZE_URL = f"{OAUTH_BASE}/oauth/authorize"
TOKEN_URL = f"{OAUTH_BASE}/oauth/token"
API_BASE = "https://api.zid.sa/v1"

# === NEW: JSON Database ===
JSON_DB_FILE = "merchants.json"
# This lock is crucial to prevent race conditions
# where two requests try to write to the file at the same time.
db_lock = threading.Lock()

# === Boto3 Clients (Initialize once) ===
personalize_runtime = boto3.client('personalize-runtime', region_name='your-aws-region')
personalize_events = boto3.client('personalize-events', region_name='your-aws-region')

# === NEW: JSON Database Helpers ===

def load_db():
    """Safely loads the JSON database from file."""
    with db_lock:
        try:
            with open(JSON_DB_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}  # Return an empty dict if file is empty or missing

def save_db(data):
    """Safely saves data to the JSON database file."""
    with db_lock:
        with open(JSON_DB_FILE, "w") as f:
            json.dump(data, f, indent=2)

# === Auth Helpers (Modified for JSON DB) ===

def save_merchant_tokens(store_id, token_resp, manager_token):
    """Saves merchant tokens to the JSON file."""
    db_data = load_db()
    
    expires_at = int(time.time()) + int(token_resp.get("expires_in", 3600))
    
    # In a real app, you would provision AWS resources here and get these IDs
    placeholder_tracking_id = "YOUR_TRACKING_ID_FOR_" + str(store_id)
    placeholder_campaign_arn = "YOUR_CAMPAIGN_ARN_FOR_" + str(store_id)

    # Add or update the data for this store_id
    db_data[store_id] = {
        "store_id": store_id,
        "access_token": token_resp["access_token"],
        "refresh_token": token_resp["refresh_token"],
        "manager_token": manager_token,
        "expires_at": expires_at,
        "tracking_id": placeholder_tracking_id, # You must update this after provisioning
        "campaign_arn": placeholder_campaign_arn # You must update this after provisioning
    }
    
    save_db(db_data)
    print(f"Saved tokens for store {store_id}")

def get_merchant_by_store_id(store_id):
    """Fetches merchant data from the JSON file by store_id."""
    db_data = load_db()
    merchant = db_data.get(store_id)
    
    # You should add refresh logic here if token_is_expired(merchant['expires_at'])
    return merchant

def get_store_info_from_token(token_resp):
    """
    Helper to call Zid API immediately after auth to get store_id
    and manager_token. (No changes needed here)
    """
    try:
        auth_token = token_resp.get("access_token")
        manager_token = token_resp.get("manager_token") or token_resp.get("x_manager_token") or auth_token
        
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "X-MANAGER-TOKEN": manager_token,
            "Accept": "application/json"
        }
        url = API_BASE + "/app/v1/managers/account/profile"
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        
        profile = r.json()
        store_id = profile.get("store", {}).get("id") 
        if not store_id:
             raise Exception("Could not find store_id in profile response")

        return str(store_id), manager_token
        
    except Exception as e:
        print(f"Error getting profile: {e}")
        return None, None

# === Auth Routes (No changes needed here) ===

@app.route("/")
def index():
    return "<p>My Recommendation App Backend. Use /install to start.</p>"

@app.route("/install")
def install():
    scopes = request.args.get("scopes", "read_products,read_orders")
    redirect_url = f"{AUTHORIZE_URL}?{urlencode({'client_id': CLIENT_ID, 'redirect_uri': REDIRECT_URI, 'response_type': 'code', 'scope': scopes})}"
    return redirect(redirect_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Missing code parameter", 400

    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    resp = requests.post(TOKEN_URL, data=payload, timeout=10)
    if resp.status_code != 200:
        return f"Token endpoint error: {resp.text}", resp.status_code

    token_resp = resp.json()

    store_id, manager_token = get_store_info_from_token(token_resp)
    if not store_id:
        return "Could not fetch store profile. Installation failed.", 500

    # Save tokens to our new JSON database
    save_merchant_tokens(store_id, token_resp, manager_token)
    
    # *** PROVISIONING STEP (To-Do) ***
    # (Same as before)
    # This is where you would start a background job to:
    # 1. Fetch products/orders from Zid API -> Create CSVs -> Upload to S3
    # 2. Create AWS Personalize resources
    # 3. Update the merchant's entry in merchants.json with the real tracking_id and campaign_arn

    return f"App installed successfully for store {store_id}!"

# === API ENDPOINTS (No changes needed here) ===

@app.route("/track", methods=["POST"])
def track_event():
    """Receives tracking data from the frontend snippet."""
    data = request.json
    store_id = data.get("store_id")
    merchant = get_merchant_by_store_id(store_id)
    
    if not merchant or not merchant.get("tracking_id"):
        return jsonify({"error": "Store not configured"}), 404

    try:
        personalize_events.put_events(
            trackingId=merchant["tracking_id"],
            userId=data.get("user_id"),
            sessionId=data.get("session_id"),
            eventList=[{
                'eventType': data.get("event_type"),
                'itemId': data.get("item_id"),
                'sentAt': int(time.time())
            }]
        )
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error putting event: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/recommend/related", methods=["GET"])
def get_related_items():
    """Serves related-item recommendations to the snippet."""
    store_id = request.args.get("store_id")
    item_id = request.args.get("item_id")
    user_id = request.args.get("user_id")
    
    merchant = get_merchant_by_store_id(store_id)
    if not merchant or not merchant.get("campaign_arn"):
        return jsonify({"error": "Store not configured"}), 404

    try:
        params = {
            'campaignArn': merchant["campaign_arn"],
            'itemId': item_id,
            'numResults': 10
        }
        if user_id:
            params['userId'] = user_id
            
        response = personalize_runtime.get_recommendations(**params)
        return jsonify(response)
        
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        return jsonify({"error": "Internal server error"}), 500

# === Run ===
if __name__ == "__main__":
    # The JSON file will be created automatically on first install
    app.run(host="0.0.0.0", port=5000, debug=True)