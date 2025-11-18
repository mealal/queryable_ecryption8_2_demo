"""
Create Denodo REST Web Services via VQL execution
Uses the Denodo VQL endpoint to deploy REST services
"""
import requests
from requests.auth import HTTPBasicAuth
import time

DENODO_HOST = "localhost"
DENODO_PORT = 9090
DENODO_VDP_PORT = 9999
DENODO_USER = "admin"
DENODO_PASSWORD = "admin"
DATABASE = "poc_integration"

def execute_vql(vql_statement):
    """Execute VQL via Denodo RESTful Web Service admin endpoint"""
    url = f"http://{DENODO_HOST}:{DENODO_PORT}/denodo-restfulws/admin/vql"

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }

    data = {
        'query': vql_statement
    }

    try:
        response = requests.post(
            url,
            auth=HTTPBasicAuth(DENODO_USER, DENODO_PASSWORD),
            headers=headers,
            data=data,
            timeout=30
        )

        if response.status_code == 200:
            return True, "Success"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
    except Exception as e:
        return False, str(e)

def create_rest_services():
    """Create REST web services for the views"""
    print("=" * 80)
    print("Creating Denodo REST Web Services")
    print("=" * 80)

    # Connect to database
    print("\n1. Connecting to database...")
    success, msg = execute_vql(f"CONNECT DATABASE {DATABASE};")
    if not success:
        print(f"  [ERROR] {msg}")
        return False
    print("  [OK] Connected")

    # Create REST services - simplified version without CONNECTION clause
    services = [
        ("phone_search", "Phone search REST service"),
        ("email_prefix_search", "Email prefix search REST service"),
        ("name_substring_search", "Name substring search REST service")
    ]

    print("\n2. Creating REST web services...")

    for service_name, description in services:
        print(f"  - Creating {service_name}...")

        # Minimal VQL for REST service
        vql = f"""
        CREATE OR REPLACE REST WEBSERVICE {service_name}
            RESOURCES (
                VIEW {service_name}
            );
        """

        success, msg = execute_vql(vql)
        if success:
            print(f"    [OK] {service_name} created")
        else:
            print(f"    [WARN] {service_name}: {msg}")

    print("\n" + "=" * 80)
    print("REST Web Services Creation Complete")
    print("=" * 80)
    print("\nREST endpoints should be available at:")
    print(f"  http://{DENODO_HOST}:{DENODO_PORT}/denodo-restfulws/{DATABASE}/views/{services[0][0]}")
    print(f"  http://{DENODO_HOST}:{DENODO_PORT}/denodo-restfulws/{DATABASE}/views/{services[1][0]}")
    print(f"  http://{DENODO_HOST}:{DENODO_PORT}/denodo-restfulws/{DATABASE}/views/{services[2][0]}")

    return True

if __name__ == '__main__':
    # Wait a moment for Denodo to be fully ready
    print("Waiting for Denodo to be ready...")
    time.sleep(2)

    try:
        success = create_rest_services()
        exit(0 if success else 1)
    except Exception as e:
        print(f"[ERROR] {e}")
        exit(1)
