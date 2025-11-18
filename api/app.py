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
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
import os
import time
import logging
from datetime import datetime, timezone
import base64

# MongoDB imports
from pymongo import MongoClient
from pymongo.encryption import ClientEncryption, Algorithm, AutoEncryptionOpts
from pymongo.encryption_options import TextOpts, SubstringOpts, PrefixOpts, SuffixOpts
from bson.binary import Binary, STANDARD
from bson.codec_options import CodecOptions
import bson

# PostgreSQL imports
import psycopg2
from psycopg2.extras import RealDictCursor
import json

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

class SearchRequest(BaseModel):
    """Request model for customer search"""
    query: str
    field: str = "email"  # email, name, phone
    mode: str = "id_only"  # id_only, full_data

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

    def connect_mongodb(self):
        """Connect to MongoDB with encryption support"""
        try:
            # Read master key
            with open(MASTER_KEY_PATH, 'r') as f:
                master_key = f.read().strip()

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
                                    "strMaxQueryLength": 30,
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
# Helper Functions
# =====================================================================

def search_mongodb_preview(plaintext_value: str, field: str, query_type: str) -> tuple[List[str], float]:
    """
    Search MongoDB with preview query types (prefix, suffix, substring)
    using automatic encryption

    With automatic encryption, simply query with plaintext - the driver encrypts
    automatically based on the field configuration. For preview queries on fields
    configured with prefixPreview/suffixPreview/substringPreview, pass the search
    value directly and MongoDB will match based on the configured query type.

    Args:
        plaintext_value: Plaintext search value (full or partial)
        field: Field name to search ("email" or "name")
        query_type: Type of preview query ("prefix", "suffix", "substring")

    Returns:
        Tuple of (list of UUIDs, elapsed time in ms)
    """
    start_time = time.time()

    # Map field names to MongoDB field names
    field_map = {
        "email": "searchable_email",
        "name": "searchable_name"
    }

    mongo_field = field_map.get(field)
    if not mongo_field:
        raise ValueError(f"Preview queries not supported for field: {field}")

    # Build MongoDB 8.2 preview query using $expr and encryption operators
    # Reference: https://www.mongodb.com/docs/manual/core/queryable-encryption/qe-encrypted-queries/
    if query_type == "prefix":
        # Use $encStrStartsWith for prefix queries
        query = {
            "$expr": {
                "$encStrStartsWith": {
                    "input": f"${mongo_field}",
                    "prefix": plaintext_value
                }
            }
        }
    elif query_type == "substring":
        # Use $encStrContains for substring queries
        query = {
            "$expr": {
                "$encStrContains": {
                    "input": f"${mongo_field}",
                    "substring": plaintext_value
                }
            }
        }
    else:
        raise ValueError(f"Unsupported query type: {query_type}")

    results = list(db_manager.mongodb_collection.find(query, {"alloy_record_id": 1}))

    # Extract UUIDs
    uuids = [doc.get("alloy_record_id") for doc in results if "alloy_record_id" in doc]

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"MongoDB preview search ({query_type}) completed in {elapsed_ms:.2f}ms. Found {len(uuids)} results.")

    return uuids, elapsed_ms

