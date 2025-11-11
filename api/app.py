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
from datetime import datetime
import base64

# MongoDB imports
from pymongo import MongoClient
from pymongo.encryption import ClientEncryption, Algorithm
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
    """Response model for customer data"""
    customer_id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    tier: Optional[str] = None
    loyalty_points: Optional[int] = None
    lifetime_value: Optional[float] = None
    total_orders: Optional[int] = None
    total_spent: Optional[float] = None

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

            # Connect to MongoDB
            self.mongodb_client = MongoClient(MONGODB_URI)
            self.mongodb_db = self.mongodb_client[MONGODB_DATABASE]
            self.mongodb_collection = self.mongodb_db[MONGODB_COLLECTION]

            # Setup client encryption
            self.client_encryption = ClientEncryption(
                kms_providers=kms_providers,
                key_vault_namespace=KEY_VAULT_NAMESPACE,
                key_vault_client=self.mongodb_client,
                codec_options=CodecOptions()
            )

            # Load key IDs from key vault
            key_vault = self.mongodb_client.get_database("encryption").get_collection("__keyVault")
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

            logger.info(f"MongoDB connected. Loaded {len(self.key_ids)} encryption keys.")
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

def encrypt_search_term(value: str, field: str, query_type: str = "equality") -> Binary:
    """
    Encrypt a search term using MongoDB Queryable Encryption

    Args:
        value: The plaintext value to encrypt
        field: The field name (determines which key to use)
        query_type: The type of query - "equality", "prefix", "suffix", or "substring"
                    Note: prefix/suffix/substring are preview features in MongoDB 8.2

    Returns:
        Encrypted binary value
    """
    # Validate query_type
    valid_query_types = ["equality", "prefix", "suffix", "substring"]
    if query_type not in valid_query_types:
        raise ValueError(f"Invalid query_type: {query_type}. Must be one of {valid_query_types}")

    # Map to MongoDB preview query type names
    query_type_map = {
        "equality": "equality",
        "prefix": "prefixPreview",
        "suffix": "suffixPreview",
        "substring": "substringPreview"
    }
    mongodb_query_type = query_type_map[query_type]

    # Map field names to key names
    field_key_map = {
        "email": "searchable_email",
        "name": "searchable_name",
        "phone": "searchable_phone",
        "category": "metadata_category",
        "status": "metadata_status"
    }

    key_name = field_key_map.get(field)
    if not key_name:
        raise ValueError(f"Unknown field: {field}")

    key_id = db_manager.key_ids.get(key_name)
    if not key_id:
        raise ValueError(f"Encryption key not found for field: {field}")

    # Determine which algorithm to use based on query type
    # Preview query types (prefix, suffix, substring) require TEXTPREVIEW algorithm
    # Equality queries use INDEXED algorithm
    if query_type in ["prefix", "suffix", "substring"]:
        algorithm = Algorithm.TEXTPREVIEW
        # Configure text options for preview query types - must specify the preview type
        text_opts_kwargs = {
            "case_sensitive": False,
            "diacritic_sensitive": False
        }
        # Add the specific preview type parameter (requires Opts objects, not bool)
        # Parameters must match the schema configuration
        if query_type == "prefix":
            text_opts_kwargs["prefix"] = PrefixOpts(
                strMinQueryLength=1,     # Min prefix query length
                strMaxQueryLength=50     # Max prefix query length (realistic for email search)
            )
        elif query_type == "suffix":
            text_opts_kwargs["suffix"] = SuffixOpts(
                strMinQueryLength=1,
                strMaxQueryLength=50
            )
        elif query_type == "substring":
            text_opts_kwargs["substring"] = SubstringOpts(
                strMinQueryLength=2,    # Min substring query length
                strMaxQueryLength=10,   # Max substring query length
                strMaxLength=60         # Max field value length
            )

        text_opts = TextOpts(**text_opts_kwargs)
    else:
        algorithm = Algorithm.INDEXED
        text_opts = None

    # Encrypt the value with specified query type
    if text_opts:
        encrypted_value = db_manager.client_encryption.encrypt(
            value,
            algorithm,
            key_id=key_id,
            contention_factor=0,
            query_type=mongodb_query_type,
            text_opts=text_opts
        )
    else:
        encrypted_value = db_manager.client_encryption.encrypt(
            value,
            algorithm,
            key_id=key_id,
            contention_factor=0,
            query_type=mongodb_query_type
        )

    return encrypted_value

