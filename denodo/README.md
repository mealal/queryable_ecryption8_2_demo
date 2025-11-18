# Denodo Integration

This directory contains the Denodo Virtual DataPort 9.0 Express integration for the MongoDB Queryable Encryption POC.

---

## Overview

Denodo Virtual DataPort provides a data virtualization layer that connects to both MongoDB (encrypted data) and AlloyDB (full customer data), exposing unified views through REST APIs.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Denodo Virtual DataPort                   │
│                     (Port 9090, 9999)                        │
├──────────────────────┬──────────────────────────────────────┤
│  MongoDB Connector   │      PostgreSQL/AlloyDB Connector    │
│  (Encrypted Data)    │      (Full Customer Data)            │
└──────────┬───────────┴──────────────┬───────────────────────┘
           │                          │
           ▼                          ▼
   ┌──────────────┐          ┌──────────────────┐
   │  MongoDB 8.2 │          │  AlloyDB (PG 15) │
   │  (Encrypted) │          │  (Unencrypted)   │
   └──────────────┘          └──────────────────┘
```

**Denodo's Role:**
- Acts as a virtualization layer over MongoDB + AlloyDB
- Provides unified REST API endpoints
- Handles query routing and data federation
- Subject to Express license limitations

---

## License Limitations

**Denodo Express License (denodo-express-lic-9-202511.lic):**

- **MaxSimultaneousRequests**: 3 concurrent requests
- **MaxRowsPerQuery**: 10,000 rows per query
- **Expiration**: 2026-12-01
- **Product**: Virtual DataPort 9.0 Express

### Impact on Testing

The test suite (`run_tests.py`) tracks these limitations:
- **Concurrent Request Limit**: Enforced via semaphore (max 3 simultaneous)
- **Throttled Requests**: Counted and reported
- **License Violations**: Tracked if limits are exceeded
- **Test Report**: Includes dedicated Denodo License Usage section

---

## Components

### 1. Docker Configuration

**File**: [Dockerfile](Dockerfile)

- Base Image: `denodo/denodovdp:9.0-latest`
- License: Mounted from root directory
- Ports:
  - `9999`: Virtual DataPort Server
  - `9090`: REST API & Web Panel
- Health Check: REST API ping endpoint

### 2. VQL Initialization Scripts

**Directory**: [init/](init/)

Executed in order during deployment:

#### [01-datasources.vql](init/01-datasources.vql)
- Creates `poc_integration` database
- Configures MongoDB data source
- Configures AlloyDB/PostgreSQL data source

#### [02-base-views.vql](init/02-base-views.vql)
- `bv_mongodb_customers`: Base view of MongoDB encrypted collection
- `bv_alloydb_customers`: Base view of AlloyDB customers table

#### [03-derived-views.vql](init/03-derived-views.vql)
Derived views for search operations:
- `dv_search_email_prefix`: Email prefix search
- `dv_search_name_substring`: Name substring search
- `dv_search_phone`: Phone equality search
- `dv_search_category`: Category equality search
- `dv_search_status`: Status equality search
- `dv_get_customer`: Customer lookup by ID

#### [04-rest-webservices.vql](init/04-rest-webservices.vql)
REST web service definitions:
- `email_prefix_search`
- `name_substring_search`
- `phone_search`
- `category_search`
- `status_search`
- `get_customer`

**Connection Pool**: Configured for max 3 concurrent connections (license limit)

### 3. Python Wrapper

**File**: [denodo_wrapper.py](denodo_wrapper.py)

Provides Python interface to Denodo REST APIs:

**Classes:**
- `DenodoLicenseLimiter`: Tracks and enforces license limitations
- `DenodoClient`: REST API client for Denodo services

**Features:**
- Concurrent request limiting (semaphore)
- Automatic throttling detection
- License usage statistics
- API-compatible response formatting

### 4. Initialization Script

**File**: [init_denodo.py](init_denodo.py)

Automated Denodo setup:
- Waits for Denodo service to be ready
- Executes VQL scripts in order
- Validates successful initialization
- Called automatically by `deploy.py`

---

## Deployment

### Automatic Deployment (Recommended)

```bash
# Deploy entire stack including Denodo
python deploy.py start
```

The deployment script will:
1. Start Denodo container
2. Wait for Denodo to be ready (2-3 minutes)
3. Execute all VQL initialization scripts
4. Verify REST API availability

### Manual Denodo Initialization

If automatic initialization fails:

```bash
# Run Denodo initialization manually
python denodo/init_denodo.py
```

### Verify Denodo Status

```bash
# Check if Denodo is running
docker ps | grep poc_denodo

# Check Denodo logs
docker logs poc_denodo

# Test REST API ping
curl -u admin:admin http://localhost:9090/denodo-restfulws/admin/ping
```

---

## REST API Endpoints

**Base URL**: `http://localhost:9090/denodo-restfulws/poc_integration`

**Authentication**: Basic Auth (admin:admin)

### Available Endpoints

#### 1. Email Prefix Search
```bash
curl -u admin:admin \
  "http://localhost:9090/denodo-restfulws/poc_integration/email_prefix_search?prefix=john"
```

#### 2. Name Substring Search
```bash
curl -u admin:admin \
  "http://localhost:9090/denodo-restfulws/poc_integration/name_substring_search?substring=Smith"
```

#### 3. Phone Search
```bash
curl -u admin:admin \
  "http://localhost:9090/denodo-restfulws/poc_integration/phone_search?phone=%2B1-555-0101"
```

