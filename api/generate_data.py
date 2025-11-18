#!/usr/bin/env python3
"""
POC Data Generation Script
Generates consistent test dataset for MongoDB (encrypted) and AlloyDB

Usage:
    python generate_data.py              # Generate default (10000 customers)
    python generate_data.py --count 50   # Generate 50 customers
    python generate_data.py --reset      # Reset and regenerate data
"""

import sys
import os
import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
import random
from pathlib import Path
import base64

# Import encryption libraries
from pymongo import MongoClient
from pymongo.encryption import ClientEncryption, Algorithm, AutoEncryptionOpts
from pymongo.encryption_options import TextOpts, SubstringOpts, PrefixOpts
from bson.binary import Binary
from bson.codec_options import CodecOptions
import psycopg2
from psycopg2.extras import execute_batch

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text:^80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")

def print_success(text):
    print(f"{Colors.OKGREEN}[OK] {text}{Colors.ENDC}")

def print_error(text):
    print(f"{Colors.FAIL}[ERROR] {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.OKCYAN}[INFO] {text}{Colors.ENDC}")

def print_warning(text):
    print(f"{Colors.WARNING}[WARNING] {text}{Colors.ENDC}")

def print_progress(current, total, message=""):
    """Print progress bar"""
    bar_length = 50
    progress = current / total
    filled = int(bar_length * progress)
    bar = '#' * filled + '-' * (bar_length - filled)
    percent = progress * 100
    print(f"\r{Colors.OKCYAN}[{bar}] {percent:.1f}% {message}{Colors.ENDC}", end='', flush=True)
    if current == total:
        print()  # New line when complete

# Sample data
FIRST_NAMES = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
               "William", "Barbara", "David", "Elizabeth", "Richard", "Susan", "Joseph", "Jessica"]

LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
              "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor"]

CITIES = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
          "San Antonio", "San Diego", "Dallas", "San Jose"]

STATES = ["NY", "CA", "IL", "TX", "AZ", "PA", "TX", "CA", "TX", "CA"]

TIERS = ["bronze", "silver", "gold", "platinum", "premium"]

PRODUCTS = [
    {"name": "Widget A", "price": 29.99},
    {"name": "Gadget B", "price": 49.99},
    {"name": "Tool C", "price": 89.99},
    {"name": "Device D", "price": 129.99},
    {"name": "Equipment E", "price": 199.99}
]

def generate_customer_data(count):
    """Generate random customer data"""
    customers = []

    for i in range(count):
        customer_id = str(uuid.uuid4())
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        full_name = f"{first_name} {last_name}"

        # Add unique suffix if name collision possible
        email_suffix = f"{i+1}" if count > 50 else ""
        email = f"{first_name.lower()}.{last_name.lower()}{email_suffix}@example.com"

        city_idx = random.randint(0, len(CITIES)-1)

        customer = {
            "id": customer_id,
            "full_name": full_name,
            "email": email,
            "phone": f"+1-555-{random.randint(1000, 9999)}",
            "address": f"{random.randint(100, 9999)} {random.choice(['Main', 'Oak', 'Elm', 'Pine'])} St",
            "city": CITIES[city_idx],
            "state": STATES[city_idx],
            "zip_code": f"{random.randint(10000, 99999)}",
            "tier": random.choice(TIERS),
            "loyalty_points": random.randint(0, 1000),
            "lifetime_value": round(random.uniform(100, 10000), 2),
            "last_purchase_date": (datetime.now() - timedelta(days=random.randint(1, 365))).isoformat(),
            "category": random.choice(["retail", "enterprise", "government"]),
            "status": random.choice(["active", "inactive", "pending"]),
            "preferences": json.dumps({
                "newsletter": random.choice([True, False]),
                "sms": random.choice([True, False])
            })
        }

        customers.append(customer)

    return customers

