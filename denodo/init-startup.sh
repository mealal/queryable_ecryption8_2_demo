#!/bin/bash
# Denodo Startup Initialization Script
# Executes VQL scripts after Denodo server is ready

DENODO_HOST="localhost"
DENODO_PORT="9999"
DENODO_USER="admin"
DENODO_PASSWORD="admin"
INIT_DIR="/opt/denodo/init"
MAX_RETRIES=30
RETRY_DELAY=5

echo "=========================================="
echo "Denodo Startup Initialization"
echo "=========================================="

# Wait for Denodo to be ready
echo "Waiting for Denodo Virtual DataPort to be ready..."
for i in $(seq 1 $MAX_RETRIES); do
    if timeout 5 bash -c "cat < /dev/null > /dev/tcp/$DENODO_HOST/$DENODO_PORT" 2>/dev/null; then
        echo "[OK] Denodo is ready"
        break
    fi
    echo "  Waiting... ($i/$MAX_RETRIES)"
    sleep $RETRY_DELAY

    if [ $i -eq $MAX_RETRIES ]; then
        echo "[FAIL] Denodo failed to start"
        exit 1
    fi
done

# Additional delay to ensure Denodo is fully initialized
sleep 10

# Execute VQL files in order
echo ""
echo "Executing VQL initialization scripts..."
SERVER_URI="${DENODO_HOST}:${DENODO_PORT}/admin?${DENODO_USER}@${DENODO_PASSWORD}"

for vql_file in $(ls -1 $INIT_DIR/*.vql 2>/dev/null | sort); do
    if [ -f "$vql_file" ]; then
        filename=$(basename "$vql_file")
        echo "  - Executing $filename..."

        # Execute VQL file using import.sh
        /opt/denodo/bin/import.sh \
            --file "$vql_file" \
            --server "$SERVER_URI" \
            --verbose \
            2>&1 | grep -v "^$" || true

        exit_code=${PIPESTATUS[0]}

        if [ $exit_code -eq 0 ]; then
            echo "    [OK] $filename completed successfully"
        else
            echo "    [WARN] $filename completed with warnings (exit code: $exit_code)"
        fi

        # Brief delay between scripts
        sleep 2
    fi
done

echo ""
echo "=========================================="
echo "Denodo Initialization Complete"
echo "=========================================="
echo "REST API: http://localhost:9090/denodo-restfulws/poc_integration"
echo "Web Panel: http://localhost:9090"
echo ""

exit 0
