# zid_export.py
import os
import csv
import json
import time
import requests
from datetime import datetime

# Try to import from app.py (optional, for database mode)
try:
    from app import (
        load_db,
        get_merchant_by_store_id,
        CLIENT_ID,
        CLIENT_SECRET,
        TOKEN_URL,
        API_BASE,
        token_is_expired,
        refresh_merchant_token,
    )
    APP_AVAILABLE = True
except ImportError:
    APP_AVAILABLE = False
    API_BASE = "https://api.zid.sa/v1"

# -------------------------------------------------------------------
# Token configuration (from test_call.py)
# -------------------------------------------------------------------

# Static tokens from test_call.py (WORKING TOKENS - updated from test_call.py)
# These are the exact tokens that work from test_call.py
STATIC_ACCESS_TOKEN = "eyJpdiI6IldKSEV6enliOStURVRYQ3NSVW1FVEE9PSIsInZhbHVlIjoiQ3FMMnVpazFST0kyeUQ2UENDNVQ1Y2lFdjFIaFBsc29IOE00c1p2V2NVN2JjaTd0V2NTMmZCVWFnOVI5OE0vUjJBV1ZMYitoWktFaXVEaWhCODlQUUIzTTNvaWNkM1RqZDAydUw1TTJvN3BYZmY0QkRvdWpEcHVZS3lSUFpvTFNCV0tobDlscTFSYjI2amhMdmRwTXZDQkEzbGxtSjVZQlBTUnplNUllKzFaNDZqcTFBVm5ySkIxQW44dkRyT0FlUG1YazRrazlrNHJTMnQ0cmdrb0d2MDJmV05zVUt1QmltTXlBL1lyYU00Yz0iLCJtYWMiOiIwZTljN2RiMWM5ZTUyNTA5ZjEwYmQ3N2I5MDIwNWRkZGMyMzgzNjlkYmY5MWM2ZDY0Y2EyODFmMWFhYTJjMThjIiwidGFnIjoiIn0="

