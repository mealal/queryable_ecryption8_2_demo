#!/usr/bin/env python3
"""
MongoDB 8.2 Queryable Encryption Setup Script
This script sets up queryable encryption for the POC database
"""

import os
import json
from pymongo import MongoClient
from pymongo.encryption import ClientEncryption, Algorithm
from pymongo.encryption_options import AutoEncryptionOpts
from bson.binary import Binary, UuidRepresentation
from bson.codec_options import CodecOptions
import base64

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = "poc_database"
COLLECTION_NAME = "customers"
KEY_VAULT_NAMESPACE = "encryption.__keyVault"

# Local KMS configuration (for POC - use AWS KMS/Azure Key Vault in production)
LOCAL_MASTER_KEY = os.getenv("LOCAL_MASTER_KEY")
KEY_FILE_PATH = ".encryption_key"

if not LOCAL_MASTER_KEY:
    # Generate a random 96-byte master key for local testing
    LOCAL_MASTER_KEY = base64.b64encode(os.urandom(96)).decode('utf-8')
    print(f"Generated Local Master Key: {LOCAL_MASTER_KEY}")
    print("IMPORTANT: Store this key securely. Add to environment: export LOCAL_MASTER_KEY='{}'".format(LOCAL_MASTER_KEY))

    # Save key to file
    with open(KEY_FILE_PATH, 'w') as f:
        f.write(LOCAL_MASTER_KEY)
    print(f"Key saved to {KEY_FILE_PATH}")

KMS_PROVIDERS = {
    "local": {
        "key": base64.b64decode(LOCAL_MASTER_KEY)
    }
}


def create_data_encryption_keys(client_encryption, field_names):
    """Create Data Encryption Keys (DEKs) in the key vault for each field"""
    print(f"Creating {len(field_names)} Data Encryption Keys...")

    key_ids = {}
    for field_name in field_names:
        key_alt_name = f"customer_{field_name}_key"
        key_id = client_encryption.create_data_key(
            "local",
            key_alt_names=[key_alt_name]
        )
        key_ids[field_name] = key_id
        print(f"  Created DEK for '{field_name}': {key_id}")

    return key_ids


def setup_queryable_encryption_schema(key_ids):
    """Define the queryable encryption schema using MongoDB 8.2 encryptedFields format

    This schema demonstrates REALISTIC search patterns optimized for production use cases:

    1. **Name**: substringPreview ONLY
       - Use case: Flexible text search - find "John" in "John Smith" or "Smith" in middle/end
       - Most versatile for name searches (first name, last name, partial match)
       - Cannot combine with equality, but substring covers exact match use case

    2. **Email**: prefixPreview ONLY
       - Use case: Search by username prefix (common pattern: "john@...")
       - Also supports full email exact match via full-value prefix
       - Suffix (domain search) not as important in practice

    3. **Phone**: equality ONLY
       - Use case: Exact phone number lookup (standard behavior)
       - Prefix/suffix/substring not useful for phone numbers

    4. **Category & Status**: equality ONLY
       - Use case: Exact match for enumerated values (premium, gold, active, etc.)

    MongoDB 8.2 LIMITATIONS:
    - Maximum 2 query types per field
    - Multiple query types can ONLY be: prefixPreview + suffixPreview
    - substringPreview CANNOT be combined with any other type (must be alone)
    - Cannot mix equality with preview types

    DESIGN CHOICE: Prioritize most useful query pattern per field rather than trying
    to support all patterns. Substring on name gives maximum flexibility, prefix on
    email covers 90% of use cases, equality on phone/category/status is standard.
    """
    encrypted_fields = {
        "fields": [
            {
                "keyId": key_ids["searchable_name"],
                "path": "searchable_name",
                "bsonType": "string",
                "queries": [
                    {
                        "queryType": "substringPreview",
                        "min": 2,
                        "max": 10,
                        "strMinQueryLength": 2,    # Minimum substring query length
                        "strMaxQueryLength": 10,   # Maximum substring query length (max 10 for substringPreview)
                        "strMaxLength": 60,        # Maximum field value length (max 60 for substringPreview)
                        "caseSensitive": False,
                        "diacriticSensitive": False
                    }
                ]
            },
            {
                "keyId": key_ids["searchable_email"],
                "path": "searchable_email",
                "bsonType": "string",
                "queries": [
                    {
                        "queryType": "prefixPreview",
                        "min": 1,
                        "max": 30,
                        "strMinQueryLength": 1,     # Minimum prefix query length
                        "strMaxQueryLength": 50,    # Maximum prefix query length (realistic for email search)
                        "strMaxLength": 100,        # Maximum field value length (realistic email length)
                        "caseSensitive": False,
                        "diacriticSensitive": False
                    }
                ]
            },
            {
                "keyId": key_ids["searchable_phone"],
                "path": "searchable_phone",
                "bsonType": "string",
                "queries": [{"queryType": "equality"}]
            },
            {
                "keyId": key_ids["metadata_category"],
                "path": "metadata.category",
                "bsonType": "string",
                "queries": [{"queryType": "equality"}]
            },
            {
                "keyId": key_ids["metadata_status"],
                "path": "metadata.status",
                "bsonType": "string",
                "queries": [{"queryType": "equality"}]
            }
        ]
    }
    return encrypted_fields


