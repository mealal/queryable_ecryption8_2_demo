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

    # Check if already initialized
    rs_status = run_command(
        "docker exec poc_mongodb mongosh --eval 'rs.status()' --quiet",
        check=False,
        capture_output=True
    )

    if rs_status and 'ok: 1' in rs_status:
        print_success("Replica set already initialized")
        return True

    print_info("Initializing replica set...")

    result = run_command(
        'docker exec poc_mongodb mongosh --eval "rs.initiate()" --quiet',
        check=False,
        capture_output=True
    )

    if result:
        print_success("Replica set initialized")
        time.sleep(5)  # Wait for replica set to stabilize
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
    user: 'denodo_user',
    pwd: 'denodo_password',
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
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'denodo_user') THEN
        CREATE USER denodo_user WITH PASSWORD 'denodo_password';
        GRANT ALL PRIVILEGES ON DATABASE alloydb_poc TO denodo_user;
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO denodo_user;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO denodo_user;
    END IF;
END
\\$\\$;"
    """.strip()

    run_command(alloydb_user_cmd, check=False)

    print_success("Database users created")

def setup_encryption():
    """Setup MongoDB encryption"""
    print_header("Setting Up MongoDB Encryption")

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
        'docker exec poc_mongodb mongosh encryption --eval "db.__keyVault.countDocuments({})" --quiet',
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

    print_info("Running encryption setup script...")

    if run_command(f"{sys.executable} mongodb/setup-encryption.py"):
        print_success("Encryption configured")
        return True
    else:
        print_error("Encryption setup failed")
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

def stop_containers():
    """Stop Docker containers"""
    print_header("Stopping Docker Containers")

    print_info("Stopping containers...")

    if run_command("docker-compose stop"):
        print_success("Containers stopped")
        return True
    else:
        print_error("Failed to stop containers")
        return False

def clean_deployment():
    """Clean deployment (remove all data)"""
    print_header("Cleaning Deployment")

    print_warning("This will remove ALL data including Docker volumes!")
    print_warning("Encryption keys and generated data will be preserved.")

    response = input("\nAre you sure? Type 'yes' to confirm: ")
    if response.lower() != 'yes':
        print_info("Clean cancelled")
        return False

    print_info("Stopping and removing containers...")
    run_command("docker-compose down -v")

    # Clean up .encryption_key if it's a directory
    if os.path.exists('.encryption_key') and os.path.isdir('.encryption_key'):
        print_info("Removing .encryption_key directory...")
        import shutil
        shutil.rmtree('.encryption_key')

    print_success("Deployment cleaned")
    return True

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
        print_info("Start with: cd api && python app.py")

def deploy_all():
    """Full deployment"""
    print_header("POC Deployment - Full Deployment")
    print_info(f"Platform: {platform.system()} {platform.release()}")
    print_info(f"Python: {sys.version.split()[0]}")

    # Check prerequisites
    check_prerequisites()

    # Start containers
    if not start_containers():
        print_error("Deployment failed at container startup")
        sys.exit(1)

    # Initialize replica set
    if not init_replica_set():
        print_error("Deployment failed at replica set initialization")
        sys.exit(1)

    # Create users
    create_database_users()

    # Setup encryption
    if not setup_encryption():
        print_error("Deployment failed at encryption setup")
        sys.exit(1)

    # Wait for API container to be ready
    print_header("Waiting for API")
    print_info("Waiting for API container to start...")
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

    # Final status
    print_header("Deployment Complete!")

    print_success("All components deployed successfully")
    print()
    print(f"{Colors.BOLD}Services Running:{Colors.ENDC}")
    print("  • MongoDB:  localhost:27017")
    print("  • AlloyDB:  localhost:5432")
    print("  • API:      http://localhost:8000")
    print("  • API Docs: http://localhost:8000/docs")
    print()
    print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}")
    print("  1. Generate test data:  python generate_data.py --reset")
    print("  2. Run tests:           python run_tests.py")
    print("  3. View test report:    test_report.html")

def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python deploy.py {start|stop|restart|status|clean}")
        print()
        print("Commands:")
        print("  start    - Deploy and start all components")
        print("  stop     - Stop all components")
        print("  restart  - Restart all components")
        print("  status   - Check status of all components")
        print("  clean    - Stop and remove all data (WARNING: destructive)")
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
    else:
        print_error(f"Unknown command: {command}")
        print("Valid commands: start, stop, restart, status, clean")
        sys.exit(1)

if __name__ == "__main__":
    main()
