-- AlloyDB (PostgreSQL) Schema for POC
-- Encrypted data storage for fair performance comparison with MongoDB
-- Uses pgcrypto for field-level encryption (decrypt by ID only, no search)
-- Identical data structure to MongoDB encrypted output

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Create customers table with encrypted PII fields
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Encrypted PII fields (stored as BYTEA)
    full_name_encrypted BYTEA NOT NULL,
    email_encrypted BYTEA NOT NULL,
    phone_encrypted BYTEA,
    address_encrypted BYTEA,
    preferences_encrypted BYTEA,

    -- Non-PII fields (plaintext for metadata/analytics)
    tier VARCHAR(50) DEFAULT 'gold',
    category VARCHAR(50),
    status VARCHAR(50),
    loyalty_points INTEGER DEFAULT 0,
    last_purchase_date VARCHAR(100),
    lifetime_value DECIMAL(12, 2) DEFAULT 0.00,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE customers IS 'Customer data table with encrypted PII fields using pgcrypto - decryption happens in application layer';