STATIC_AUTHORIZATION_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI1NDEwIiwianRpIjoiZmIwMGNmMmJiMzM1Nzg5YTZhYjVjNDAxNjViYzM3OWU0YWYwNTI4ODFiZmRhNzVmMWVlZmU5NDc1YjU5N2IyMjVlZjM1YmNhNGU5ODE5M2QiLCJpYXQiOjE3NjMyMTg3MDEuMTMzNDUsIm5iZiI6MTc2MzIxODcwMS4xMzM0NTMsImV4cCI6MTg1NzkxMzEwMS4wNTg4ODksInN1YiI6IjI4NTk4NzMiLCJzY29wZXMiOlsidGhpcmRfYWNjb3VudF9yZWFkIiwidGhpcmRfdmF0X3JlYWQiLCJ0aGlyZF9jYXRlZ29yaWVzX3JlYWQiLCJ0aGlyZF9jYXRlZ29yaWVzX3dyaXRlIiwidGhpcmRfY3VzdG9tZXJzX3JlYWQiLCJ0aGlyZF9jdXN0b21lcnNfd3JpdGUiLCJ0aGlyZF9vcmRlcl9yZWFkIiwidGhpcmRfb3JkZXJfd3JpdGUiLCJ0aGlyZF9jb3Vwb25zX3dyaXRlIiwidGhpcmRfZGVsaXZlcnlfb3B0aW9uc19yZWFkIiwidGhpcmRfZGVsaXZlcnlfb3B0aW9uc193cml0ZSIsInRoaXJkX2FiYW5kb25lZF9jYXJ0c19yZWFkIiwidGhpcmRfcGF5bWVudF9yZWFkIiwidGhpcmRfd2ViaG9va19yZWFkIiwidGhpcmRfd2ViaG9va193cml0ZSIsInRoaXJkX3Byb2R1Y3RfcmVhZCIsInRoaXJkX3Byb2R1Y3Rfd3JpdGUiLCJ0aGlyZF9jb3VudHJpZXNfcmVhZCIsInRoaXJkX2NhdGFsb2dfd3JpdGUiLCJ0aGlyZF9zdWJzY3JpcHRpb25fcmVhZCIsInRoaXJkX2ludmVudG9yeV9yZWFkIiwidGhpcmRfanNfd3JpdGUiLCJ0aGlyZF9idW5kbGVfb2ZmZXJzX3JlYWQiLCJ0aGlyZF9jcmVhdGVfb3JkZXIiLCJ0aGlyZF9wcm9kdWN0X3N0b2NrX3JlYWQiLCJ0aGlyZF9wcm9kdWN0X3N0b2NrX3dyaXRlIiwidGhpcmRfaW52ZW50b3J5X3dyaXRlIiwiZW1iZWRkZWRfYXBwc190b2tlbnNfd3JpdGUiLCJ0aGlyZF9sb3lhbHR5X3JlYWQiLCJ0aGlyZF9sb3lhbHR5X3dyaXRlIiwidGhpcmRfb3JkZXJfcmV2ZXJzZV93cml0ZSIsInRoaXJkX29yZGVyX3JldmVyc2VfcmVhZCIsInRoaXJkX3Byb2R1Y3RfYXZhaWxhYmlsaXR5X25vdGlmaWNhdGlvbnNfcmVhZCIsInRoaXJkX3Byb2R1Y3RfYXZhaWxhYmlsaXR5X25vdGlmaWNhdGlvbnNfd3JpdGUiLCJ0aGlyZF9jb3Vwb25zX3JlYWQiLCJ0aGlyZF9zdWJzY3JpcHRpb25fd3JpdGUiXX0.IfFn7w-MW3nRox4ik6Q1aeoSf0mzdfJwMb1jLzr0QuE2xKUd86uhj2WbkXaSDyk7hHWjRwumq1PvQJN4_sDaR1Yq6Nknps2KUKv6a7BL6Iy90aFxub_FWf3gwBV6wQVH583MDql6ow7w6X110-IgDvEWXtI-bUM9vT78M1RZkJ93ad3OBpaSP0Yy7Zpldm2b6v_oHtenZvQSijok1u9cLQZuvXUYryUmu7OE6d5nVPFwZuyE-UGzFk5gcDl0my26v8sUV9Qqk8PL1K7mlA2rEtkSlWO7baRT4xzP25ekfnD4lX6xSuSSRW-JxQofyKfjs2mBKJF3Q-1vz0X1vI2Kq73zcqGyuE4WOWOH0iIdH4lUI0qmOGNgkjhmKc92MVle1eeUp53eG-tjoRo1rR0yE4pu-70mDm83_JpxImUhdXlhI_V4ob2iF1X4-KY46hcdbw86aZdI73A_17EahrX5m0vWCClaPbVa-vtrRfiCU235LX6HICm5TYZIqNMIkWu3RizRxQUfEgcBOGy8hUk-NIGXkjUff4cH-Q8JRVZUt8zyw29BcY1H08qDOjKBv4s3hqf4IZDFDJ2YNqKhJ7Gh14acPtLmkesEtorvHOQ0Bpns3sNPKlphuxxV_c8bJH4QMjICEeELeXueGgJcJYpxQ3JpOkVge8lsGR9joSqwm78"

STATIC_STORE_ID = "2803554"  # From test_call.py (Store-Id header)

# Fallback tokens (can be overridden via environment variables)
DEFAULT_ACCESS_TOKEN = os.getenv("ZID_ACCESS_TOKEN", STATIC_ACCESS_TOKEN)
DEFAULT_AUTHORIZATION_TOKEN = os.getenv("ZID_AUTHORIZATION_TOKEN", STATIC_AUTHORIZATION_TOKEN)
DEFAULT_STORE_ID = os.getenv("ZID_STORE_ID", STATIC_STORE_ID)

# -------------------------------------------------------------------
# Token handling
# -------------------------------------------------------------------

