"""
POC Integration API - MongoDB Queryable Encryption + AlloyDB
Demonstrates complete workflow: Encrypt → Search → Retrieve

FastAPI REST API that:
1. Encrypts search terms using MongoDB 8.2 Queryable Encryption
2. Searches MongoDB encrypted collection
3. Retrieves UUIDs from MongoDB results
4. Fetches complete customer data from AlloyDB
5. Returns combined results with performance metrics
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import time
import logging
from datetime import datetime, timezone
import base64
import json

# MongoDB imports
from pymongo import MongoClient
from pymongo.encryption_options import AutoEncryptionOpts

# PostgreSQL imports
import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =====================================================================
# Configuration
# =====================================================================

# MongoDB Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/?directConnection=true")
MONGODB_DATABASE = "poc_database"
MONGODB_COLLECTION = "customers"

# AlloyDB Configuration
ALLOYDB_URI = os.getenv("ALLOYDB_URI", "postgresql://postgres:postgres_password@localhost:5432/alloydb_poc")

# Encryption Configuration
MASTER_KEY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".encryption_key")
KEY_VAULT_NAMESPACE = "encryption.__keyVault"

# =====================================================================
# Initialize FastAPI
# =====================================================================

app = FastAPI(
    title="POC Integration API",
    description="MongoDB Queryable Encryption + AlloyDB Integration",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# Pydantic Models
# =====================================================================

class CustomerResponse(BaseModel):
    """Response model for customer data - identical fields in both modes"""
    customer_id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None
    tier: Optional[str] = None
    loyalty_points: Optional[int] = None
    last_purchase_date: Optional[str] = None
    lifetime_value: Optional[float] = None

class PerformanceMetrics(BaseModel):
    """Performance metrics for the request"""
    mongodb_search_ms: float
    mongodb_decrypt_ms: Optional[float] = 0.0  # Time to decrypt MongoDB results (mongodb_only mode)
    alloydb_fetch_ms: Optional[float] = 0.0     # Time to fetch from AlloyDB (hybrid mode)
    total_ms: float
    results_count: int
    mode: str = "hybrid"  # "hybrid" or "mongodb_only"

class SearchResponse(BaseModel):
    """Complete search response with data and metrics"""
    success: bool
    data: List[CustomerResponse]
    metrics: PerformanceMetrics
    timestamp: str

# =====================================================================
# Database Connections
# =====================================================================

class DatabaseManager:
    """Manages MongoDB and AlloyDB connections"""

    def __init__(self):
        self.mongodb_client = None
        self.mongodb_db = None
        self.mongodb_collection = None
        self.client_encryption = None
        self.key_ids = {}
        self.alloydb_conn = None
        self.alloydb_encryption_key = None  # For pgcrypto decryption

    def connect_mongodb(self):
        """Connect to MongoDB with encryption support"""
        try:
            # Read master key (used for both MongoDB and AlloyDB encryption)
            with open(MASTER_KEY_PATH, 'r') as f:
                master_key = f.read().strip()

            # Store for AlloyDB pgcrypto decryption
            self.alloydb_encryption_key = master_key

            # Convert from base64 to bytes (96 bytes for local KMS)
            local_master_key = base64.b64decode(master_key)

            # KMS providers
            kms_providers = {
                "local": {
                    "key": local_master_key
                }
            }

            # First, connect without encryption to load key IDs
            temp_client = MongoClient(MONGODB_URI)
            key_vault = temp_client.get_database("encryption").get_collection("__keyVault")
            raw_keys = {}
            for key_doc in key_vault.find():
                if "keyAltNames" in key_doc and key_doc["keyAltNames"]:
                    key_name = key_doc["keyAltNames"][0]
                    raw_keys[key_name] = key_doc["_id"]

            # Create simplified key mapping (customer_searchable_email_key -> searchable_email)
            for full_key_name, key_id in raw_keys.items():
                # Extract field name from "customer_{field}_key" format
                if full_key_name.startswith("customer_") and full_key_name.endswith("_key"):
                    field_name = full_key_name[9:-4]  # Remove "customer_" prefix and "_key" suffix
                    self.key_ids[field_name] = key_id
                else:
                    # Keep original name if it doesn't match expected format
                    self.key_ids[full_key_name] = key_id

            temp_client.close()

            logger.info(f"Loaded {len(self.key_ids)} encryption keys")

            # Configure encryptedFieldsMap for automatic encryption
            encrypted_fields_map = {
                "poc_database.customers": {
                    "fields": [
                        {
                            "path": "searchable_name",
                            "bsonType": "string",
                            "keyId": self.key_ids["searchable_name"],
                            "queries": [
                                {
                                    "queryType": "substringPreview",
                                    "contention": 0,
                                    "strMinQueryLength": 2,
                                    "strMaxQueryLength": 10,
                                    "strMaxLength": 60,
                                    "caseSensitive": False,
                                    "diacriticSensitive": False
                                }
                            ]
                        },
                        {
                            "path": "searchable_email",
                            "bsonType": "string",
                            "keyId": self.key_ids["searchable_email"],
                            "queries": [
                                {
                                    "queryType": "prefixPreview",
                                    "contention": 0,
                                    "strMinQueryLength": 3,
                                    "strMaxQueryLength": 60,
                                    "strMaxLength": 100,
                                    "caseSensitive": False,
                                    "diacriticSensitive": False
                                }
                            ]
                        },
                        {
                            "path": "searchable_phone",
                            "bsonType": "string",
                            "keyId": self.key_ids["searchable_phone"],
                            "queries": [{"queryType": "equality", "contention": 0}]
                        },
                        {
                            "path": "metadata.category",
                            "bsonType": "string",
                            "keyId": self.key_ids["metadata_category"],
                            "queries": [{"queryType": "equality", "contention": 0}]
                        },
                        {
                            "path": "metadata.status",
                            "bsonType": "string",
                            "keyId": self.key_ids["metadata_status"],
                            "queries": [{"queryType": "equality", "contention": 0}]
                        }
                    ]
                }
            }

            # Configure automatic encryption options
            auto_encryption_opts = AutoEncryptionOpts(
                kms_providers=kms_providers,
                key_vault_namespace=KEY_VAULT_NAMESPACE,
                encrypted_fields_map=encrypted_fields_map,
                crypt_shared_lib_path="/usr/local/lib/mongo_crypt/mongo_crypt_v1.so",
                crypt_shared_lib_required=True
            )

            # Connect to MongoDB with automatic encryption
            self.mongodb_client = MongoClient(
                f"{MONGODB_URI}/?directConnection=true&w=1&readPreference=primary",
                auto_encryption_opts=auto_encryption_opts
            )
            self.mongodb_db = self.mongodb_client[MONGODB_DATABASE]
            self.mongodb_collection = self.mongodb_db[MONGODB_COLLECTION]

            logger.info("MongoDB connected with automatic encryption")
            return True

        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise

    def connect_alloydb(self):
        """Connect to AlloyDB (PostgreSQL)"""
        try:
            self.alloydb_conn = psycopg2.connect(ALLOYDB_URI)
            logger.info("AlloyDB connected successfully")
            return True
        except Exception as e:
            logger.error(f"AlloyDB connection failed: {e}")
            raise

    def close(self):
        """Close all database connections"""
        if self.mongodb_client:
            self.mongodb_client.close()
        if self.alloydb_conn:
            self.alloydb_conn.close()
        logger.info("All database connections closed")

# Global database manager
db_manager = DatabaseManager()

# =====================================================================
# Startup and Shutdown Events
# =====================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database connections on startup"""
    logger.info("Starting POC Integration API...")
    db_manager.connect_mongodb()
    db_manager.connect_alloydb()
    logger.info("API ready to accept requests")

