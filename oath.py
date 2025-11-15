# zid_oauth.py
import os
import json
import time
from urllib.parse import urlencode

from flask import Flask, redirect, request, jsonify
import requests

app = Flask(__name__)

# === CONFIG - set these in environment or edit here for testing ===
CLIENT_ID = int(os.getenv("ZID_CLIENT_ID", "5410"))
CLIENT_SECRET = os.getenv("ZID_CLIENT_SECRET", "1ACdU5lGCsCCw0iOPPEKkWfLyMVaIcbopDOjaahO")
REDIRECT_URI = os.getenv("ZID_REDIRECT_URI", "https://m5dzci.zid.store")

OAUTH_BASE = "https://oauth.zid.sa"
AUTHORIZE_URL = f"{OAUTH_BASE}/oauth/authorize"
TOKEN_URL = f"{OAUTH_BASE}/oauth/token"
API_BASE = "https://api.zid.sa/v1"   # use https://api.zid.dev/... for dev if needed

# Where tokens are persisted (very small demo). Replace with secure DB/storage in production.
TOKENS_FILE = "zid_tokens.json"

# === Helpers ===
def load_tokens():
    try:
        with open(TOKENS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_tokens(data):
    with open(TOKENS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def token_is_expired(token_info):
    # token_info expected to have 'obtained_at' (epoch) and 'expires_in' (seconds)
    if not token_info:
        return True
    obtained = token_info.get("obtained_at", 0)
    expires_in = int(token_info.get("expires_in", 0))
    # subtract small safety margin (e.g., 60s)
    return time.time() >= (obtained + expires_in - 60)

def build_authorize_redirect(scopes=None, extra=None):
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
    }
    if scopes:
        # scopes as space-separated string (Zid dashboard may configure)
        params["scope"] = " ".join(scopes) if isinstance(scopes, (list, tuple)) else scopes
    if extra:
        params.update(extra)
    return AUTHORIZE_URL + "?" + urlencode(params)

# === Routes ===
@app.route("/")
def index():
    return (
        "<h3>Zid OAuth demo</h3>"
        "<p>Use <a href='/install'>/install</a> to start the install (authorize) flow.</p>"
        "<p>After install you'll be redirected to <code>/callback</code> which exchanges the code for tokens.</p>"
    )

@app.route("/install")
def install():
    """
    Redirect merchant to Zid authorize page.
    Example: /install?scopes=read_products,write_orders
    """
    scopes = request.args.get("scopes")  # comma or space separated optional
    if scopes:
        # allow comma separated in query
        scopes = scopes.replace(",", " ")
    redirect_url = build_authorize_redirect(scopes=scopes)
    return redirect(redirect_url)

@app.route("/callback")
def callback():
    """
    OAuth callback that Zid will redirect to with ?code=...
    Exchanges the code for tokens and stores them.
    """
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        return f"Error from Zid OAuth: {error}", 400
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
        return (
            f"Token endpoint returned {resp.status_code}: {resp.text}",
            resp.status_code,
        )

    token_resp = resp.json()
    # expected keys: access_token, refresh_token, expires_in, maybe manager_token or other fields
    token_resp["obtained_at"] = int(time.time())

    # Persist full response (demo: single merchant). In real app, associate with merchant/store id.
    tokens = load_tokens()
    tokens["default"] = token_resp
    save_tokens(tokens)

    # Return a minimal success page with basic token info (don't show secrets in prod)
    display = {
        "message": "Installation successful. Tokens saved server-side.",
        "stored_keys": list(token_resp.keys()),
    }
    return jsonify(display)

@app.route("/refresh", methods=["POST", "GET"])
def refresh():
    """
    Refresh saved refresh_token for the default merchant.
    In production, you would identify which merchant/store to refresh.
    """
    tokens = load_tokens()
    current = tokens.get("default")
    if not current:
        return "No tokens saved for default merchant", 404

    refresh_token = current.get("refresh_token")
    if not refresh_token:
        return "No refresh_token found", 400

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(TOKEN_URL, data=payload, timeout=10)
    if resp.status_code != 200:
        return f"Refresh failed: {resp.status_code} {resp.text}", resp.status_code

    new_tokens = resp.json()
    new_tokens["obtained_at"] = int(time.time())

    tokens["default"] = new_tokens
    save_tokens(tokens)
    return jsonify({"message": "Refreshed tokens", "stored_keys": list(new_tokens.keys())})

# === Example API call using both headers ===
def api_get_profile():
    """
    Example GET to: GET /app/v1/managers/account/profile
    Will return JSON or raise an exception.
    """
    tokens = load_tokens().get("default")
    if not tokens:
        raise RuntimeError("No tokens stored")

    # If expired, attempt to refresh automatically
    if token_is_expired(tokens):
        # naive automatic refresh: call token endpoint
        if tokens.get("refresh_token"):
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
            }
            r = requests.post(TOKEN_URL, data=payload, timeout=10)
            if r.status_code == 200:
                new = r.json()
                new["obtained_at"] = int(time.time())
                stored = load_tokens()
                stored["default"] = new
                save_tokens(stored)
                tokens = new
            else:
                raise RuntimeError(f"Failed to refresh token: {r.status_code} {r.text}")

    # Authorization header uses the OAuth "authorization token" (Bearer access_token)
    auth_token = tokens.get("access_token")
    # X-MANAGER-TOKEN should contain the manager token if provided by Zid; otherwise use access_token
    manager_token = tokens.get("manager_token") or tokens.get("x_manager_token") or tokens.get("access_token")

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "X-MANAGER-TOKEN": manager_token,
        "Accept": "application/json",
        "Accept-Language": "en",
    }
    url = API_BASE + "/app/v1/managers/account/profile"
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()

@app.route("/profile")
def profile_route():
    """
    Small route to demo calling the Zid API with stored tokens and returning the result.
    """
    try:
        data = api_get_profile()
        return jsonify(data)
    except Exception as e:
        return {"error": str(e)}, 500

# === Run ===
if __name__ == "__main__":
    # dev server - in production use gunicorn/uvicorn + TLS termination
    app.run(host="0.0.0.0", port=5000, debug=True)