#### 4. Category Search
```bash
curl -u admin:admin \
  "http://localhost:9090/denodo-restfulws/poc_integration/category_search?category=premium"
```

#### 5. Status Search
```bash
curl -u admin:admin \
  "http://localhost:9090/denodo-restfulws/poc_integration/status_search?status=active"
```

#### 6. Get Customer by ID
```bash
curl -u admin:admin \
  "http://localhost:9090/denodo-restfulws/poc_integration/get_customer?customer_id=550e8400-e29b-41d4-a716-446655440001"
```

---

## Testing

### Run Tests with Denodo Mode

```bash
# Full test suite including Denodo tests
python run_tests.py

# Quick tests only (includes Denodo functional tests)
python run_tests.py --quick

# Performance tests (includes Denodo benchmarks)
python run_tests.py --performance --iterations 100
```

### Denodo Test Coverage

**Functional Tests (10 tests - dual data source):**
1. Phone Search (Denodo-AlloyDB)
2. Category Search (Denodo-AlloyDB)
3. Status Search (Denodo-AlloyDB)
4. Email Prefix Search (Denodo-AlloyDB)
5. Name Substring Search (Denodo-AlloyDB)
6. Phone Search (Denodo-MongoDB)
7. Category Search (Denodo-MongoDB)
8. Status Search (Denodo-MongoDB)
9. Email Prefix Search (Denodo-MongoDB)
10. Name Substring Search (Denodo-MongoDB)

**Performance Benchmarks:**
- Same 10 operations (5 × 2 data sources) with 100 iterations each
- License limitation tracking
- Throttling detection
- AlloyDB vs MongoDB performance comparison

### Test Report

After running tests, open `test_report.html` to view:

**Denodo License Usage Section:**
- Total Requests
- Max Concurrent Requests
- Throttled Requests
- License Violations
- Max Rows Per Query limit

---

## Web Panel Access

**URL**: http://localhost:9090

**Credentials**:
- Username: `admin`
- Password: `admin`

**Features:**
- VQL Editor
- Data Source Management
- View Designer
- Query Execution
- REST API Configuration

---

## Troubleshooting

### Denodo Container Not Starting

```bash
# Check container status
docker ps -a | grep denodo

# View logs
docker logs poc_denodo

# Restart container
docker restart poc_denodo
```

### VQL Initialization Failed

```bash
# Retry initialization
python denodo/init_denodo.py

# Check individual VQL files
cat denodo/init/01-datasources.vql
```

### REST API Not Responding

```bash
# Wait for Denodo to fully start (may take 2-3 minutes)
curl -u admin:admin http://localhost:9090/denodo-restfulws/admin/ping

# Check if port 9090 is accessible
netstat -an | grep 9090  # Linux/Mac
netstat -an | findstr 9090  # Windows
```

### License Exceeded Errors

**Symptoms:**
- Throttled requests in test report
- Concurrent request limit exceeded

**Solutions:**
- Run fewer tests concurrently
- Use `--iterations` flag with lower value
- Tests automatically enforce semaphore limit

---

## Performance Comparison

### Expected Query Times

**Denodo Mode** (AlloyDB-only via Denodo):
- Phone Search: ~20-30ms
- Email Prefix: ~25-35ms
- Name Substring: ~20-30ms

**vs. Hybrid Mode** (MongoDB + AlloyDB):
- Similar performance for non-encrypted fields
- Faster for direct AlloyDB access
- No encryption overhead

**vs. MongoDB-Only Mode**:
- Denodo may be slower due to virtualization layer
- No client-side decryption overhead
- Trade-off: Unified data access vs. performance

---

## Architecture Benefits

### Why Use Denodo?

1. **Data Virtualization**: Single API for multiple data sources
2. **Query Federation**: Join data across MongoDB and AlloyDB
3. **Security Layer**: Centralized access control
4. **Abstraction**: Hide complexity from clients
5. **Flexibility**: Easy to add new data sources

### Use Cases

- **Analytics**: Join encrypted search results with AlloyDB analytics
- **Reporting**: Unified reporting across multiple sources
- **Data Governance**: Centralized security and audit
- **Legacy Integration**: Connect old systems to modern data sources

---

## Next Steps

1. **Production Deployment**:
   - Upgrade to full Denodo license
   - Configure external KMS integration
   - Enable HTTPS/TLS
   - Set up authentication (LDAP/OAuth)

2. **Advanced Features**:
   - Create aggregate views
   - Implement caching strategies
   - Add data masking rules
   - Configure incremental refreshes

3. **Monitoring**:
   - Enable Denodo metrics
   - Set up alerting for license limits
   - Track query performance
   - Monitor connection pool usage

---

## Files Reference

```
denodo/
├── README.md                  # This file
├── Dockerfile                 # Denodo container definition
├── denodo_wrapper.py          # Python REST API client
├── init_denodo.py             # Initialization script
└── init/                      # VQL scripts
    ├── 01-datasources.vql     # Data source configuration
    ├── 02-base-views.vql      # Base views
    ├── 03-derived-views.vql   # Derived/search views
    └── 04-rest-webservices.vql # REST API definitions
```

---

## Support

- **Denodo Documentation**: https://community.denodo.com/docs/html/browse/latest
- **REST API Guide**: https://community.denodo.com/docs/html/browse/latest/vdp/restfulws/overview
- **License Information**: See `denodo-express-lic-9-202511.lic`
- **POC Issues**: Check main [README.md](../README.md) for general troubleshooting

---

**Version:** 1.0
**Denodo Version:** 9.0 Express
**License Expiration:** 2026-12-01
**Integration Status:** ✅ Fully Integrated
