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

COMMENT ON TABLE customers IS 'Customer data table with encrypted PII fields using pgcrypto - decryption happens in application layer';
COMMENT ON FUNCTION get_customers_by_ids IS 'Retrieve encrypted customer data by UUIDs (IDs from MongoDB search results)';
