import os
import json
import time
import threading  # <-- Added for file-write safety
from urllib.parse import urlencode

from flask import Flask, redirect, request, jsonify
import requests
import boto3
import logging  # Import logging

# Make functions available for import
__all__ = [
    'load_db', 'save_db', 'get_merchant_by_store_id', 
    'CLIENT_ID', 'CLIENT_SECRET', 'TOKEN_URL', 'API_BASE',
    'token_is_expired', 'refresh_merchant_token'
]


app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === CONFIG ===
CLIENT_ID = int(os.getenv("ZID_CLIENT_ID", "5410"))
CLIENT_SECRET = os.getenv("ZID_CLIENT_SECRET", "1ACdU5lGCsCCw0iOPPEKkWfLyMVaIcbopDOjaahO")
REDIRECT_URI = "https://asnb-app.duckdns.org/callback"

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
    """
    Saves merchant tokens to the JSON file.
    Note: According to Zid docs, tokens expire in 1 year, but expires_in 
    is provided in the response and should be used for calculation.
    """
    db_data = load_db()
    
    # Calculate expiry time (tokens expire in 1 year according to docs, but use expires_in if provided)
    expires_in = token_resp.get("expires_in", 31536000)  # Default to 1 year in seconds if not provided
    expires_at = int(time.time()) + int(expires_in)
    
    # In a real app, you would provision AWS resources here and get these IDs
    placeholder_tracking_id = "YOUR_TRACKING_ID_FOR_" + str(store_id)
    placeholder_campaign_arn = "YOUR_CAMPAIGN_ARN_FOR_" + str(store_id)

    # Add or update the data for this store_id
    db_data[store_id] = {
        "store_id": store_id,
        "access_token": token_resp.get("access_token"),
        "authorization": token_resp.get("authorization"),  # Store authorization field if present
        "refresh_token": token_resp.get("refresh_token"),
        "manager_token": manager_token,  # This is actually the access_token used as Access-Token header
        "expires_at": expires_at,
        "tracking_id": placeholder_tracking_id, # You must update this after provisioning
        "campaign_arn": placeholder_campaign_arn # You must update this after provisioning
    }
    
    save_db(db_data)
    logger.info(f"Saved tokens for store {store_id}")

def token_is_expired(expires_at):
    """Check if token has expired (with 60 second safety margin)."""
    if not expires_at:
        return True
    return time.time() >= (expires_at - 60)

def get_merchant_by_store_id(store_id):
    """Fetches merchant data from the JSON file by store_id."""
    db_data = load_db()
    merchant = db_data.get(store_id)
    
    # Check if token needs refresh
    if merchant and token_is_expired(merchant.get('expires_at')):
        logger.info(f"Token expired for store {store_id}, attempting refresh...")
        refreshed = refresh_merchant_token(store_id)
        if refreshed:
            merchant = refreshed
    
    return merchant