def get_valid_tokens(store_id: str = None) -> dict:
    """
    Get tokens - PROOF OF CONCEPT: Using static tokens from test_call.py
    
    Priority (for now, using static tokens):
    1. Static tokens from test_call.py (PROOF OF CONCEPT)
    2. Database (merchants.json) if app.py is available and store_id provided
    3. Environment variables (ZID_ACCESS_TOKEN, ZID_AUTHORIZATION_TOKEN)
    """
    # PROOF OF CONCEPT: Use static tokens from test_call.py first
    print(f"[export.py] 🔧 PROOF OF CONCEPT MODE: Using static tokens from test_call.py")
    print(f"[export.py] Using STATIC_STORE_ID: {STATIC_STORE_ID}")
    print(f"[export.py] Using STATIC_ACCESS_TOKEN: {STATIC_ACCESS_TOKEN[:50]}...")
    print(f"[export.py] Using STATIC_AUTHORIZATION_TOKEN: {STATIC_AUTHORIZATION_TOKEN[:50]}...")
    
    # Return static tokens (these are the ones that work!)
    return {
        "access_token": STATIC_ACCESS_TOKEN,
        "authorization": STATIC_AUTHORIZATION_TOKEN,
        "store_id": STATIC_STORE_ID  # Use static store_id from test_call.py
    }
    
    # NOTE: Database lookup disabled for proof of concept
    # Uncomment below to enable database lookup later:
    """
    # PRIORITY 1: Try database first if store_id is provided
    if APP_AVAILABLE and store_id:
        try:
            merchant = get_merchant_by_store_id(store_id)
            if merchant:
                has_auth = bool(merchant.get("authorization"))
                has_access = bool(merchant.get("access_token"))
                if has_auth and has_access:
                    print(f"[export.py] Using tokens from database for store_id: {store_id}")
                    return merchant
        except Exception as e:
            print(f"[export.py] ERROR getting merchant from database: {e}")
            pass
    
    # PRIORITY 2: Check environment variables
    access_token = os.getenv("ZID_ACCESS_TOKEN", STATIC_ACCESS_TOKEN)
    auth_token = os.getenv("ZID_AUTHORIZATION_TOKEN", STATIC_AUTHORIZATION_TOKEN)
    
    return {
        "access_token": access_token,
        "authorization": auth_token,
        "store_id": store_id or STATIC_STORE_ID
    }
    """


def build_auth_headers(tokens: dict, store_id: str = None) -> dict:
    """
    Build Zid auth headers EXACTLY matching test_call.py format:
    
    test_call.py format:
    headers = {
       'Accept-Language': '',
       'Access-Token': '...',
       'Authorization': 'Bearer ...',
       'Store-Id': '2803554',
       'Role': 'Manager'
    }
    """
    print(f"[export.py] ===== BUILDING HEADERS (matching test_call.py) =====")
    print(f"[export.py] Input tokens keys: {list(tokens.keys())}")
    print(f"[export.py] Input store_id: {store_id}")
    
    # Get tokens - EXACTLY as test_call.py
    access_token = tokens.get("access_token")
    auth_token = tokens.get("authorization")
    
    if not access_token:
        print(f"[export.py] ERROR: No access_token found!")
        print(f"[export.py] Tokens dict keys: {list(tokens.keys())}")
        raise RuntimeError("Missing required access_token")
    
    if not auth_token:
        print(f"[export.py] ERROR: No authorization token found!")
        print(f"[export.py] Tokens dict keys: {list(tokens.keys())}")
        raise RuntimeError("Missing required authorization token")
    
    final_store_id = store_id or tokens.get("store_id") or DEFAULT_STORE_ID

    # Build headers EXACTLY like test_call.py - same order, same format
    headers = {
        'Accept-Language': '',  # Empty string
        'Access-Token': access_token,  # Direct access_token value
        'Authorization': f'Bearer {auth_token}',  # Bearer + authorization token
        'Store-Id': str(final_store_id),
        'Role': 'Manager'
    }
    
    print(f"[export.py] ✅ Built headers matching test_call.py format")
    print(f"[export.py] Store-Id: {final_store_id}")
    print(f"[export.py] Authorization: Bearer {auth_token}... (length: {len(auth_token)})")
    print(f"[export.py] Access-Token: {access_token}... (length: {len(access_token)})")
    print(f"[export.py] Header keys order: {list(headers.keys())}")
    print(f"[export.py] ================================================")
    
    return headers


# -------------------------------------------------------------------
# Low-level request helper
# -------------------------------------------------------------------

