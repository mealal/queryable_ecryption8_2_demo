-- AlloyDB (PostgreSQL) Schema for POC
-- Simplified schema with single customers table for fair performance comparison
-- No joins needed - identical data structure to MongoDB decrypted output

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create customers table with all fields
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(50),
    address JSONB,
    preferences JSONB,
    tier VARCHAR(50) DEFAULT 'gold',
    loyalty_points INTEGER DEFAULT 0,
    last_purchase_date VARCHAR(100),
    lifetime_value DECIMAL(12, 2) DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_customers_phone ON customers(phone);
CREATE INDEX idx_customers_tier ON customers(tier);
CREATE INDEX idx_customers_created_at ON customers(created_at);

-- Create GIN index for JSONB columns
CREATE INDEX idx_customers_address_gin ON customers USING GIN (address);
CREATE INDEX idx_customers_preferences_gin ON customers USING GIN (preferences);

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

-- Create function to query by ID list
CREATE OR REPLACE FUNCTION get_customers_by_ids(id_list UUID[])
RETURNS TABLE (
    id UUID,
    full_name VARCHAR,
    email VARCHAR,
    phone VARCHAR,
    address JSONB,
    preferences JSONB,
    tier VARCHAR,
    loyalty_points INTEGER,
    last_purchase_date VARCHAR,
    lifetime_value DECIMAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.full_name,
        c.email,
        c.phone,
        c.address,
        c.preferences,
        c.tier,
        c.loyalty_points,
        c.last_purchase_date,
        c.lifetime_value
    FROM customers c
    WHERE c.id = ANY(id_list);
END;
$$ LANGUAGE plpgsql;

-- Insert sample data for testing
INSERT INTO customers (id, full_name, email, phone, address, preferences, tier, loyalty_points, last_purchase_date, lifetime_value) VALUES
(
    '550e8400-e29b-41d4-a716-446655440001',
    'John Doe',
    'john.doe@example.com',
    '+1-555-0101',
    '{"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001", "country": "USA"}',
    '{"newsletter": true, "notifications": {"email": true, "sms": false}, "language": "en"}',
    'gold',
    1250,
    '2025-10-15',
    5420.50
),
(
    '550e8400-e29b-41d4-a716-446655440002',
    'Jane Smith',
    'jane.smith@example.com',
    '+1-555-0102',
    '{"street": "456 Oak Ave", "city": "Los Angeles", "state": "CA", "zip": "90001", "country": "USA"}',
    '{"newsletter": false, "notifications": {"email": true, "sms": true}, "language": "en"}',
    'silver',
    340,
    '2025-10-20',
    890.25
),
(
    '550e8400-e29b-41d4-a716-446655440003',
    'Bob Johnson',
    'bob.johnson@example.com',
    '+1-555-0103',
    '{"street": "789 Pine Rd", "city": "Chicago", "state": "IL", "zip": "60601", "country": "USA"}',
    '{"newsletter": true, "notifications": {"email": false, "sms": false}, "language": "en"}',
    'platinum',
    2100,
    '2024-08-10',
    12340.75
);

COMMENT ON TABLE customers IS 'Main customer data table - contains full unencrypted customer information with all metadata';
COMMENT ON FUNCTION get_customers_by_ids IS 'Retrieve customers by array of UUIDs from MongoDB';