def create_encrypted_collection(db, encrypted_fields):
    """Create collection with encryption enabled using MongoDB 8.2 format"""
    print(f"Creating encrypted collection: {COLLECTION_NAME}")

    # Create collection with encryptedFields
    db.create_collection(
        COLLECTION_NAME,
        encryptedFields=encrypted_fields
    )

    # Create indexes for queryable fields
    collection = db[COLLECTION_NAME]
    # Note: Queryable Encryption automatically creates indexes for encrypted fields
    # We only need to create additional indexes for non-encrypted fields
    collection.create_index("alloy_record_id")

    print("Encrypted collection created with indexes")


def main():
    """Main setup function"""
    print("=" * 60)
    print("MongoDB 8.2 Queryable Encryption Setup")
    print("=" * 60)

    # Connect to MongoDB without encryption for setup
    print(f"\nConnecting to MongoDB: {MONGODB_URI}")
    # Use directConnection=true to bypass replica set hostname issues
    setup_client = MongoClient(MONGODB_URI + "?directConnection=true")

    # Create key vault collection
    key_vault_db, key_vault_coll = KEY_VAULT_NAMESPACE.split(".", 1)
    key_vault_collection = setup_client[key_vault_db][key_vault_coll]
    key_vault_collection.create_index("keyAltNames", unique=True)

    # Initialize ClientEncryption
    client_encryption = ClientEncryption(
        KMS_PROVIDERS,
        KEY_VAULT_NAMESPACE,
        setup_client,
        CodecOptions(uuid_representation=UuidRepresentation.STANDARD)
    )

    # Define field names for encryption
    field_names = [
        "searchable_name",
        "searchable_email",
        "searchable_phone",
        "metadata_category",
        "metadata_status"
    ]

    # Check if keys already exist and create missing ones
    key_ids = {}
    for field_name in field_names:
        key_alt_name = f"customer_{field_name}_key"
        existing_key = key_vault_collection.find_one({"keyAltNames": key_alt_name})

        if existing_key:
            print(f"Using existing DEK for '{field_name}'")
            key_ids[field_name] = existing_key["_id"]
        else:
            print(f"Creating new DEK for '{field_name}'...")
            key_id = client_encryption.create_data_key(
                "local",
                key_alt_names=[key_alt_name]
            )
            key_ids[field_name] = key_id
            print(f"  Created: {key_id}")

    # Create encryption schema
    encrypted_fields = setup_queryable_encryption_schema(key_ids)

    # Save schema to file
    encrypted_fields_map = {f"{DATABASE_NAME}.{COLLECTION_NAME}": encrypted_fields}
    with open("encryption-schema.json", "w") as f:
        json.dump(encrypted_fields_map, f, indent=2, default=str)
    print("Schema saved to encryption-schema.json")

    # Create encrypted collection
    db = setup_client[DATABASE_NAME]

    # Drop existing collection if it exists
    if COLLECTION_NAME in db.list_collection_names():
        print(f"Dropping existing collection: {COLLECTION_NAME}")
        db.drop_collection(COLLECTION_NAME)

    create_encrypted_collection(db, encrypted_fields)

    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    print(f"\nDatabase: {DATABASE_NAME}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Key Vault: {KEY_VAULT_NAMESPACE}")
    print("\nEncryption schema created. Use generate_data.py to populate with data.")

    setup_client.close()


if __name__ == "__main__":
    main()