def zid_request(method: str, url_or_path: str, store_id: str, **kwargs):
    """
    Make an authenticated request to Zid - EXACTLY like test_call.py
    
    test_call.py format:
    url = "https://api.zid.sa/v1/products/"
    payload={}
    headers = {
       'Accept-Language': '',
       'Access-Token': '...',
       'Authorization': 'Bearer ...',
       'Store-Id': '2803554',
       'Role': 'Manager'
    }
    response = requests.request("GET", url, headers=headers, data=payload)
    """
    tokens = get_valid_tokens(store_id)
    print(f"[export.py] ===== zid_request (matching test_call.py) =====")
    print(f"[export.py] Method: {method}")
    print(f"[export.py] URL/Path: {url_or_path}")
    print(f"[export.py] Store ID: {store_id}")
    print(f"[export.py] Tokens available: {bool(tokens.get('authorization') and tokens.get('access_token'))}")
    
    # Use the store_id from tokens if available (might be more accurate)
    token_store_id = tokens.get("store_id")
    if token_store_id and str(token_store_id) != str(store_id):
        print(f"[export.py] Using store_id from tokens: {token_store_id} (instead of {store_id})")
        store_id = str(token_store_id)
    
    # Build headers EXACTLY like test_call.py
    headers = build_auth_headers(tokens, store_id)
    
    # Merge with any caller-provided headers (from kwargs)
    extra_headers = kwargs.pop("headers", {})
    headers.update(extra_headers)

    # Build URL EXACTLY like test_call.py
    if url_or_path.startswith("http"):
        url = url_or_path
    else:
        # Build full URL like test_call.py: "https://api.zid.sa/v1/products/"
        url = API_BASE.rstrip("/") + "/" + url_or_path.lstrip("/")

    # Build payload EXACTLY like test_call.py (empty dict)
    payload = kwargs.pop("data", {}) or kwargs.pop("json", {}) or {}
    
    # Get params if provided
    params = kwargs.pop("params", {})

    print(f"[export.py] Final URL: {url}")
    print(f"[export.py] Params: {params}")
    print(f"[export.py] Payload: {payload}")
    print(f"[export.py] Headers keys: {list(headers.keys())}")
    
    # Make request EXACTLY like test_call.py: requests.request("GET", url, headers=headers, data=payload)
    resp = requests.request(method, url, headers=headers, data=payload, params=params, timeout=15, **kwargs)
    
    # Log response details
    if resp.status_code != 200:
        print(f"[export.py] ❌ Request failed with status {resp.status_code}")
        print(f"[export.py] URL: {url}")
        print(f"[export.py] Method: {method}")
        print(f"[export.py] Response: {resp.text}")
        print(f"[export.py] Headers sent:")
        for key, value in headers.items():
            if key in ['Authorization', 'Access-Token']:
                print(f"  {key}: {value[:80]}... (length: {len(value)})")
            else:
                print(f"  {key}: {value}")
    else:
        print(f"[export.py] ✅ Request successful (status {resp.status_code})")
    
    resp.raise_for_status()
    return resp.json()


# -------------------------------------------------------------------
# Fetch all products
# GET https://api.zid.sa/v1/products/?page_size=&page=
# Note: Products endpoint uses /products/ (not /managers/store/products)
# -------------------------------------------------------------------

def fetch_all_products(store_id: str, page_size: int = 100) -> list:
    """
    Retrieve all products for a store, following pagination via `next` URL.
    Uses /products/ endpoint (not manager endpoint).
    Returns a list of product dicts (results[]).
    """
    products = []

    # First page
    params = {"page_size": page_size, "page": 1}
    data = zid_request("GET", "/products/", store_id, params=params)
    products.extend(data.get("results", []))

    # Paginate using `next` (full URL) if present
    next_url = data.get("next")
    while next_url:
        print(f"  Fetching next page: {next_url}")
        data = zid_request("GET", next_url, store_id)
        products.extend(data.get("results", []))
        next_url = data.get("next")

    return products


# -------------------------------------------------------------------
# Fetch all customers
# GET https://api.zid.sa/v1/managers/store/customers?page&per_page
# -------------------------------------------------------------------

def fetch_all_customers(store_id: str, per_page: int = 100) -> list:
    """
    Retrieve all customers for a store using page/per_page.
    The response has structure:
      {
        "status": "...",
        "customers": [...],
        "total_customers_count": ...,
        ...
      }
    We loop until we get fewer than per_page results.
    """
    customers = []
    page = 1

    while True:
        params = {"page": page, "per_page": per_page}
        data = zid_request(
            "GET", "/managers/store/customers", store_id, params=params
        )
        batch = data.get("customers", [])
        customers.extend(batch)
        
        print(f"  Fetched page {page}: {len(batch)} customers")

        if not batch or len(batch) < per_page:
            break

        page += 1

    return customers


# -------------------------------------------------------------------
# Fetch all orders
# GET https://api.zid.sa/v1/managers/store/orders?page&per_page
# -------------------------------------------------------------------

def fetch_all_orders(store_id: str, per_page: int = 100) -> list:
    """
    Retrieve all orders for a store using page/per_page.
    The response has structure:
      {
        "status": "...",
        "orders": [...],
        "total_orders_count": ...,
        ...
      }
    We loop until we get fewer than per_page results.
    """
    orders = []
    page = 1

    while True:
        params = {"page": page, "per_page": per_page}
        data = zid_request(
            "GET", "/managers/store/orders", store_id, params=params
        )
        batch = data.get("orders", [])
        orders.extend(batch)
        
        print(f"  Fetched page {page}: {len(batch)} orders")

        if not batch or len(batch) < per_page:
            break

        page += 1

    return orders


