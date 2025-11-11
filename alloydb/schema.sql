-- AlloyDB (PostgreSQL) Schema for POC
-- This schema stores the actual business data referenced by MongoDB IDs

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create customers table
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(50),
    address JSONB,
    preferences JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create orders table
CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    order_number VARCHAR(50) UNIQUE NOT NULL,
    order_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL,
    items JSONB NOT NULL,
    shipping_address JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create customer_metadata table (for additional non-encrypted metadata)
CREATE TABLE customer_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    loyalty_points INTEGER DEFAULT 0,
    tier VARCHAR(50) DEFAULT 'standard',
    last_purchase_date TIMESTAMP WITH TIME ZONE,
    lifetime_value DECIMAL(12, 2) DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_customers_created_at ON customers(created_at);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_customer_metadata_customer_id ON customer_metadata(customer_id);
CREATE INDEX idx_customer_metadata_tier ON customer_metadata(tier);

-- Create GIN index for JSONB columns
CREATE INDEX idx_customers_address_gin ON customers USING GIN (address);
CREATE INDEX idx_customers_preferences_gin ON customers USING GIN (preferences);
CREATE INDEX idx_orders_items_gin ON orders USING GIN (items);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to all tables
CREATE TRIGGER update_customers_updated_at
    BEFORE UPDATE ON customers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_customer_metadata_updated_at
    BEFORE UPDATE ON customer_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create view for Denodo integration
CREATE OR REPLACE VIEW v_customer_full_data AS
SELECT
    c.id,
    c.full_name,
    c.email,
    c.phone,
    c.address,
    c.preferences,
    cm.loyalty_points,
    cm.tier,
    cm.last_purchase_date,
    cm.lifetime_value,
    c.created_at,
    c.updated_at
FROM customers c
LEFT JOIN customer_metadata cm ON c.id = cm.customer_id;

-- Create view for customer order summary
CREATE OR REPLACE VIEW v_customer_order_summary AS
SELECT
    c.id as customer_id,
    c.full_name,
    c.email,
    COUNT(o.id) as total_orders,
    SUM(o.total_amount) as total_spent,
    MAX(o.order_date) as last_order_date,
    MIN(o.order_date) as first_order_date
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
GROUP BY c.id, c.full_name, c.email;

-- Insert sample data
INSERT INTO customers (id, full_name, email, phone, address, preferences) VALUES
(
    '550e8400-e29b-41d4-a716-446655440001',
    'John Doe',
    'john.doe@example.com',
    '+1-555-0101',
    '{"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001", "country": "USA"}',
    '{"newsletter": true, "notifications": {"email": true, "sms": false}, "language": "en"}'
),
(
    '550e8400-e29b-41d4-a716-446655440002',
    'Jane Smith',
    'jane.smith@example.com',
    '+1-555-0102',
    '{"street": "456 Oak Ave", "city": "Los Angeles", "state": "CA", "zip": "90001", "country": "USA"}',
    '{"newsletter": false, "notifications": {"email": true, "sms": true}, "language": "en"}'
),
(
    '550e8400-e29b-41d4-a716-446655440003',
    'Bob Johnson',
    'bob.johnson@example.com',
    '+1-555-0103',
    '{"street": "789 Pine Rd", "city": "Chicago", "state": "IL", "zip": "60601", "country": "USA"}',
    '{"newsletter": true, "notifications": {"email": false, "sms": false}, "language": "en"}'
);

-- Insert customer metadata
INSERT INTO customer_metadata (customer_id, loyalty_points, tier, last_purchase_date, lifetime_value) VALUES
('550e8400-e29b-41d4-a716-446655440001', 1250, 'premium', '2025-10-15 14:30:00', 5420.50),
('550e8400-e29b-41d4-a716-446655440002', 340, 'standard', '2025-10-20 09:15:00', 890.25),
('550e8400-e29b-41d4-a716-446655440003', 2100, 'premium', '2024-08-10 16:45:00', 12340.75);

-- Insert sample orders
INSERT INTO orders (customer_id, order_number, order_date, total_amount, status, items, shipping_address) VALUES
(
    '550e8400-e29b-41d4-a716-446655440001',
    'ORD-2025-001',
    '2025-10-15 14:30:00',
    299.99,
    'delivered',
    '[{"product_id": "PROD-001", "name": "Laptop Stand", "quantity": 1, "price": 299.99}]',
    '{"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001", "country": "USA"}'
),
(
    '550e8400-e29b-41d4-a716-446655440002',
    'ORD-2025-002',
    '2025-10-20 09:15:00',
    149.50,
    'shipped',
    '[{"product_id": "PROD-002", "name": "Wireless Mouse", "quantity": 2, "price": 74.75}]',
    '{"street": "456 Oak Ave", "city": "Los Angeles", "state": "CA", "zip": "90001", "country": "USA"}'
),
(
    '550e8400-e29b-41d4-a716-446655440001',
    'ORD-2025-003',
    '2025-10-25 11:00:00',
    599.00,
    'processing',
    '[{"product_id": "PROD-003", "name": "Mechanical Keyboard", "quantity": 1, "price": 599.00}]',
    '{"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001", "country": "USA"}'
);

-- Create function for Denodo to query by ID list
CREATE OR REPLACE FUNCTION get_customers_by_ids(id_list UUID[])
RETURNS TABLE (
    id UUID,
    full_name VARCHAR,
    email VARCHAR,
    phone VARCHAR,
    address JSONB,
    preferences JSONB,
    loyalty_points INTEGER,
    tier VARCHAR,
    last_purchase_date TIMESTAMP WITH TIME ZONE,
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
        cm.loyalty_points,
        cm.tier,
        cm.last_purchase_date,
        cm.lifetime_value
    FROM customers c
    LEFT JOIN customer_metadata cm ON c.id = cm.customer_id
    WHERE c.id = ANY(id_list);
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE customers IS 'Main customer data table - contains full unencrypted customer information';
COMMENT ON TABLE orders IS 'Customer order history';
COMMENT ON TABLE customer_metadata IS 'Additional customer metadata and analytics';
COMMENT ON VIEW v_customer_full_data IS 'Denodo view - Full customer data with metadata';
COMMENT ON VIEW v_customer_order_summary IS 'Denodo view - Customer order summary statistics';
COMMENT ON FUNCTION get_customers_by_ids IS 'Denodo function - Retrieve customers by array of UUIDs from MongoDB';
