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
from datetime import datetime, timedelta
import random
from pathlib import Path
import base64

# Import encryption libraries
from pymongo import MongoClient
from pymongo.encryption import ClientEncryption, Algorithm
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

def connect_mongodb():
    """Connect to MongoDB"""
    print_info("Connecting to MongoDB...")

    try:
        client = MongoClient("mongodb://localhost:27017/?directConnection=true")
        db = client["poc_database"]

        # Test connection
        client.admin.command('ping')

        print_success("Connected to MongoDB")
        return client, db
    except Exception as e:
        print_error(f"MongoDB connection failed: {e}")
        sys.exit(1)

def connect_alloydb():
    """Connect to AlloyDB"""
    print_info("Connecting to AlloyDB...")

    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="alloydb_poc",
            user="postgres",
            password="postgres_password"
        )

        print_success("Connected to AlloyDB")
        return conn
    except Exception as e:
        print_error(f"AlloyDB connection failed: {e}")
        sys.exit(1)

def setup_encryption(client):
    """Setup encryption client"""
    print_info("Loading encryption keys...")

    # Read master key
    key_path = Path(".encryption_key")
    if not key_path.exists():
        print_error("Encryption key not found. Run: python mongodb/setup-encryption.py")
        sys.exit(1)

    with open(key_path, 'r') as f:
        master_key = f.read().strip()

    kms_providers = {
        "local": {
            "key": base64.b64decode(master_key)
        }
    }

    client_encryption = ClientEncryption(
        kms_providers=kms_providers,
        key_vault_namespace="encryption.__keyVault",
        key_vault_client=client,
        codec_options=CodecOptions()
    )

    # Load key IDs
    key_vault = client.get_database("encryption").get_collection("__keyVault")
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

    return client_encryption, key_mapping