def fetch_and_decrypt_from_mongodb_preview(plaintext_value: str, field: str, query_type: str) -> tuple[List[Dict], float]:
    """
    Fetch customer data from MongoDB with preview query and automatic decryption

    With automatic encryption, query with plaintext and MongoDB automatically
    decrypts the results based on the encryptedFieldsMap configuration.

    Args:
        plaintext_value: Plaintext search value (full or partial)
        field: Field name ("email" or "name")
        query_type: Preview query type ("prefix", "suffix", "substring")

    Returns:
        Tuple of (customer data list, elapsed time in ms)
    """
    start_time = time.time()

    # Map field names to MongoDB field names
    field_map = {
        "email": "searchable_email",
        "name": "searchable_name"
    }

    mongo_field = field_map.get(field)
    if not mongo_field:
        raise ValueError(f"Preview queries not supported for field: {field}")

    # Build MongoDB 8.2 preview query using $expr and encryption operators
    # Reference: https://www.mongodb.com/docs/manual/core/queryable-encryption/qe-encrypted-queries/
    if query_type == "prefix":
        # Use $encStrStartsWith for prefix queries
        query = {
            "$expr": {
                "$encStrStartsWith": {
                    "input": f"${mongo_field}",
                    "prefix": plaintext_value
                }
            }
        }
    elif query_type == "substring":
        # Use $encStrContains for substring queries
        query = {
            "$expr": {
                "$encStrContains": {
                    "input": f"${mongo_field}",
                    "substring": plaintext_value
                }
            }
        }
    else:
        raise ValueError(f"Unsupported query type: {query_type}")

    # Execute query with automatic encryption/decryption
    results = list(db_manager.mongodb_collection.find(query))

    # Extract customer data - fields are automatically decrypted
    customers = []
    for doc in results:
        try:
            address = doc.get("address")
            if isinstance(address, str):
                try:
                    address = json.loads(address)
                except json.JSONDecodeError:
                    address = {}

            preferences = doc.get("preferences")
            if isinstance(preferences, str):
                try:
                    preferences = json.loads(preferences)
                except json.JSONDecodeError:
                    preferences = {}

            customer = {
                "customer_id": doc.get("alloy_record_id"),
                "full_name": doc.get("searchable_name"),
                "email": doc.get("searchable_email"),
                "phone": doc.get("searchable_phone"),
                "address": address,
                "preferences": preferences,
                "tier": doc.get("metadata", {}).get("tier"),
                "loyalty_points": doc.get("metadata", {}).get("loyalty_points", 0),
                "last_purchase_date": doc.get("metadata", {}).get("last_purchase_date"),
                "lifetime_value": float(doc.get("metadata", {}).get("lifetime_value", 0.0))
            }
            customers.append(customer)
        except Exception as e:
            logger.error(f"Failed to process document: {e}")
            continue

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"MongoDB preview fetch ({query_type}) completed in {elapsed_ms:.2f}ms. Retrieved {len(customers)} records.")

    return customers, elapsed_ms

def search_mongodb(plaintext_value: str, field: str) -> List[str]:
    """
    Search MongoDB encrypted collection using automatic encryption

    Args:
        plaintext_value: Plaintext search value (driver will encrypt automatically)
        field: Field name to search

    Returns:
        List of UUIDs from matching documents
    """
    start_time = time.time()

    # Map field names to MongoDB field names
    field_map = {
        "email": "searchable_email",
        "name": "searchable_name",
        "phone": "searchable_phone",
        "category": "metadata.category",
        "status": "metadata.status"
    }

    mongo_field = field_map.get(field, field)

    # Query MongoDB with plaintext - driver encrypts automatically
    query = {mongo_field: plaintext_value}
    results = list(db_manager.mongodb_collection.find(query, {"alloy_record_id": 1}))

    # Extract UUIDs
    uuids = [doc.get("alloy_record_id") for doc in results if "alloy_record_id" in doc]

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"MongoDB search completed in {elapsed_ms:.2f}ms. Found {len(uuids)} results.")

    return uuids, elapsed_ms