def refresh_merchant_token(store_id):
    """Refreshes the access token for a merchant using their refresh token."""
    db_data = load_db()
    merchant = db_data.get(store_id)
    
    if not merchant or not merchant.get("refresh_token"):
        logger.warning(f"No refresh token found for store {store_id}")
        return None
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": merchant["refresh_token"],
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    
    try:
        resp = requests.post(TOKEN_URL, data=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Token refresh failed: {resp.status_code} {resp.text}")
            return None
        
        token_resp = resp.json()
        # Update the merchant's tokens
        save_merchant_tokens(store_id, token_resp, merchant.get("manager_token"))
        
        # Return the updated merchant data
        return load_db().get(store_id)
    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        return None

def get_store_info_from_token(token_resp):
    """
    Helper to call Zid API immediately after auth to get store_id
    and manager_token.
    Based on actual Zid API requirements:
    - Authorization header: Bearer token (from authorization field or access_token)
    - Access-Token header: Manager token (from access_token or authorization)
    - Store-Id header: Store ID (will be extracted from profile response)
    - Role header: Manager
    """
    try:
        # Token response has: access_token, authorization, refresh_token, etc.
        logger.info(f"Token response keys: {list(token_resp.keys())}")
        
        # Use authorization field if available, otherwise use access_token
        auth_token = token_resp.get("authorization") or token_resp.get("access_token")
        if not auth_token:
            logger.error("No authorization or access_token in token response!")
            logger.error(f"Token response keys: {list(token_resp.keys())}")
            return None, None
        
        # Access-Token header uses access_token (manager token)
        access_token = token_resp.get("access_token")
        if not access_token:
            logger.error("No access_token in token response!")
            return None, None
        
        logger.info("Attempting to fetch store profile from Zid API...")
        logger.info(f"Using Authorization token: {auth_token}...")
        logger.info(f"Using Access-Token: {access_token}...")
        
        # Try first call without Store-Id (to get the store_id from profile)
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Access-Token": access_token,
            "Accept": "application/json",
            "Accept-Language": "en",
            "Role": "Manager"
        }
        url = API_BASE + "/app/v1/managers/account/profile"
        logger.info(f"Calling: {url}")
        
        r = requests.get(url, headers=headers, timeout=10)
        
        logger.info(f"Profile API response status: {r.status_code}")
        logger.info(f"Profile API response headers: {dict(r.headers)}")
        
        if r.status_code != 200:
            logger.error(f"Profile API error: {r.status_code}")
            logger.error(f"Response text: {r.text}")
            logger.error(f"Response headers: {dict(r.headers)}")
            return None, None
        
        profile = r.json()
        logger.info(f"Profile response keys: {list(profile.keys())}")
        logger.info(f"Full profile response: {json.dumps(profile, indent=2)}")
        
        # Try different possible paths for store_id
        store_id = None
        
        # Try common response structures
        if "store" in profile:
            if isinstance(profile["store"], dict):
                store_id = profile["store"].get("id") or profile["store"].get("store_id")
            else:
                store_id = profile["store"]
        
        if not store_id and "data" in profile:
            data = profile["data"]
            if isinstance(data, dict):
                if "store" in data:
                    store_obj = data["store"]
                    if isinstance(store_obj, dict):
                        store_id = store_obj.get("id") or store_obj.get("store_id")
                    else:
                        store_id = store_obj
                else:
                    store_id = data.get("id") or data.get("store_id")
        
        if not store_id and "id" in profile:
            store_id = profile.get("id")
        
        # Also check if store_id is directly in response
        if not store_id:
            store_id = profile.get("store_id")
        
        if not store_id:
            logger.error("Could not find store_id in profile response!")
            logger.error(f"Profile structure: {json.dumps(profile, indent=2)}")
            # Try to extract from any nested structure
            import json as json_module
            profile_str = json_module.dumps(profile)
            logger.error(f"Full profile JSON: {profile_str}")
            return None, None

        logger.info(f"Successfully extracted store_id: {store_id}")
        # Return store_id and access_token (which is used as Access-Token header)
        return str(store_id), access_token
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error getting profile: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response text: {e.response.text}")
        return None, None
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None, None

# === Auth Routes (No changes needed here) ===
    
@app.route("/")
def index():
    logger.debug("Index route accessed")
    return f"""
    <h2>Zid OAuth App Backend</h2>
    <p>Use <a href="/install">/install</a> to start the OAuth flow.</p>
    <hr>
    <h3>Configuration Check:</h3>
    <ul>
        <li><strong>Client ID:</strong> {CLIENT_ID}</li>
        <li><strong>Redirect URI:</strong> <code>{REDIRECT_URI}</code> ✅ Registered</li>
        <li><strong>OAuth Base:</strong> {OAUTH_BASE}</li>
    </ul>
    <hr>
    <h3>📊 View Data:</h3>
    <ul>
        <li><a href="/data">📈 Data Dashboard</a> - Visual view of all merchants</li>
        <li><a href="/merchants">📋 Merchants API</a> - JSON list of all merchants</li>
    </ul>
    <hr>
    <div style="background: #d1ecf1; padding: 15px; margin: 20px 0; border-left: 4px solid #0c5460;">
        <h3>⚠️ If you see error_code=UNKNOWN:</h3>
        <ol>
            <li><strong>Verify Client ID:</strong> Check Partner Dashboard - your Client ID should be <code>{CLIENT_ID}</code></li>
            <li><strong>Check App Status:</strong> Ensure app is <strong>Published/Approved</strong> (not Draft)</li>
            <li><strong>Application URL:</strong> Should match: <code>https://asnb-app.duckdns.org</code></li>
        </ol>
    </div>
    <p><a href="/verify">Click here to verify your configuration</a></p>
    """

