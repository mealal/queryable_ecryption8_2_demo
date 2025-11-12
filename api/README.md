# POC Integration API

FastAPI REST API for MongoDB 8.2 Queryable Encryption + AlloyDB integration with dual-mode support.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start API (runs on port 8000)
python app.py
```

**API:** http://localhost:8000
**Interactive Docs:** http://localhost:8000/docs
**OpenAPI Spec:** http://localhost:8000/openapi.json

---

## Dual-Mode Architecture

All search endpoints support the `?mode=` parameter to control data retrieval:

### **Hybrid Mode** (Default)
- MongoDB: Encrypted search → Returns UUIDs only
- AlloyDB: Fetch full customer data by UUID
- **Use case:** Leveraging AlloyDB's relational features and joins

### **MongoDB-Only Mode**
- MongoDB: Encrypted search → Decrypt ALL fields from MongoDB
- AlloyDB: Not used
- **Use case:** Testing MongoDB 8.2 queryable encryption in isolation

**Example:**
```bash
# Hybrid mode (default)
curl "http://localhost:8000/api/v1/customers/search/email?email=john@example.com"

# MongoDB-only mode
curl "http://localhost:8000/api/v1/customers/search/email?email=john@example.com&mode=mongodb_only"
```

---

## Endpoints

All search endpoints support `?mode=hybrid` or `?mode=mongodb_only`:

### Search Endpoints (Encrypted)
- `GET /api/v1/customers/search/email?email={email}&mode={mode}`
  Email prefix/substring search using MongoDB 8.2 TEXTPREVIEW encryption

- `GET /api/v1/customers/search/name?name={name}&mode={mode}`
  Name substring search using MongoDB 8.2 TEXTPREVIEW encryption

- `GET /api/v1/customers/search/phone?phone={phone}&mode={mode}`
  Phone equality search using MongoDB 8.2 INDEXED encryption

- `GET /api/v1/customers/search/category?category={category}&mode={mode}`
  Category equality search using MongoDB 8.2 INDEXED encryption

- `GET /api/v1/customers/search/status?status={status}&mode={mode}`
  Status equality search using MongoDB 8.2 INDEXED encryption

### Lookup Endpoints
- `GET /api/v1/customers/{id}?mode={mode}`
  Direct customer lookup by UUID

### Health
- `GET /health` - Service health check

---

## MongoDB 8.2 Encryption Algorithms

This API leverages MongoDB 8.2's queryable encryption with three algorithms:

1. **INDEXED** (Equality Queries)
   - Fields: `phone`, `category`, `status`
   - Supports: Exact match queries
   - Example: `?phone=555-1234`

2. **TEXTPREVIEW** (Prefix/Substring Queries)
   - Fields: `email` (prefixPreview), `name` (substringPreview)
   - Supports: Partial text matching
   - Example: `?email=john` matches `john@example.com`

3. **UNINDEXED** (Non-Searchable)
   - 13 fields: address, city, state, zip, country, SSN, DOB, credit card, CVV, registration date, last login, account balance, notes
   - Encrypted at rest, decrypted on retrieval
   - Not searchable via MongoDB queries

---

## Testing

```bash
# Run comprehensive test suite (from project root)
python run_tests.py

# Manual API tests
curl "http://localhost:8000/api/v1/customers/search/email?email=richard.martin1@example.com"
curl "http://localhost:8000/api/v1/customers/search/email?email=richard.martin1@example.com&mode=mongodb_only"
curl "http://localhost:8000/api/v1/customers/search/name?name=Martin"
curl "http://localhost:8000/api/v1/customers/search/phone?phone=555-0001"
curl "http://localhost:8000/health"
```

---

## Docker Deployment

The API runs in a Docker container as part of the full stack:

```bash
# Deploy all services (MongoDB, AlloyDB, API)
python deploy.py start

# API will be available at http://localhost:8000
```

**Container Details:**
- Base: `python:3.11-slim`
- Port: 8000
- Auto-restart: `always`
- Depends on: MongoDB, AlloyDB containers

---

See main [README.md](../README.md) for complete documentation and performance benchmarks.