def generate_orders(customers):
    """Generate orders for customers"""
    orders = []

    for customer in customers:
        # Each customer gets 1-5 orders
        num_orders = random.randint(1, 5)

        for i in range(num_orders):
            order_id = str(uuid.uuid4())
            order_date = datetime.now() - timedelta(days=random.randint(1, 365))

            # Each order has 1-3 items
            items = []
            total_amount = 0
            for _ in range(random.randint(1, 3)):
                product = random.choice(PRODUCTS)
                quantity = random.randint(1, 3)
                item_total = product["price"] * quantity
                total_amount += item_total

                items.append({
                    "product": product["name"],
                    "price": product["price"],
                    "quantity": quantity
                })

            order = {
                "id": order_id,
                "customer_id": customer["id"],
                "order_number": f"ORD-{random.randint(10000, 99999)}",
                "order_date": order_date,
                "total_amount": round(total_amount, 2),
                "status": random.choice(["completed", "pending", "shipped"]),
                "items": json.dumps(items),
                "shipping_address": json.dumps({
                    "street": customer["address"],
                    "city": customer["city"],
                    "state": customer["state"],
                    "zip_code": customer["zip_code"]
                })
            }

            orders.append(order)

    return orders

def load_encryption_keys():
    """Load encryption keys from MongoDB key vault"""
    print_info("Loading encryption keys...")

    # Get MongoDB URI from environment variable (for Docker compatibility)
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')

    # Create a temporary client just to load keys
    temp_client = MongoClient(
        f"{mongodb_uri}/?directConnection=true&"
        "w=1&"
        "readPreference=primary&"
        "serverSelectionTimeoutMS=5000"
    )

    try:
        # Test connection
        temp_client.admin.command('ping')

        # Load encryption master key
        key_path = Path('.encryption_key')
        if not key_path.exists():
            print_error("Encryption key file not found: .encryption_key")
            print_error("Please run: python deploy.py start")
            print_error("This will setup encryption and start all services.")
            sys.exit(1)

        with open(key_path, 'r') as f:
            master_key = f.read().strip()

        kms_providers = {
            "local": {
                "key": base64.b64decode(master_key)
            }
        }

        # Load key IDs from key vault
        key_vault = temp_client.get_database("encryption").get_collection("__keyVault")
        key_ids = {}
        for key_doc in key_vault.find():
            if "keyAltNames" in key_doc and key_doc["keyAltNames"]:
                key_name = key_doc["keyAltNames"][0]
                key_ids[key_name] = key_doc["_id"]

        if len(key_ids) != 5:
            print_error(f"Expected 5 encryption keys, found {len(key_ids)}")
            print_error(f"Found keys: {list(key_ids.keys())}")
            sys.exit(1)

        print_success(f"Loaded {len(key_ids)} encryption keys: {', '.join(key_ids.keys())}")

        # Create simplified key mapping
        key_mapping = {
            "searchable_name": key_ids.get("customer_searchable_name_key") or key_ids.get("searchable_name"),
            "searchable_email": key_ids.get("customer_searchable_email_key") or key_ids.get("searchable_email"),
            "searchable_phone": key_ids.get("customer_searchable_phone_key") or key_ids.get("searchable_phone"),
            "metadata_category": key_ids.get("customer_metadata_category_key") or key_ids.get("metadata_category"),
            "metadata_status": key_ids.get("customer_metadata_status_key") or key_ids.get("metadata_status"),
        }

        return kms_providers, key_mapping

    finally:
        temp_client.close()