# -------------------------------------------------------------------
# Flattening helpers: turn nested JSON into flat columns
# -------------------------------------------------------------------

def flatten_record(obj, parent_key="", sep="."):
    """
    Recursively flattens a dict/list structure.

    Examples:
      {"name": {"en": "Shirt"}} -> {"name.en": "Shirt"}
      {"weight": {"value": 100, "unit": "kg"}} -> {"weight.value": 100, "weight.unit": "kg"}
      {"keywords": ["sport", "summer"]} -> {"keywords": "sport,summer"}
      list of complex objects -> JSON string
    """
    items = {}

    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            items.update(flatten_record(v, new_key, sep=sep))

    elif isinstance(obj, list):
        # Simple list -> comma-separated
        if all(isinstance(x, (str, int, float, bool, type(None))) for x in obj):
            items[parent_key] = ",".join("" if x is None else str(x) for x in obj)
        else:
            # More complex list -> JSON blob
            items[parent_key] = json.dumps(obj, ensure_ascii=False)

    else:
        items[parent_key] = obj

    return items


def flatten_many(records: list) -> list:
    return [flatten_record(r) for r in records]


# -------------------------------------------------------------------
# CSV writing
# -------------------------------------------------------------------

def write_csv(records: list, filename: str):
    """
    Writes a list of dicts to CSV, with union of all keys as columns.
    """
    if not records:
        print(f"[WARN] No records to write for {filename}")
        return

    flat_records = flatten_many(records)

    # Collect all possible columns
    fieldnames = sorted({k for rec in flat_records for k in rec.keys()})

    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in flat_records:
            writer.writerow(rec)

    print(f"[OK] Wrote {len(flat_records)} rows to {filename}")


def convert_to_unix_timestamp(iso_timestamp: str) -> int:
    """
    Convert ISO 8601 timestamp to Unix epoch timestamp.
    Example: "2025-11-15T10:33:56.839743Z" -> 1763202836
    """
    try:
        # Parse ISO format with timezone
        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        # Convert to Unix timestamp
        return int(dt.timestamp())
    except Exception as e:
        print(f"[WARN] Failed to parse timestamp '{iso_timestamp}': {e}")
        return 0


def extract_category_name(categories: list) -> str:
    """
    Extract the main category name from categories array.
    Prefers Arabic name, falls back to English, then slug.
    """
    if not categories or len(categories) == 0:
        return ""
    
    # Get first category
    first_cat = categories[0]
    
    # Try Arabic name first
    if isinstance(first_cat, dict):
        name_obj = first_cat.get("name", {})
        if isinstance(name_obj, dict):
            category_name = name_obj.get("ar") or name_obj.get("en") or ""
            if category_name:
                return category_name
        
        # Fall back to slug if name not available
        slug = first_cat.get("slug", "")
        if slug:
            return slug
    
    return ""


def format_product_for_items_csv(product: dict) -> dict:
    """
    Format a product for AWS Personalize items.csv format.
    Returns dict with: ITEM_ID, CREATION_TIMESTAMP, category
    """
    item_id = product.get("id", "")
    
    # Convert created_at to Unix timestamp
    created_at = product.get("created_at", "")
    creation_timestamp = convert_to_unix_timestamp(created_at) if created_at else 0
    
    # Extract category name
    categories = product.get("categories", [])
    category = extract_category_name(categories)
    
    return {
        "ITEM_ID": item_id,
        "CREATION_TIMESTAMP": creation_timestamp,
        "category": category
    }


def write_items_csv(products: list, filename: str = "items.csv"):
    """
    Write products to AWS Personalize items.csv format.
    Only includes: ITEM_ID, CREATION_TIMESTAMP, category
    Always creates the file, even if empty (with header only).
    """
    fieldnames = ["ITEM_ID", "CREATION_TIMESTAMP", "category"]
    
    # Create directory if needed
    dir_path = os.path.dirname(filename)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    
    # Format products for items.csv
    items = []
    if products:
        print(f"[export.py] Processing {len(products)} products for items CSV...")
        for p in products:
            try:
                item = format_product_for_items_csv(p)
                if item.get("ITEM_ID"):  # Only include items with ITEM_ID
                    items.append(item)
            except Exception as e:
                print(f"[export.py] ERROR processing product {p.get('id', 'unknown')}: {e}")
                import traceback
                traceback.print_exc()
    else:
        print(f"[export.py] WARN: No products provided for {filename}")
    
    # Always create the file (even if empty, with header)
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                writer.writerow(item)
        
        file_size = os.path.getsize(filename)
        if items:
            print(f"[export.py] ✅ Wrote {len(items)} items to {filename} ({file_size} bytes)")
        else:
            print(f"[export.py] ⚠️ Created empty items CSV at {filename} (header only, {file_size} bytes)")
        print(f"[export.py]     Format: ITEM_ID, CREATION_TIMESTAMP, category")
    except Exception as e:
        print(f"[export.py] ❌ ERROR writing items CSV to {filename}: {e}")
        import traceback
        traceback.print_exc()
        raise


