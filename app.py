import os
import json
import time
import threading  # <-- Added for file-write safety
import csv
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

# === AWS Configuration (HARDCODED) ===
AWS_REGION = "ap-south-1"  # Asia Pacific (Mumbai)
S3_BUCKET = "my-zid-app-data"
AWS_PERSONALIZE_ROLE_ARN = "arn:aws:iam::536394435533:role/PersonalizeS3AccessRole"

# === AWS Credentials (HARDCODED) ===
AWS_ACCESS_KEY_ID = "AKIAXZY4ZRPGTB32EA6X"
AWS_SECRET_ACCESS_KEY = "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"

# === Boto3 Clients (Initialize with hardcoded credentials) ===
personalize_runtime = boto3.client(
    'personalize-runtime',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
personalize_events = boto3.client(
    'personalize-events',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
personalize = boto3.client(
    'personalize',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
s3_client = boto3.client(
    's3',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# === NEW: JSON Database Helpers ===

def load_db():
    """Safely loads the JSON database from file."""
    with db_lock:
        try:
            file_path = os.path.abspath(JSON_DB_FILE)
            logger.debug(f"Loading merchants.json from: {file_path}")
            with open(JSON_DB_FILE, "r") as f:
                data = json.load(f)
                logger.debug(f"Loaded {len(data)} merchants from merchants.json")
                return data
        except FileNotFoundError:
            logger.warning(f"merchants.json not found at: {os.path.abspath(JSON_DB_FILE)}")
            return {}  # Return an empty dict if file is empty or missing
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing merchants.json: {e}")
            return {}

def save_db(data):
    """Safely saves data to the JSON database file."""
    with db_lock:
        file_path = os.path.abspath(JSON_DB_FILE)
        logger.info(f"Saving merchants.json to: {file_path}")
        with open(JSON_DB_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(data)} merchants to merchants.json")

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

def get_store_id_from_jwt(token):
    """
    Try to extract store_id from JWT token payload.
    Returns store_id if found, None otherwise.
    """
    try:
        import base64
        # JWT format: header.payload.signature
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        # Decode payload (add padding if needed)
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        decoded = base64.urlsafe_b64decode(payload)
        payload_data = json.loads(decoded)
        
        # Try to find store_id in various fields
        store_id = (
            payload_data.get("store_id") or
            payload_data.get("store") or
            payload_data.get("sub")  # Subject might be store_id
        )
        
        if store_id:
            logger.info(f"Extracted store_id from JWT: {store_id}")
            return str(store_id)
    except Exception as e:
        logger.debug(f"Could not extract store_id from JWT: {e}")
    return None


def get_store_info_from_token(token_resp):
    """
    Helper to call Zid API immediately after auth to get store_id
    and manager_token.
    Based on actual Zid API requirements:
    - Authorization header: Bearer token (from authorization field)
    - Access-Token header: Also uses authorization field (same token)
    - Store-Id header: Store ID (will be extracted from profile response or JWT)
    - Role header: Manager
    """
    try:
        # Token response has: access_token, authorization, refresh_token, etc.
        logger.info(f"Token response keys: {list(token_resp.keys())}")
        
        # Both headers use the authorization field
        auth_token = token_resp.get("authorization")
        if not auth_token:
            logger.error("No authorization field in token response!")
            logger.error(f"Token response keys: {list(token_resp.keys())}")
            return None, None
        
        logger.info("Attempting to fetch store profile from Zid API...")
        logger.info(f"Using Authorization token (Bearer): {auth_token[:50]}...")
        logger.info(f"Using Access-Token (same): {auth_token[:50]}...")
        
        # Try to extract store_id from JWT token first (as fallback)
        store_id_from_jwt = get_store_id_from_jwt(auth_token)
        
        # Get access_token for Access-Token header (different from authorization!)
        access_token = token_resp.get("access_token")
        if not access_token:
            logger.error("No access_token in token response!")
            logger.error(f"Token response keys: {list(token_resp.keys())}")
            return None, None
        
        # Try first call without Store-Id (to get the store_id from profile)
        headers = {
            "Authorization": f"Bearer {auth_token}",  # From authorization field
            "Access-Token": access_token,  # From access_token field - DIFFERENT!
            "Accept": "application/json",
            "Accept-Language": "en",
            "Role": "Manager"
        }
        
        # If we got store_id from JWT, try with Store-Id header
        if store_id_from_jwt:
            headers["Store-Id"] = store_id_from_jwt
            logger.info(f"Adding Store-Id header from JWT: {store_id_from_jwt}")
        
        url = API_BASE + "/app/v1/managers/account/profile"
        logger.info(f"Calling: {url}")
        logger.info(f"Headers: {list(headers.keys())}")
        
        r = requests.get(url, headers=headers, timeout=30)  # Increased timeout for server
        
        logger.info(f"Profile API response status: {r.status_code}")
        logger.info(f"Profile API response headers: {dict(r.headers)}")
        
        if r.status_code != 200:
            logger.error(f"Profile API error: {r.status_code}")
            logger.error(f"Response text: {r.text[:500]}")  # Limit response text length
            logger.error(f"Response headers: {dict(r.headers)}")
            
            # If we have store_id from JWT, use it as fallback
            if store_id_from_jwt:
                logger.warning(f"API call failed, but using store_id from JWT: {store_id_from_jwt}")
                return str(store_id_from_jwt), auth_token
            
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
            logger.warning("Could not find store_id in profile response!")
            logger.warning(f"Profile structure: {json.dumps(profile, indent=2)}")
            
            # Fallback: Try to use store_id from JWT if available
            if store_id_from_jwt:
                logger.warning(f"Using store_id from JWT as fallback: {store_id_from_jwt}")
                return str(store_id_from_jwt), auth_token
            
            # Last resort: Try to extract from any nested structure
            import json as json_module
            profile_str = json_module.dumps(profile)
            logger.error(f"Full profile JSON: {profile_str}")
            return None, None

        logger.info(f"Successfully extracted store_id: {store_id}")
        # Return store_id and access_token (for Access-Token header)
        # Note: authorization token is used for Authorization header, access_token for Access-Token header
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

# === Onboarding Job Functions ===

def upload_csv_to_s3(file_path: str, s3_key: str) -> bool:
    """Upload a CSV file to S3."""
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return False
        
        # Check file size
        file_size = os.path.getsize(file_path)
        logger.info(f"Uploading {file_path} ({file_size} bytes) to s3://{S3_BUCKET}/{s3_key}")
        logger.info(f"Using hardcoded AWS credentials (Access Key ID: {AWS_ACCESS_KEY_ID[:10]}...)")
        
        # Upload to S3
        s3_client.upload_file(file_path, S3_BUCKET, s3_key)
        logger.info(f"✅ Successfully uploaded {file_path} to s3://{S3_BUCKET}/{s3_key}")
        return True
    except FileNotFoundError as e:
        logger.error(f"❌ File not found: {file_path}")
        logger.error(f"Error details: {e}")
        return False
    except Exception as e:
        error_type = type(e).__name__
        logger.error(f"❌ Failed to upload {file_path} to S3")
        logger.error(f"Error type: {error_type}")
        logger.error(f"Error details: {str(e)}")
        
        # Provide helpful error messages for common issues
        if "NoCredentialsError" in error_type or "credentials" in str(e).lower():
            logger.error("")
            logger.error("=" * 60)
            logger.error("AWS CREDENTIALS NOT CONFIGURED!")
            logger.error("=" * 60)
            logger.error("You need to set AWS credentials. Options:")
            logger.error("")
            logger.error("Option 1: Environment Variables (Recommended)")
            logger.error("  export AWS_ACCESS_KEY_ID=your_access_key")
            logger.error("  export AWS_SECRET_ACCESS_KEY=your_secret_key")
            logger.error("  export AWS_DEFAULT_REGION=ap-south-1")
            logger.error("")
            logger.error("Option 2: AWS Credentials File")
            logger.error("  Create ~/.aws/credentials with:")
            logger.error("  [default]")
            logger.error("  aws_access_key_id = your_access_key")
            logger.error("  aws_secret_access_key = your_secret_key")
            logger.error("")
            logger.error("Option 3: If running on EC2, use IAM Role")
            logger.error("=" * 60)
        
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False


def create_personalize_resources(store_id: str) -> tuple:
    """
    Create all AWS Personalize resources for a store.
    Returns (campaign_arn, tracking_id) or (None, None) on failure.
    """
    try:
        dataset_group_name = f"zid-store-{store_id}"
        
        # Step 1: Create Dataset Group
        logger.info(f"[{store_id}] Creating Dataset Group: {dataset_group_name}")
        dataset_group_response = personalize.create_dataset_group(name=dataset_group_name)
        dataset_group_arn = dataset_group_response['datasetGroupArn']
        logger.info(f"[{store_id}] Dataset Group ARN: {dataset_group_arn}")
        
        # Wait for dataset group to be active
        while True:
            status = personalize.describe_dataset_group(datasetGroupArn=dataset_group_arn)['datasetGroup']['status']
            if status == 'ACTIVE':
                break
            logger.info(f"[{store_id}] Waiting for dataset group to be active... Status: {status}")
            time.sleep(5)
        
        # Step 2: Create Schemas
        logger.info(f"[{store_id}] Creating schemas...")
        
        # Items schema
        items_schema = {
            "type": "record",
            "name": "Items",
            "fields": [
                {"name": "ITEM_ID", "type": "string"},
                {"name": "CREATION_TIMESTAMP", "type": "long"},
                {"name": "category", "type": "string"}
            ]
        }
        items_schema_response = personalize.create_schema(
            name=f"{dataset_group_name}-items-schema",
            schema=json.dumps(items_schema)
        )
        items_schema_arn = items_schema_response['schemaArn']
        logger.info(f"[{store_id}] Items Schema ARN: {items_schema_arn}")
        
        # Interactions schema
        interactions_schema = {
            "type": "record",
            "name": "Interactions",
            "fields": [
                {"name": "USER_ID", "type": "string"},
                {"name": "ITEM_ID", "type": "string"},
                {"name": "TIMESTAMP", "type": "long"},
                {"name": "EVENT_TYPE", "type": "string"}
            ]
        }
        interactions_schema_response = personalize.create_schema(
            name=f"{dataset_group_name}-interactions-schema",
            schema=json.dumps(interactions_schema)
        )
        interactions_schema_arn = interactions_schema_response['schemaArn']
        logger.info(f"[{store_id}] Interactions Schema ARN: {interactions_schema_arn}")
        
        # Step 3: Create Datasets
        logger.info(f"[{store_id}] Creating datasets...")
        
        items_dataset_response = personalize.create_dataset(
            name=f"{dataset_group_name}-items",
            datasetGroupArn=dataset_group_arn,
            datasetType='ITEMS',
            schemaArn=items_schema_arn
        )
        items_dataset_arn = items_dataset_response['datasetArn']
        logger.info(f"[{store_id}] Items Dataset ARN: {items_dataset_arn}")
        
        interactions_dataset_response = personalize.create_dataset(
            name=f"{dataset_group_name}-interactions",
            datasetGroupArn=dataset_group_arn,
            datasetType='INTERACTIONS',
            schemaArn=interactions_schema_arn
        )
        interactions_dataset_arn = interactions_dataset_response['datasetArn']
        logger.info(f"[{store_id}] Interactions Dataset ARN: {interactions_dataset_arn}")
        
        # Step 4: Create Dataset Import Jobs
        logger.info(f"[{store_id}] Creating import jobs...")
        
        # Use hardcoded IAM role ARN (required for Personalize to access S3)
        role_arn = AWS_PERSONALIZE_ROLE_ARN
        if not role_arn or "YOUR_ACCOUNT_ID" in role_arn:
            error_msg = (
                "AWS_PERSONALIZE_ROLE_ARN is not configured!\n"
                "Please update AWS_PERSONALIZE_ROLE_ARN in app.py with your actual role ARN.\n"
                "See AWS_SETUP.md for instructions on creating the role."
            )
            logger.error(f"[{store_id}] {error_msg}")
            raise Exception(error_msg)
        
        logger.info(f"[{store_id}] Using IAM Role ARN: {role_arn}")
        
        items_s3_path = f"s3://{S3_BUCKET}/{store_id}/items.csv"
        logger.info(f"[{store_id}] Items S3 path: {items_s3_path}")
        items_import_response = personalize.create_dataset_import_job(
            jobName=f"{dataset_group_name}-items-import",
            datasetArn=items_dataset_arn,
            dataSource={'dataLocation': items_s3_path},
            roleArn=role_arn
        )
        items_import_job_arn = items_import_response['datasetImportJobArn']
        logger.info(f"[{store_id}] Items Import Job ARN: {items_import_job_arn}")
        
        interactions_s3_path = f"s3://{S3_BUCKET}/{store_id}/interactions.csv"
        logger.info(f"[{store_id}] Interactions S3 path: {interactions_s3_path}")
        interactions_import_response = personalize.create_dataset_import_job(
            jobName=f"{dataset_group_name}-interactions-import",
            datasetArn=interactions_dataset_arn,
            dataSource={'dataLocation': interactions_s3_path},
            roleArn=role_arn
        )
        interactions_import_job_arn = interactions_import_response['datasetImportJobArn']
        logger.info(f"[{store_id}] Interactions Import Job ARN: {interactions_import_job_arn}")
        
        # Wait for import jobs to complete
        logger.info(f"[{store_id}] Waiting for import jobs to complete...")
        for job_arn in [items_import_job_arn, interactions_import_job_arn]:
            while True:
                status = personalize.describe_dataset_import_job(datasetImportJobArn=job_arn)['datasetImportJob']['status']
                if status == 'ACTIVE':
                    break
                elif status == 'CREATE FAILED':
                    raise Exception(f"Import job failed: {job_arn}")
                logger.info(f"[{store_id}] Import job {job_arn} status: {status}")
                time.sleep(10)
        
        # Step 5: Create Solution
        logger.info(f"[{store_id}] Creating solution...")
        solution_response = personalize.create_solution(
            name=f"{dataset_group_name}-solution",
            datasetGroupArn=dataset_group_arn,
            recipeArn='arn:aws:personalize:::recipe/aws-similar-items'
        )
        solution_arn = solution_response['solutionArn']
        logger.info(f"[{store_id}] Solution ARN: {solution_arn}")
        
        # Create Solution Version (trains the model)
        logger.info(f"[{store_id}] Creating solution version (this takes 30-60 minutes)...")
        solution_version_response = personalize.create_solution_version(solutionArn=solution_arn)
        solution_version_arn = solution_version_response['solutionVersionArn']
        logger.info(f"[{store_id}] Solution Version ARN: {solution_version_arn}")
        
        # Wait for solution version to complete
        while True:
            status = personalize.describe_solution_version(solutionVersionArn=solution_version_arn)['solutionVersion']['status']
            if status == 'ACTIVE':
                break
            elif status == 'CREATE FAILED':
                raise Exception(f"Solution version failed: {solution_version_arn}")
            logger.info(f"[{store_id}] Solution version status: {status} (this takes 30-60 minutes)")
            time.sleep(60)  # Check every minute
        
        # Step 6: Create Campaign
        logger.info(f"[{store_id}] Creating campaign...")
        campaign_response = personalize.create_campaign(
            name=f"{dataset_group_name}-campaign",
            solutionVersionArn=solution_version_arn,
            minProvisionedTPS=1
        )
        campaign_arn = campaign_response['campaignArn']
        logger.info(f"[{store_id}] Campaign ARN: {campaign_arn}")
        
        # Wait for campaign to be active
        while True:
            status = personalize.describe_campaign(campaignArn=campaign_arn)['campaign']['status']
            if status == 'ACTIVE':
                break
            logger.info(f"[{store_id}] Campaign status: {status}")
            time.sleep(10)
        
        # Step 7: Create Event Tracker
        logger.info(f"[{store_id}] Creating event tracker...")
        tracker_response = personalize.create_event_tracker(
            name=f"{dataset_group_name}-tracker",
            datasetGroupArn=dataset_group_arn
        )
        tracking_id = tracker_response['trackingId']
        logger.info(f"[{store_id}] Tracking ID: {tracking_id}")
        
        return campaign_arn, tracking_id
        
    except Exception as e:
        logger.error(f"[{store_id}] Error creating Personalize resources: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, None


def run_onboarding_job(store_id: str):
    """
    Background job to onboard a new merchant.
    Steps:
    1. Fetch products/orders from Zid API -> Create CSVs -> Upload to S3
    2. Create AWS Personalize resources
    3. Update merchants.json with campaign_arn and tracking_id
    """
    logger.info(f"[{store_id}] Starting onboarding job...")
    
    try:
        # Import export functions
        from export import (
            fetch_all_products,
            fetch_all_orders,
            write_items_csv,
            write_interactions_csv,
            get_valid_tokens
        )
        
        # Step 1: Fetch data and create CSVs
        logger.info(f"[{store_id}] Step 1: Fetching products and orders...")
        
        # Verify tokens are available before fetching
        merchant = get_merchant_by_store_id(store_id)
        if not merchant:
            raise Exception(f"Merchant {store_id} not found in database!")
        
        auth_token = merchant.get("authorization")
        access_token = merchant.get("access_token")
        
        logger.info(f"[{store_id}] ===== TOKEN VERIFICATION =====")
        logger.info(f"[{store_id}] Merchant keys: {list(merchant.keys())}")
        logger.info(f"[{store_id}] Has authorization token: {bool(auth_token)}")
        logger.info(f"[{store_id}] Has access_token: {bool(access_token)}")
        
        if auth_token:
            logger.info(f"[{store_id}] Authorization token length: {len(auth_token)}")
            logger.info(f"[{store_id}] Authorization token preview: {auth_token[:50]}...")
            logger.info(f"[{store_id}] Authorization token ends with: ...{auth_token[-20:]}")
        else:
            logger.error(f"[{store_id}] ERROR: No authorization token!")
        
        if access_token:
            logger.info(f"[{store_id}] Access-Token length: {len(access_token)}")
            logger.info(f"[{store_id}] Access-Token preview: {access_token[:50]}...")
            logger.info(f"[{store_id}] Access-Token ends with: ...{access_token[-20:]}")
        else:
            logger.error(f"[{store_id}] ERROR: No access_token!")
        
        logger.info(f"[{store_id}] Store ID from merchant: {merchant.get('store_id')}")
        logger.info(f"[{store_id}] Tokens match store_id: {merchant.get('store_id') == store_id}")
        logger.info(f"[{store_id}] ================================")
        
        if not auth_token or not access_token:
            logger.error(f"[{store_id}] ERROR: Missing required tokens!")
            logger.error(f"[{store_id}] Full merchant data: {json.dumps({k: str(v)[:100] if isinstance(v, str) else v for k, v in merchant.items()}, indent=2)}")
            raise Exception(f"Merchant {store_id} missing required tokens! Has auth: {bool(auth_token)}, Has access: {bool(access_token)}")
        
        # Check if tokens are expired
        expires_at = merchant.get("expires_at")
        if expires_at:
            time_until_expiry = expires_at - int(time.time())
            logger.info(f"[{store_id}] Token expires in: {time_until_expiry} seconds ({time_until_expiry/86400:.2f} days)")
            if token_is_expired(expires_at):
                logger.warning(f"[{store_id}] Token is expired! Attempting refresh...")
                refreshed = refresh_merchant_token(store_id)
                if refreshed:
                    merchant = refreshed
                    auth_token = merchant.get("authorization")
                    access_token = merchant.get("access_token")
                    logger.info(f"[{store_id}] Token refreshed successfully")
                else:
                    raise Exception(f"Token expired and refresh failed for store {store_id}")
        
        logger.info(f"[{store_id}] ✅ Verified tokens available and valid for API calls")
        
        products = fetch_all_products(store_id)
        logger.info(f"[{store_id}] Fetched {len(products)} products")
        
        orders = fetch_all_orders(store_id)
        logger.info(f"[{store_id}] Fetched {len(orders)} orders")
        
        # Create CSV files locally
        items_csv_path = f"/tmp/{store_id}_items.csv"
        interactions_csv_path = f"/tmp/{store_id}_interactions.csv"
        
        logger.info(f"[{store_id}] Creating CSV files...")
        logger.info(f"[{store_id}] Items CSV path: {items_csv_path}")
        logger.info(f"[{store_id}] Interactions CSV path: {interactions_csv_path}")
        
        try:
            write_items_csv(products, items_csv_path)
            logger.info(f"[{store_id}] ✅ Created items.csv at {items_csv_path}")
        except Exception as e:
            logger.error(f"[{store_id}] ❌ Failed to create items.csv: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        
        try:
            write_interactions_csv(orders, interactions_csv_path)
            logger.info(f"[{store_id}] ✅ Created interactions.csv at {interactions_csv_path}")
        except Exception as e:
            logger.error(f"[{store_id}] ❌ Failed to create interactions.csv: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        
        # Verify files were created
        if not os.path.exists(items_csv_path):
            raise Exception(f"Items CSV file was not created at {items_csv_path}")
        if not os.path.exists(interactions_csv_path):
            raise Exception(f"Interactions CSV file was not created at {interactions_csv_path}")
        
        logger.info(f"[{store_id}] Files verified. Items CSV size: {os.path.getsize(items_csv_path)} bytes")
        logger.info(f"[{store_id}] Files verified. Interactions CSV size: {os.path.getsize(interactions_csv_path)} bytes")
        
        # Step 2: Upload to S3
        logger.info(f"[{store_id}] Step 2: Uploading CSVs to S3...")
        logger.info(f"[{store_id}] S3 Bucket: {S3_BUCKET}")
        logger.info(f"[{store_id}] AWS Region: {AWS_REGION}")
        
        items_s3_key = f"{store_id}/items.csv"
        interactions_s3_key = f"{store_id}/interactions.csv"
        
        logger.info(f"[{store_id}] Uploading items.csv to s3://{S3_BUCKET}/{items_s3_key}")
        if not upload_csv_to_s3(items_csv_path, items_s3_key):
            raise Exception(f"Failed to upload items.csv to S3. Check logs for details.")
        
        logger.info(f"[{store_id}] Uploading interactions.csv to s3://{S3_BUCKET}/{interactions_s3_key}")
        if not upload_csv_to_s3(interactions_csv_path, interactions_s3_key):
            raise Exception(f"Failed to upload interactions.csv to S3. Check logs for details.")
        
        # Step 3: Create Personalize resources
        logger.info(f"[{store_id}] Step 3: Creating AWS Personalize resources...")
        campaign_arn, tracking_id = create_personalize_resources(store_id)
        
        if not campaign_arn or not tracking_id:
            raise Exception("Failed to create Personalize resources")
        
        # Step 4: Update merchants.json
        logger.info(f"[{store_id}] Step 4: Updating merchants.json...")
        db_data = load_db()
        if store_id in db_data:
            db_data[store_id]["campaign_arn"] = campaign_arn
            db_data[store_id]["tracking_id"] = tracking_id
            save_db(db_data)
            logger.info(f"[{store_id}] Successfully updated merchants.json")
        else:
            logger.error(f"[{store_id}] Store not found in merchants.json!")
        
        logger.info(f"[{store_id}] ✅ Onboarding job completed successfully!")
        logger.info(f"[{store_id}] Campaign ARN: {campaign_arn}")
        logger.info(f"[{store_id}] Tracking ID: {tracking_id}")
        
    except Exception as e:
        logger.error(f"[{store_id}] ❌ Onboarding job failed: {e}")
        import traceback
        logger.error(traceback.format_exc())


# === Auth Routes (No changes needed here) ===
    
@app.route("/")
def index():
    logger.debug("Index route accessed")
    content = f"""
    <div class="card card-info">
        <h3>🚀 Welcome to Zid OAuth App</h3>
        <p>This application integrates with Zid's OAuth 2.0 system and AWS Personalize for intelligent product recommendations.</p>
        <a href="/install" class="btn">Start OAuth Installation</a>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <h3>Client ID</h3>
            <p class="number">{CLIENT_ID}</p>
        </div>
        <div class="stat-card">
            <h3>Status</h3>
            <p class="number">✅ Active</p>
        </div>
    </div>
    
    <h2>⚙️ Configuration</h2>
    <table>
        <tr>
            <th>Setting</th>
            <th>Value</th>
        </tr>
        <tr>
            <td><strong>Client ID</strong></td>
            <td><code>{CLIENT_ID}</code></td>
        </tr>
        <tr>
            <td><strong>Redirect URI</strong></td>
            <td><code>{REDIRECT_URI}</code> <span class="badge badge-success">Registered</span></td>
        </tr>
        <tr>
            <td><strong>OAuth Base</strong></td>
            <td><code>{OAUTH_BASE}</code></td>
        </tr>
    </table>
    
    <h2>📊 Quick Links</h2>
    <div style="display: flex; gap: 15px; flex-wrap: wrap;">
        <a href="/data" class="btn">📈 Data Dashboard</a>
        <a href="/merchants" class="btn btn-secondary">📋 Merchants API</a>
        <a href="/recommendations/demo" class="btn btn-success">🤖 View Recommendations</a>
    </div>
    
    <div class="card card-warning">
        <h3>⚠️ Troubleshooting</h3>
        <p><strong>If you see error_code=UNKNOWN:</strong></p>
        <ol>
            <li><strong>Verify Client ID:</strong> Check Partner Dashboard - your Client ID should be <code>{CLIENT_ID}</code></li>
            <li><strong>Check App Status:</strong> Ensure app is <strong>Published/Approved</strong> (not Draft)</li>
            <li><strong>Application URL:</strong> Should match: <code>https://asnb-app.duckdns.org</code></li>
        </ol>
        <a href="/verify" class="btn">Verify Configuration</a>
    </div>
    """
    return render_page("Home", content)

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
    
    content = f"""
    <div class="card card-danger">
        <h2>⚠️ Zid OAuth Error</h2>
        <p><strong>Error Code:</strong> <span class="badge badge-danger">{error_code or 'N/A'}</span></p>
        <p><strong>Message:</strong> {message}</p>
    </div>
    
    <h2>🔧 Your Configuration</h2>
    <table>
        <tr>
            <th>Setting</th>
            <th>Value</th>
        </tr>
        <tr>
            <td><strong>Client ID</strong></td>
            <td><code>{CLIENT_ID}</code></td>
        </tr>
        <tr>
            <td><strong>Redirect URI</strong></td>
            <td><code>{REDIRECT_URI}</code></td>
        </tr>
        <tr>
            <td><strong>App ID</strong></td>
            <td>{app_id or 'N/A'}</td>
        </tr>
    </table>
    
    <div class="card card-info">
        <h3>🔨 Common Fixes</h3>
        <ol>
            <li><strong>Verify Client ID:</strong> Make sure Client ID <code>{CLIENT_ID}</code> matches your app in Partner Dashboard</li>
            <li><strong>Register Redirect URI:</strong> Add <code>{REDIRECT_URI}</code> to "Allowed Redirect URIs"</li>
            <li><strong>Publish App:</strong> Ensure your app is Published/Approved (not Draft)</li>
            <li><strong>Check App Status:</strong> Go to Partner Dashboard and verify app is active</li>
        </ol>
    </div>
    
    <div style="margin-top: 30px;">
        <a href="/verify" class="btn">Go to Verification Page</a>
        <a href="https://partner.zid.sa" target="_blank" class="btn btn-secondary">Zid Partner Dashboard</a>
        <a href="/" class="btn btn-secondary">← Back to Home</a>
    </div>
    """
    return render_page("OAuth Error", content)

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
    
    content = f"""
    <div class="card card-info">
        <h3>🔍 OAuth Configuration Verification</h3>
        <p>Verify that your OAuth configuration matches the Zid Partner Dashboard settings.</p>
    </div>
    
    <h2>⚙️ Current Configuration</h2>
    <table>
        <tr>
            <th>Setting</th>
            <th>Value</th>
        </tr>
        <tr>
            <td><strong>Client ID</strong></td>
            <td><code>{CLIENT_ID}</code></td>
        </tr>
        <tr>
            <td><strong>Redirect URI (Expected)</strong></td>
            <td><code>{expected_redirect}</code> <span class="badge badge-success">Registered</span></td>
        </tr>
        <tr>
            <td><strong>OAuth Base URL</strong></td>
            <td><code>{OAUTH_BASE}</code></td>
        </tr>
    </table>
    
    <div class="card card-warning">
        <h3>⚠️ Important Notes</h3>
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
    
    <div class="card card-danger">
        <h3>⚠️ CRITICAL: Redirect URI Registration</h3>
        <p>You MUST register this EXACT URL in Zid Partner Dashboard:</p>
        <pre><code>{expected_redirect}</code></pre>
    </div>
    
    <h2>📋 Steps to Fix</h2>
    <ol>
        <li>Go to <a href="https://partner.zid.sa" target="_blank">Zid Partner Dashboard</a></li>
        <li>Navigate to your app (Client ID: {CLIENT_ID})</li>
        <li>Find "Allowed Redirect URIs" or "Redirect URIs" section</li>
        <li>Add this EXACT URL (copy-paste to avoid typos):</li>
    </ol>
    <div class="card">
        <pre><code>{expected_redirect}</code></pre>
    </div>
    <ol start="5">
        <li>Ensure your app is <strong>Published/Approved</strong> (not Draft)</li>
        <li>Save changes</li>
    </ol>
    
    <h2>🧪 Test OAuth Flow</h2>
    <a href="/install" class="btn btn-success">Start OAuth Flow</a>
    
    <div class="card">
        <h3>Expected OAuth URL:</h3>
        <pre style="word-break: break-all; font-size: 0.85em;">{authorize_url}</pre>
    </div>
    
    <h2>❌ Common Issues</h2>
    <table>
        <tr>
            <th>Issue</th>
            <th>Example</th>
            <th>Status</th>
        </tr>
        <tr>
            <td>Trailing slash</td>
            <td><code>{expected_redirect}/</code></td>
            <td><span class="badge badge-danger">❌ Wrong</span></td>
        </tr>
        <tr>
            <td>HTTP instead of HTTPS</td>
            <td><code>http://asnb-app.duckdns.org/callback</code></td>
            <td><span class="badge badge-danger">❌ Wrong</span></td>
        </tr>
        <tr>
            <td>Different path</td>
            <td><code>https://asnb-app.duckdns.org/callbacks</code></td>
            <td><span class="badge badge-danger">❌ Wrong</span></td>
        </tr>
        <tr>
            <td>Correct format</td>
            <td><code>{expected_redirect}</code></td>
            <td><span class="badge badge-success">✅ Correct</span></td>
        </tr>
    </table>
    """
    return render_page("Configuration Verification", content)

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
    
    # Print authorization code if received
    if code:
        logger.info("=" * 60)
        logger.info("🔑 AUTHORIZATION CODE RECEIVED!")
        logger.info("=" * 60)
        logger.info(f"Authorization Code: {code}")
        logger.info(f"Code length: {len(code)} characters")
        logger.info(f"Full callback URL: {request.url}")
        logger.info("=" * 60)
        print("\n" + "=" * 60)
        print("🔑 AUTHORIZATION CODE RECEIVED!")
        print("=" * 60)
        print(f"Authorization Code: {code}")
        print(f"Code length: {len(code)} characters")
        print(f"Full callback URL: {request.url}")
        print("=" * 60 + "\n")
    
    if error:
        logger.error(f"OAuth error received: {error}")
        logger.error(f"Error description: {error_description}")
        print(f"\n❌ OAuth Error: {error}")
        print(f"Description: {error_description}\n")
        return f"Error from Zid OAuth: {error}<br>Description: {error_description or 'No description provided'}<br>Check server logs for details.", 400
    
    if not code:
        logger.error("Missing code parameter in callback!")
        logger.error(f"All received parameters: {list(request.args.keys())}")
        logger.error(f"Full request URL: {request.url}")
        logger.error(f"Referer: {referer}")
        logger.error(f"Is from Zid: {is_from_zid}")
        print("\n❌ ERROR: No authorization code received!")
        print(f"Received parameters: {list(request.args.keys())}\n")
        
        # Check if this might be a direct browser access (not from OAuth redirect)
        # If referer is from Zid but no params, it's likely redirect URI mismatch
        if is_from_zid and not request.args:
            logger.error("CRITICAL: Zid redirected but sent NO parameters!")
            logger.error("This means the redirect URI is NOT registered in Partner Dashboard")
            logger.error(f"Expected redirect URI: {REDIRECT_URI}")
        
        # Provide helpful error message based on context
        if not is_from_zid and not request.args:
            content = f"""
            <div class="card card-danger">
                <h2>❌ OAuth Callback Error</h2>
                <p><strong>Issue:</strong> No authorization code received from Zid.</p>
            </div>
            
            <h2>🔍 Possible Causes</h2>
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
            
            <div class="card card-info">
                <h3>🔧 How to Fix</h3>
                <ol>
                    <li>Go to <a href="https://partner.zid.sa" target="_blank">Zid Partner Dashboard</a></li>
                    <li>Navigate to your app (Client ID: {CLIENT_ID})</li>
                    <li>Check "Allowed Redirect URIs" section</li>
                    <li>Ensure <code>{REDIRECT_URI}</code> is listed EXACTLY</li>
                    <li>Make sure your app is published/approved</li>
                </ol>
            </div>
            
            <p><strong>Note:</strong> Check server logs for detailed debugging information.</p>
            <a href="/verify" class="btn">Verify Configuration</a>
            <a href="/" class="btn btn-secondary">← Back to Home</a>
            """
            return render_page("OAuth Callback Error", content), 400
        else:
            return f"Missing code parameter.<br>Received parameters: {list(request.args.keys())}<br>Full URL: {request.url}<br>Referer: {referer}<br>Check server logs for more details.", 400
    
    logger.info("=" * 60)
    logger.info("🔄 EXCHANGING AUTHORIZATION CODE FOR TOKENS...")
    logger.info("=" * 60)
    logger.info(f"Using authorization code: {code[:20]}...{code[-10:]}")
    logger.info(f"Token URL: {TOKEN_URL}")
    logger.info(f"Client ID: {CLIENT_ID}")
    logger.info(f"Redirect URI: {REDIRECT_URI}")
    print("\n" + "=" * 60)
    print("🔄 EXCHANGING AUTHORIZATION CODE FOR TOKENS...")
    print("=" * 60)
    print(f"Authorization Code: {code}")
    print(f"Code length: {len(code)} characters")
    print(f"Token URL: {TOKEN_URL}")
    print(f"Client ID: {CLIENT_ID}")
    print(f"Redirect URI: {REDIRECT_URI}")
    print("=" * 60)

    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    resp = requests.post(TOKEN_URL, data=payload, timeout=10)
    if resp.status_code != 200:
        logger.error(f"Token endpoint error: {resp.status_code}")
        logger.error(f"Response: {resp.text}")
        print(f"\n❌ Token Exchange Failed!")
        print(f"Status Code: {resp.status_code}")
        print(f"Response: {resp.text}\n")
        return f"Token endpoint error: {resp.text}", resp.status_code

    token_resp = resp.json()
    
    logger.info("=" * 60)
    logger.info("🎟️ TOKEN RESPONSE RECEIVED!")
    logger.info("=" * 60)
    logger.info(f"Token response keys: {list(token_resp.keys())}")
    
    # Print ALL token details
    print("\n" + "=" * 60)
    print("🎟️ TOKEN RESPONSE RECEIVED!")
    print("=" * 60)
    print(f"Token Response Keys: {list(token_resp.keys())}")
    print("=" * 60)
    
    if "access_token" in token_resp:
        access_token = token_resp["access_token"]
        logger.info(f"Access Token: {access_token[:30]}...{access_token[-20:]} (length: {len(access_token)})")
        print(f"\nAccess Token:")
        print(f"  {access_token}")
        print(f"  Length: {len(access_token)} characters")
    
    if "authorization" in token_resp:
        auth_token = token_resp["authorization"]
        logger.info(f"Authorization Token: {auth_token[:30]}...{auth_token[-20:]} (length: {len(auth_token)})")
        print(f"\nAuthorization Token:")
        print(f"  {auth_token}")
        print(f"  Length: {len(auth_token)} characters")
    
    if "refresh_token" in token_resp:
        refresh_token = token_resp["refresh_token"]
        logger.info(f"Refresh Token: {refresh_token[:30]}...{refresh_token[-20:]} (length: {len(refresh_token)})")
        print(f"\nRefresh Token:")
        print(f"  {refresh_token}")
        print(f"  Length: {len(refresh_token)} characters")
    
    if "expires_in" in token_resp:
        expires_in = token_resp["expires_in"]
        logger.info(f"Expires In: {expires_in} seconds ({expires_in/86400:.2f} days)")
        print(f"\nExpires In:")
        print(f"  {expires_in} seconds")
        print(f"  {expires_in/86400:.2f} days")
    
    if "token_type" in token_resp:
        token_type = token_resp["token_type"]
        logger.info(f"Token Type: {token_type}")
        print(f"\nToken Type: {token_type}")
    
    logger.info("=" * 60)
    print("=" * 60)

    # According to Zid docs, the token response contains:
    # - access_token: Used as Authorization token
    # - refresh_token: Used to refresh tokens
    # - expires_in: Token expiry time
    # - manager_token/x_manager_token: May be included, otherwise use access_token

    store_id, manager_token = get_store_info_from_token(token_resp)
    
    # Print Store ID
    print("\n" + "=" * 60)
    print("📦 STORE INFORMATION")
    print("=" * 60)
    if store_id:
        print(f"Store ID: {store_id}")
        logger.info(f"Store ID: {store_id}")
    else:
        print("Store ID: NOT FOUND")
        logger.error("Store ID: NOT FOUND")
    print("=" * 60 + "\n")
    
    if not store_id:
        logger.error("Failed to get store_id from profile")
        logger.error("Token response received successfully, but profile API call failed")
        logger.error("Check logs above for detailed error information")
        content = f"""
        <div class="card card-danger">
            <h2>⚠️ Installation Error</h2>
            <p><strong>Issue:</strong> Could not fetch store profile from Zid API.</p>
            <p>The OAuth flow completed successfully, but the profile API call failed.</p>
        </div>
        
        <h2>🔍 Possible Causes</h2>
        <ul>
            <li>API endpoint might be incorrect</li>
            <li>Token format might be wrong</li>
            <li>API response structure might be different</li>
            <li>Network/connectivity issue</li>
        </ul>
        
        <div class="card card-info">
            <h3>📋 Check Server Logs</h3>
            <p>Detailed error information is logged. Check your server logs for:</p>
            <ul>
                <li>Profile API response status</li>
                <li>Response body structure</li>
                <li>Error messages</li>
            </ul>
        </div>
        
        <div class="card">
            <h3>Token Response Keys:</h3>
            <pre><code>{list(token_resp.keys())}</code></pre>
        </div>
        
        <a href="/" class="btn">← Back to Home</a>
        """
        return render_page("Installation Error", content), 500

    # Save tokens to our new JSON database
    save_merchant_tokens(store_id, token_resp, manager_token)
    logger.info(f"Successfully saved tokens for store {store_id}")
    
    # Verify tokens were saved correctly
    saved_merchant = get_merchant_by_store_id(store_id)
    if saved_merchant:
        logger.info(f"Verified tokens saved - has authorization: {bool(saved_merchant.get('authorization'))}")
        logger.info(f"Saved merchant keys: {list(saved_merchant.keys())}")
    else:
        logger.error(f"ERROR: Could not retrieve saved merchant for {store_id}!")
    
    # Small delay to ensure file is fully written
    import time
    time.sleep(1)
    
    # Start background onboarding job
    logger.info(f"Starting background onboarding job for store {store_id}")
    onboarding_thread = threading.Thread(
        target=run_onboarding_job,
        args=(store_id,),
        daemon=True
    )
    onboarding_thread.start()
    
    content = f"""
    <div class="card card-success">
        <h2>✅ App Installed Successfully!</h2>
        <p><strong>Store ID:</strong> <span class="badge badge-info">{store_id}</span></p>
        <p>Your onboarding job has started. This process typically takes 30-60 minutes.</p>
        <p>You will be notified when your Personalize model is ready.</p>
    </div>
    
    <div class="card card-info">
        <h3>🔄 What's Happening Now?</h3>
        <ol>
            <li>Fetching historical data (products, customers, orders)</li>
            <li>Creating CSV files (items.csv, users.csv, interactions.csv)</li>
            <li>Uploading to AWS S3</li>
            <li>Creating AWS Personalize resources</li>
            <li>Training recommendation model</li>
        </ol>
    </div>
    
    <div style="margin-top: 30px;">
        <a href="/data" class="btn">📊 View Dashboard</a>
        <a href="/" class="btn btn-secondary">🏠 Home</a>
    </div>
    """
    return render_page("Installation Success", content)

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
    file_path = os.path.abspath(JSON_DB_FILE)
    
    if not db_data:
        return jsonify({
            "message": "No merchants installed yet",
            "count": 0,
            "merchants": [],
            "debug": {
                "file_path": file_path,
                "file_exists": os.path.exists(JSON_DB_FILE),
                "current_directory": os.getcwd()
            }
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
        "merchants": merchants_list,
        "debug": {
            "file_path": os.path.abspath(JSON_DB_FILE),
            "file_exists": os.path.exists(JSON_DB_FILE)
        }
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
        content = """
        <div class="card card-info">
            <h2>📊 No Data Available</h2>
            <p>No merchants have installed the app yet.</p>
            <a href="/install" class="btn">Start OAuth Flow</a>
        </div>
        """
        return render_page("Dashboard", content)
    
    active_count = sum(1 for m in db_data.values() if not token_is_expired(m.get('expires_at', 0)))
    expired_count = sum(1 for m in db_data.values() if token_is_expired(m.get('expires_at', 0)))
    
    content = f"""
    <div class="stats-grid">
        <div class="stat-card">
            <h3>Total Stores</h3>
            <p class="number">{len(db_data)}</p>
        </div>
        <div class="stat-card">
            <h3>Active Tokens</h3>
            <p class="number">{active_count}</p>
        </div>
        <div class="stat-card">
            <h3>Expired Tokens</h3>
            <p class="number">{expired_count}</p>
        </div>
    </div>
    
    <h2>🏪 Merchant Stores</h2>
    """
    
    for store_id, merchant in db_data.items():
        expires_at = merchant.get("expires_at", 0)
        expires_in = expires_at - int(time.time()) if expires_at else 0
        is_expired = token_is_expired(expires_at)
        expires_readable = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at)) if expires_at else "Never"
        
        status_badge = '<span class="badge badge-danger">Expired</span>' if is_expired else '<span class="badge badge-success">Active</span>'
        card_class = "card-danger" if is_expired else "card-success"
        
        content += f"""
        <div class="card {card_class}">
            <h3>🏪 Store ID: {store_id} {status_badge}</h3>
            <table>
                <tr>
                    <th>Property</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td><strong>Token Expiry</strong></td>
                    <td>{expires_readable}</td>
                </tr>
                <tr>
                    <td><strong>Expires In</strong></td>
                    <td>{round(expires_in / 86400, 2)} days</td>
                </tr>
                <tr>
                    <td><strong>Access Token</strong></td>
                    <td><code>{merchant.get('access_token', 'N/A')[:30]}...</code></td>
                </tr>
                <tr>
                    <td><strong>Has Refresh Token</strong></td>
                    <td>{'✅ Yes' if merchant.get('refresh_token') else '❌ No'}</td>
                </tr>
                <tr>
                    <td><strong>Tracking ID</strong></td>
                    <td><code>{merchant.get('tracking_id', 'Not configured')}</code></td>
                </tr>
                <tr>
                    <td><strong>Campaign ARN</strong></td>
                    <td><code style="word-break: break-all;">{merchant.get('campaign_arn', 'Not configured')}</code></td>
                </tr>
                <tr>
                    <td><strong>Actions</strong></td>
                    <td>
                        <a href="/profile?store_id={store_id}" class="btn btn-secondary" style="padding: 8px 16px; font-size: 0.9em;">View Profile</a>
                        <a href="/refresh?store_id={store_id}" class="btn btn-secondary" style="padding: 8px 16px; font-size: 0.9em;">Refresh Token</a>
                        <a href="/merchants/{store_id}" class="btn btn-secondary" style="padding: 8px 16px; font-size: 0.9em;">JSON Details</a>
                    </td>
                </tr>
            </table>
        </div>
        """
    
    return render_page("Merchant Dashboard", content, [
        ("🏠 Home", "/"),
        ("📊 Dashboard", "/data"),
        ("📋 API", "/merchants"),
    ])

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

def track_interaction(store_id: str, user_id: str, session_id: str, event_type: str, item_id: str):
    """
    Helper function to track an interaction with AWS Personalize Events API.
    """
    merchant = get_merchant_by_store_id(store_id)
    
    if not merchant or not merchant.get("tracking_id"):
        logger.error(f"Store {store_id} not configured or missing tracking_id")
        return False, "Store not configured"
    
    if not item_id:
        logger.error("Missing item_id in tracking request")
        return False, "item_id is required"
    
    try:
        # Prepare event for AWS Personalize
        event = {
            'eventType': event_type,
            'itemId': str(item_id),
                'sentAt': int(time.time())
        }
        
        # Add userId if provided
        params = {
            'trackingId': merchant["tracking_id"],
            'sessionId': session_id or f"session-{int(time.time())}",
            'eventList': [event]
        }
        
        if user_id:
            params['userId'] = str(user_id)
        
        # Send event to AWS Personalize
        personalize_events.put_events(**params)
        
        logger.info(f"✅ Tracked {event_type} event for store {store_id}, user {user_id}, item {item_id}")
        return True, "Event tracked successfully"
        
    except Exception as e:
        logger.error(f"❌ Error tracking event: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, f"Error: {str(e)}"


@app.route("/track/purchase", methods=["POST"])
def track_purchase():
    """
    Track purchase events from frontend snippet.
    Expected JSON: { store_id, user_id, session_id, item_id }
    """
    try:
        data = request.json or {}
        store_id = data.get("store_id")
        user_id = data.get("user_id")
        session_id = data.get("session_id")
        item_id = data.get("item_id")
        
        if not store_id:
            return jsonify({"error": "store_id is required"}), 400
        if not item_id:
            return jsonify({"error": "item_id is required"}), 400
        
        success, message = track_interaction(
            store_id=store_id,
            user_id=user_id,
            session_id=session_id,
            event_type="purchase",
            item_id=item_id
        )
        
        if success:
            return jsonify({"status": "ok", "message": message}), 200
        else:
            return jsonify({"error": message}), 500
            
    except Exception as e:
        logger.error(f"Error in track_purchase: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/track/view", methods=["POST"])
def track_view():
    """
    Track product view events from frontend snippet.
    Expected JSON: { store_id, user_id, session_id, item_id }
    """
    try:
        data = request.json or {}
        store_id = data.get("store_id")
        user_id = data.get("user_id")
        session_id = data.get("session_id")
        item_id = data.get("item_id")
        
        if not store_id:
            return jsonify({"error": "store_id is required"}), 400
        if not item_id:
            return jsonify({"error": "item_id is required"}), 400
        
        success, message = track_interaction(
            store_id=store_id,
            user_id=user_id,
            session_id=session_id,
            event_type="view",
            item_id=item_id
        )
        
        if success:
            return jsonify({"status": "ok", "message": message}), 200
        else:
            return jsonify({"error": message}), 500
            
    except Exception as e:
        logger.error(f"Error in track_view: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/track/cart", methods=["POST"])
def track_cart():
    """
    Track add-to-cart events from frontend snippet.
    Expected JSON: { store_id, user_id, session_id, item_id }
    """
    try:
        data = request.json or {}
        store_id = data.get("store_id")
        user_id = data.get("user_id")
        session_id = data.get("session_id")
        item_id = data.get("item_id")
        
        if not store_id:
            return jsonify({"error": "store_id is required"}), 400
        if not item_id:
            return jsonify({"error": "item_id is required"}), 400
        
        success, message = track_interaction(
            store_id=store_id,
            user_id=user_id,
            session_id=session_id,
            event_type="add_to_cart",
            item_id=item_id
        )
        
        if success:
            return jsonify({"status": "ok", "message": message}), 200
        else:
            return jsonify({"error": message}), 500
            
    except Exception as e:
        logger.error(f"Error in track_cart: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/track", methods=["POST"])
def track_event():
    """Generic tracking endpoint (backward compatibility)."""
    try:
        data = request.json or {}
        store_id = data.get("store_id")
        user_id = data.get("user_id")
        session_id = data.get("session_id")
        event_type = data.get("event_type", "view")
        item_id = data.get("item_id")
        
        if not store_id:
            return jsonify({"error": "store_id is required"}), 400
        if not item_id:
            return jsonify({"error": "item_id is required"}), 400
        
        success, message = track_interaction(
            store_id=store_id,
            user_id=user_id,
            session_id=session_id,
            event_type=event_type,
            item_id=item_id
        )
        
        if success:
            return jsonify({"status": "ok", "message": message}), 200
        else:
            return jsonify({"error": message}), 500
            
    except Exception as e:
        logger.error(f"Error in track_event: {e}")
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

def read_csv_file(filename):
    """Helper function to read CSV file and return list of dictionaries."""
    data = []
    if not os.path.exists(filename):
        return data
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            data = list(reader)
    except Exception as e:
        logger.error(f"Error reading {filename}: {e}")
    return data

@app.route("/recommendations/demo")
def show_recommendations_demo():
    """Display recommendations from recomentaion.json file and related CSV data."""
    try:
        # Read the recommendations JSON file
        json_file = "recomentaion.json"
        if not os.path.exists(json_file):
            content = f"""
            <div class="card card-danger">
                <h2>❌ File Not Found</h2>
                <p>The recommendations file <code>{json_file}</code> was not found.</p>
            </div>
            <a href="/" class="btn">← Back to Home</a>
            """
            return render_page("Recommendations Demo", content), 404
        
        with open(json_file, 'r', encoding='utf-8') as f:
            recommendations_data = json.load(f)
        
        # Read CSV files
        items_data = read_csv_file("items.csv")
        users_data = read_csv_file("users.csv")
        interactions_data = read_csv_file("interactions.csv")
        
        # Create lookup dictionaries for quick access
        items_dict = {item.get('ITEM_ID', ''): item for item in items_data}
        users_dict = {user.get('USER_ID', ''): user for user in users_data}
        
        # Extract data
        item_list = recommendations_data.get("itemList", [])
        recommendation_id = recommendations_data.get("recommendationId", "N/A")
        
        # Build the display content for recommended items with details
        items_html = ""
        for idx, item in enumerate(item_list, 1):
            item_id = item.get("itemId", "N/A")
            item_details = items_dict.get(item_id, {})
            category = item_details.get('category', 'N/A')
            price = item_details.get('price', 'N/A')
            timestamp = item_details.get('CREATION_TIMESTAMP', 'N/A')
            
            # Count interactions for this item
            item_interactions = [i for i in interactions_data if i.get('ITEM_ID') == item_id]
            view_count = len([i for i in item_interactions if i.get('EVENT_TYPE') == 'view'])
            purchase_count = len([i for i in item_interactions if i.get('EVENT_TYPE') == 'purchase'])
            
            items_html += f"""
            <div class="recommendation-item">
                <div class="item-rank">#{idx}</div>
                <div class="item-content">
                    <h4>Product ID: <code>{item_id}</code></h4>
                    <div class="item-details">
                        <p><strong>Category:</strong> {category}</p>
                        <p><strong>Price:</strong> ${price if price != 'N/A' else 'N/A'}</p>
                        <p><strong>Views:</strong> {view_count} | <strong>Purchases:</strong> {purchase_count}</p>
                    </div>
                    <p class="item-label">✨ Recommended by AWS Personalize</p>
                </div>
            </div>
            """
        
        # Build statistics section
        stats_html = f"""
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Items</h3>
                <p class="number">{len(items_data)}</p>
            </div>
            <div class="stat-card">
                <h3>Total Users</h3>
                <p class="number">{len(users_data)}</p>
            </div>
            <div class="stat-card">
                <h3>Total Interactions</h3>
                <p class="number">{len(interactions_data)}</p>
            </div>
            <div class="stat-card">
                <h3>Recommendations</h3>
                <p class="number">{len(item_list)}</p>
            </div>
        </div>
        """
        
        # Build items table
        items_table_html = ""
        if items_data:
            items_table_html = """
            <h2>📦 All Items Catalog</h2>
            <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Item ID</th>
                        <th>Category</th>
                        <th>Price</th>
                        <th>Created</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in items_data[:20]:  # Show first 20 items
                item_id = item.get('ITEM_ID', 'N/A')
                category = item.get('category', 'N/A')
                price = item.get('price', 'N/A')
                timestamp = item.get('CREATION_TIMESTAMP', 'N/A')
                # Convert timestamp to readable date if it's a number
                try:
                    if timestamp and timestamp != 'N/A':
                        readable_date = time.strftime('%Y-%m-%d', time.localtime(int(timestamp)))
                    else:
                        readable_date = 'N/A'
                except:
                    readable_date = timestamp
                
                items_table_html += f"""
                    <tr>
                        <td><code>{item_id}</code></td>
                        <td>{category}</td>
                        <td>${price}</td>
                        <td>{readable_date}</td>
                    </tr>
                """
            items_table_html += """
                </tbody>
            </table>
            </div>
            """
        
        # Build users table
        users_table_html = ""
        if users_data:
            users_table_html = """
            <h2>👥 Users Data</h2>
            <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>User ID</th>
                        <th>Location</th>
                        <th>Gender</th>
                    </tr>
                </thead>
                <tbody>
            """
            for user in users_data:
                user_id = user.get('USER_ID', 'N/A')
                location = user.get('location', 'N/A')
                gender = user.get('gender', 'N/A')
                
                users_table_html += f"""
                    <tr>
                        <td><code>{user_id}</code></td>
                        <td>{location}</td>
                        <td>{gender}</td>
                    </tr>
                """
            users_table_html += """
                </tbody>
            </table>
            </div>
            """
        
        # Build interactions table
        interactions_table_html = ""
        if interactions_data:
            interactions_table_html = """
            <h2>🔄 Recent Interactions</h2>
            <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>User ID</th>
                        <th>Item ID</th>
                        <th>Event Type</th>
                        <th>Timestamp</th>
                    </tr>
                </thead>
                <tbody>
            """
            for interaction in interactions_data[:20]:  # Show first 20 interactions
                user_id = interaction.get('USER_ID', 'N/A')
                item_id = interaction.get('ITEM_ID', 'N/A')
                event_type = interaction.get('EVENT_TYPE', 'N/A')
                timestamp = interaction.get('TIMESTAMP', 'N/A')
                
                # Convert timestamp to readable date
                try:
                    if timestamp and timestamp != 'N/A':
                        readable_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(timestamp)))
                    else:
                        readable_date = 'N/A'
                except:
                    readable_date = timestamp
                
                event_badge = 'badge-success' if event_type == 'purchase' else 'badge-info'
                
                interactions_table_html += f"""
                    <tr>
                        <td><code>{user_id}</code></td>
                        <td><code>{item_id}</code></td>
                        <td><span class="badge {event_badge}">{event_type}</span></td>
                        <td>{readable_date}</td>
                    </tr>
                """
            interactions_table_html += """
                </tbody>
            </table>
            </div>
            """
        
        content = f"""
        <div class="card card-success">
            <h2>🤖 AWS Personalize Recommendations</h2>
            <p>These recommendations were generated by AWS Personalize using machine learning algorithms.</p>
            <p><strong>Recommendation ID:</strong> <code>{recommendation_id}</code></p>
        </div>
        
        {stats_html}
        
        <div class="card card-info">
            <h3>📊 Recommendation Details</h3>
            <table>
                <tr>
                    <th>Total Recommendations</th>
                    <td><span class="badge badge-info">{len(item_list)}</span></td>
                </tr>
                <tr>
                    <th>Recommendation ID</th>
                    <td><code>{recommendation_id}</code></td>
                </tr>
                <tr>
                    <th>Source</th>
                    <td>AWS Personalize ML Model</td>
                </tr>
                <tr>
                    <th>Items in Catalog</th>
                    <td>{len(items_data)}</td>
                </tr>
                <tr>
                    <th>Total Users</th>
                    <td>{len(users_data)}</td>
                </tr>
                <tr>
                    <th>Total Interactions</th>
                    <td>{len(interactions_data)}</td>
                </tr>
            </table>
        </div>
        
        <h2>🎯 Recommended Products</h2>
        <div class="recommendations-container">
            {items_html}
        </div>
        
        {items_table_html}
        
        {users_table_html}
        
        {interactions_table_html}
        
        <div style="margin-top: 30px;">
            <a href="/" class="btn">← Back to Home</a>
            <button onclick="location.reload()" class="btn btn-secondary">🔄 Refresh</button>
        </div>
        """
        
        # Add custom CSS for recommendations display
        custom_css = """
        <style>
            .recommendations-container {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 20px;
                margin: 20px 0;
            }
            
            .recommendation-item {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border-radius: 12px;
                padding: 20px;
                display: flex;
                align-items: flex-start;
                gap: 15px;
                box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
                transition: transform 0.3s, box-shadow 0.3s;
            }
            
            .recommendation-item:hover {
                transform: translateY(-5px);
                box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
            }
            
            .item-rank {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 50%;
                width: 50px;
                height: 50px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.5em;
                font-weight: 700;
                flex-shrink: 0;
            }
            
            .item-content {
                flex: 1;
            }
            
            .item-content h4 {
                color: white;
                margin: 0 0 10px 0;
                font-size: 1.2em;
            }
            
            .item-details {
                margin: 10px 0;
                font-size: 0.9em;
                opacity: 0.95;
            }
            
            .item-details p {
                margin: 5px 0;
            }
            
            .item-content code {
                background: rgba(255, 255, 255, 0.2);
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 1.1em;
            }
            
            .item-label {
                margin: 10px 0 0 0;
                opacity: 0.9;
                font-size: 0.9em;
                font-weight: 600;
            }
            
            .table-container {
                overflow-x: auto;
                margin: 20px 0;
            }
            
            @media (max-width: 768px) {
                .recommendations-container {
                    grid-template-columns: 1fr;
                }
            }
        </style>
        """
        
        # Inject custom CSS into the page
        page_html = render_page("AWS Personalize Recommendations", content)
        page_html = page_html.replace("</head>", custom_css + "</head>")
        
        return page_html
        
    except json.JSONDecodeError as e:
        content = f"""
        <div class="card card-danger">
            <h2>❌ JSON Parse Error</h2>
            <p>Failed to parse the recommendations JSON file.</p>
            <p><strong>Error:</strong> {str(e)}</p>
        </div>
        <a href="/" class="btn">← Back to Home</a>
        """
        return render_page("Recommendations Demo", content), 500
        
    except Exception as e:
        logger.error(f"Error reading recommendations file: {e}")
        content = f"""
        <div class="card card-danger">
            <h2>❌ Error</h2>
            <p>An error occurred while reading the recommendations file.</p>
            <p><strong>Error:</strong> {str(e)}</p>
        </div>
        <a href="/" class="btn">← Back to Home</a>
        """
        return render_page("Recommendations Demo", content), 500

# === UI Helper Functions ===
def render_page(title: str, content: str, nav_links: list = None):
    """
    Render a modern HTML page with consistent styling.
    nav_links: List of tuples [(text, url), ...]
    """
    if nav_links is None:
        nav_links = [
            ("🏠 Home", "/"),
            ("📊 Dashboard", "/data"),
            ("📋 API", "/merchants"),
        ]
    
    nav_html = ""
    for text, url in nav_links:
        nav_html += f'<a href="{url}" class="nav-link">{text}</a>'
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Zid OAuth App</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
                color: #333;
            }}
            
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 16px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                overflow: hidden;
            }}
            
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }}
            
            .header h1 {{
                font-size: 2.5em;
                margin-bottom: 10px;
                font-weight: 700;
            }}
            
            .header p {{
                opacity: 0.9;
                font-size: 1.1em;
            }}
            
            .nav {{
                background: #f8f9fa;
                padding: 15px 30px;
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
                border-bottom: 2px solid #e9ecef;
            }}
            
            .nav-link {{
                color: #667eea;
                text-decoration: none;
                padding: 8px 16px;
                border-radius: 8px;
                transition: all 0.3s;
                font-weight: 500;
            }}
            
            .nav-link:hover {{
                background: #667eea;
                color: white;
                transform: translateY(-2px);
            }}
            
            .content {{
                padding: 40px;
            }}
            
            h2 {{
                color: #667eea;
                font-size: 2em;
                margin-bottom: 20px;
                border-bottom: 3px solid #667eea;
                padding-bottom: 10px;
            }}
            
            h3 {{
                color: #764ba2;
                font-size: 1.5em;
                margin: 25px 0 15px 0;
            }}
            
            .card {{
                background: #f8f9fa;
                border-radius: 12px;
                padding: 25px;
                margin: 20px 0;
                border-left: 4px solid #667eea;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            
            .card-success {{
                background: #d4edda;
                border-left-color: #28a745;
            }}
            
            .card-warning {{
                background: #fff3cd;
                border-left-color: #ffc107;
            }}
            
            .card-danger {{
                background: #f8d7da;
                border-left-color: #dc3545;
            }}
            
            .card-info {{
                background: #d1ecf1;
                border-left-color: #17a2b8;
            }}
            
            .btn {{
                display: inline-block;
                padding: 12px 24px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                transition: all 0.3s;
                border: none;
                cursor: pointer;
                margin: 5px;
            }}
            
            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
            }}
            
            .btn-secondary {{
                background: #6c757d;
            }}
            
            .btn-success {{
                background: #28a745;
            }}
            
            .btn-danger {{
                background: #dc3545;
            }}
            
            code {{
                background: #f4f4f4;
                padding: 2px 8px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                color: #e83e8c;
                font-size: 0.9em;
            }}
            
            pre {{
                background: #2d2d2d;
                color: #f8f8f2;
                padding: 20px;
                border-radius: 8px;
                overflow-x: auto;
                margin: 15px 0;
            }}
            
            pre code {{
                background: none;
                color: inherit;
                padding: 0;
            }}
            
            ul, ol {{
                margin-left: 25px;
                margin-top: 10px;
            }}
            
            li {{
                margin: 8px 0;
                line-height: 1.6;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                background: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            
            th {{
                background: #667eea;
                color: white;
                padding: 15px;
                text-align: left;
                font-weight: 600;
            }}
            
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid #e9ecef;
            }}
            
            tr:hover {{
                background: #f8f9fa;
            }}
            
            .badge {{
                display: inline-block;
                padding: 5px 12px;
                border-radius: 20px;
                font-size: 0.85em;
                font-weight: 600;
                margin: 0 5px;
            }}
            
            .badge-success {{
                background: #28a745;
                color: white;
            }}
            
            .badge-danger {{
                background: #dc3545;
                color: white;
            }}
            
            .badge-warning {{
                background: #ffc107;
                color: #333;
            }}
            
            .badge-info {{
                background: #17a2b8;
                color: white;
            }}
            
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin: 30px 0;
            }}
            
            .stat-card {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 25px;
                border-radius: 12px;
                text-align: center;
                box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            }}
            
            .stat-card h3 {{
                color: white;
                font-size: 1em;
                margin: 0 0 10px 0;
                opacity: 0.9;
                border: none;
                padding: 0;
            }}
            
            .stat-card .number {{
                font-size: 2.5em;
                font-weight: 700;
                margin: 0;
            }}
            
            .footer {{
                background: #f8f9fa;
                padding: 20px;
                text-align: center;
                color: #6c757d;
                border-top: 2px solid #e9ecef;
            }}
            
            @media (max-width: 768px) {{
                .content {{
                    padding: 20px;
                }}
                
                .header h1 {{
                    font-size: 1.8em;
                }}
                
                .nav {{
                    flex-direction: column;
                }}
                
                .stats-grid {{
                    grid-template-columns: 1fr;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{title}</h1>
                <p>Zid OAuth Integration & AWS Personalize</p>
            </div>
            <div class="nav">
                {nav_html}
            </div>
            <div class="content">
                {content}
            </div>
            <div class="footer">
                <p>© 2025 Zid OAuth App | Powered by AWS Personalize</p>
            </div>
        </div>
    </body>
    </html>
    """

# === Run ===
if __name__ == "__main__":
    # The JSON file will be created automatically on first install
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    pass    