def connect_mongodb(kms_providers, key_ids):
    """Connect to MongoDB with automatic encryption enabled"""
    print_info("Connecting to MongoDB with automatic encryption...")

    try:
        # Configure encryptedFieldsMap for automatic encryption
        encrypted_fields_map = {
            "poc_database.customers": {
                "fields": [
                    {
                        "path": "searchable_name",
                        "bsonType": "string",
                        "keyId": key_ids["searchable_name"],
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
                        "keyId": key_ids["searchable_email"],
                        "queries": [
                            {
                                "queryType": "prefixPreview",
                                "contention": 0,
                                "strMinQueryLength": 1,
                                "strMaxQueryLength": 50,
                                "caseSensitive": False,
                                "diacriticSensitive": False
                            }
                        ]
                    },
                    {
                        "path": "searchable_phone",
                        "bsonType": "string",
                        "keyId": key_ids["searchable_phone"],
                        "queries": [
                            {
                                "queryType": "equality",
                                "contention": 0
                            }
                        ]
                    },
                    {
                        "path": "metadata.category",
                        "bsonType": "string",
                        "keyId": key_ids["metadata_category"],
                        "queries": [
                            {
                                "queryType": "equality",
                                "contention": 0
                            }
                        ]
                    },
                    {
                        "path": "metadata.status",
                        "bsonType": "string",
                        "keyId": key_ids["metadata_status"],
                        "queries": [
                            {
                                "queryType": "equality",
                                "contention": 0
                            }
                        ]
                    }
                ]
            }
        }

        # Configure automatic encryption options
        # crypt_shared_lib_path: Path to the crypt_shared library (installed via Dockerfile)
        # crypt_shared_lib_required=True: Force use of crypt_shared library (no mongocryptd)
        # This is the recommended approach for MongoDB Queryable Encryption
        auto_encryption_opts = AutoEncryptionOpts(
            kms_providers=kms_providers,
            key_vault_namespace="encryption.__keyVault",
            encrypted_fields_map=encrypted_fields_map,
            crypt_shared_lib_path="/usr/local/lib/mongo_crypt/mongo_crypt_v1.so",
            crypt_shared_lib_required=True  # Require crypt_shared library (recommended)
        )

        # Get MongoDB URI from environment variable
        mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')

        # Create client with automatic encryption
        client = MongoClient(
            f"{mongodb_uri}/?directConnection=true&"
            "w=1&"
            "readPreference=primary&"
            "readConcernLevel=local&"
            "serverSelectionTimeoutMS=5000&"
            "socketTimeoutMS=10000",
            auto_encryption_opts=auto_encryption_opts
        )
        db = client["poc_database"]

        # Test connection
        client.admin.command('ping')

        print_success("Connected to MongoDB with automatic encryption enabled")
        return client, db
    except Exception as e:
        print_error(f"MongoDB connection failed: {e}")
        sys.exit(1)

def connect_alloydb():
    """Connect to AlloyDB"""
    print_info("Connecting to AlloyDB...")

    try:
        # Get AlloyDB URI from environment variable (for Docker compatibility)
        alloydb_uri = os.getenv('ALLOYDB_URI', 'postgresql://postgres:postgres_password@localhost:5432/alloydb_poc')

        # Parse connection string or use defaults
        conn = psycopg2.connect(alloydb_uri)

        print_success("Connected to AlloyDB")
        return conn
    except Exception as e:
        print_error(f"AlloyDB connection failed: {e}")
        sys.exit(1)

def insert_mongodb_data(db, key_ids, customers):
    """Insert encrypted customer data into MongoDB using AUTOMATIC encryption"""
    print_header("Inserting Data into MongoDB")

    collection = db["customers"]

    # Check existing count
    existing_count = collection.count_documents({})
    print_info(f"Collection currently has {existing_count} documents")

    print_info(f"Inserting {len(customers)} additional customer records with AUTOMATIC encryption...")
    print_info("Note: MongoDB driver will encrypt searchable fields automatically based on encryptedFields schema")

    for i, customer in enumerate(customers):
        # With AUTOMATIC encryption, we insert PLAINTEXT data
        # The MongoDB driver will encrypt the fields defined in encryptedFields schema automatically
        # This approach enables queryable encryption to work correctly

        doc = {
            "alloy_record_id": customer["id"],
            # Encrypted searchable fields - MongoDB driver encrypts these automatically
            # When queried with encryption client, these are returned decrypted
            "searchable_name": customer["full_name"],
            "searchable_email": customer["email"],
            "searchable_phone": customer["phone"],
            # Metadata with encrypted searchable fields
            "metadata": {
                "category": customer["category"],
                "status": customer["status"],
                "tier": customer["tier"],
                "loyalty_points": customer["loyalty_points"],
                "last_purchase_date": customer["last_purchase_date"],
                "lifetime_value": str(customer["lifetime_value"])
            },
            # Non-sensitive fields that can remain unencrypted
            "address": customer["address"],
            "preferences": customer["preferences"],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }

        collection.insert_one(doc)
        print_progress(i+1, len(customers), f"({i+1}/{len(customers)} customers)")

    # Ensure all output is flushed
    sys.stdout.flush()
    sys.stderr.flush()

    print_info("Counting inserted documents...")
    sys.stdout.flush()

    # Count documents using the existing collection
    final_count = collection.estimated_document_count()
    print_success(f"MongoDB: {final_count} total customer records")

