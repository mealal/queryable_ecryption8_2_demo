#!/bin/bash
# Denodo VQL Initialization Script
# Runs inside the Denodo container to execute VQL files

DENODO_HOST="localhost"
DENODO_PORT="9999"
DENODO_USER="admin"
DENODO_PASSWORD="admin"
INIT_DIR="/opt/denodo/init"

echo "=========================================="
echo "Denodo VQL Initialization"
echo "=========================================="

# Check if Denodo is ready
echo "Checking Denodo connectivity..."
if ! timeout 5 bash -c "cat < /dev/null > /dev/tcp/$DENODO_HOST/$DENODO_PORT" 2>/dev/null; then
    echo "[ERROR] Denodo is not ready on port $DENODO_PORT"
    exit 1
fi

echo "[OK] Denodo is ready"
echo ""

# Execute VQL files in order
echo "Executing VQL initialization scripts..."
SERVER_URI="${DENODO_HOST}:${DENODO_PORT}/admin?${DENODO_USER}@${DENODO_PASSWORD}"

success_count=0
total_count=0

for vql_file in $(ls -1 $INIT_DIR/*.vql 2>/dev/null | sort); do
    if [ -f "$vql_file" ]; then
        filename=$(basename "$vql_file")
        echo "  - Executing $filename..."
        total_count=$((total_count + 1))

        # Execute VQL file using import.sh
        if /opt/denodo/bin/import.sh \
            --file "$vql_file" \
            --server "$SERVER_URI" \
            2>&1 | grep -q "ERRORS SUMMARY"; then
            echo "    [WARN] $filename completed with errors"
        else
            echo "    [OK] $filename completed successfully"
            success_count=$((success_count + 1))
        fi

        # Brief delay between scripts
        sleep 1
    fi
done

echo ""
echo "=========================================="
echo "Initialization Complete: $success_count/$total_count scripts succeeded"
echo "=========================================="

if [ $success_count -eq $total_count ] && [ $total_count -gt 0 ]; then
    echo "[OK] All VQL scripts executed successfully"
    exit 0
elif [ $success_count -gt 0 ]; then
    echo "[WARN] Some scripts had warnings"
    exit 0
else
    echo "[ERROR] No scripts executed successfully"
    exit 1
fi