def calculate_age(date_of_birth: str) -> int:
    """
    Calculate age from date of birth string.
    Returns age in years, or empty string if not available.
    """
    if not date_of_birth:
        return ""
    
    try:
        # Try to parse various date formats
        if isinstance(date_of_birth, str):
            # Try ISO format first
            try:
                dob = datetime.fromisoformat(date_of_birth.replace('Z', '+00:00'))
            except:
                # Try other common formats
                for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                    try:
                        dob = datetime.strptime(date_of_birth, fmt)
                        break
                    except:
                        continue
                else:
                    return ""
            
            today = datetime.now()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return max(0, age)  # Ensure non-negative
    except Exception as e:
        print(f"[WARN] Failed to calculate age from '{date_of_birth}': {e}")
    
    return ""


def extract_location(customer: dict) -> str:
    """
    Extract location (city name) from customer data.
    Returns city name as string (prefers English name, falls back to Arabic name or name field).
    """
    # Check if city is a dictionary (common in Zid API)
    city = customer.get("city")
    if isinstance(city, dict):
        # Extract city name from dictionary (prefer English name, then Arabic, then name)
        location = (
            city.get("en_name") or
            city.get("name") or
            city.get("ar_name") or
            ""
        )
        if location:
            return str(location).strip()
    
    # Check nested address structure
    address = customer.get("address", {})
    if isinstance(address, dict):
        city_field = address.get("city")
        if isinstance(city_field, dict):
            # Extract city name from nested city dict
            location = (
                city_field.get("en_name") or
                city_field.get("name") or
                city_field.get("ar_name") or
                ""
            )
            if location:
                return str(location).strip()
        
        # Check other address fields
        location = (
            address.get("city") or 
            address.get("region") or 
            address.get("state") or
            address.get("country") or
            ""
        )
        if location and isinstance(location, str):
            return location.strip()
    
    # Check direct fields (if they're strings)
    location = (
        customer.get("city") or
        customer.get("location") or
        customer.get("region") or
        ""
    )
    
    # If location is still a dict, try to extract name
    if isinstance(location, dict):
        location = (
            location.get("en_name") or
            location.get("name") or
            location.get("ar_name") or
            ""
        )
    
    return str(location).strip() if location else ""


def extract_gender(customer: dict) -> str:
    """
    Extract gender from customer data.
    Checks: gender, sex, title (Mr/Mrs/Miss)
    """
    # Direct gender field
    gender = customer.get("gender", "")
    if gender:
        # Normalize to common values
        gender_lower = str(gender).lower()
        if gender_lower in ["male", "m", "man", "ذكر"]:
            return "male"
        elif gender_lower in ["female", "f", "woman", "أنثى"]:
            return "female"
        return gender
    
    # Check title field (Mr/Mrs/Miss)
    title = customer.get("title", "")
    if title:
        title_lower = str(title).lower()
        if "mr" in title_lower or "mister" in title_lower:
            return "male"
        elif "mrs" in title_lower or "miss" in title_lower or "ms" in title_lower:
            return "female"
    
    return ""


def extract_membership_level(customer: dict) -> str:
    """
    Extract membership level from customer data.
    Returns membership level as string, or empty string if not available.
    """
    # Check various possible fields for membership level
    membership_level = (
        customer.get("membership_level") or
        customer.get("membership") or
        customer.get("tier") or
        customer.get("loyalty_tier") or
        customer.get("points_tier") or
        ""
    )
    
    # If found, convert to string and normalize
    if membership_level:
        return str(membership_level).strip()
    
    return ""


