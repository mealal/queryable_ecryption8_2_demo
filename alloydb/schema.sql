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

-- Create indexes for performance (only on non-encrypted fields)
-- Note: Cannot index encrypted BYTEA fields (no search functionality needed)
CREATE INDEX idx_customers_tier ON customers(tier);
CREATE INDEX idx_customers_category ON customers(category);
CREATE INDEX idx_customers_status ON customers(status);
CREATE INDEX idx_customers_created_at ON customers(created_at);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to customers table
CREATE TRIGGER update_customers_updated_at
    BEFORE UPDATE ON customers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create function to query by ID list (returns encrypted data)
-- Decryption happens in application layer for performance measurement
CREATE OR REPLACE FUNCTION get_customers_by_ids(id_list UUID[])
RETURNS TABLE (
    id UUID,
    full_name_encrypted BYTEA,
    email_encrypted BYTEA,
    phone_encrypted BYTEA,
    address_encrypted BYTEA,
    preferences_encrypted BYTEA,
    tier VARCHAR,
    loyalty_points INTEGER,
    last_purchase_date VARCHAR,
    lifetime_value DECIMAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.full_name_encrypted,
        c.email_encrypted,
        c.phone_encrypted,
        c.address_encrypted,
        c.preferences_encrypted,
        c.tier,
        c.loyalty_points,
        c.last_purchase_date,
        c.lifetime_value
    FROM customers c
    WHERE c.id = ANY(id_list);
END;
$$ LANGUAGE plpgsql;

-- Insert sample encrypted data for testing
-- Note: Encryption key is stored in .encryption_key file (created during deployment)
-- Sample data uses a test key for demonstration
INSERT INTO customers (
    id,
    full_name_encrypted,
    email_encrypted,
    phone_encrypted,
    address_encrypted,
    preferences_encrypted,
    tier,
    loyalty_points,
    last_purchase_date,
    lifetime_value
) VALUES
(
    '550e8400-e29b-41d4-a716-446655440001',
    pgp_sym_encrypt('John Doe', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('john.doe@example.com', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('+1-555-0101', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('{"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001", "country": "USA"}', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('{"newsletter": true, "notifications": {"email": true, "sms": false}, "language": "en"}', 'test_key_replace_with_actual'),
    'gold',
    1250,
    '2025-10-15',
    5420.50
),
(
    '550e8400-e29b-41d4-a716-446655440002',
    pgp_sym_encrypt('Jane Smith', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('jane.smith@example.com', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('+1-555-0102', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('{"street": "456 Oak Ave", "city": "Los Angeles", "state": "CA", "zip": "90001", "country": "USA"}', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('{"newsletter": false, "notifications": {"email": true, "sms": true}, "language": "en"}', 'test_key_replace_with_actual'),
    'silver',
    340,
    '2025-10-20',
    890.25
),
(
    '550e8400-e29b-41d4-a716-446655440003',
    pgp_sym_encrypt('Bob Johnson', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('bob.johnson@example.com', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('+1-555-0103', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('{"street": "789 Pine Rd", "city": "Chicago", "state": "IL", "zip": "60601", "country": "USA"}', 'test_key_replace_with_actual'),
    pgp_sym_encrypt('{"newsletter": true, "notifications": {"email": false, "sms": false}, "language": "en"}', 'test_key_replace_with_actual'),
    'platinum',
    2100,
    '2024-08-10',
    12340.75
);

COMMENT ON TABLE customers IS 'Customer data table with encrypted PII fields using pgcrypto - decryption happens in application layer';
COMMENT ON FUNCTION get_customers_by_ids IS 'Retrieve encrypted customer data by UUIDs (IDs from MongoDB search results)';