def search_mongodb(encrypted_value: Binary, field: str) -> List[str]:
    """
    Search MongoDB encrypted collection

    Args:
        encrypted_value: Encrypted search value
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

    # Query MongoDB
    query = {mongo_field: encrypted_value}
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
            # Query customers with metadata and order summary
            query = """
                SELECT
                    c.id AS customer_id,
                    c.full_name,
                    c.email,
                    c.phone,
                    c.address,
                    c.preferences,
                    m.tier,
                    m.loyalty_points,
                    m.lifetime_value,
                    m.last_purchase_date,
                    COUNT(o.id) AS total_orders,
                    COALESCE(SUM(o.total_amount), 0) AS total_spent
                FROM customers c
                LEFT JOIN customer_metadata m ON c.id = m.customer_id
                LEFT JOIN orders o ON c.id = o.customer_id
                WHERE c.id = ANY(%s::uuid[])
                GROUP BY c.id, c.full_name, c.email, c.phone, c.address, c.preferences,
                         m.tier, m.loyalty_points, m.lifetime_value, m.last_purchase_date
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

def fetch_and_decrypt_from_mongodb(encrypted_value: Binary, field: str) -> tuple[List[Dict], float]:
    """
    Fetch and decrypt ALL customer data directly from MongoDB (MongoDB-only mode)

    Args:
        encrypted_value: Encrypted search value
        field: Field name to search (searchable_name, searchable_email, searchable_phone, etc.)

    Returns:
        Tuple of (decrypted customer data list, elapsed time in ms)
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

    # Query MongoDB
    query = {mongo_field: encrypted_value}
    results = list(db_manager.mongodb_collection.find(query))

    # Decrypt all fields from each document
    customers = []
    for doc in results:
        try:
            # Decrypt all encrypted fields
            customer = {
                "customer_id": doc.get("alloy_record_id"),
                "full_name": db_manager.client_encryption.decrypt(doc["full_name"]) if "full_name" in doc else None,
                "email": db_manager.client_encryption.decrypt(doc["email"]) if "email" in doc else None,
                "phone": db_manager.client_encryption.decrypt(doc["phone"]) if "phone" in doc else None,
                "address": json.loads(db_manager.client_encryption.decrypt(doc["address"])) if "address" in doc else None,
                "preferences": json.loads(db_manager.client_encryption.decrypt(doc["preferences"])) if "preferences" in doc else None,
                "tier": db_manager.client_encryption.decrypt(doc["metadata"]["tier"]) if doc.get("metadata", {}).get("tier") else None,
                "loyalty_points": int(db_manager.client_encryption.decrypt(doc["metadata"]["loyalty_points"])) if doc.get("metadata", {}).get("loyalty_points") else 0,
                "lifetime_value": float(db_manager.client_encryption.decrypt(doc["metadata"]["lifetime_value"])) if doc.get("metadata", {}).get("lifetime_value") else 0.0,
                "last_purchase_date": db_manager.client_encryption.decrypt(doc["metadata"]["last_purchase_date"]) if doc.get("metadata", {}).get("last_purchase_date") else None,
                "total_orders": None,  # Not available in MongoDB-only mode
                "total_spent": None    # Not available in MongoDB-only mode
            }
            customers.append(customer)
        except Exception as e:
            logger.error(f"Failed to decrypt document: {e}")
            continue

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"MongoDB decrypt completed in {elapsed_ms:.2f}ms. Decrypted {len(customers)} records.")

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
    try:
        # Check MongoDB
        db_manager.mongodb_client.admin.command('ping')
        mongodb_status = "connected"
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
        "encryption_keys": len(db_manager.key_ids),
        "timestamp": datetime.utcnow().isoformat()
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
        # Step 1: Encrypt search term
        logger.info(f"Searching for email: {email} (mode: {mode})")
        encrypted_email = encrypt_search_term(email, "email")

        # MongoDB-only mode: decrypt all fields from MongoDB
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_email, "email")

            if not customers:
                return SearchResponse(
                    success=True,
                    data=[],
                    metrics=PerformanceMetrics(
                        mongodb_search_ms=0.0,
                        mongodb_decrypt_ms=decrypt_time,
                        alloydb_fetch_ms=0.0,
                        total_ms=(time.time() - request_start) * 1000,
                        results_count=0,
                        mode="mongodb_only"
                    ),
                    timestamp=datetime.utcnow().isoformat()
                )

            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode (default): MongoDB search + AlloyDB fetch
        # Step 2: Search MongoDB
        uuids, mongodb_time = search_mongodb(encrypted_email, "email")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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
        encrypted_name = encrypt_search_term(name, "name")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_name, "name")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_name, "name")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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
        encrypted_phone = encrypt_search_term(phone, "phone")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_phone, "phone")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_phone, "phone")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
        )

    except Exception as e:
        logger.error(f"Search by phone failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/category", response_model=SearchResponse)
async def search_by_category(
    category: str = Query(..., description="Customer category to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """Search customers by category (encrypted search)"""
    request_start = time.time()

    try:
        logger.info(f"Searching for category: {category} (mode: {mode})")
        encrypted_category = encrypt_search_term(category, "category")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_category, "category")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_category, "category")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
        )

    except Exception as e:
        logger.error(f"Search by category failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customers/search/status", response_model=SearchResponse)
async def search_by_status(
    status: str = Query(..., description="Customer status to search"),
    mode: str = Query("hybrid", description="Search mode: 'hybrid' (MongoDB+AlloyDB) or 'mongodb_only' (MongoDB decrypt only)")
):
    """Search customers by status (encrypted search)"""
    request_start = time.time()

    try:
        logger.info(f"Searching for status: {status} (mode: {mode})")
        encrypted_status = encrypt_search_term(status, "status")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_status, "status")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_status, "status")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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

    Preview Feature: Uses MongoDB 8.2 prefixPreview query type
    Note: This is a preview feature and should not be used in production

    Example: prefix="john" will match "john@example.com", "john.doe@test.com", etc.
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for email prefix: {prefix} (mode: {mode})")
        encrypted_value = encrypt_search_term(prefix, "email", query_type="prefix")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_value, "email")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_value, "email")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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

    Preview Feature: Uses MongoDB 8.2 suffixPreview query type
    Note: This is a preview feature and should not be used in production

    Example: suffix="example.com" will match emails ending with "example.com"
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for email suffix: {suffix} (mode: {mode})")
        encrypted_value = encrypt_search_term(suffix, "email", query_type="suffix")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_value, "email")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_value, "email")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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

    Preview Feature: Uses MongoDB 8.2 substringPreview query type
    Note: This is a preview feature and should not be used in production

    Example: substring="doe" will match "john.doe@example.com", "jane.doe@test.com", etc.

    Constraints:
    - Minimum length: 2 characters
    - Maximum length: 10 characters
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for email substring: {substring} (mode: {mode})")
        encrypted_value = encrypt_search_term(substring, "email", query_type="substring")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_value, "email")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_value, "email")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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

    Preview Feature: Uses MongoDB 8.2 prefixPreview query type
    Note: This is a preview feature and should not be used in production

    Example: prefix="John" will match "John Doe", "John Smith", etc.
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for name prefix: {prefix} (mode: {mode})")
        encrypted_value = encrypt_search_term(prefix, "name", query_type="prefix")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_value, "name")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_value, "name")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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

    Preview Feature: Uses MongoDB 8.2 suffixPreview query type
    Note: This is a preview feature and should not be used in production

    Example: suffix="Smith" will match "John Smith", "Jane Smith", etc.
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for name suffix: {suffix} (mode: {mode})")
        encrypted_value = encrypt_search_term(suffix, "name", query_type="suffix")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_value, "name")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_value, "name")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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

    Preview Feature: Uses MongoDB 8.2 substringPreview query type
    Note: This is a preview feature and should not be used in production

    Example: substring="mit" will match "John Smith", "Smith Johnson", etc.

    Constraints:
    - Minimum length: 2 characters
    - Maximum length: 10 characters
    """
    request_start = time.time()

    try:
        logger.info(f"Searching for name substring: {substring} (mode: {mode})")
        encrypted_value = encrypt_search_term(substring, "name", query_type="substring")

        # MongoDB-only mode
        if mode == "mongodb_only":
            customers, decrypt_time = fetch_and_decrypt_from_mongodb(encrypted_value, "name")
            return SearchResponse(
                success=True,
                data=[CustomerResponse(**c) for c in customers],
                metrics=PerformanceMetrics(
                    mongodb_search_ms=0.0,
                    mongodb_decrypt_ms=decrypt_time,
                    alloydb_fetch_ms=0.0,
                    total_ms=(time.time() - request_start) * 1000,
                    results_count=len(customers),
                    mode="mongodb_only"
                ),
                timestamp=datetime.utcnow().isoformat()
            )

        # Hybrid mode
        uuids, mongodb_time = search_mongodb(encrypted_value, "name")

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
                timestamp=datetime.utcnow().isoformat()
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
            timestamp=datetime.utcnow().isoformat()
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
            query = """
                SELECT
                    c.id AS customer_id,
                    c.full_name,
                    c.email,
                    c.phone,
                    c.address,
                    m.tier,
                    m.loyalty_points,
                    m.lifetime_value,
                    COUNT(o.id) AS total_orders,
                    COALESCE(SUM(o.total_amount), 0) AS total_spent
                FROM customers c
                LEFT JOIN customer_metadata m ON c.id = m.customer_id
                LEFT JOIN orders o ON c.id = o.customer_id
                WHERE m.tier = %s
                GROUP BY c.id, c.full_name, c.email, c.phone, c.address,
                         m.tier, m.loyalty_points, m.lifetime_value
            """

            cursor.execute(query, (tier,))
            results = cursor.fetchall()

            customers = []
            for row in results:
                customer = dict(row)
                if customer.get('address') and isinstance(customer['address'], str):
                    customer['address'] = json.loads(customer['address'])
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
            timestamp=datetime.utcnow().isoformat()
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