@app.route("/test-install")
def test_install():
    """Test install route matching documentation example exactly (no scope)."""
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code'
    }
    redirect_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
    
    logger.info("=" * 60)
    logger.info("TEST INSTALL (No scope) - Matching docs example")
    logger.info(f"Redirect URL: {redirect_url}")
    logger.info("=" * 60)
    
    return redirect(redirect_url)

@app.route("/error-handler")
def error_handler():
    """Handle errors from Zid marketplace redirects."""
    error_code = request.args.get("error_code")
    app_id = request.args.get("app_id")
    
    logger.error(f"Zid marketplace error: error_code={error_code}, app_id={app_id}")
    
    error_messages = {
        "UNKNOWN": "Unknown error. Check app configuration in Partner Dashboard.",
        "APP_NOT_FOUND": "App not found. Verify Client ID is correct.",
        "APP_NOT_PUBLISHED": "App is not published. Publish your app in Partner Dashboard.",
        "REDIRECT_URI_MISMATCH": "Redirect URI mismatch. Register the redirect URI in Partner Dashboard.",
    }
    
    message = error_messages.get(error_code, f"Error code: {error_code}")
    
    return f"""
    <h2>⚠️ Zid OAuth Error</h2>
    <p><strong>Error Code:</strong> {error_code}</p>
    <p><strong>Message:</strong> {message}</p>
    <hr>
    <h3>Your Configuration:</h3>
    <ul>
        <li><strong>Client ID:</strong> {CLIENT_ID}</li>
        <li><strong>Redirect URI:</strong> <code>{REDIRECT_URI}</code></li>
    </ul>
    <hr>
    <h3>Common Fixes:</h3>
    <ol>
        <li><strong>Verify Client ID:</strong> Make sure Client ID {CLIENT_ID} matches your app in Partner Dashboard</li>
        <li><strong>Register Redirect URI:</strong> Add <code>{REDIRECT_URI}</code> to "Allowed Redirect URIs"</li>
        <li><strong>Publish App:</strong> Ensure your app is Published/Approved (not Draft)</li>
        <li><strong>Check App Status:</strong> Go to Partner Dashboard and verify app is active</li>
    </ol>
    <p><a href="/verify">Go to Verification Page</a> | <a href="https://partner.zid.sa" target="_blank">Zid Partner Dashboard</a></p>
    """