def fetch_from_alloydb(uuids: List[str]) -> tuple[List[Dict], float]:
    """
    Fetch customer data from AlloyDB by UUIDs

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
            # Simple query - no joins for fair performance comparison
            query = """
                SELECT
                    id AS customer_id,
                    full_name,
                    email,
                    phone,
                    address,
                    preferences,
                    tier,
                    loyalty_points,
                    last_purchase_date,
                    lifetime_value
                FROM customers
                WHERE id = ANY(%s::uuid[])
            """

            cursor.execute(query, (uuids,))
            results = cursor.fetchall()

            # Convert to list of dicts
            customers = []
            for row in results:
                customer = dict(row)
                # Parse JSONB fields
                if customer.get('address') and isinstance(customer['address'], str):
                    customer['address'] = json.loads(customer['address'])
                if customer.get('preferences') and isinstance(customer['preferences'], str):
                    customer['preferences'] = json.loads(customer['preferences'])
                customers.append(customer)

    except Exception as e:
        logger.error(f"AlloyDB query failed: {e}")
        raise

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"AlloyDB fetch completed in {elapsed_ms:.2f}ms. Retrieved {len(customers)} records.")

    return customers, elapsed_ms

def fetch_and_decrypt_from_mongodb(plaintext_value: str, field: str) -> tuple[List[Dict], float]:
    """
    Fetch customer data directly from MongoDB with automatic decryption (MongoDB-only mode)

    Args:
        plaintext_value: Plaintext search value (driver will encrypt automatically)
        field: Field name to search (searchable_name, searchable_email, searchable_phone, etc.)

    Returns:
        Tuple of (customer data list, elapsed time in ms)
    """
    start_time = time.time()

    # Field mapping
    field_map = {
        "name": "searchable_name",
        "email": "searchable_email",
        "phone": "searchable_phone",
        "category": "metadata.category",
        "status": "metadata.status"
    }

    mongo_field = field_map.get(field, field)

    # Query MongoDB with plaintext - driver encrypts automatically
    query = {mongo_field: plaintext_value}
    results = list(db_manager.mongodb_collection.find(query))

    # Extract customer data - fields are automatically decrypted by driver
    customers = []
    for doc in results:
        try:
            # Parse address and preferences if they're strings
            address = doc.get("address")
            if isinstance(address, str):
                try:
                    address = json.loads(address)
                except json.JSONDecodeError:
                    address = {}

            preferences = doc.get("preferences")
            if isinstance(preferences, str):
                try:
                    preferences = json.loads(preferences)
                except json.JSONDecodeError:
                    preferences = {}

            customer = {
                "customer_id": doc.get("alloy_record_id"),
                # Searchable fields are automatically decrypted
                "full_name": doc.get("searchable_name"),
                "email": doc.get("searchable_email"),
                "phone": doc.get("searchable_phone"),
                # Non-sensitive fields
                "address": address,
                "preferences": preferences,
                # Metadata fields
                "tier": doc.get("metadata", {}).get("tier"),
                "loyalty_points": doc.get("metadata", {}).get("loyalty_points", 0),
                "last_purchase_date": doc.get("metadata", {}).get("last_purchase_date"),
                "lifetime_value": float(doc.get("metadata", {}).get("lifetime_value", 0.0))
            }
            customers.append(customer)
        except Exception as e:
            logger.error(f"Failed to process document: {e}")
            continue

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"MongoDB fetch completed in {elapsed_ms:.2f}ms. Retrieved {len(customers)} records.")

    return customers, elapsed_ms

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
            "search_by_name": "/api/v1/customers/search/name",
            "search_by_phone": "/api/v1/customers/search/phone",
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
    request_start = time.time()

    try:
        # Search with plaintext - driver handles encryption automatically
        logger.info(f"Searching for email: {email} (mode: {mode})")

        # MongoDB-only mode: fetch all fields from MongoDB
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb(email, "email")

            if not customers:
                return SearchResponse(
                    success=True,
                    data=[],
                    metrics=PerformanceMetrics(
                        mongodb_search_ms=0.0,
                        mongodb_decrypt_ms=fetch_time,
                        alloydb_fetch_ms=0.0,
                        total_ms=(time.time() - request_start) * 1000,
                        results_count=0,
                        mode="mongodb_only"
                    ),
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

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

        # Hybrid mode (default): MongoDB search + AlloyDB fetch
        # Search MongoDB with plaintext
        uuids, mongodb_time = search_mongodb(email, "email")

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

        # Step 3: Fetch from AlloyDB
        customers, alloydb_time = fetch_from_alloydb(uuids)

        # Calculate total time
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Search by email failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/name", response_model=SearchResponse)
async def search_by_name(
    name: str = Query(..., description="Customer name to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """Search customers by name (encrypted search)"""
    request_start = time.time()

    try:
        logger.info(f"Searching for name: {name} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb(name, "name")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(name, "name")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Search by name failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/phone", response_model=SearchResponse)
async def search_by_phone(
    phone: str = Query(..., description="Customer phone to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """Search customers by phone (encrypted search)"""
    request_start = time.time()

    try:
        logger.info(f"Searching for phone: {phone} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb(phone, "phone")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(phone, "phone")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Search by phone failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/category", response_model=SearchResponse)
async def search_by_category(
    category: str = Query(..., description="Customer category to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """Search customers by category (plaintext metadata field - not encrypted)"""
    request_start = time.time()

    try:
        logger.info(f"Searching for category: {category} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb(category, "category")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(category, "category")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Search by category failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/status", response_model=SearchResponse)
async def search_by_status(
    status: str = Query(..., description="Customer status to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """Search customers by status (plaintext metadata field - not encrypted)"""
    request_start = time.time()

    try:
        logger.info(f"Searching for status: {status} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb(status, "status")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(status, "status")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Search by status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================================
# Prefix/Suffix/Substring Search Endpoints (Preview Features)
# =====================================================================

@app.get("/api/v1/customers/search/email/prefix", response_model=SearchResponse)
async def search_by_email_prefix(
    prefix: str = Query(..., description="Email prefix to search", min_length=1),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """
    Search customers by email prefix (encrypted prefix search)

    Preview Feature: Uses MongoDB 8.2 prefixPreview query type with automatic encryption
    Note: This is a preview feature and should not be used in production

    Example: prefix="john" will match "john@example.com", "john.doe@test.com", etc.
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for email prefix: {prefix} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb_preview(prefix, "email", "prefix")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb_preview(prefix, "email", "prefix")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Email prefix search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/email/suffix", response_model=SearchResponse)
async def search_by_email_suffix(
    suffix: str = Query(..., description="Email suffix to search", min_length=1),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """
    Search customers by email suffix (encrypted suffix search)

    Preview Feature: Uses MongoDB 8.2 suffixPreview query type with automatic encryption
    Note: This is a preview feature and should not be used in production

    Example: suffix="example.com" will match emails ending with "example.com"
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for email suffix: {suffix} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb_preview(suffix, "email", "suffix")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb_preview(suffix, "email", "suffix")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Email suffix search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/email/substring", response_model=SearchResponse)
async def search_by_email_substring(
    substring: str = Query(..., description="Email substring to search", min_length=2, max_length=10),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """
    Search customers by email substring (encrypted substring search)

    Preview Feature: Uses MongoDB 8.2 substringPreview query type with automatic encryption
    Note: This is a preview feature and should not be used in production

    Example: substring="doe" will match "john.doe@example.com", "jane.doe@test.com", etc.

    Constraints:
    - Minimum length: 2 characters
    - Maximum length: 10 characters
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for email substring: {substring} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb_preview(substring, "email", "substring")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb_preview(substring, "email", "substring")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Email substring search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/name/prefix", response_model=SearchResponse)
async def search_by_name_prefix(
    prefix: str = Query(..., description="Name prefix to search", min_length=1),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """
    Search customers by name prefix (encrypted prefix search)

    Preview Feature: Uses MongoDB 8.2 prefixPreview query type with automatic encryption
    Note: This is a preview feature and should not be used in production

    Example: prefix="John" will match "John Doe", "John Smith", etc.
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for name prefix: {prefix} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb_preview(prefix, "name", "prefix")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb_preview(prefix, "name", "prefix")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Name prefix search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/name/suffix", response_model=SearchResponse)
async def search_by_name_suffix(
    suffix: str = Query(..., description="Name suffix to search", min_length=1),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """
    Search customers by name suffix (encrypted suffix search)

    Preview Feature: Uses MongoDB 8.2 suffixPreview query type with automatic encryption
    Note: This is a preview feature and should not be used in production

    Example: suffix="Smith" will match "John Smith", "Jane Smith", etc.
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for name suffix: {suffix} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb_preview(suffix, "name", "suffix")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb_preview(suffix, "name", "suffix")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Name suffix search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/name/substring", response_model=SearchResponse)
async def search_by_name_substring(
    substring: str = Query(..., description="Name substring to search", min_length=2, max_length=10),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
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
    request_start = time.time()

    try:
        logger.info(f"Searching for name substring: {substring} (mode: {mode})")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, fetch_time = fetch_and_decrypt_from_mongodb_preview(substring, "name", "substring")
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

        # Hybrid mode
        uuids, mongodb_time = search_mongodb_preview(substring, "name", "substring")

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
        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=mongodb_time,
                mongodb_decrypt_ms=0.0,
                alloydb_fetch_ms=alloydb_time,
                total_ms=total_time,
                results_count=len(customers),
                mode="hybrid"
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Name substring search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/v1/customers/tier/{tier}", response_model=SearchResponse)
async def get_customers_by_tier(tier: str):
    """Get all customers by tier (direct AlloyDB query)

    Args:
        tier: Customer tier (bronze, silver, gold, platinum, premium)
    """
    request_start = time.time()

    try:
        with db_manager.alloydb_conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Simple query - no joins
            query = """
                SELECT
                    id AS customer_id,
                    full_name,
                    email,
                    phone,
                    address,
                    preferences,
                    tier,
                    loyalty_points,
                    last_purchase_date,
                    lifetime_value
                FROM customers
                WHERE tier = %s
            """

            cursor.execute(query, (tier,))
            results = cursor.fetchall()

            customers = []
            for row in results:
                customer = dict(row)
                if customer.get('address') and isinstance(customer['address'], str):
                    customer['address'] = json.loads(customer['address'])
                if customer.get('preferences') and isinstance(customer['preferences'], str):
                    customer['preferences'] = json.loads(customer['preferences'])
                customers.append(customer)

        total_time = (time.time() - request_start) * 1000

        return SearchResponse(
            success=True,
            data=[CustomerResponse(**c) for c in customers],
            metrics=PerformanceMetrics(
                mongodb_search_ms=0.0,
                alloydb_fetch_ms=total_time,
                total_ms=total_time,
                results_count=len(customers)
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Get customers by tier failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