@app.on_event("shutdown")
async def shutdown_event():
    """Close database connections on shutdown"""
    logger.info("Shutting down POC Integration API...")
    db_manager.close()

# =====================================================================
# Constants
# =====================================================================

# Field mapping from API field names to MongoDB field names
FIELD_MAPPING = {
    "email": "searchable_email",
    "name": "searchable_name",
    "phone": "searchable_phone",
    "category": "metadata.category",
    "status": "metadata.status"
}

# =====================================================================
# Helper Functions
# =====================================================================

def get_mongo_field(field: str) -> str:
    """Get MongoDB field name from API field name

    Args:
        field: API field name

    Returns:
        MongoDB field name
    """
    return FIELD_MAPPING.get(field, field)

def build_mongodb_query(field: str, value: str, query_type: str) -> dict:
    """Build MongoDB query for all query types (equality, prefix, suffix, substring)

    Args:
        field: Field name to search (email, name, phone, category, status)
        value: Search value
        query_type: Type of query ("equality", "prefix", "suffix", "substring")

    Returns:
        MongoDB query dictionary

    Raises:
        ValueError: If query_type is not supported
    """
    # Get MongoDB field name using centralized mapping
    mongo_field = get_mongo_field(field)

    # Equality queries use simple field match
    if query_type == "equality":
        return {mongo_field: value}

    # Build query based on type
    if query_type == "prefix":
        return {
            "$expr": {
                "$encStrStartsWith": {
                    "input": f"${mongo_field}",
                    "prefix": value
                }
            }
        }
    elif query_type == "suffix":
        return {
            "$expr": {
                "$encStrEndsWith": {
                    "input": f"${mongo_field}",
                    "suffix": value
                }
            }
        }
    elif query_type == "substring":
        return {
            "$expr": {
                "$encStrContains": {
                    "input": f"${mongo_field}",
                    "substring": value
                }
            }
        }
    else:
        raise ValueError(f"Unsupported query type: {query_type}")