@app.route("/verify")
def verify():
    """Verification endpoint to check OAuth configuration."""
    expected_redirect = REDIRECT_URI
    # Match documentation example (no scope)
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code'
    }
    authorize_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
    
    return f"""
    <h2>OAuth Configuration Verification</h2>
    <h3>Current Configuration:</h3>
    <table border="1" cellpadding="10">
        <tr><td><strong>Client ID</strong></td><td>{CLIENT_ID}</td></tr>
        <tr><td><strong>Redirect URI (Expected)</strong></td><td><code>{expected_redirect}</code></td></tr>
        <tr><td><strong>OAuth Base URL</strong></td><td>{OAUTH_BASE}</td></tr>
    </table>
    
    <div style="background: #fff3cd; padding: 15px; margin: 20px 0; border-left: 4px solid #ffc107;">
        <h3>⚠️ Important Notes:</h3>
        <p><strong>Your Dashboard Configuration:</strong></p>
        <ul>
            <li>✅ Redirect URI: <code>{expected_redirect}</code> - Registered</li>
            <li>✅ Callback URL: <code>{expected_redirect}</code> - Registered</li>
            <li>✅ Application URL: <code>https://asnb-app.duckdns.org</code> - Matches</li>
        </ul>
        <p><strong>If you see error_code=UNKNOWN, check:</strong></p>
        <ol>
            <li><strong>Client ID:</strong> Verify Client ID <code>{CLIENT_ID}</code> matches your app's API Key in Partner Dashboard</li>
            <li><strong>App Status:</strong> Ensure app is <strong>Published/Approved</strong> (not Draft or Pending)</li>
            <li><strong>App Type:</strong> Check if your app type allows OAuth flows</li>
        </ol>
    </div>
    
    <h3>⚠️ CRITICAL: Redirect URI Registration</h3>
    <p>You MUST register this EXACT URL in Zid Partner Dashboard:</p>
    <p style="background: #f0f0f0; padding: 10px; font-family: monospace; font-size: 14px;">
        {expected_redirect}
    </p>
    
    <h3>Steps to Fix:</h3>
    <ol>
        <li>Go to <a href="https://partner.zid.sa" target="_blank">Zid Partner Dashboard</a></li>
        <li>Navigate to your app (Client ID: {CLIENT_ID})</li>
        <li>Find "Allowed Redirect URIs" or "Redirect URIs" section</li>
        <li>Add this EXACT URL (copy-paste to avoid typos):</li>
        <li style="background: #fff3cd; padding: 10px; margin: 10px 0;">
            <code>{expected_redirect}</code>
        </li>
        <li>Ensure your app is <strong>Published/Approved</strong> (not Draft)</li>
        <li>Save changes</li>
    </ol>
    
    <h3>Test OAuth Flow:</h3>
    <p><a href="/install">Start OAuth Flow</a></p>
    <p><strong>Expected OAuth URL:</strong></p>
    <p style="word-break: break-all; background: #f0f0f0; padding: 10px; font-size: 12px;">
        {authorize_url}
    </p>
    
    <h3>Common Issues:</h3>
    <ul>
        <li>❌ Trailing slash: <code>{expected_redirect}/</code></li>
        <li>❌ HTTP instead of HTTPS: <code>http://asnb-app.duckdns.org/callback</code></li>
        <li>❌ Different path: <code>https://asnb-app.duckdns.org/callbacks</code></li>
        <li>✅ Correct: <code>{expected_redirect}</code></li>
    </ul>
    """

@app.route("/install")
def install():
    scopes = request.args.get("scopes", "read_products read_orders")
    # Convert comma-separated to space-separated if needed (Zid expects space-separated)
    if "," in scopes:
        scopes = scopes.replace(",", " ")
    
    # Build query parameters - match documentation example exactly
    # Note: Documentation example doesn't include scope, but it's optional
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code'
    }
    
    # Only add scope if provided (scopes are configured in Partner Dashboard)
    if scopes:
        params['scope'] = scopes
    
    redirect_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
    
    logger.info("=" * 60)
    logger.info("INSTALL ROUTE - Starting OAuth flow")
    logger.info(f"Client ID: {CLIENT_ID}")
    logger.info(f"Redirect URI: {REDIRECT_URI}")
    logger.info(f"Scopes: {scopes}")
    logger.info(f"Full redirect URL: {redirect_url}")
    logger.info("=" * 60)
    
    # Warn if there might be a Client ID mismatch
    logger.warning(f"If redirected to web.zid.sa/market/app/... with error_code=UNKNOWN:")
    logger.warning(f"  - Verify Client ID {CLIENT_ID} matches your app in Partner Dashboard")
    logger.warning(f"  - Ensure app is Published/Approved")
    logger.warning(f"  - Check redirect URI is registered: {REDIRECT_URI}")
    
    return redirect(redirect_url)

