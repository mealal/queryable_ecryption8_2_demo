#!/usr/bin/env python3
"""
POC Deployment Script
Cross-platform deployment for MongoDB + AlloyDB + API

Usage:
    python deploy.py start    # Deploy and start all components
    python deploy.py stop     # Stop all components
    python deploy.py restart  # Restart all components
    python deploy.py status   # Check status of all components
    python deploy.py clean    # Stop and remove all data (WARNING: destructive)
"""

import subprocess
import sys
import time
import os
import platform
from pathlib import Path

# ANSI color codes for terminal output
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
    """Print formatted header"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text:^80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")

def print_success(text):
    """Print success message"""
    print(f"{Colors.OKGREEN}[OK] {text}{Colors.ENDC}")

def print_error(text):
    """Print error message"""
    print(f"{Colors.FAIL}[ERROR] {text}{Colors.ENDC}")

def print_info(text):
    """Print info message"""
    print(f"{Colors.OKCYAN}[INFO] {text}{Colors.ENDC}")

def print_warning(text):
    """Print warning message"""
    print(f"{Colors.WARNING}[WARNING] {text}{Colors.ENDC}")

def run_command(cmd, check=True, capture_output=False):
    """Run shell command"""
    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                shell=True,
                check=check,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        else:
            subprocess.run(cmd, shell=True, check=check)
            return True
    except subprocess.CalledProcessError as e:
        if check:
            print_error(f"Command failed: {cmd}")
            if capture_output and e.stderr:
                print(e.stderr)
        return False

def check_deployment_state():
    """Check current state of deployment to determine what actions are safe"""
    state = {
        'containers_exist': False,
        'containers_running': False,
        'mongodb_healthy': False,
        'alloydb_healthy': False,
        'api_running': False,
        'replica_set_initialized': False,
        'encryption_key_exists': False,
        'data_exists': False
    }

    # Check if containers exist
    result = run_command("docker ps -a --filter name=poc_ --format '{{.Names}}'", check=False, capture_output=True)
    if result and 'poc_' in result:
        state['containers_exist'] = True

        # Check if running
        running = run_command("docker ps --filter name=poc_ --format '{{.Names}}'", check=False, capture_output=True)
        if running and 'poc_' in running:
            state['containers_running'] = True

            # Check MongoDB health
            mongo_check = run_command(
                "docker exec poc_mongodb mongosh --eval 'db.adminCommand({ping:1})' --quiet",
                check=False, capture_output=True
            )
            if mongo_check and 'ok: 1' in mongo_check:
                state['mongodb_healthy'] = True

                # Check replica set
                rs_check = run_command(
                    "docker exec poc_mongodb mongosh --eval 'rs.status().ok' --quiet",
                    check=False, capture_output=True
                )
                if rs_check and '1' in rs_check:
                    state['replica_set_initialized'] = True

            # Check AlloyDB health
            alloydb_check = run_command(
                'docker exec poc_alloydb psql -U postgres -d alloydb_poc -c "SELECT 1;" -t',
                check=False, capture_output=True
            )
            if alloydb_check and '1' in alloydb_check:
                state['alloydb_healthy'] = True

            # Check API
            api_check = run_command("curl -s http://localhost:8000/health", check=False, capture_output=True)
            if api_check and 'healthy' in api_check:
                state['api_running'] = True

    # Check encryption key
    if os.path.exists('.encryption_key') and os.path.isfile('.encryption_key'):
        state['encryption_key_exists'] = True

    # Check if data exists (check MongoDB)
    if state['mongodb_healthy']:
        count_check = run_command(
            "docker exec poc_mongodb mongosh poc_database --eval 'db.customers.countDocuments()' --quiet",
            check=False, capture_output=True
        )
        if count_check and count_check.strip() != '0':
            state['data_exists'] = True

    return state

def check_prerequisites():
    """Check if required tools are installed"""
    print_header("Checking Prerequisites")

    prerequisites = {
        'docker': 'Docker',
        'docker-compose': 'Docker Compose',
        'python': 'Python 3.9+'
    }

    all_ok = True
    for cmd, name in prerequisites.items():
        result = run_command(f"{cmd} --version", check=False, capture_output=True)
        if result:
            print_success(f"{name}: Installed")
            if cmd == 'python':
                print(f"  Version: {result.split()[1]}")
            elif cmd == 'docker':
                version_line = result.split('\n')[0]
                print(f"  {version_line}")
        else:
            print_error(f"{name}: Not found")
            all_ok = False

    if not all_ok:
        print_error("\nMissing required tools. Please install them first.")
        sys.exit(1)

    print_success("\nAll prerequisites satisfied")

def pull_denodo_image():
    """Pull Denodo Express image from Harbor registry"""
    print_header("Pulling Denodo Image")

    # Denodo image with SHA256 digest for exact version
    denodo_image = "harbor.open.denodo.com/denodo-express/denodo-platform@sha256:7e10101863621ed0656e525ec9463a487be867bc6a3a12b09293153929e3bb54"

    print_info("Checking if Denodo image is available...")

    # Check if image already exists
    check_image = run_command(
        f"docker images -q {denodo_image}",
        check=False,
        capture_output=True
    )

    if check_image and check_image.strip():
        print_success("Denodo image already exists locally")
        return True

    print_info(f"Pulling Denodo image from Harbor registry...")
    print_info("Image: harbor.open.denodo.com/denodo-express/denodo-platform")

    # Try to pull the image
    pull_result = run_command(
        f"docker pull {denodo_image}",
        check=False,
        capture_output=True
    )

    if pull_result and ("Downloaded" in pull_result or "up to date" in pull_result or "Digest: sha256" in pull_result):
        print_success("Denodo image pulled successfully")
        return True
    else:
        print_warning("Failed to pull Denodo image")
        print_warning("This may be due to:")
        print_warning("  1. Not authenticated with Harbor registry")
        print_warning("  2. Network connectivity issues")
        print_warning("  3. Invalid credentials")
        print()
        print_info("To authenticate with Harbor:")
        print_info("  1. Visit: https://harbor.open.denodo.com")
        print_info("  2. Login and generate CLI secret from User Profile")
        print_info("  3. Run: docker login harbor.open.denodo.com --username YOUR_USERNAME")
        print_info("  4. Enter the CLI secret when prompted")
        print()
        print_info("Deployment will continue, but Denodo will not be available.")
        print_info("See DENODO_DOCKER_SETUP.md for detailed instructions.")
        return False

def start_containers():
    """Start Docker containers"""
    print_header("Starting Docker Containers")

    print_info("Starting MongoDB and AlloyDB containers...")

    if not run_command("docker-compose up -d"):
        print_error("Failed to start containers")
        return False

    print_success("Containers started")

    # Wait for containers to be healthy
    print_info("Waiting for containers to be healthy...")
    max_wait = 30
    for i in range(max_wait):
        time.sleep(2)

        # Check MongoDB
        mongo_result = run_command(
            "docker exec poc_mongodb mongosh --eval \"db.adminCommand({ping: 1})\"",
            check=False,
            capture_output=True
        )

        # Check AlloyDB
        alloydb_result = run_command(
            'docker exec poc_alloydb psql -U postgres -d alloydb_poc -c "SELECT 1;" -t',
            check=False,
            capture_output=True
        )

        if mongo_result and "ok: 1" in mongo_result and alloydb_result and "1" in alloydb_result:
            print_success("All containers are healthy")
            return True

        print(f"  Waiting... ({i+1}/{max_wait})")

    print_warning("Containers started but health check timed out")
    return True

def init_replica_set():
    """Initialize MongoDB replica set"""
    print_header("Initializing MongoDB Replica Set")

    print_info("Checking replica set status...")

    # Check if already initialized - rs.status() returns ok:1 when operational
    rs_status = run_command(
        "docker exec poc_mongodb mongosh --eval 'rs.status().ok' --quiet",
        check=False,
        capture_output=True
    )

    if rs_status and '1' in rs_status:
        print_success("Replica set already initialized and operational")
        return True

    # Try to get replica set config - if it exists, we just need to wait or reconfigure
    rs_conf = run_command(
        "docker exec poc_mongodb mongosh --eval 'rs.conf()' --quiet",
        check=False,
        capture_output=True
    )

    if rs_conf and '_id' in rs_conf:
        print_info("Replica set config exists but not ready, reconfiguring with correct hostname...")

        # Reconfigure with correct hostname
        reconfig_result = run_command(
            'docker exec poc_mongodb mongosh --eval "var cfg = rs.conf(); cfg.members[0].host = \'poc_mongodb:27017\'; rs.reconfig(cfg, {force: true});" --quiet',
            check=False,
            capture_output=True
        )

        if reconfig_result:
            print_success("Replica set reconfigured")
            time.sleep(10)  # Wait for replica set to stabilize after reconfig
            return True

    print_info("Initializing replica set...")

    result = run_command(
        'docker exec poc_mongodb mongosh --eval "rs.initiate({_id: \'rs0\', members: [{_id: 0, host: \'poc_mongodb:27017\'}]})" --quiet',
        check=False,
        capture_output=True
    )

    # Check for "already initialized" error - this is actually success
    if result and ('ok: 1' in result or 'already initialized' in result):
        print_success("Replica set initialized")
        time.sleep(10)  # Wait for replica set to stabilize

        # Verify it's operational
        for i in range(10):
            rs_check = run_command(
                "docker exec poc_mongodb mongosh --eval 'rs.status().ok' --quiet",
                check=False,
                capture_output=True
            )
            if rs_check and '1' in rs_check:
                print_success("Replica set is operational")
                return True
            time.sleep(2)
            print(f"  Waiting for replica set... ({i+1}/10)")

        print_warning("Replica set initialized but taking longer to become operational")
        return True
    else:
        print_error("Failed to initialize replica set")
        return False

def create_database_users():
    """Create database users"""
    print_header("Creating Database Users")

    # Create MongoDB user
    print_info("Creating MongoDB user...")
    mongo_user_cmd = """