def extract_customer_from_document(doc: dict) -> dict:
    """Extract and parse customer data from MongoDB document

    Args:
        doc: MongoDB document

    Returns:
        Customer dictionary with parsed fields
    """
    customer = {
        "customer_id": doc.get("alloy_record_id"),
        "full_name": doc.get("searchable_name"),
        "email": doc.get("searchable_email"),
        "phone": doc.get("searchable_phone"),
        "address": doc.get("address"),
        "preferences": doc.get("preferences"),
        "tier": doc.get("metadata", {}).get("tier"),
        "loyalty_points": doc.get("metadata", {}).get("loyalty_points", 0),
        "last_purchase_date": doc.get("metadata", {}).get("last_purchase_date"),
        "lifetime_value": float(doc.get("metadata", {}).get("lifetime_value", 0.0))
    }
    return parse_json_fields(customer)

def parse_json_fields(customer_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Parse JSON string fields (address, preferences) into dictionaries

    Args:
        customer_dict: Customer data dictionary

    Returns:
        Customer dictionary with parsed JSON fields
    """
    # Parse address field
    address = customer_dict.get('address')
    if isinstance(address, str):
        try:
            customer_dict['address'] = json.loads(address)
        except json.JSONDecodeError:
            customer_dict['address'] = {}

    # Parse preferences field
    preferences = customer_dict.get('preferences')
    if isinstance(preferences, str):
        try:
            customer_dict['preferences'] = json.loads(preferences)
        except json.JSONDecodeError:
            customer_dict['preferences'] = {}

    return customer_dict

def search_mongodb(plaintext_value: str, field: str, query_type: str = "equality", limit: int = 100) -> tuple[List[str], float]:
    """
    Search MongoDB encrypted collection using automatic encryption

    Handles all query types: equality, prefix, suffix, substring.
    With automatic encryption, the driver encrypts the query automatically.

    Args:
        plaintext_value: Plaintext search value (driver will encrypt automatically)
        field: Field name to search
        query_type: Type of query ("equality", "prefix", "suffix", "substring")
        limit: Maximum number of results to return (default: 100)

    Returns:
        Tuple of (list of UUIDs, elapsed time in ms)
    """
    start_time = time.time()

    # Build query using unified helper function
    query = build_mongodb_query(field, plaintext_value, query_type)

    results = list(db_manager.mongodb_collection.find(query, {"alloy_record_id": 1}).limit(limit))

    # Extract UUIDs
    uuids = [doc.get("alloy_record_id") for doc in results if "alloy_record_id" in doc]

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"MongoDB search ({query_type}) completed in {elapsed_ms:.2f}ms. Found {len(uuids)} results.")

    return uuids, elapsed_ms

def fetch_from_alloydb(uuids: List[str]) -> tuple[List[Dict], float]:
    """
    Fetch customer data from AlloyDB by UUIDs and decrypt using pgcrypto

    Args:
        uuids: List of customer UUIDs

    Returns:
        Tuple of (customer data list, elapsed time in ms)
    """
    if not uuids:
        return [], 0.0

    start_time = time.time()

    try:
        with db_manager.alloydb_conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Fetch encrypted data and decrypt using pgp_sym_decrypt
            # Decryption happens in database for fair performance comparison with MongoDB
            query = """
                SELECT
                    id AS customer_id,
                    pgp_sym_decrypt(full_name_encrypted, %s) AS full_name,
                    pgp_sym_decrypt(email_encrypted, %s) AS email,
                    pgp_sym_decrypt(phone_encrypted, %s) AS phone,
                    pgp_sym_decrypt(address_encrypted, %s) AS address,
                    pgp_sym_decrypt(preferences_encrypted, %s) AS preferences,
                    tier,
                    loyalty_points,
                    last_purchase_date,
                    lifetime_value
                FROM customers
                WHERE id = ANY(%s::uuid[])
            """

            # Execute with decryption key for each encrypted field
            cursor.execute(query, (
                db_manager.alloydb_encryption_key,
                db_manager.alloydb_encryption_key,
                db_manager.alloydb_encryption_key,
                db_manager.alloydb_encryption_key,
                db_manager.alloydb_encryption_key,
                uuids
            ))
            results = cursor.fetchall()

            # Convert to list of dicts
            customers = []
            for row in results:
                customer = parse_json_fields(dict(row))
                customers.append(customer)

            # Commit the transaction
            db_manager.alloydb_conn.commit()

    except Exception as e:
        # Rollback the transaction on error
        if db_manager.alloydb_conn:
            db_manager.alloydb_conn.rollback()
        logger.error(f"AlloyDB query failed: {e}")
        raise

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"AlloyDB fetch completed in {elapsed_ms:.2f}ms. Retrieved {len(customers)} records.")

    return customers, elapsed_ms

def fetch_and_decrypt_from_mongodb(plaintext_value: str, field: str, query_type: str = "equality", limit: int = 100) -> tuple[List[Dict], float]:
    """
    Fetch customer data directly from MongoDB with automatic decryption (MongoDB-only mode)

    Handles all query types: equality, prefix, suffix, substring.
    With automatic encryption, the driver encrypts queries and decrypts results.

    Args:
        plaintext_value: Plaintext search value (driver will encrypt automatically)
        field: Field name to search
        query_type: Type of query ("equality", "prefix", "suffix", "substring")
        limit: Maximum number of results to return (default: 100)

    Returns:
        Tuple of (customer data list, elapsed time in ms)
    """
    start_time = time.time()

    # Build query using unified helper function
    query = build_mongodb_query(field, plaintext_value, query_type)

    # Execute query with automatic encryption/decryption
    results = list(db_manager.mongodb_collection.find(query).limit(limit))

    # Extract customer data - fields are automatically decrypted by driver
    customers = []
    for doc in results:
        try:
            customer = extract_customer_from_document(doc)
            customers.append(customer)
        except Exception as e:
            logger.error(f"Failed to process document: {e}")
            continue

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"MongoDB fetch ({query_type}) completed in {elapsed_ms:.2f}ms. Retrieved {len(customers)} records.")

    return customers, elapsed_ms

async def unified_search_handler(
    value: str,
    field: str,
    mode: str,
    query_type: str = "equality",
    limit: int = 100
) -> SearchResponse:
    """
    Unified search handler for all query types

    This function consolidates the logic for all search operations (equality, prefix,
    suffix, substring) across both modes (hybrid and mongodb_only), eliminating
    endpoint duplication.

    Args:
        value: Search value (email, name, phone, etc.)
        field: Field name to search ("email", "name", "phone", "category", "status")
        mode: Search mode ("hybrid" or "mongodb_only")
        query_type: Type of query ("equality", "prefix", "suffix", "substring")
        limit: Maximum number of results to return

    Returns:
        SearchResponse with customer data and performance metrics

    Raises:
        HTTPException: On search failure
    """
    request_start = time.time()

    try:
        logger.info(f"Searching {field} ({query_type}): {value} (mode: {mode}, limit: {limit})")

        # MongoDB-only mode: fetch all fields from MongoDB
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb(value, field, query_type, limit)

            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=fetch_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.now(timezone.utc).isoformat()
            )

        # Hybrid mode: MongoDB search + AlloyDB fetch
        uuids, mongodb_time = search_mongodb(value, field, query_type, limit)

        if not uuids:
            return SearchResponse(
                success=True,
                data=[],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=mongodb_time,
                    mongodb_decrypt_ms=0.0,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=0,
                    mode="hybrid"
                ),
                timestamp=datetime.now(timezone.utc).isoformat()
            )

        customers, alloydb_time = fetch_from_alloydb(uuids)

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=(time.time() - request_start) * 1000,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Search failed ({field}, {query_type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================================
# API Endpoints
# =====================================================================

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "POC Integration API",
        "version": "1.0.0",
        "description": "MongoDB Queryable Encryption + AlloyDB Integration",
        "endpoints": {
            "search_by_email": "/api/v1/customers/search/email",
            "search_by_email_prefix": "/api/v1/customers/search/email/prefix",
            "search_by_name": "/api/v1/customers/search/name",
            "search_by_name_substring": "/api/v1/customers/search/name/substring",
            "search_by_phone": "/api/v1/customers/search/phone",
            "search_by_category": "/api/v1/customers/search/category",
            "search_by_status": "/api/v1/customers/search/status",
            "get_by_id": "/api/v1/customers/{customer_id}",
            "health": "/health"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    mongodb_customers = 0
    try:
        # Check MongoDB
        db_manager.mongodb_client.admin.command('ping')
        mongodb_status = "connected"
        # Get customer count
        mongodb_customers = db_manager.mongodb_db.customers.count_documents({})
    except Exception as e:
        mongodb_status = f"error: {str(e)}"

    try:
        # Check AlloyDB
        with db_manager.alloydb_conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        alloydb_status = "connected"
    except Exception as e:
        alloydb_status = f"error: {str(e)}"

    return {
        "status": "healthy" if mongodb_status == "connected" and alloydb_status == "connected" else "degraded",
        "mongodb": mongodb_status,
        "alloydb": alloydb_status,
        "mongodb_customers": mongodb_customers,
        "encryption_keys": len(db_manager.key_ids),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/v1/customers/search/email", response_model=SearchResponse)
async def search_by_email(
    email: str = Query(..., description="Customer email to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """
    Search customers by email (encrypted search)

    Workflow (hybrid mode):
    1. Encrypt the email search term
    2. Query MongoDB encrypted collection
    3. Get UUIDs from MongoDB results
    4. Fetch full customer data from AlloyDB
    5. Return combined results with performance metrics

    Workflow (mongodb_only mode):
    1. Encrypt the email search term
    2. Query MongoDB encrypted collection
    3. Decrypt all fields directly from MongoDB
    4. Return decrypted results with performance metrics
    """
    return await unified_search_handler(email, "email", mode, "equality")

@app.get("/api/v1/customers/search/name", response_model=SearchResponse)
async def search_by_name(
    name: str = Query(..., description="Customer name to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """Search customers by name (encrypted search)"""
    return await unified_search_handler(name, "name", mode, "equality")

@app.get("/api/v1/customers/search/phone", response_model=SearchResponse)
async def search_by_phone(
    phone: str = Query(..., description="Customer phone to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)"),
    limit: int = Query(100, description="Maximum number of results to return (1-10000)", ge=1, le=10000)
):
    """Search customers by phone (encrypted search)"""
    return await unified_search_handler(phone, "phone", mode, "equality", limit)

@app.get("/api/v1/customers/search/category", response_model=SearchResponse)
async def search_by_category(
    category: str = Query(..., description="Customer category to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)"),
    limit: int = Query(100, description="Maximum number of results to return (1-10000)", ge=1, le=10000)
):
    """Search customers by category (encrypted metadata field)"""
    return await unified_search_handler(category, "category", mode, "equality", limit)

@app.get("/api/v1/customers/search/status", response_model=SearchResponse)
async def search_by_status(
    status: str = Query(..., description="Customer status to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)"),
    limit: int = Query(100, description="Maximum number of results to return (1-10000)", ge=1, le=10000)
):
    """Search customers by status (encrypted metadata field)"""
    return await unified_search_handler(status, "status", mode, "equality", limit)

# =====================================================================
# Preview Search Endpoints (Email Prefix, Name Substring)
# =====================================================================

@app.get("/api/v1/customers/search/email/prefix", response_model=SearchResponse)
async def search_by_email_prefix(
    prefix: str = Query(..., description="Email prefix to search", min_length=1),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)"),
    limit: int = Query(100, description="Maximum number of results to return (1-10000)", ge=1, le=10000)
):
    """
    Search customers by email prefix (encrypted prefix search)

    Preview Feature: Uses MongoDB 8.2 prefixPreview query type with automatic encryption
    Note: This is a preview feature and should not be used in production

    Example: prefix="john" will match "john@example.com", "john.doe@test.com", etc.
    """
    return await unified_search_handler(prefix, "email", mode, "prefix", limit)

@app.get("/api/v1/customers/search/name/substring", response_model=SearchResponse)
async def search_by_name_substring(
    substring: str = Query(..., description="Name substring to search", min_length=2, max_length=10),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)"),
    limit: int = Query(100, description="Maximum number of results to return (1-10000)", ge=1, le=10000)
):
    """
    Search customers by name substring (encrypted substring search)

    Preview Feature: Uses MongoDB 8.2 substringPreview query type with automatic encryption
    Note: This is a preview feature and should not be used in production

    Example: substring="mit" will match "John Smith", "Smith Johnson", etc.

    Constraints:
    - Minimum length: 2 characters
    - Maximum length: 10 characters
    """
    return await unified_search_handler(substring, "name", mode, "substring", limit)

@app.get("/api/v1/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer_by_id(customer_id: str):
    """Get customer by UUID (direct AlloyDB query, no encryption)"""
    try:
        customers, _ = fetch_from_alloydb([customer_id])

        if not customers:
            raise HTTPException(status_code=404, detail="Customer not found")

        return CustomerResponse(**customers[0])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get customer by ID failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