@app.route("/callback")
def callback():
    # Log ALL incoming data for debugging
    logger.info("=" * 60)
    logger.info("CALLBACK ROUTE HIT")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Query parameters: {dict(request.args)}")
    logger.info(f"Form data: {dict(request.form)}")
    logger.info(f"Referer: {request.headers.get('Referer', 'No referer')}")
    logger.info("=" * 60)
    
    code = request.args.get("code")
    error = request.args.get("error")
    error_description = request.args.get("error_description")
    
    # Check if this is a direct access (not from Zid OAuth)
    referer = request.headers.get('Referer', '')
    is_from_zid = 'zid.sa' in referer or 'oauth.zid.sa' in referer
    
    if error:
        logger.error(f"OAuth error received: {error}")
        logger.error(f"Error description: {error_description}")
        return f"Error from Zid OAuth: {error}<br>Description: {error_description or 'No description provided'}<br>Check server logs for details.", 400
    
    if not code:
        logger.error("Missing code parameter in callback!")
        logger.error(f"All received parameters: {list(request.args.keys())}")
        logger.error(f"Full request URL: {request.url}")
        logger.error(f"Referer: {referer}")
        logger.error(f"Is from Zid: {is_from_zid}")
        
        # Check if this might be a direct browser access (not from OAuth redirect)
        # If referer is from Zid but no params, it's likely redirect URI mismatch
        if is_from_zid and not request.args:
            logger.error("CRITICAL: Zid redirected but sent NO parameters!")
            logger.error("This means the redirect URI is NOT registered in Partner Dashboard")
            logger.error(f"Expected redirect URI: {REDIRECT_URI}")
        
        # Provide helpful error message based on context
        if not is_from_zid and not request.args:
            error_msg = """
            <h2>OAuth Callback Error</h2>
            <p><strong>Issue:</strong> No authorization code received from Zid.</p>
            <h3>Possible Causes:</h3>
            <ol>
                <li><strong>Redirect URI Mismatch:</strong> The redirect URI in your code must EXACTLY match what's registered in Zid Partner Dashboard.
                    <ul>
                        <li>Expected: <code>https://asnb-app.duckdns.org/callback</code></li>
                        <li>Check: No trailing slash, exact match, same protocol (https)</li>
                    </ul>
                </li>
                <li><strong>App Not Approved:</strong> Your app might need to be approved/published in Zid Partner Dashboard.</li>
                <li><strong>Merchant Denied Access:</strong> The merchant may have cancelled the authorization.</li>
            </ol>
            <h3>How to Fix:</h3>
            <ol>
                <li>Go to <a href="https://partner.zid.sa" target="_blank">Zid Partner Dashboard</a></li>
                <li>Navigate to your app (Client ID: 5410)</li>
                <li>Check "Allowed Redirect URIs" section</li>
                <li>Ensure <code>https://asnb-app.duckdns.org/callback</code> is listed EXACTLY</li>
                <li>Make sure your app is published/approved</li>
            </ol>
            <p><strong>Note:</strong> Check server logs for detailed debugging information.</p>
            """
            return error_msg, 400
        else:
            return f"Missing code parameter.<br>Received parameters: {list(request.args.keys())}<br>Full URL: {request.url}<br>Referer: {referer}<br>Check server logs for more details.", 400
    
    logger.info("Received authorization code, exchanging for tokens...")

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
    logger.info(f"Token response received. Keys: {list(token_resp.keys())}")

    # According to Zid docs, the token response contains:
    # - access_token: Used as Authorization token
    # - refresh_token: Used to refresh tokens
    # - expires_in: Token expiry time
    # - manager_token/x_manager_token: May be included, otherwise use access_token

    store_id, manager_token = get_store_info_from_token(token_resp)
    if not store_id:
        logger.error("Failed to get store_id from profile")
        logger.error("Token response received successfully, but profile API call failed")
        logger.error("Check logs above for detailed error information")
        return f"""
        <h2>⚠️ Installation Error</h2>
        <p><strong>Issue:</strong> Could not fetch store profile from Zid API.</p>
        <p>The OAuth flow completed successfully, but the profile API call failed.</p>
        <h3>Possible Causes:</h3>
        <ul>
            <li>API endpoint might be incorrect</li>
            <li>Token format might be wrong</li>
            <li>API response structure might be different</li>
            <li>Network/connectivity issue</li>
        </ul>
        <h3>Check Server Logs:</h3>
        <p>Detailed error information is logged. Check your server logs for:</p>
        <ul>
            <li>Profile API response status</li>
            <li>Response body structure</li>
            <li>Error messages</li>
        </ul>
        <p><strong>Token Response Keys:</strong> {list(token_resp.keys())}</p>
        <p><a href="/">← Back to Home</a></p>
        """, 500

    # Save tokens to our new JSON database
    save_merchant_tokens(store_id, token_resp, manager_token)
    logger.info(f"Successfully saved tokens for store {store_id}")
    
    # *** PROVISIONING STEP (To-Do) ***
    # (Same as before)
    # This is where you would start a background job to:
    # 1. Fetch products/orders from Zid API -> Create CSVs -> Upload to S3
    # 2. Create AWS Personalize resources
    # 3. Update the merchant's entry in merchants.json with the real tracking_id and campaign_arn

    return f"App installed successfully for store {store_id}!"