docker exec poc_mongodb mongosh --eval "
db.getSiblingDB('admin').createUser({
    user: 'api_user',
    pwd: 'api_password',
    roles: [{role: 'readWrite', db: 'poc_database'}]
})" --quiet
    """.strip()

    run_command(mongo_user_cmd, check=False)

    # Create AlloyDB user
    print_info("Creating AlloyDB user...")
    alloydb_user_cmd = """
docker exec poc_alloydb psql -U postgres -d alloydb_poc -c "
DO \\$\\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'api_user') THEN
        CREATE USER api_user WITH PASSWORD 'api_password';
        GRANT ALL PRIVILEGES ON DATABASE alloydb_poc TO api_user;
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO api_user;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO api_user;
    END IF;
END
\\$\\$;"
    """.strip()

    run_command(alloydb_user_cmd, check=False)

    print_success("Database users created")

def setup_encryption():
    """Setup MongoDB encryption schema (no data generation)"""
    print_header("Setting Up MongoDB Encryption Schema")

    # Clean up .encryption_key if it's a directory
    if os.path.exists('.encryption_key'):
        if os.path.isdir('.encryption_key'):
            print_warning(".encryption_key is a directory, removing...")
            import shutil
            shutil.rmtree('.encryption_key')
        elif os.path.isfile('.encryption_key'):
            # File exists, check if we need to recreate
            pass

    # Check if encryption keys exist in MongoDB
    print_info("Checking encryption key vault...")
    key_check = run_command(
        'docker exec poc_mongodb mongosh encryption --eval "db.getCollection(\'__keyVault\').countDocuments({})" --quiet',
        check=False,
        capture_output=True
    )

    # Extract count from output
    key_count = 0
    if key_check:
        import re
        match = re.search(r'\b(\d+)\b', key_check)
        if match:
            key_count = int(match.group(1))

    # If we have 5 keys and the key file exists, skip
    if key_count == 5 and os.path.exists('.encryption_key') and os.path.isfile('.encryption_key'):
        print_success(f"Encryption already configured (5 keys found)")
        return True

    # If keys exist but don't match expected count, warn and recreate
    if key_count > 0 and key_count != 5:
        print_warning(f"Found {key_count} keys (expected 5), recreating...")
        run_command('docker exec poc_mongodb mongosh --eval "db.getSiblingDB(\'encryption\').dropDatabase()" --quiet', check=False)
        run_command('docker exec poc_mongodb mongosh --eval "db.getSiblingDB(\'poc_database\').dropDatabase()" --quiet', check=False)
        if os.path.exists('.encryption_key'):
            if os.path.isdir('.encryption_key'):
                import shutil
                shutil.rmtree('.encryption_key')
            else:
                os.remove('.encryption_key')

    print_info("Running encryption setup script (schema only, no data)...")

    if run_command(f"{sys.executable} mongodb/setup-encryption.py"):
        print_success("Encryption schema configured")
        return True
    else:
        print_error("Encryption setup failed")
        return False

def setup_alloydb_schema():
    """Setup AlloyDB schema"""
    print_header("Setting Up AlloyDB Schema")

    print_info("Creating AlloyDB tables and indexes...")

    # Apply schema from alloydb/schema.sql
    schema_result = run_command(
        "docker exec -i poc_alloydb psql -U postgres -d alloydb_poc < alloydb/schema.sql",
        check=False,
        capture_output=True
    )

    if schema_result or schema_result == "":  # Empty string means success with no output
        print_success("AlloyDB schema created")
        return True
    else:
        print_error("Failed to create AlloyDB schema")
        return False

def generate_initial_data(count=100):
    """Generate initial test data using generate_data.py"""
    print_header(f"Generating Initial Test Data ({count} records)")

    print_info(f"Generating {count} customer records in both databases...")

    if run_command(f"docker exec poc_api python api/generate_data.py --count {count}"):
        print_success(f"Generated {count} initial customer records")
        return True
    else:
        print_error("Data generation failed")
        return False

def install_api_dependencies():
    """Install API dependencies"""
    print_header("Installing API Dependencies")

    print_info("Installing Python packages...")

    if run_command(f"{sys.executable} -m pip install -r api/requirements.txt"):
        print_success("API dependencies installed")
        return True
    else:
        print_error("Failed to install dependencies")
        return False

def init_denodo():
    """Initialize Denodo with VQL scripts"""
    print_header("Initializing Denodo")

    # Check if Denodo container is running
    denodo_check = run_command(
        "docker ps --filter name=poc_denodo --format '{{.Names}}'",
        check=False,
        capture_output=True
    )

    if not denodo_check or 'poc_denodo' not in denodo_check:
        print_warning("Denodo container not running, skipping initialization")
        return False

    # Wait for Denodo to be ready
    print_info("Waiting for Denodo to be ready (this may take 2-3 minutes)...")
    max_wait = 40  # Denodo takes longer to start
    denodo_ready = False

    for i in range(max_wait):
        denodo_ping = run_command(
            "curl -s -u admin:admin http://localhost:9090/denodo-restfulws/admin/ping",
            check=False,
            capture_output=True
        )

        if denodo_ping and ('ok' in denodo_ping.lower() or '200' in denodo_ping):
            denodo_ready = True
            print_success("Denodo is ready")
            break

        if i % 5 == 0:
            print(f"  Waiting for Denodo... ({i+1}/{max_wait})")
        time.sleep(3)

    if not denodo_ready:
        print_warning("Denodo not ready after waiting. VQL initialization skipped.")
        print_info("You can manually initialize later with: python denodo/init_denodo.py")
        return False

    # Run Denodo initialization script inside the container
    print_info("Executing VQL initialization scripts...")

    if run_command("docker exec poc_denodo bash /opt/denodo/init_vql.sh"):
        print_success("Denodo initialized successfully")
        print_info("  REST API: http://localhost:9090/denodo-restfulws/poc_integration")
        print_info("  Web Panel: http://localhost:9090")
        return True
    else:
        print_warning("Denodo VQL initialization encountered issues")
        print_info("You can retry with: docker exec poc_denodo bash /opt/denodo/init_vql.sh")
        return False

def stop_containers():
    """Stop Docker containers"""
    print_header("Stopping Docker Containers")

    # Check current state
    state = check_deployment_state()

    if not state['containers_exist']:
        print_info("No containers found. Nothing to stop.")
        return True

    if not state['containers_running']:
        print_info("Containers already stopped.")
        return True

    print_info("Stopping containers...")

    if run_command("docker-compose stop", check=False):
        print_success("Containers stopped successfully")
        print()
        print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
        print("  • To start again:  python deploy.py start")
        print("  • To check status: python deploy.py status")
        return True
    else:
        print_error("Failed to stop containers")
        return False

def clean_deployment():
    """Clean deployment (remove all data)"""
    print_header("Cleaning Deployment")

    # Check current state
    state = check_deployment_state()

    if not state['containers_exist']:
        print_info("No deployment found. Nothing to clean.")
        return True

    print_warning("This will remove ALL data including Docker volumes!")
    print_warning("The following will be deleted:")
    print()

    if state['containers_exist']:
        print(f"  • Docker containers: {Colors.FAIL}poc_mongodb, poc_alloydb, poc_api{Colors.ENDC}")
    if state['data_exists']:
        print(f"  • Database data: {Colors.FAIL}MongoDB and AlloyDB data{Colors.ENDC}")
    if state['encryption_key_exists']:
        print(f"  • Encryption key: {Colors.WARNING}Will be preserved{Colors.ENDC}")

    print()
    print_info("To start fresh after cleaning, run: python deploy.py start")
    print()

    response = input("Are you sure? Type 'yes' to confirm: ")
    if response.lower() != 'yes':
        print_info("Clean cancelled")
        return False

    print_info("Stopping and removing containers...")
    run_command("docker-compose down -v", check=False)

    # Clean up .encryption_key if it's a directory
    if os.path.exists('.encryption_key') and os.path.isdir('.encryption_key'):
        print_info("Removing .encryption_key directory...")
        import shutil
        shutil.rmtree('.encryption_key')

    print_success("Deployment cleaned successfully")
    print()
    print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
    print("  1. Start fresh deployment: python deploy.py start")
    print("  2. Run tests:              python run_tests.py")
    return True

def generate_more_data():
    """Generate additional test data"""
    # Parse count from command line
    count = 10000  # default
    if len(sys.argv) > 2:
        for i, arg in enumerate(sys.argv[2:], start=2):
            if arg == '--count' and i + 1 < len(sys.argv):
                try:
                    count = int(sys.argv[i + 1])
                except ValueError:
                    print_error(f"Invalid count: {sys.argv[i + 1]}")
                    sys.exit(1)

    print_header(f"Generating Additional Test Data ({count} records)")

    # Check deployment state
    state = check_deployment_state()

    if not state['api_running']:
        print_error("API is not running. Start deployment first with: python deploy.py start")
        sys.exit(1)

    print_info(f"Generating {count} additional customer records...")

    if run_command(f"docker exec poc_api python api/generate_data.py --count {count}"):
        print_success(f"Generated {count} additional customer records")
        print()
        print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
        print("  1. Run tests:        python run_tests.py")
        print("  2. Check status:     python deploy.py status")
    else:
        print_error("Data generation failed")
        sys.exit(1)

def check_status():
    """Check status of all components"""
    print_header("Component Status")

    # Check Docker containers
    print(f"{Colors.BOLD}Docker Containers:{Colors.ENDC}")
    containers = run_command(
        'docker ps --filter "name=poc_"',
        capture_output=True,
        check=False
    )
    if containers and "poc_" in containers:
        print(containers)
    else:
        print_warning("No containers running")

    # Check MongoDB
    print(f"\n{Colors.BOLD}MongoDB:{Colors.ENDC}")
    mongo_check = run_command(
        "docker exec poc_mongodb mongosh --eval \"db.adminCommand({ping: 1})\"",
        check=False,
        capture_output=True
    )
    if mongo_check and "ok: 1" in mongo_check:
        print_success("MongoDB: Healthy")

        # Check encryption
        if os.path.exists('.encryption_key'):
            print_success("Encryption: Configured")
        else:
            print_warning("Encryption: Not configured")

        # Check data
        count_cmd = "docker exec poc_mongodb mongosh poc_database --eval \"db.customers.countDocuments()\""
        count = run_command(count_cmd, check=False, capture_output=True)
        if count:
            # Extract just the number from the output
            import re
            match = re.search(r'\b(\d+)\b', count)
            if match:
                print_info(f"Customer records: {match.group(1)}")
    else:
        print_error("MongoDB: Not accessible")

    # Check AlloyDB
    print(f"\n{Colors.BOLD}AlloyDB:{Colors.ENDC}")
    alloydb_check = run_command(
        'docker exec poc_alloydb psql -U postgres -d alloydb_poc -c "SELECT 1;" -t',
        check=False,
        capture_output=True
    )
    if alloydb_check:
        print_success("AlloyDB: Healthy")

        # Check data
        count_cmd = 'docker exec poc_alloydb psql -U postgres -d alloydb_poc -c "SELECT COUNT(*) FROM customers;" -t'
        count = run_command(count_cmd, check=False, capture_output=True)
        if count:
            print_info(f"Customer records: {count.strip()}")
    else:
        print_error("AlloyDB: Not accessible")

    # Check API
    print(f"\n{Colors.BOLD}Integration API:{Colors.ENDC}")
    api_check = run_command(
        "curl -s http://localhost:8000/health",
        check=False,
        capture_output=True
    )
    if api_check and 'healthy' in api_check:
        print_success("API: Running (http://localhost:8000)")
    else:
        print_warning("API: Not running")
        print_info("The API runs in Docker. Check logs with: docker logs poc_api")
        print_info("Restart with: docker restart poc_api")

def deploy_all():
    """Full deployment with state checking"""
    print_header("POC Deployment - Full Deployment")
    print_info(f"Platform: {platform.system()} {platform.release()}")
    print_info(f"Python: {sys.version.split()[0]}")

    # Check current state
    print_info("Checking current deployment state...")
    state = check_deployment_state()

    # Check if already fully deployed
    if state['containers_running'] and state['mongodb_healthy'] and state['alloydb_healthy'] and state['api_running']:
        print_warning("Deployment already exists and is healthy!")
        print()
        print(f"{Colors.BOLD}Current State:{Colors.ENDC}")
        print(f"  • Containers: {Colors.OKGREEN}Running{Colors.ENDC}")
        print(f"  • MongoDB: {Colors.OKGREEN}Healthy{Colors.ENDC}")
        print(f"  • AlloyDB: {Colors.OKGREEN}Healthy{Colors.ENDC}")
        print(f"  • API: {Colors.OKGREEN}Running{Colors.ENDC}")
        if state['replica_set_initialized']:
            print(f"  • Replica Set: {Colors.OKGREEN}Initialized{Colors.ENDC}")
        if state['encryption_key_exists']:
            print(f"  • Encryption Key: {Colors.OKGREEN}Present{Colors.ENDC}")
        if state['data_exists']:
            print(f"  • Data: {Colors.OKGREEN}Present{Colors.ENDC}")
        print()
        print(f"{Colors.BOLD}Options:{Colors.ENDC}")
        print("  • To restart:        python deploy.py restart")
        print("  • To check status:   python deploy.py status")
        print("  • To clean and redeploy: python deploy.py clean && python deploy.py start")
        print()
        return

    # If containers exist but not running, restart them
    if state['containers_exist'] and not state['containers_running']:
        print_info("Containers exist but not running. Starting them...")
        run_command("docker-compose start", check=False)
        time.sleep(5)
        # Re-check state
        state = check_deployment_state()

    # Check prerequisites
    check_prerequisites()

    # Pull Denodo image (optional - won't fail deployment if unsuccessful)
    pull_denodo_image()

    # Start containers if needed
    if not state['containers_running']:
        if not start_containers():
            print_error("Deployment failed at container startup")
            sys.exit(1)
        state = check_deployment_state()

    # Initialize replica set if needed
    if not state['replica_set_initialized']:
        if not init_replica_set():
            print_error("Deployment failed at replica set initialization")
            sys.exit(1)

    # Create users (idempotent - will skip if already exist)
    create_database_users()

    # Setup encryption schema (always call - function is idempotent and checks MongoDB key vault)
    if not setup_encryption():
        print_error("Deployment failed at encryption setup")
        sys.exit(1)

    # Setup AlloyDB schema
    if not setup_alloydb_schema():
        print_error("Deployment failed at AlloyDB schema setup")
        sys.exit(1)

    # Recreate API container to remount encryption key file
    if not state['api_running']:
        print_info("Starting API container...")
        run_command("docker rm -f poc_api", check=False)
        run_command("docker-compose up -d api", check=False)
        time.sleep(3)

        # Wait for API container to be ready
        print_info("Waiting for API to start...")
        max_wait = 30
        api_ready = False
        for i in range(max_wait):
            time.sleep(2)
            result = run_command("curl -s http://localhost:8000/health", check=False, capture_output=True)
            if result and "healthy" in result:
                print_success("API is ready")
                api_ready = True
                break
            print(f"  Waiting... ({i+1}/{max_wait})")

        if not api_ready:
            print_warning("API health check timed out, but continuing...")

    # Generate initial test data (100 records)
    if not state['data_exists']:
        if not generate_initial_data(count=100):
            print_warning("Initial data generation failed, but deployment can continue")
    else:
        print_info("Data already exists, skipping initial data generation")

    # Initialize Denodo (optional - won't fail deployment if skipped)
    init_denodo()

    # Final status
    print_header("Deployment Complete!")

    print_success("All components deployed successfully")
    print()
    print(f"{Colors.BOLD}Services Running:{Colors.ENDC}")
    print("  • MongoDB:  localhost:27017")
    print("  • AlloyDB:  localhost:5432")
    print("  • API:      http://localhost:8000")
    print("  • API Docs: http://localhost:8000/docs")
    print("  • Denodo:   http://localhost:9090 (if initialized)")
    print()
    print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
    print("  1. Run tests:                python run_tests.py")
    print("  2. Generate more data:       python deploy.py generate --count 10000")
    print("  3. View test report:         Open test_report.html in browser (generated after tests)")

def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python deploy.py {start|stop|restart|status|clean|generate}")
        print()
        print("Commands:")
        print("  start              - Deploy and start all components")
        print("  stop               - Stop all components")
        print("  restart            - Restart all components")
        print("  status             - Check status of all components")
        print("  clean              - Stop and remove all data (WARNING: destructive)")
        print("  generate [--count N] - Generate additional test data (default: 10000)")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == 'start':
        deploy_all()
    elif command == 'stop':
        stop_containers()
    elif command == 'restart':
        stop_containers()
        time.sleep(2)
        deploy_all()
    elif command == 'status':
        check_status()
    elif command == 'clean':
        clean_deployment()
    elif command == 'generate':
        generate_more_data()
    else:
        print_error(f"Unknown command: {command}")
        print("Valid commands: start, stop, restart, status, clean, generate")
        sys.exit(1)

if __name__ == "__main__":
    main()