def insert_alloydb_data(conn, customers):
    """Insert customer data into AlloyDB (simplified - no orders or metadata tables)"""
    print_header("Inserting Data into AlloyDB")

    cursor = conn.cursor()

    # Check existing count
    cursor.execute("SELECT COUNT(*) FROM customers")
    existing_count = cursor.fetchone()[0]
    print_info(f"Table currently has {existing_count} customers")

    # Insert customers with all fields
    print_info(f"Inserting {len(customers)} additional customer records...")

    customer_records = [
        (
            c["id"],
            c["full_name"],
            c["email"],
            c["phone"],
            json.dumps({
                "street": c["address"],
                "city": c["city"],
                "state": c["state"],
                "zip_code": c["zip_code"]
            }),
            c["preferences"],
            c["tier"],
            c["category"],
            c["status"],
            c["loyalty_points"],
            c["last_purchase_date"],
            c["lifetime_value"]
        )
        for c in customers
    ]

    # Insert in batches with progress
    batch_size = 1000

    for i in range(0, len(customer_records), batch_size):
        batch = customer_records[i:i + batch_size]
        execute_batch(
            cursor,
            """
            INSERT INTO customers (id, full_name, email, phone, address, preferences, tier, category, status, loyalty_points, last_purchase_date, lifetime_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            batch
        )
        records_done = min(i + batch_size, len(customer_records))
        print_progress(records_done, len(customer_records), f"({records_done}/{len(customer_records)} customers)")

    print_success(f"AlloyDB: {len(customers)} customer records")

    conn.commit()
    cursor.close()

    # Verify counts
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM customers")
    customer_count = cursor.fetchone()[0]
    cursor.close()

    print_success(f"AlloyDB: {customer_count} total customers")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Generate POC test data - appends additional data to existing datasets")
    parser.add_argument('--count', type=int, default=10000, help='Number of customers to generate (default: 10000)')
    args = parser.parse_args()

    print_header("POC Data Generation")
    print_info(f"Generating {args.count} additional customers")

    # Generate data
    print_info("Generating random customer data...")
    customers = generate_customer_data(args.count)
    print_success(f"Generated {len(customers)} customers")

    # Load encryption keys first (needed for MongoDB client configuration)
    kms_providers, key_ids = load_encryption_keys()

    # Connect to databases with automatic encryption enabled
    mongo_client, mongo_db = connect_mongodb(kms_providers, key_ids)
    alloydb_conn = connect_alloydb()

    # Insert data (MongoDB driver will automatically encrypt)
    insert_mongodb_data(mongo_db, key_ids, customers)
    insert_alloydb_data(alloydb_conn, customers)

    # Close connections
    mongo_client.close()
    alloydb_conn.close()

    print_header("Data Generation Complete!")
    print_success(f"Successfully generated and inserted test data")
    print()
    print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
    print(f"  • Customers: {len(customers)}")
    print(f"  • MongoDB: Encrypted searchable fields")
    print(f"  • AlloyDB: Complete customer data (identical to MongoDB decrypted)")
    print()
    print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
    print("  1. Run tests: python run_tests.py")
    print("  2. Test API:  http://localhost:8000/docs (API runs in Docker)")
    print()
    print(f"{Colors.BOLD}Mode Switching:{Colors.ENDC}")
    print("  • Hybrid mode:        Default (MongoDB search -> AlloyDB fetch)")
    print("  • MongoDB-only mode:  Add ?mode=mongodb_only to any search endpoint")
    print("  • Both modes return identical data for fair performance comparison")

if __name__ == "__main__":
    main()
