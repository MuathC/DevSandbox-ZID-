# zid_export.py
import os
import csv
import json
import time
import requests

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

# Tokens from test_call.py - can be overridden via environment variables
DEFAULT_ACCESS_TOKEN = os.getenv(
    "ZID_ACCESS_TOKEN",
    "eyJpdiI6InRqVVB4VG5sV1JwODlKU212cS9XVWc9PSIsInZhbHVlIjoiOGpFOUhQQzRLYytMR2N1MmNPbGVaZ200M2hMM3BCbnlVclFhbzl6dUNzRXZyUnFqa2ZUMEtEYmoyQU5MQkRGMzZ5bUlCZDhsdjZHWWFYay9BV3RvNVN4OStSQVIrMXEvQWRPblpwSVZOQkUvWjVaSEpRRWtvUWZmYXcyUkxBUVdrTnRMK09QQ3llREFqZHlKdkNNYUEyOWpzUmV0c20vZXF0SGFtRmtYYmRLMTBNdlpQVWZZTHpDRkp3SDJaZzRTQTRlZGgxTml1R2N2TGJudVVCdTBRMUxzZDJCRllzTENFbk90QURHL3pyMD0iLCJtYWMiOiI5YjViMmNhNzUyNjAxMjk2YjU1MmYwMjYxODdmMjcxNTEzYTZlZWFlMDhiN2U1YzIwY2I2MTQ5N2ZjNzMyYWQzIiwidGFnIjoiIn0="
)

DEFAULT_AUTHORIZATION_TOKEN = os.getenv(
    "ZID_AUTHORIZATION_TOKEN",
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI1NDEwIiwianRpIjoiZmE2MjhiNGJmMzdjNzA0MTZjN2VhY2M3ODA2MTBjZmZkNWFkZjMwNmIxMDhiM2I0OTI2NjgyNmY2ZjI2NzUwYWM0MjgxMGE1M2Y3MDQxMzgiLCJpYXQiOjE3NjMyMTE2ODQuOTM0MTgzLCJuYmYiOjE3NjMyMTE2ODQuOTM0MTg3LCJleHAiOjE4NTc5MDYwODQuODQzNTk1LCJzdWIiOiIyODU5ODczIiwic2NvcGVzIjpbInRoaXJkX2FjY291bnRfcmVhZCIsInRoaXJkX3ZhdF9yZWFkIiwidGhpcmRfY2F0ZWdvcmllc19yZWFkIiwidGhpcmRfY2F0ZWdvcmllc193cml0ZSIsInRoaXJkX2N1c3RvbWVyc19yZWFkIiwidGhpcmRfY3VzdG9tZXJzX3dyaXRlIiwidGhpcmRfb3JkZXJfcmVhZCIsInRoaXJkX29yZGVyX3dyaXRlIiwidGhpcmRfY291cG9uc193cml0ZSIsInRoaXJkX2RlbGl2ZXJ5X29wdGlvbnNfcmVhZCIsInRoaXJkX2RlbGl2ZXJ5X29wdGlvbnNfd3JpdGUiLCJ0aGlyZF9hYmFuZG9uZWRfY2FydHNfcmVhZCIsInRoaXJkX3BheW1lbnRfcmVhZCIsInRoaXJkX3dlYmhvb2tfcmVhZCIsInRoaXJkX3dlYmhvb2tfd3JpdGUiLCJ0aGlyZF9wcm9kdWN0X3JlYWQiLCJ0aGlyZF9wcm9kdWN0X3dyaXRlIiwidGhpcmRfY291bnRyaWVzX3JlYWQiLCJ0aGlyZF9jYXRhbG9nX3dyaXRlIiwidGhpcmRfc3Vic2NyaXB0aW9uX3JlYWQiLCJ0aGlyZF9pbnZlbnRvcnlfcmVhZCIsInRoaXJkX2pzX3dyaXRlIiwidGhpcmRfYnVuZGxlX29mZmVyc19yZWFkIiwidGhpcmRfY3JlYXRlX29yZGVyIiwidGhpcmRfcHJvZHVjdF9zdG9ja19yZWFkIiwidGhpcmRfcHJvZHVjdF9zdG9ja193cml0ZSIsInRoaXJkX2ludmVudG9yeV93cml0ZSIsImVtYmVkZGVkX2FwcHNfdG9rZW5zX3dyaXRlIiwidGhpcmRfbG95YWx0eV9yZWFkIiwidGhpcmRfbG95YWx0eV93cml0ZSIsInRoaXJkX29yZGVyX3JldmVyc2Vfd3JpdGUiLCJ0aGlyZF9vcmRlcl9yZXZlcnNlX3JlYWQiLCJ0aGlyZF9wcm9kdWN0X2F2YWlsYWJpbGl0eV9ub3RpZmljYXRpb25zX3JlYWQiLCJ0aGlyZF9wcm9kdWN0X2F2YWlsYWJpbGl0eV9ub3RpZmljYXRpb25zX3dyaXRlIiwidGhpcmRfY291cG9uc19yZWFkIiwidGhpcmRfc3Vic2NyaXB0aW9uX3dyaXRlIl19.Q5G-zWHhXW1YH2_TZxl-LfZciXoDYNyZR7VCvn7HBpj2IeFdjNoyWlVzC_tCZpNwXIInHRvsTeCmq8MeNxSkefMxzqX1c1r_FPcm72FtaJeUhwuu-5d3rDMwwv6TwxEQ3beL86405W_jDkiEvE7naL0HaL--aagXMkmC1dHZv-H-EXy7b2NL12i-L9E1ZVq5A7QhacMfTzhVe1GwOeX9BYmpVbTLc233yWQctiK_a-ayksTQDLHOq4TQnbpWME0f-XfThXBFPXfVO9gvL6Ln6IoMSw2m8FFewWSIpEeTkv636VrUZBkAnh3ZgD1DDA4nkstmi7v72_6O0IPDKsiTSKFyhyJmDswauE8Dt1lT8lwdkkbSScVvWHPq7cSUO2QMBB77QnMWBYDqFHshYbw4hnMYsydFhi4sCKiXyZi2QUBiN3frj0PiLBa4JmsqFQshknApivReNIPnxEcO-Qo6XkfQwtWoV_xY9m_i4rCvVQXdnIjv3zl7334KucHV3DXCA06zR0sjA61uUGoNpIUnMazRf-AjaQUMi-MXHvvLiMdzYhcosxVo1tRs-Uc-PFtDdZZW9TKOPrb_02xAB6uhVzqiKGoZD2S1pA3uh-cvvzIjPDRD6dyhnnUy9l8dTAIZFnichFbY-QzrxsrGPd1iqM6tgysl_is25d_uUl2rc9g"
)