def format_customer_for_users_csv(customer: dict) -> dict:
    """
    Format a customer for AWS Personalize users.csv format.
    Returns dict with: USER_ID, age, location, membership_level
    """
    # USER_ID (Required) - use id or customer_id
    user_id = customer.get("id") or customer.get("customer_id") or customer.get("user_id")
    if not user_id:
        return None  # Skip if no USER_ID
    
    # Calculate age from date_of_birth (Numerical)
    date_of_birth = (
        customer.get("date_of_birth") or 
        customer.get("birth_date") or 
        customer.get("dob") or
        ""
    )
    age = calculate_age(date_of_birth)
    
    # Extract location (Categorical)
    location = extract_location(customer)
    
    # Extract membership_level (Categorical)
    membership_level = extract_membership_level(customer)
    
    return {
        "USER_ID": str(user_id),
        "age": age if age != "" else "",
        "location": location,
        "membership_level": membership_level
    }


def write_users_csv(customers: list, filename: str = "users.csv"):
    """
    Write customers to AWS Personalize users.csv format.
    Only includes: USER_ID, age, location, membership_level
    """
    if not customers:
        print(f"[export.py] WARN: No customers provided for {filename}")
        return
    
    # Format customers for users.csv
    users = []
    for customer in customers:
        try:
            user = format_customer_for_users_csv(customer)
            if user:  # Only add if USER_ID exists
                users.append(user)
        except Exception as e:
            print(f"[export.py] ERROR processing customer {customer.get('id', 'unknown')}: {e}")
            import traceback
            traceback.print_exc()
    
    if not users:
        print(f"[export.py] WARN: No valid users to write for {filename}")
        return
    
    fieldnames = ["USER_ID", "age", "location", "membership_level"]
    
    # Create directory if needed
    dir_path = os.path.dirname(filename)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    
    # Always create the file (even if empty, with header)
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for user in users:
                writer.writerow(user)
        
        file_size = os.path.getsize(filename)
        print(f"[export.py] ✅ Wrote {len(users)} users to {filename} ({file_size} bytes)")
        print(f"[export.py]     Format: USER_ID, age, location, membership_level")
    except Exception as e:
        print(f"[export.py] ❌ ERROR writing users CSV to {filename}: {e}")
        import traceback
        traceback.print_exc()
        raise


def format_order_for_interactions_csv(order: dict) -> list:
    """
    Convert an order into interaction records for AWS Personalize.
    Each order item becomes one interaction record.
    
    Returns list of dicts with:
    - USER_ID (String): Unique customer ID
    - ITEM_ID (String): Product ID (must match items.csv)
    - TIMESTAMP (Long): Unix epoch format from order created_at
    - EVENT_TYPE (String): Event name (e.g., 'purchase')
    """
    interactions = []
    
    # Extract USER_ID (String) - unique customer ID
    user_id = (
        order.get("customer_id") or 
        order.get("customer", {}).get("id") or
        order.get("user_id") or
        ""
    )
    if not user_id:
        return interactions  # Skip orders without customer
    
    # Extract timestamp from order created_at
    order_timestamp = order.get("created_at") or order.get("created_date") or ""
    if not order_timestamp:
        return interactions  # Skip orders without timestamp
    
    # Convert to Unix timestamp (Long)
    timestamp = convert_to_unix_timestamp(order_timestamp)
    if not timestamp or timestamp == 0:
        return interactions
    
    # Ensure timestamp is an integer (Long type)
    timestamp = int(timestamp)
    
    # Extract order items
    items = order.get("items", []) or order.get("order_items", []) or []
    
    # Each item becomes an interaction with EVENT_TYPE = "purchase"
    for item in items:
        # Extract ITEM_ID (String) - product ID (must match items.csv)
        item_id = item.get("product_id") or item.get("item_id") or item.get("id")
        if not item_id:
            continue  # Skip items without product_id
        
        interactions.append({
            "USER_ID": str(user_id),  # String
            "ITEM_ID": str(item_id),   # String (must match items.csv)
            "TIMESTAMP": timestamp,    # Long (Unix epoch)
            "EVENT_TYPE": "purchase"   # String (lowercase as per AWS Personalize convention)
        })
    
    return interactions


