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

# Import database libraries
from pymongo import MongoClient
from pymongo.encryption_options import AutoEncryptionOpts
import psycopg2

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

def build_mongodb_document(customer):
    """Build MongoDB document from customer data

    Args:
        customer: Customer dictionary with fields: id, full_name, email, phone,
                  category, status, tier, loyalty_points, last_purchase_date,
                  lifetime_value, address, preferences

    Returns:
        MongoDB document dictionary ready for insertion
    """
    return {
        "alloy_record_id": customer["id"],
        # Encrypted searchable fields - MongoDB driver encrypts these automatically
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

def build_alloydb_address_json(customer):
    """Build AlloyDB address JSON from customer data

    Args:
        customer: Customer dictionary with fields: address, city, state, zip_code

    Returns:
        JSON string of address object
    """
    return json.dumps({
        "street": customer["address"],
        "city": customer["city"],
        "state": customer["state"],
        "zip_code": customer["zip_code"]
    })

def get_database_counts(mongo_db, alloydb_conn):
    """Get current record counts from both databases

    Args:
        mongo_db: MongoDB database instance
        alloydb_conn: AlloyDB connection

    Returns:
        Tuple of (mongodb_count, alloydb_count)
    """
    mongo_count = mongo_db["customers"].count_documents({})

    alloydb_cursor = alloydb_conn.cursor()
    alloydb_cursor.execute("SELECT COUNT(*) FROM customers")
    alloydb_count = alloydb_cursor.fetchone()[0]
    alloydb_cursor.close()

    return mongo_count, alloydb_count

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

def insert_batch_with_validation(mongo_db, alloydb_conn, batch, batch_num, total_batches, encryption_key, total_inserted=0, target_count=10000):
    """Insert a batch into both databases and validate consistency

    MongoDB: Stores encrypted data (handled by driver with queryable encryption)
    AlloyDB: Stores encrypted data using pgcrypto (encrypted in this function before insert)
    """
    records_after = total_inserted + len(batch)
    print_info(f"Generated {total_inserted}/{target_count} records... processing next {len(batch)} (batch {batch_num}/{total_batches})")

    mongo_collection = mongo_db["customers"]
    alloydb_cursor = alloydb_conn.cursor()

    # Track successful inserts
    mongo_inserted = []
    alloydb_inserted = []

    for customer in batch:
        # Insert into MongoDB (driver encrypts automatically)
        try:
            doc = build_mongodb_document(customer)
            mongo_collection.insert_one(doc)
            mongo_inserted.append(customer["id"])
        except Exception as e:
            print_warning(f"MongoDB insert failed for {customer['id']}: {e}")
            # If MongoDB fails, skip this record entirely
            continue

        # Insert into AlloyDB with pgcrypto encryption (only if MongoDB succeeded)
        try:
            # Prepare encrypted data using pgp_sym_encrypt
            # Note: Encryption happens in database using pgcrypto extension
            alloydb_cursor.execute(
                """
                INSERT INTO customers (
                    id,
                    full_name_encrypted,
                    email_encrypted,
                    phone_encrypted,
                    address_encrypted,
                    preferences_encrypted,
                    tier,
                    category,
                    status,
                    loyalty_points,
                    last_purchase_date,
                    lifetime_value
                )
                VALUES (
                    %s,
                    pgp_sym_encrypt(%s, %s),
                    pgp_sym_encrypt(%s, %s),
                    pgp_sym_encrypt(%s, %s),
                    pgp_sym_encrypt(%s, %s),
                    pgp_sym_encrypt(%s, %s),
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    customer["id"],
                    customer["full_name"], encryption_key,
                    customer["email"], encryption_key,
                    customer["phone"], encryption_key,
                    build_alloydb_address_json(customer), encryption_key,
                    customer["preferences"], encryption_key,
                    customer["tier"],
                    customer["category"],
                    customer["status"],
                    customer["loyalty_points"],
                    customer["last_purchase_date"],
                    customer["lifetime_value"]
                )
            )
            alloydb_inserted.append(customer["id"])
        except Exception as e:
            print_warning(f"AlloyDB insert failed for {customer['id']}: {e}")
            # Rollback MongoDB insert if AlloyDB fails
            print_warning(f"Rolling back MongoDB insert for {customer['id']}")
            mongo_collection.delete_one({"alloy_record_id": customer["id"]})
            mongo_inserted.remove(customer["id"])

    # Commit AlloyDB transaction
    alloydb_conn.commit()
    alloydb_cursor.close()

    # Validate consistency
    if len(mongo_inserted) != len(alloydb_inserted):
        print_error(f"Inconsistency detected! MongoDB: {len(mongo_inserted)}, AlloyDB: {len(alloydb_inserted)}")
        print_error(f"Difference: {set(mongo_inserted) ^ set(alloydb_inserted)}")
        return False

    print_success(f"Batch {batch_num}/{total_batches}: Successfully inserted {len(mongo_inserted)} records into both databases")
    return True

def main():
    """Main entry point with batch processing and validation"""
    parser = argparse.ArgumentParser(description="Generate POC test data - appends additional data to existing datasets")
    parser.add_argument('--count', type=int, default=10000, help='Number of customers to generate (default: 10000)')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for inserts (default: 100)')
    args = parser.parse_args()

    print_header("POC Data Generation")
    print_info(f"Generating {args.count} customers in batches of {args.batch_size}")

    # Load encryption keys first (needed for MongoDB client configuration)
    kms_providers, key_ids = load_encryption_keys()

    # Load encryption master key for AlloyDB pgcrypto encryption
    key_path = Path('.encryption_key')
    with open(key_path, 'r') as f:
        alloydb_encryption_key = f.read().strip()

    # Connect to databases with automatic encryption enabled
    mongo_client, mongo_db = connect_mongodb(kms_providers, key_ids)
    alloydb_conn = connect_alloydb()

    # Get initial counts
    mongo_initial, alloydb_initial = get_database_counts(mongo_db, alloydb_conn)

    print_info(f"Initial counts - MongoDB: {mongo_initial}, AlloyDB: {alloydb_initial}")

    # Process in batches
    total_inserted = 0
    total_batches = (args.count + args.batch_size - 1) // args.batch_size

    print_header("Batch Processing with Validation")

    for batch_num in range(1, total_batches + 1):
        # Calculate batch size for this iteration
        remaining = args.count - total_inserted
        current_batch_size = min(args.batch_size, remaining)

        # Generate batch data
        batch = generate_customer_data(current_batch_size)

        # Insert with validation (pass encryption key for AlloyDB pgcrypto)
        success = insert_batch_with_validation(
            mongo_db, alloydb_conn, batch, batch_num, total_batches, alloydb_encryption_key,
            total_inserted, args.count
        )

        if not success:
            print_error("Batch processing failed. Stopping.")
            break

        total_inserted += len(batch)

    # Get final counts and validate
    print_header("Final Validation")

    mongo_final, alloydb_final = get_database_counts(mongo_db, alloydb_conn)

    print_info(f"Final counts - MongoDB: {mongo_final}, AlloyDB: {alloydb_final}")
    print_info(f"Records added - MongoDB: {mongo_final - mongo_initial}, AlloyDB: {alloydb_final - alloydb_initial}")

    if mongo_final == alloydb_final:
        print_success("Database consistency validated!")
    else:
        print_error(f"Database inconsistency detected! Difference: {abs(mongo_final - alloydb_final)} records")

    # Close connections
    mongo_client.close()
    alloydb_conn.close()

    print_header("Data Generation Complete!")
    print_success(f"Successfully generated and inserted {total_inserted} records")
    print()
    print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
    print(f"  • Total customers inserted: {total_inserted}")
    print(f"  • MongoDB total: {mongo_final}")
    print(f"  • AlloyDB total: {alloydb_final}")
    print(f"  • Databases consistent: {'Yes' if mongo_final == alloydb_final else 'No'}")
    print()
    print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
    print("  1. Run tests: python run_tests.py --iterations 5")
    print("  2. Test API:  http://localhost:8000/docs (API runs in Docker)")
    print()
    print(f"{Colors.BOLD}Mode Switching:{Colors.ENDC}")
    print("  • Hybrid mode:        Default (MongoDB search -> AlloyDB fetch)")
    print("  • MongoDB-only mode:  Add ?mode=mongodb_only to any search endpoint")
    print("  • Both modes return identical data for fair performance comparison")

if __name__ == "__main__":
    main()