@app.route("/refresh", methods=["POST", "GET"])
def refresh():
    """
    Manually refresh tokens for a specific store.
    Query param: store_id
    """
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id parameter required"}), 400
    
    merchant = load_db().get(store_id)
    if not merchant:
        return jsonify({"error": f"No merchant found for store_id {store_id}"}), 404
    
    refreshed = refresh_merchant_token(store_id)
    if refreshed:
        return jsonify({
            "message": "Tokens refreshed successfully",
            "store_id": store_id,
            "expires_at": refreshed.get("expires_at")
        })
    else:
        return jsonify({"error": "Failed to refresh tokens"}), 500

@app.route("/merchants")
def list_merchants():
    """
    List all installed merchants/stores.
    Returns: JSON list of all merchants with basic info (no sensitive tokens)
    """
    db_data = load_db()
    
    if not db_data:
        return jsonify({
            "message": "No merchants installed yet",
            "count": 0,
            "merchants": []
        })
    
    # Format merchant list (hide sensitive tokens)
    merchants_list = []
    for store_id, merchant_data in db_data.items():
        expires_at = merchant_data.get("expires_at", 0)
        expires_in = expires_at - int(time.time()) if expires_at else 0
        is_expired = token_is_expired(expires_at)
        
        merchants_list.append({
            "store_id": store_id,
            "expires_at": expires_at,
            "expires_in_seconds": expires_in,
            "expires_in_days": round(expires_in / 86400, 2) if expires_in > 0 else 0,
            "is_expired": is_expired,
            "has_tracking_id": bool(merchant_data.get("tracking_id")),
            "has_campaign_arn": bool(merchant_data.get("campaign_arn")),
            "tracking_id": merchant_data.get("tracking_id"),
            "campaign_arn": merchant_data.get("campaign_arn"),
        })
    
    return jsonify({
        "count": len(merchants_list),
        "merchants": merchants_list
    })

@app.route("/merchants/<store_id>")
def get_merchant_details(store_id):
    """
    Get detailed information about a specific merchant.
    Returns: JSON with merchant details (tokens are partially masked for security)
    """
    merchant = load_db().get(store_id)
    
    if not merchant:
        return jsonify({"error": f"No merchant found for store_id {store_id}"}), 404
    
    expires_at = merchant.get("expires_at", 0)
    expires_in = expires_at - int(time.time()) if expires_at else 0
    is_expired = token_is_expired(expires_at)
    
    # Mask sensitive tokens (show first 10 and last 4 characters)
    def mask_token(token):
        if not token:
            return None
        if len(token) <= 14:
            return "***masked***"
        return f"{token[:10]}...{token[-4:]}"
    
    return jsonify({
        "store_id": store_id,
        "tokens": {
            "access_token": mask_token(merchant.get("access_token")),
            "refresh_token": mask_token(merchant.get("refresh_token")),
            "manager_token": mask_token(merchant.get("manager_token")),
        },
        "expiry": {
            "expires_at": expires_at,
            "expires_at_readable": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at)) if expires_at else None,
            "expires_in_seconds": expires_in,
            "expires_in_days": round(expires_in / 86400, 2) if expires_in > 0 else 0,
            "is_expired": is_expired,
        },
        "aws_config": {
            "tracking_id": merchant.get("tracking_id"),
            "campaign_arn": merchant.get("campaign_arn"),
        },
        "endpoints": {
            "profile": f"/profile?store_id={store_id}",
            "refresh": f"/refresh?store_id={store_id}",
        }
    })