def write_interactions_csv(orders: list, filename: str = "interactions.csv"):
    """
    Write orders to AWS Personalize interactions.csv format.
    Only includes: USER_ID, ITEM_ID, TIMESTAMP, EVENT_TYPE
    Always creates the file, even if empty (with header only).
    """
    fieldnames = ["USER_ID", "ITEM_ID", "TIMESTAMP", "EVENT_TYPE"]
    
    # Create directory if needed
    dir_path = os.path.dirname(filename)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    
    # Convert all orders to interactions
    all_interactions = []
    if orders:
        print(f"[export.py] Processing {len(orders)} orders for interactions CSV...")
        for order in orders:
            try:
                interactions = format_order_for_interactions_csv(order)
                all_interactions.extend(interactions)
            except Exception as e:
                print(f"[export.py] ERROR processing order {order.get('id', 'unknown')}: {e}")
                import traceback
                traceback.print_exc()
    else:
        print(f"[export.py] WARN: No orders provided for {filename}")
    
    # Always create the file (even if empty, with header)
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for interaction in all_interactions:
                writer.writerow(interaction)
        
        file_size = os.path.getsize(filename)
        if all_interactions:
            print(f"[export.py] ✅ Wrote {len(all_interactions)} interactions to {filename} ({file_size} bytes)")
        else:
            print(f"[export.py] ⚠️ Created empty interactions CSV at {filename} (header only, {file_size} bytes)")
        print(f"[export.py]     Format: USER_ID, ITEM_ID, TIMESTAMP, EVENT_TYPE")
    except Exception as e:
        print(f"[export.py] ❌ ERROR writing interactions CSV to {filename}: {e}")
        import traceback
        traceback.print_exc()
        raise


# -------------------------------------------------------------------
# Main export entrypoint
# -------------------------------------------------------------------

def export_store_to_csv(
    store_id: str,
    products_csv: str = "products.csv",
    customers_csv: str = "customers.csv",
    items_csv: str = None,
    users_csv: str = None,
):
    """
    Export both products and customers for the given store_id into CSVs.
    Optionally export items.csv and users.csv for AWS Personalize.

    Usage from CLI:
      python export.py
        -> exports first available store_id into products.csv & customers.csv

      ZID_STORE_ID=2803554 python export.py
        -> uses store_id="2803554"
      
      ZID_ITEMS_CSV=items.csv python export.py
        -> also creates items.csv with simplified format
      
      ZID_USERS_CSV=users.csv python export.py
        -> also creates users.csv with simplified format
    """
    print(f"Using store_id = {store_id}")
    print(f"Fetching data from Zid API...")

    # PRODUCTS
    print("\n[1/2] Fetching products ...")
    try:
        products = fetch_all_products(store_id)

        
        # Also create items.csv if requested
        if items_csv:
            print(f"\n[EXTRA] Creating items.csv for AWS Personalize...")
            write_items_csv(products, items_csv)
    except Exception as e:
        print(f"[ERROR] Failed to fetch products: {e}")
        raise

    # CUSTOMERS
    print("\n[2/2] Fetching customers ...")
    try:
        customers = fetch_all_customers(store_id)
        print(f"  Found {len(customers)} customers")
        write_csv(customers, customers_csv)
        
        # Also create users.csv if requested
        if users_csv:
            print(f"\n[EXTRA] Creating users.csv for AWS Personalize...")
            write_users_csv(customers, users_csv)
    except Exception as e:
        print(f"[ERROR] Failed to fetch customers: {e}")
        raise

    print(f"\n[SUCCESS] Export complete!")
    print(f"  Products: {products_csv}")
    print(f"  Customers: {customers_csv}")
    if items_csv:
        print(f"  Items (AWS Personalize): {items_csv}")
    if users_csv:
        print(f"  Users (AWS Personalize): {users_csv}")


if __name__ == "__main__":
    # Get store_id from environment or use default from test_call.py
    store_id = os.getenv("ZID_STORE_ID", DEFAULT_STORE_ID)
    
    # Try to get from database if not set and app is available
    if store_id == DEFAULT_STORE_ID and APP_AVAILABLE:
        try:
            db_data = load_db()
            if db_data:
                store_id = list(db_data.keys())[0]
                print(f"Using store_id from database: {store_id}")
        except:
            pass
    
    print(f"Using store_id: {store_id}")
    print("Using tokens from test_call.py (can be overridden with ZID_ACCESS_TOKEN and ZID_AUTHORIZATION_TOKEN env vars)")

    products_csv = os.getenv("ZID_PRODUCTS_CSV", "products.csv")
    customers_csv = os.getenv("ZID_CUSTOMERS_CSV", "customers.csv")
    items_csv = os.getenv("ZID_ITEMS_CSV", "items.csv")  # Default to items.csv
    users_csv = os.getenv("ZID_USERS_CSV", "users.csv")  # Default to users.csv

    export_store_to_csv(
        store_id=store_id,
        products_csv=products_csv,
        customers_csv=customers_csv,
        items_csv=items_csv,  # Always create items.csv
        users_csv=users_csv,  # Always create users.csv
    )