DEFAULT_STORE_ID = os.getenv("ZID_STORE_ID", "2803554")

# -------------------------------------------------------------------
# Token handling
# -------------------------------------------------------------------

def get_valid_tokens(store_id: str = None) -> dict:
    """
    Get tokens - priority:
    1. Environment variables (ZID_ACCESS_TOKEN, ZID_AUTHORIZATION_TOKEN)
    2. Database (merchants.json) if app.py is available
    3. Default tokens from test_call.py
    """
    # Check environment variables first
    access_token = os.getenv("ZID_ACCESS_TOKEN", DEFAULT_ACCESS_TOKEN)
    auth_token = os.getenv("ZID_AUTHORIZATION_TOKEN", DEFAULT_AUTHORIZATION_TOKEN)
    
    # If env vars are set, use them
    if os.getenv("ZID_ACCESS_TOKEN") or os.getenv("ZID_AUTHORIZATION_TOKEN"):
        return {
            "access_token": access_token,
            "authorization": auth_token,
            "store_id": store_id or DEFAULT_STORE_ID
        }
    
    # Try database if available
    if APP_AVAILABLE and store_id:
        try:
            merchant = get_merchant_by_store_id(store_id)
            if merchant:
                return merchant
        except:
            pass
    
    # Fall back to default tokens from test_call.py
    return {
        "access_token": access_token,
        "authorization": auth_token,
        "store_id": store_id or DEFAULT_STORE_ID
    }


def build_auth_headers(tokens: dict, store_id: str = None) -> dict:
    """
    Build Zid auth headers matching test_call.py format:
      - Authorization: Bearer <authorization token>
      - Access-Token: <access_token>
      - Store-Id: <store_id>
      - Role: Manager
    """
    # Get tokens
    auth_token = tokens.get("authorization") or tokens.get("access_token")
    access_token = tokens.get("access_token")
    final_store_id = store_id or tokens.get("store_id") or DEFAULT_STORE_ID
    
    if not auth_token or not access_token:
        raise RuntimeError("Missing required tokens")

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Access-Token": access_token,
        "Store-Id": str(final_store_id),
        "Accept": "application/json",
        "Accept-Language": "en",
        "Role": "Manager"
    }
    
    return headers


# -------------------------------------------------------------------
# Low-level request helper
# -------------------------------------------------------------------

def zid_request(method: str, url_or_path: str, store_id: str, **kwargs):
    """
    Make an authenticated request to Zid.
    url_or_path can be either:
      - full URL (https://api.zid.sa/v1/...)
      - path starting with '/' relative to API_BASE.
    """
    tokens = get_valid_tokens(store_id)
    headers = build_auth_headers(tokens, store_id)

    # Merge with any caller-provided headers
    extra_headers = kwargs.pop("headers", {})
    headers.update(extra_headers)

    if url_or_path.startswith("http"):
        url = url_or_path
    else:
        # Assume relative to API_BASE
        url = API_BASE.rstrip("/") + url_or_path

    resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)
    resp.raise_for_status()
    return resp.json()


# -------------------------------------------------------------------
# Fetch all products
# GET https://api.zid.sa/v1/products/?page_size=&page=&attribute_values=...
# -------------------------------------------------------------------

def fetch_all_products(store_id: str, page_size: int = 100) -> list:
    """
    Retrieve all products for a store, following pagination via `next` URL.
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


# -------------------------------------------------------------------
# Main export entrypoint
# -------------------------------------------------------------------

def export_store_to_csv(
    store_id: str,
    products_csv: str = "products.csv",
    customers_csv: str = "customers.csv",
):
    """
    Export both products and customers for the given store_id into CSVs.

    Usage from CLI:
      python export.py
        -> exports first available store_id into products.csv & customers.csv

      ZID_STORE_ID=2803554 python export.py
        -> uses store_id="2803554"
    """
    print(f"Using store_id = {store_id}")
    print(f"Fetching data from Zid API...")

    # PRODUCTS
    print("\n[1/2] Fetching products ...")
    try:
        products = fetch_all_products(store_id)
        print(f"  Found {len(products)} products")
        write_csv(products, products_csv)
    except Exception as e:
        print(f"[ERROR] Failed to fetch products: {e}")
        raise

    # CUSTOMERS
    print("\n[2/2] Fetching customers ...")
    try:
        customers = fetch_all_customers(store_id)
        print(f"  Found {len(customers)} customers")
        write_csv(customers, customers_csv)
    except Exception as e:
        print(f"[ERROR] Failed to fetch customers: {e}")
        raise

    print(f"\n[SUCCESS] Export complete!")
    print(f"  Products: {products_csv}")
    print(f"  Customers: {customers_csv}")


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

    export_store_to_csv(
        store_id=store_id,
        products_csv=products_csv,
        customers_csv=customers_csv,
    )
