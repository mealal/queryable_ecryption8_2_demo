"""
Create Denodo Views and REST Services via REST API
This is simpler than writing complex VQL for MongoDB base views
"""
import requests
import json
import time
from requests.auth import HTTPBasicAuth

DENODO_HOST = "localhost"
DENODO_PORT = 9090
DENODO_USER = "admin"
DENODO_PASSWORD = "admin"
DATABASE = "poc_integration"

BASE_URL = f"http://{DENODO_HOST}:{DENODO_PORT}/denodo-restfulws"
AUTH = HTTPBasicAuth(DENODO_USER, DENODO_PASSWORD)

def create_view_via_vql(vql_statement):
    """Execute VQL statement via REST API"""
    url = f"{BASE_URL}/admin/vql"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'query': vql_statement
    }

    try:
        response = requests.post(url, auth=AUTH, headers=headers, data=data, timeout=30)
        if response.status_code == 200:
            print(f"  [OK] VQL executed successfully")
            return True
        else:
            print(f"  [ERROR] {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def main():
    print("=" * 80)
    print("Creating Denodo Views via REST API")
    print("=" * 80)

    # Test connection
    print("\n1. Testing Denodo connection...")
    try:
        response = requests.get(f"{BASE_URL}/{DATABASE}", auth=AUTH, timeout=5)
        if response.status_code == 200:
            print("  [OK] Connected to Denodo")
        else:
            print(f"  [ERROR] Cannot connect: {response.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] Cannot connect: {e}")
        return False

    # Create derived views for queries
    print("\n2. Creating derived views...")

    # Phone search view - simple AlloyDB query
    print("  - Creating phone_search view...")
    vql_phone = f"""
    CREATE OR REPLACE VIEW phone_search AS
    SELECT id as customer_id, full_name, email, phone, tier, address, preferences,
           loyalty_points, lifetime_value, last_purchase_date
    FROM bv_alloydb_customers
    WHERE phone = ?
    """
    create_view_via_vql(vql_phone)

    # Email prefix search view
    print("  - Creating email_prefix_search view...")
    vql_email = f"""
    CREATE OR REPLACE VIEW email_prefix_search AS
    SELECT id as customer_id, full_name, email, phone, tier, address, preferences,
           loyalty_points, lifetime_value, last_purchase_date
    FROM bv_alloydb_customers
    WHERE email LIKE CONCAT(?, '%')
    """
    create_view_via_vql(vql_email)

    # Name substring search view
    print("  - Creating name_substring_search view...")
    vql_name = f"""
    CREATE OR REPLACE VIEW name_substring_search AS
    SELECT id as customer_id, full_name, email, phone, tier, address, preferences,
           loyalty_points, lifetime_value, last_purchase_date
    FROM bv_alloydb_customers
    WHERE full_name LIKE CONCAT('%', ?, '%')
    """
    create_view_via_vql(vql_name)

    # Create REST web services
    print("\n3. Creating REST web services...")
    print("  Note: REST service creation via VQL is complex.")
    print("  Recommend using Denodo Admin Tool to publish REST services for:")
    print("    - phone_search")
    print("    - email_prefix_search")
    print("    - name_substring_search")

    print("\n" + "=" * 80)
    print("View Creation Complete")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Open http://localhost:9090 (admin/admin)")
    print("2. Navigate to 'poc_integration' database")
    print("3. Right-click each view and select 'Publish' -> 'REST Web Service'")
    print("4. Use default settings and publish")

    return True

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