@app.route("/data")
def show_data():
    """
    HTML page showing all available merchant data.
    """
    db_data = load_db()
    
    if not db_data:
        return """
        <h2>No Data Available</h2>
        <p>No merchants have installed the app yet.</p>
        <p><a href="/install">Start OAuth Flow</a></p>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Merchant Data</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
            h1 {{ color: #333; }}
            .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
            .stat-box {{ background: #e3f2fd; padding: 15px; border-radius: 5px; flex: 1; }}
            .merchant-card {{ border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }}
            .merchant-card h3 {{ margin-top: 0; color: #1976d2; }}
            .expired {{ background: #ffebee; border-left: 4px solid #f44336; }}
            .active {{ background: #e8f5e9; border-left: 4px solid #4caf50; }}
            .token {{ font-family: monospace; background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
            th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #f5f5f5; }}
            .badge {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 12px; }}
            .badge-success {{ background: #4caf50; color: white; }}
            .badge-danger {{ background: #f44336; color: white; }}
            .badge-warning {{ background: #ff9800; color: white; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Merchant Data Dashboard</h1>
            <p><a href="/">← Back to Home</a> | <a href="/merchants">JSON API</a></p>
            
            <div class="stats">
                <div class="stat-box">
                    <h3>Total Stores</h3>
                    <p style="font-size: 24px; margin: 0;">{len(db_data)}</p>
                </div>
                <div class="stat-box">
                    <h3>Active Tokens</h3>
                    <p style="font-size: 24px; margin: 0;">
                        {sum(1 for m in db_data.values() if not token_is_expired(m.get('expires_at', 0)))}
                    </p>
                </div>
                <div class="stat-box">
                    <h3>Expired Tokens</h3>
                    <p style="font-size: 24px; margin: 0;">
                        {sum(1 for m in db_data.values() if token_is_expired(m.get('expires_at', 0)))}
                    </p>
                </div>
            </div>
    """
    
    for store_id, merchant in db_data.items():
        expires_at = merchant.get("expires_at", 0)
        expires_in = expires_at - int(time.time()) if expires_at else 0
        is_expired = token_is_expired(expires_at)
        expires_readable = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at)) if expires_at else "Never"
        
        status_class = "expired" if is_expired else "active"
        status_badge = '<span class="badge badge-danger">Expired</span>' if is_expired else '<span class="badge badge-success">Active</span>'
        
        html += f"""
            <div class="merchant-card {status_class}">
                <h3>Store ID: {store_id} {status_badge}</h3>
                <table>
                    <tr><th>Token Expiry</th><td>{expires_readable}</td></tr>
                    <tr><th>Expires In</th><td>{round(expires_in / 86400, 2)} days</td></tr>
                    <tr><th>Access Token</th><td><span class="token">{merchant.get('access_token', 'N/A')[:20]}...</span></td></tr>
                    <tr><th>Has Refresh Token</th><td>{'✅ Yes' if merchant.get('refresh_token') else '❌ No'}</td></tr>
                    <tr><th>Tracking ID</th><td>{merchant.get('tracking_id', 'Not configured')}</td></tr>
                    <tr><th>Campaign ARN</th><td>{merchant.get('campaign_arn', 'Not configured')}</td></tr>
                    <tr><th>Actions</th>
                        <td>
                            <a href="/profile?store_id={store_id}">View Profile</a> |
                            <a href="/refresh?store_id={store_id}">Refresh Token</a> |
                            <a href="/merchants/{store_id}">JSON Details</a>
                        </td>
                    </tr>
                </table>
            </div>
        """
    
    html += """
        </div>
    </body>
    </html>
    """
    
    return html

@app.route("/profile")
def profile():
    """
    Demo route: fetches the merchant's profile from Zid API.
    Query param: store_id
    """
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id parameter required"}), 400
    
    merchant = get_merchant_by_store_id(store_id)
    if not merchant:
        return jsonify({"error": f"No merchant found for store_id {store_id}"}), 404
    
    try:
        # Get tokens from stored merchant data
        auth_token = merchant.get("authorization") or merchant.get("access_token")
        access_token = merchant.get("access_token")
        
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Access-Token": access_token,
            "Accept": "application/json",
            "Accept-Language": "en",
            "Role": "Manager"
        }
        url = API_BASE + "/app/v1/managers/account/profile"
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        logger.error(f"Error putting event: {e}")
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
        logger.error(f"Error getting recommendations: {e}")
        return jsonify({"error": "Internal server error"}), 500

# === Run ===
if __name__ == "__main__":
    # The JSON file will be created automatically on first install
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    pass    