def insert_mongodb_data(db, client_encryption, key_ids, customers, reset=False):
    """Insert encrypted customer data into MongoDB"""
    print_header("Inserting Data into MongoDB")

    collection = db["customers"]

    if reset:
        print_info("Resetting MongoDB collection...")
        collection.drop()
        print_success("Collection dropped, will be recreated on first insert")

    # Check existing count
    existing_count = collection.count_documents({})
    if existing_count > 0 and not reset:
        print_info(f"Collection already has {existing_count} documents (skipping insert)")
        return

    print_info(f"Inserting {len(customers)} encrypted customer records...")

    for i, customer in enumerate(customers):
        # Encrypt fields
        # Note: Use TEXTPREVIEW for fields with preview query types (prefix/suffix/substring)
        #       Use INDEXED for fields with equality-only queries

        # Configure text options for preview query types
        # Must specify which preview type: prefix, suffix, or substring
        # Parameters must match the schema configuration
        substring_text_opts = TextOpts(
            substring=SubstringOpts(
                strMinQueryLength=2,    # Min substring query length
                strMaxQueryLength=10,   # Max substring query length
                strMaxLength=60         # Max field value length
            ),
            case_sensitive=False,
            diacritic_sensitive=False
        )
        prefix_text_opts = TextOpts(
            prefix=PrefixOpts(
                strMinQueryLength=1,     # Min prefix query length
                strMaxQueryLength=50     # Max prefix query length (realistic for email search)
            ),
            case_sensitive=False,
            diacritic_sensitive=False
        )

        # For non-searchable fields, use UNINDEXED algorithm (more efficient, smaller storage)
        # We reuse the searchable_name key for general encryption purposes
        general_key_id = key_ids["searchable_name"]

        encrypted_doc = {
            "alloy_record_id": customer["id"],
            # Searchable encrypted fields (with index)
            "searchable_name": client_encryption.encrypt(
                customer["full_name"],
                Algorithm.TEXTPREVIEW,  # substringPreview requires textPreview index
                key_id=key_ids["searchable_name"],
                contention_factor=0,
                text_opts=substring_text_opts
            ),
            "searchable_email": client_encryption.encrypt(
                customer["email"],
                Algorithm.TEXTPREVIEW,  # prefixPreview requires textPreview index
                key_id=key_ids["searchable_email"],
                contention_factor=0,
                text_opts=prefix_text_opts
            ),
            "searchable_phone": client_encryption.encrypt(
                customer["phone"],
                Algorithm.INDEXED,  # equality query uses indexed algorithm
                key_id=key_ids["searchable_phone"],
                contention_factor=0
            ),
            # Additional encrypted fields (non-searchable, using UNINDEXED algorithm)
            "full_name": client_encryption.encrypt(customer["full_name"], Algorithm.UNINDEXED, key_id=general_key_id),
            "email": client_encryption.encrypt(customer["email"], Algorithm.UNINDEXED, key_id=general_key_id),
            "phone": client_encryption.encrypt(customer["phone"], Algorithm.UNINDEXED, key_id=general_key_id),
            "address": client_encryption.encrypt(json.dumps(customer["address"]), Algorithm.UNINDEXED, key_id=general_key_id),
            "preferences": client_encryption.encrypt(json.dumps(customer["preferences"]), Algorithm.UNINDEXED, key_id=general_key_id),
            "metadata": {
                "category": client_encryption.encrypt(
                    customer["category"],
                    Algorithm.INDEXED,  # equality query uses indexed algorithm
                    key_id=key_ids["metadata_category"],
                    contention_factor=0
                ),
                "status": client_encryption.encrypt(
                    customer["status"],
                    Algorithm.INDEXED,  # equality query uses indexed algorithm
                    key_id=key_ids["metadata_status"],
                    contention_factor=0
                ),
                "tier": client_encryption.encrypt(customer["tier"], Algorithm.UNINDEXED, key_id=general_key_id),
                "loyalty_points": client_encryption.encrypt(str(customer["loyalty_points"]), Algorithm.UNINDEXED, key_id=general_key_id),
                "last_purchase_date": client_encryption.encrypt(customer["last_purchase_date"], Algorithm.UNINDEXED, key_id=general_key_id),
                "lifetime_value": client_encryption.encrypt(str(customer["lifetime_value"]), Algorithm.UNINDEXED, key_id=general_key_id)
            },
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        collection.insert_one(encrypted_doc)
        print_progress(i+1, len(customers), f"({i+1}/{len(customers)} customers)")

    final_count = collection.count_documents({})
    print_success(f"MongoDB: {final_count} total customer records")

def insert_alloydb_data(conn, customers, orders, reset=False):
    """Insert customer and order data into AlloyDB"""
    print_header("Inserting Data into AlloyDB")

    cursor = conn.cursor()

    if reset:
        print_info("Resetting AlloyDB tables...")
        cursor.execute("TRUNCATE TABLE orders, customer_metadata, customers CASCADE;")
        conn.commit()
        print_success("Tables reset")

    # Insert customers
    print_info(f"Inserting {len(customers)} customer records...")

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
            c["preferences"]
        )
        for c in customers
    ]

    execute_batch(
        cursor,
        """
        INSERT INTO customers (id, full_name, email, phone, address, preferences)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        customer_records
    )

    print_success(f"Inserted {len(customers)} customers")

    # Insert customer metadata
    print_info(f"Inserting {len(customers)} customer metadata records...")

    metadata_records = [
        (
            str(uuid.uuid4()),
            c["id"],
            c["loyalty_points"],
            c["tier"],
            datetime.now() - timedelta(days=random.randint(1, 365)),
            c["lifetime_value"]
        )
        for c in customers
    ]

    execute_batch(
        cursor,
        """
        INSERT INTO customer_metadata (id, customer_id, loyalty_points, tier, last_purchase_date, lifetime_value)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        metadata_records
    )

    print_success(f"Inserted {len(customers)} metadata records")

    # Insert orders
    print_info(f"Inserting {len(orders)} order records...")

    order_records = [
        (
            o["id"],
            o["customer_id"],
            o["order_number"],
            o["order_date"],
            o["total_amount"],
            o["status"],
            o["items"],
            o["shipping_address"]
        )
        for o in orders
    ]

    execute_batch(
        cursor,
        """
        INSERT INTO orders (id, customer_id, order_number, order_date, total_amount, status, items, shipping_address)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (order_number) DO NOTHING
        """,
        order_records
    )

    print_success(f"Inserted {len(orders)} orders")

    conn.commit()
    cursor.close()

    # Verify counts
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM customers")
    customer_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM orders")
    order_count = cursor.fetchone()[0]
    cursor.close()

    print_success(f"AlloyDB: {customer_count} customers, {order_count} orders")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Generate POC test data")
    parser.add_argument('--count', type=int, default=10000, help='Number of customers to generate (default: 10000)')
    parser.add_argument('--reset', action='store_true', help='Reset and regenerate all data')
    args = parser.parse_args()

    print_header("POC Data Generation")
    print_info(f"Generating {args.count} customers")

    if args.reset:
        print_warning("Reset mode: All existing data will be deleted")

    # Generate data
    print_info("Generating random customer data...")
    customers = generate_customer_data(args.count)
    print_success(f"Generated {len(customers)} customers")

    print_info("Generating order data...")
    orders = generate_orders(customers)
    print_success(f"Generated {len(orders)} orders")

    # Connect to databases
    mongo_client, mongo_db = connect_mongodb()
    alloydb_conn = connect_alloydb()

    # Setup encryption
    client_encryption, key_ids = setup_encryption(mongo_client)

    # Insert data
    insert_mongodb_data(mongo_db, client_encryption, key_ids, customers, args.reset)
    insert_alloydb_data(alloydb_conn, customers, orders, args.reset)

    # Close connections
    mongo_client.close()
    alloydb_conn.close()

    print_header("Data Generation Complete!")
    print_success(f"Successfully generated and inserted test data")
    print()
    print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
    print(f"  • Customers: {len(customers)}")
    print(f"  • Orders: {len(orders)}")
    print(f"  • MongoDB: Encrypted searchable fields")
    print(f"  • AlloyDB: Complete customer data")
    print()
    print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
    print("  1. Start API: cd api && python app.py")
    print("  2. Run tests: python run_tests.py")

if __name__ == "__main__":
    main()
