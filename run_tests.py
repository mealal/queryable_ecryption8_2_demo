#!/usr/bin/env python3
"""
POC Testing Script with Real-time Metrics
Executes comprehensive tests and generates final report

Usage:
    python run_tests.py                    # Run all tests
    python run_tests.py --quick            # Run quick tests only
    python run_tests.py --performance      # Run performance tests only
    python run_tests.py --report test_report.html  # Custom report name
"""

# ============================================================================
# IMPORTS
# ============================================================================

import requests
import time
import argparse
import sys
import statistics
import random
import re
import subprocess
from datetime import datetime
from typing import Dict, List


# ============================================================================
# CONFIGURATION
# ============================================================================

class Colors:
    """ANSI color codes for console output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# API Configuration
API_BASE_URL = "http://localhost:8000"

# Test modes: hybrid, mongodb_only
TEST_MODES = ["hybrid", "mongodb_only"]

# ============================================================================
# DATA FETCHING FUNCTIONS
# ============================================================================

# Fetch real test data from API
def get_test_data():
    """Fetch real customer values from API for testing

    This is NOT part of performance testing - it's just to get valid test data.
    Uses the category search endpoint to get data from MongoDB (not AlloyDB tier endpoint).
    """
    try:
        # Fetch one customer using category search (searches MongoDB encrypted data)
        # This ensures we get test data that actually exists in MongoDB
        response = requests.get(
            f"{API_BASE_URL}/api/v1/customers/search/category",
            params={"category": "retail", "limit": 1},
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('success') and data.get('data') and len(data['data']) > 0:
                customer = data['data'][0]
                return {
                    "id": customer.get('customer_id'),
                    "name": customer.get('full_name'),
                    "email": customer.get('email'),
                    "phone": customer.get('phone'),
                    "tier": customer.get('tier', 'gold'),
                    "category": customer.get('category', 'retail'),
                    "status": customer.get('status', 'active')
                }
    except Exception as e:
        print(f"Warning: Could not fetch test data from API: {e}")
        return None

def get_test_data_pool(sample_size=200):
    """Fetch a pool of test values for performance testing

    Args:
        sample_size: Number of samples to fetch (default: 200)

    Returns:
        Dictionary with lists of values for each field type
    """
    try:
        # Use category endpoint to fetch multiple customers (retail category typically has many)
        response = requests.get(
            f"{API_BASE_URL}/api/v1/customers/search/category",
            params={"category": "retail", "limit": min(sample_size, 10000)},
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('success') and data.get('data'):
                customers = data['data']

                pool = {
                    "names": [],
                    "emails": [],
                    "phones": [],
                    "categories": [],
                    "statuses": [],
                    "email_prefixes": [],
                    "name_substrings": []
                }

                for customer in customers:
                    full_name = customer.get('full_name')
                    email = customer.get('email')
                    phone = customer.get('phone')
                    category = customer.get('category')
                    status = customer.get('status')

                    if full_name:
                        pool["names"].append(full_name)
                    if email:
                        pool["emails"].append(email)
                    if phone:
                        pool["phones"].append(phone)
                    if category:
                        pool["categories"].append(category)
                    if status:
                        pool["statuses"].append(status)

                    # Extract prefixes and substrings
                    if email:
                        pool["email_prefixes"].append(email.split('@')[0][:4])
                    if full_name and ' ' in full_name:
                        pool["name_substrings"].append(full_name.split()[0][:10] if len(full_name.split()[0]) > 10 else full_name.split()[0])

                return pool
    except Exception as e:
        print(f"Warning: Could not fetch test data pool from API: {e}")
        return None

# Try to get real test data, otherwise use defaults
_test_data = get_test_data()
if _test_data:
    TEST_CUSTOMER_ID = _test_data["id"]
    TEST_NAME = _test_data["name"]
    TEST_EMAIL = _test_data["email"]
    TEST_PHONE = _test_data["phone"]
    TEST_TIER = _test_data["tier"]
    TEST_CATEGORY = _test_data["category"]
    TEST_STATUS = _test_data["status"]
else:
    # Fallback to defaults
    TEST_EMAIL = "richard.martin1@example.com"
    TEST_NAME = "Richard Martin"
    TEST_PHONE = "+1-555-2879"
    TEST_CUSTOMER_ID = "3c05f00d-3161-4d2c-83c0-5208b2fa2be4"
    TEST_TIER = "gold"
    TEST_CATEGORY = "retail"  # Options: retail, enterprise, government
    TEST_STATUS = "active"    # Options: active, inactive, pending

# ============================================================================
# METRICS COLLECTION
# ============================================================================

class TestMetrics:
    """
    Track test metrics in real-time

    This class collects all test results and performance metrics during test execution.
    Data is later used to generate the HTML report with:
    - Test summary (pass/fail counts, pass rate)
    - Individual test results (name, status, duration, timestamp)
    - Performance metrics (avg, median, stddev by mode)
    - Mode comparison tables (Hybrid vs MongoDB-Only)

    Key Methods:
    - add_result(): Store individual test result with encryption type
    - add_performance_data(): Store performance metrics for report aggregation
    - generate_html_report(): Generate custom HTML report from collected data
    """

    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.total_duration = 0
        self.total_benchmark_duration = 0
        self.test_results = []           # List of all test results
        self.performance_data = []       # List of performance metrics with encryption types

    def add_result(self, test_name, passed, duration, details=None, encryption_type=None):
        """Add test result"""
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
        else:
            self.tests_failed += 1

        self.total_duration += duration

        self.test_results.append({
            "name": test_name,
            "passed": passed,
            "duration": duration,
            "details": details or {},
            "encryption_type": encryption_type,
            "timestamp": datetime.now().isoformat()
        })

    def add_performance_data(self, operation, metrics, encryption_type=None):
        """Add performance metrics"""
        self.performance_data.append({
            "operation": operation,
            "metrics": metrics,
            "encryption_type": encryption_type,
            "timestamp": datetime.now().isoformat()
        })

    def get_summary(self):
        """Get test summary"""
        pass_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0

        return {
            "total_tests": self.tests_run,
            "passed": self.tests_passed,
            "failed": self.tests_failed,
            "pass_rate": pass_rate,
            "total_duration": self.total_duration
        }

# ============================================================================
# CONSOLE OUTPUT HELPERS
# ============================================================================

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text:^80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")

def print_test_start(test_name):
    print(f"{Colors.BOLD}TEST: {test_name}{Colors.ENDC}")

def print_success(text):
    print(f"{Colors.OKGREEN}[PASS] {text}{Colors.ENDC}")

def print_error(text):
    print(f"{Colors.FAIL}[FAIL] {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.OKCYAN}[INFO] {text}{Colors.ENDC}")

def print_warning(text):
    print(f"{Colors.WARNING}[WARN] {text}{Colors.ENDC}")

def print_metric(label, value, unit=""):
    """Print real-time metric"""
    print(f"  {Colors.OKCYAN}{label:.<40} {value:>10.2f} {unit}{Colors.ENDC}")

# ============================================================================
# DATA VALIDATION
# ============================================================================

def build_api_url_and_params(field, query_type, value, mode):
    """Build API URL and parameters based on query type

    Args:
        field: Field name to search (email, name, phone, category, status)
        query_type: Type of query ("equality", "prefix", "suffix", "substring")
        value: Search value
        mode: Search mode ("hybrid" or "mongodb_only")

    Returns:
        Tuple of (url, params dict)

    Raises:
        ValueError: If query_type is not supported
    """
    base_url = f"{API_BASE_URL}/api/v1/customers/search/{field}"

    if query_type == "equality":
        return base_url, {field: value, "mode": mode}
    elif query_type == "prefix":
        return f"{base_url}/prefix", {"prefix": value, "mode": mode}
    elif query_type == "suffix":
        return f"{base_url}/suffix", {"suffix": value, "mode": mode}
    elif query_type == "substring":
        return f"{base_url}/substring", {"substring": value, "mode": mode}
    else:
        raise ValueError(f"Unknown query_type: {query_type}")

def get_test_value_from_pool(test_pool, pool_key, iteration, iterations, test_name, fallback_values):
    """Get test value from pool with fallback and special processing

    Args:
        test_pool: Dictionary of test value pools
        pool_key: Key to access in test_pool
        iteration: Current iteration number
        iterations: Total iterations
        test_name: Name of the test (for special processing)
        fallback_values: Dictionary of fallback values by field type

    Returns:
        Test value string
    """
    # Try to get value from pool
    if test_pool and pool_key in test_pool and test_pool[pool_key]:
        # If pool is big enough, use sequential values; otherwise pick randomly
        if len(test_pool[pool_key]) >= iterations:
            test_value = test_pool[pool_key][iteration % len(test_pool[pool_key])]
        else:
            # Pool too small, pick randomly
            test_value = random.choice(test_pool[pool_key])

        # Special processing for certain test types
        if "Last Name" in test_name and ' ' in test_value:
            return test_value.split()[-1][:10]  # Extract last name substring
        elif "Partial Match" in test_name and len(test_value) > 4:
            return test_value[:4]  # Take first 4 chars for partial match
        else:
            return test_value

    # Fallback to static values
    if "Phone" in test_name:
        return fallback_values.get("phone", TEST_PHONE)
    elif "Email" in test_name and "Username" in test_name:
        return fallback_values.get("email", TEST_EMAIL).split('@')[0][:4]
    elif "Email" in test_name:
        return fallback_values.get("email", TEST_EMAIL)
    elif "Category" in test_name:
        return fallback_values.get("category", TEST_CATEGORY)
    elif "Status" in test_name:
        return fallback_values.get("status", TEST_STATUS)
    else:
        return fallback_values.get("name", TEST_NAME)[:10]

def validate_result_count(results_count, expected_count, test_name):
    """
    Validate result count against expected count with standardized logic.

    Returns: (passed, should_count_performance, status_message)

    Logic:
    1. Exact match (results_count == expected_count): PASS, count performance
    2. Zero results: FAIL, don't count performance
    3. More results than expected: FAIL, don't count performance
    4. Fewer results than expected (but > 0): PASS with NA status, don't count performance
    """
    if expected_count is None:
        # No limit specified, any non-zero result is good
        if results_count > 0:
            return True, True, None
        else:
            return False, False, "No results found"

    if results_count == expected_count:
        # Exact match - perfect
        return True, True, None
    elif results_count == 0:
        # No results - fail
        return False, False, f"Expected {expected_count} results, got 0"
    elif results_count > expected_count:
        # More than expected - API limit not working, fail
        return False, False, f"Expected {expected_count} results, got {results_count} (API limit not working)"
    else:
        # Less than expected but > 0 - insufficient data, pass with NA
        print_info(f"Expected {expected_count} results, got {results_count} (insufficient test data - NA)")
        return True, False, "NA"

def validate_customer_response(customer, mode="hybrid"):
    """Validate that customer response contains all expected fields"""
    required_fields = [
        "customer_id",
        "full_name",
        "email",
        "phone",
        "address",
        "preferences",
        "tier",
        "loyalty_points",
        "lifetime_value",
        "last_purchase_date"
    ]

    missing_fields = []
    empty_fields = []

    for field in required_fields:
        if field not in customer:
            missing_fields.append(field)
        elif customer[field] is None or customer[field] == "":
            empty_fields.append(field)

    # Both modes should return identical data - no mode-specific field differences

    # Validate address object
    if "address" in customer and customer["address"]:
        if not isinstance(customer["address"], dict):
            print_error(f"Address is not an object: {type(customer['address'])}")
            return False
        address_fields = ["street", "city", "state", "zip_code"]
        for addr_field in address_fields:
            if addr_field not in customer["address"]:
                missing_fields.append(f"address.{addr_field}")

    # Validate preferences object
    if "preferences" in customer and customer["preferences"]:
        if not isinstance(customer["preferences"], dict):
            print_error(f"Preferences is not an object: {type(customer['preferences'])}")
            return False

    if missing_fields:
        print_error(f"Missing fields: {', '.join(missing_fields)}")
        return False

    if empty_fields:
        print_error(f"Empty/null fields: {', '.join(empty_fields)}")
        return False

    return True

# ============================================================================
# TEST FUNCTIONS
# ============================================================================

def test_health_check(metrics):
    """Test 1: Health Check"""
    print_test_start("Health Check")

    start = time.time()
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        duration = time.time() - start

        data = response.json()

        if response.status_code == 200 and data.get('status') == 'healthy':
            print_success("API is healthy")
            print_info(f"MongoDB: {data.get('mongodb')}")
            print_info(f"AlloyDB: {data.get('alloydb')}")
            print_info(f"Encryption Keys: {data.get('encryption_keys')}")
            print_metric("Response Time", duration * 1000, "ms")

            metrics.add_result("Health Check", True, duration, data)
            return True
        else:
            print_error("API is not healthy")
            metrics.add_result("Health Check", False, duration, data)
            return False

    except Exception as e:
        duration = time.time() - start
        print_error(f"Health check failed: {e}")
        metrics.add_result("Health Check", False, duration, {"error": str(e)})
        return False


# Unified Test Execution Function
# This function replaces test_encrypted_search, test_prefix_search, test_suffix_search, test_substring_search

def execute_test(metrics, test_config):
    """
    Unified test execution function - handles all query types with the same logic.

    Args:
        metrics: TestMetrics instance for recording results
        test_config: Dictionary containing test configuration:
            {
                'name': str,              # Test name
                'field': str,             # Field to search (email, name, phone, category, status)
                'value': str,             # Search value
                'query_type': str,        # 'equality', 'prefix', 'suffix', or 'substring'
                'mode': str,              # 'hybrid' or 'mongodb_only'
                'limit': int/None,        # Result limit (None for no limit)
                'encryption_type': str    # 'equality', 'prefix', or 'substring' for performance tracking
            }

    Returns:
        bool: True if test passed, False otherwise
    """
    test_name = test_config['name']
    field = test_config['field']
    value = test_config['value']
    query_type = test_config['query_type']
    mode = test_config.get('mode', 'hybrid')
    limit = test_config.get('limit')
    encryption_type = test_config.get('encryption_type', query_type)

    print_test_start(test_name)

    start_time = time.time()
    try:
        # Build URL based on query type
        if query_type == 'equality':
            url = f"{API_BASE_URL}/api/v1/customers/search/{field}"
            params = {field: value, "mode": mode}
        elif query_type == 'prefix':
            url = f"{API_BASE_URL}/api/v1/customers/search/{field}/prefix"
            params = {field.replace("_", ""): value} if "_" in field else {"prefix": value}
            params["mode"] = mode
        elif query_type == 'suffix':
            url = f"{API_BASE_URL}/api/v1/customers/search/{field}/suffix"
            params = {field.replace("_", ""): value} if "_" in field else {"suffix": value}
            params["mode"] = mode
        elif query_type == 'substring':
            url = f"{API_BASE_URL}/api/v1/customers/search/{field}/substring"
            params = {field.replace("_", ""): value} if "_" in field else {"substring": value}
            params["mode"] = mode
        else:
            raise ValueError(f"Unknown query_type: {query_type}")

        # Add limit if specified
        if limit is not None:
            params["limit"] = limit

        # Execute request
        response = requests.get(url, params=params, timeout=30)
        duration = time.time() - start_time

        # Check HTTP status
        if response.status_code != 200:
            print_error(f"Request failed: {response.status_code}")
            metrics.add_result(test_name, False, duration)
            return False

        # Parse response
        data = response.json()
        if not data['success']:
            print_error("API returned success=false")
            metrics.add_result(test_name, False, duration)
            return False

        # Extract metrics and results
        test_metrics = data['metrics']
        results_count = len(data['data'])
        api_total_time = test_metrics['total_ms']
        client_time = duration * 1000

        # Validate result count using centralized logic
        passed, should_count_perf, status_msg = validate_result_count(results_count, limit, test_name)

        # Handle zero results - always fail
        if results_count == 0:
            print_error(f"Query executed but returned 0 results - expected to find data")
            print_metric("API Total", api_total_time, "ms")
            print_metric("Client Time", client_time, "ms")
            metrics.add_result(test_name, False, duration, {
                "metrics": test_metrics,
                "mode": mode,
                "results_count": 0,
                "expected_count": limit,
                "error": "No results found"
            })
            return False

        # Display results
        customer = data['data'][0]
        print_success(f"Found customer: {customer.get('full_name')}")
        print_metric("Results Returned", results_count, "records")

        # Display timing metrics based on mode
        if mode == "hybrid":
            mongodb_time = test_metrics['mongodb_search_ms']
            alloydb_time = test_metrics.get('alloydb_fetch_ms', 0)
            print_metric("MongoDB Search", mongodb_time, "ms")
            print_metric("AlloyDB Fetch", alloydb_time, "ms")
        else:  # mongodb_only
            mongodb_time = test_metrics.get('mongodb_decrypt_ms', 0)
            print_metric("MongoDB Decrypt", mongodb_time, "ms")

        print_metric("API Total", api_total_time, "ms")
        print_metric("Client Total", client_time, "ms")

        # Validate customer response
        if not validate_customer_response(customer, mode):
            print_error("Customer data validation failed")
            metrics.add_result(test_name, False, duration, {
                "customer": customer,
                "metrics": test_metrics,
                "mode": mode,
                "results_count": results_count,
                "expected_count": limit,
                "error": "Validation failed"
            })
            return False

        print_success("Customer data validation passed")

        # Record result - test PASSES even with NA status (insufficient data)
        test_details = {
            "customer": customer,
            "metrics": test_metrics,
            "mode": mode,
            "results_count": results_count,
            "expected_count": limit
        }
        if status_msg:
            test_details["status"] = status_msg

        # Always mark test as PASSED if we got here (even with NA status)
        metrics.add_result(test_name, True, duration, test_details)

        # Only add performance data if should_count_perf is True (excludes NA cases)
        if should_count_perf:
            # Build performance data name based on encryption type
            perf_name = f"{test_name}" if encryption_type in test_name else f"Encrypted {field.title()} Search ({mode})"
            metrics.add_performance_data(perf_name, test_metrics)

        return True

    except Exception as e:
        duration = time.time() - start_time
        print_error(f"Test failed: {e}")
        metrics.add_result(test_name, False, duration, {"error": str(e)})
        return False


# Wrapper functions for backwards compatibility
def test_encrypted_search(metrics, field, value, test_name, mode="hybrid", limit=None):
    """Test encrypted equality search - wrapper for execute_test"""
    return execute_test(metrics, {
        'name': test_name,
        'field': field,
        'value': value,
        'query_type': 'equality',
        'mode': mode,
        'limit': limit,
        'encryption_type': 'equality'
    })


def test_prefix_search(metrics, field, prefix, test_name, mode="hybrid", limit=None):
    """Test encrypted prefix search - wrapper for execute_test"""
    return execute_test(metrics, {
        'name': test_name,
        'field': field,
        'value': prefix,
        'query_type': 'prefix',
        'mode': mode,
        'limit': limit,
        'encryption_type': 'prefix'
    })


def test_suffix_search(metrics, field, suffix, test_name, mode="hybrid"):
    """Test encrypted suffix search - wrapper for execute_test"""
    return execute_test(metrics, {
        'name': test_name,
        'field': field,
        'value': suffix,
        'query_type': 'suffix',
        'mode': mode,
        'limit': None,
        'encryption_type': 'suffix'
    })


def test_substring_search(metrics, field, substring, test_name, mode="hybrid", limit=None):
    """Test encrypted substring search - wrapper for execute_test"""
    return execute_test(metrics, {
        'name': test_name,
        'field': field,
        'value': substring,
        'query_type': 'substring',
        'mode': mode,
        'limit': limit,
        'encryption_type': 'substring'
    })

def run_performance_tests(metrics, iterations=10):
    """Run performance tests with multiple iterations for all encrypted and AlloyDB operations

    Uses different query values for each iteration to better simulate real-world usage.
    """
    print_header("Performance Testing")
    print_info(f"Running {iterations} iterations per test...")

    # Fetch sample pool for varied test data
    sample_size = max(iterations * 2, 200)  # Fetch at least twice the iterations, minimum 200
    print_info(f"Fetching sample pool of {sample_size} test values...")
    test_pool = get_test_data_pool(sample_size)

    if not test_pool:
        print_error("Failed to fetch test data pool. Using static values as fallback.")
        test_pool = None
    else:
        print_success(f"Loaded test pool: {len(test_pool['phones'])} phones, {len(test_pool['emails'])} emails, {len(test_pool['names'])} names")

    # Define all tests: (name, endpoint_type, field, query_type, param_name, pool_key, mode)
    # pool_key: the key in test_pool to get values from
    base_tests = [
        # Equality searches (phone, category, status)
        ("Phone Equality Search", "search", "phone", "equality", "phone", "phones"),
        ("Category Equality Search", "search", "category", "equality", "category", "categories"),
        ("Status Equality Search", "search", "status", "equality", "status", "statuses"),

        # Prefix searches (email) - parameter name is always "prefix"
        ("Email Exact Match via Prefix", "search", "email", "prefix", "prefix", "emails"),
        ("Email Prefix Search - Username", "search", "email", "prefix", "prefix", "email_prefixes"),

        # Substring searches (name) - parameter name is always "substring"
        ("Encrypted Name Search", "search", "name", "substring", "substring", "name_substrings"),
        ("Name Substring - First Name", "search", "name", "substring", "substring", "name_substrings"),
        ("Name Substring - Last Name", "search", "name", "substring", "substring", "names"),  # Use full names, extract last name
        ("Name Substring - Partial Match", "search", "name", "substring", "substring", "name_substrings")
    ]

    # Duplicate tests for both modes
    tests = []
    for test_name, endpoint_type, field, query_type, param_name, pool_key in base_tests:
        # Add hybrid mode version
        tests.append((f"{test_name} (Hybrid)", endpoint_type, field, query_type, param_name, pool_key, "hybrid"))
        # Add mongodb_only mode version
        tests.append((f"{test_name} (MongoDB-Only)", endpoint_type, field, query_type, param_name, pool_key, "mongodb_only"))

    results = {}

    for test_name, endpoint_type, field, query_type, param_name, pool_key, mode in tests:
        print(f"\n{Colors.BOLD}{test_name}:{Colors.ENDC}")
        times = []

        # Prepare fallback values for get_test_value_from_pool
        fallback_values = {
            "phone": TEST_PHONE,
            "email": TEST_EMAIL,
            "category": TEST_CATEGORY,
            "status": TEST_STATUS,
            "name": TEST_NAME
        }

        for i in range(iterations):
            # Add small delay between iterations to prevent MongoDB driver overload
            # This is especially important for MongoDB-only mode with high iteration counts
            if i > 0:
                time.sleep(0.05)  # 50ms delay between iterations

            start = time.time()

            try:
                # Get test value using helper function
                test_value = get_test_value_from_pool(
                    test_pool, pool_key, i, iterations, test_name, fallback_values
                )

                # Build URL and params using helper function
                url, params = build_api_url_and_params(field, query_type, test_value, mode)

                # Execute request
                response = requests.get(url, params=params, timeout=10)
                duration = (time.time() - start) * 1000

                if response.status_code == 200:
                    times.append(duration)
                    print(f"  Iteration {i+1:2d}: {duration:6.2f} ms")
                else:
                    print(f"  Iteration {i+1:2d}: FAILED (HTTP {response.status_code})")

            except Exception as e:
                print(f"  Iteration {i+1:2d}: ERROR - {e}")

        if times:
            avg_time = statistics.mean(times)
            min_time = min(times)
            max_time = max(times)
            median_time = statistics.median(times)
            stddev = statistics.stdev(times) if len(times) > 1 else 0

            print(f"\n  {Colors.OKGREEN}Statistics:{Colors.ENDC}")
            print_metric("Average", avg_time, "ms")
            print_metric("Median", median_time, "ms")
            print_metric("Min", min_time, "ms")
            print_metric("Max", max_time, "ms")
            print_metric("Std Dev", stddev, "ms")

            results[test_name] = {
                "average": avg_time,
                "median": median_time,
                "min": min_time,
                "max": max_time,
                "stddev": stddev,
                "samples": len(times),
                "mode": mode
            }

            # Track total benchmark duration
            metrics.total_benchmark_duration += sum(times) / 1000  # Convert ms to seconds

            metrics.add_performance_data(test_name, results[test_name], encryption_type=query_type)
        else:
            print(f"\n  {Colors.FAIL}No successful iterations!{Colors.ENDC}")

    return results

# ============================================================================
# HTML REPORT GENERATION
# ============================================================================

def generate_html_report(metrics, perf_results, output_file, data_stats=None, iterations=None):
    """Generate HTML test report"""
    print_info(f"Generating HTML report: {output_file}")

    summary = metrics.get_summary()

    # Add data statistics section
    data_stats_html = ""
    if data_stats:
        data_stats_html = f"""
        <div class="metric-card">
            <div class="metric-label">MongoDB Records</div>
            <div class="metric-value">{data_stats.get('mongodb_count', 0):,}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Encryption Keys</div>
            <div class="metric-value">{data_stats.get('encryption_keys', 0)}</div>
        </div>
        """

    # Add iterations information if available
    iterations_html = ""
    if iterations:
        iterations_html = f"""
        <div class="metric-card">
            <div class="metric-label">Test Iterations</div>
            <div class="metric-value">{iterations}</div>
        </div>
        """


    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>POC Test Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #666;
            margin-top: 30px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .metric-card {{
            background: #f9f9f9;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #4CAF50;
        }}
        .metric-card.failed {{
            border-left-color: #f44336;
        }}
        .metric-label {{
            font-size: 14px;
            color: #666;
            text-transform: uppercase;
        }}
        .metric-value {{
            font-size: 32px;
            font-weight: bold;
            color: #333;
            margin-top: 10px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: #4CAF50;
            color: white;
        }}
        tr:hover {{
            background: #f5f5f5;
        }}
        .passed {{
            color: #4CAF50;
            font-weight: bold;
        }}
        .failed {{
            color: #f44336;
            font-weight: bold;
        }}
        .warning {{
            background: #fff3cd !important;
            border: 2px solid #ffc107;
        }}
        .warning .metric-value {{
            color: #ff9800;
        }}
        .note {{
            background: #e7f3ff;
            border-left: 4px solid #2196F3;
            padding: 15px;
            margin-top: 20px;
            font-size: 14px;
        }}
        .perf-chart {{
            margin: 20px 0;
        }}
        .timestamp {{
            color: #999;
            font-size: 12px;
        }}
        .encryption-badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .badge-equality {{
            background: #e3f2fd;
            color: #1976d2;
        }}
        .badge-prefix {{
            background: #f3e5f5;
            color: #7b1fa2;
        }}
        .badge-substring {{
            background: #fff3e0;
            color: #e65100;
        }}
        .badge-none {{
            background: #f5f5f5;
            color: #666;
        }}
        .comparison-table {{
            margin-bottom: 20px;
        }}
        .comparison-table td:first-child {{
            text-align: left;
        }}
        h3 {{
            color: #555;
            margin-top: 25px;
            margin-bottom: 10px;
            font-size: 18px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>POC Test Report</h1>
        <p class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

        <h2>Test Summary</h2>
        <div class="summary">
            <div class="metric-card">
                <div class="metric-label">Total Tests</div>
                <div class="metric-value">{summary['total_tests']}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Passed</div>
                <div class="metric-value passed">{summary['passed']}</div>
            </div>
            <div class="metric-card {'failed' if summary['failed'] > 0 else ''}">
                <div class="metric-label">Failed</div>
                <div class="metric-value failed">{summary['failed']}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Pass Rate</div>
                <div class="metric-value">{summary['pass_rate']:.1f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Benchmark Duration</div>
                <div class="metric-value">{metrics.total_benchmark_duration:.2f}s</div>
            </div>
            {iterations_html}
            {data_stats_html}
        </div>


        <h2>Test Results</h2>
        <table>
            <thead>
                <tr>
                    <th>Test Name</th>
                    <th>Status</th>
                    <th>Duration (ms)</th>
                    <th>Timestamp</th>
                </tr>
            </thead>
            <tbody>
    """

    for result in metrics.test_results:
        status_class = "passed" if result['passed'] else "failed"
        status_text = "[PASS]" if result['passed'] else "[FAIL]"

        html += f"""
                <tr>
                    <td>{result['name']}</td>
                    <td class="{status_class}">{status_text}</td>
                    <td>{result['duration']*1000:.2f}</td>
                    <td class="timestamp">{result['timestamp']}</td>
                </tr>
        """

    html += """
            </tbody>
        </table>
    """

    # Mode Comparison by Result Set Size - Always generate if we have result-size test data
    # Build test data from all test results (include ALL tests, even with NA/insufficient data)
    all_tests = {}
    for result in metrics.test_results:
        test_name = result.get('name', '')
        # Skip health check and other non-search tests
        if 'Health Check' in test_name:
            continue

        # Extract base name and mode
        base_name = test_name.replace(" (Hybrid)", "").replace(" (MongoDB-Only)", "")
        mode = 'Hybrid' if '(Hybrid)' in test_name else 'MongoDB-Only'

        # Get timing data and test status
        test_details = result.get('details', {})
        test_metrics = test_details.get('metrics', {})
        total_time = test_metrics.get('total_ms', 0)

        # Get test status to check if it has valid data
        test_passed = result.get('passed', False)
        test_status = test_details.get('status', None)
        results_count = test_details.get('results_count', None)
        expected_count = test_details.get('expected_count', None)

        # Include ALL tests for comparison table, but only store timing if valid
        # This ensures all 9 tests appear in the table, with "-" for tests without data
        if base_name not in all_tests:
            all_tests[base_name] = {}

        # Only store timing if test passed AND has valid data
        if test_passed and test_status != "NA" and (expected_count is None or results_count == expected_count):
            all_tests[base_name][mode] = total_time
        else:
            # Store None to indicate no valid data (will show as "-" in table)
            all_tests[base_name][mode] = None

    # Performance Metrics section
    html += """
        <h2>Performance Metrics</h2>
    """

    if perf_results:
        html += """
        <table>
            <thead>
                <tr>
                    <th rowspan="2">Operation</th>
                    <th rowspan="2">Encryption Type</th>
                    <th colspan="3">Hybrid Mode</th>
                    <th colspan="3">MongoDB-Only Mode</th>
                </tr>
                <tr>
                    <th>Avg (ms)</th>
                    <th>Median (ms)</th>
                    <th>Std Dev</th>
                    <th>Avg (ms)</th>
                    <th>Median (ms)</th>
                    <th>Std Dev</th>
                </tr>
            </thead>
            <tbody>
        """

        # Build encryption type lookup from performance_data
        encryption_type_map = {}
        for perf_data in metrics.performance_data:
            encryption_type_map[perf_data['operation']] = perf_data.get('encryption_type')

        # Group by base operation name
        grouped_results = {}
        for operation, stats in perf_results.items():
            # Extract base name and mode
            base_name = operation.replace(" (Hybrid)", "").replace(" (MongoDB-Only)", "")
            mode = 'hybrid' if '(Hybrid)' in operation else 'mongodb_only'

            if base_name not in grouped_results:
                grouped_results[base_name] = {'hybrid': None, 'mongodb_only': None}

            grouped_results[base_name][mode] = stats

        # Generate grouped rows
        for base_name in sorted(grouped_results.keys()):
            modes_data = grouped_results[base_name]
            hybrid_stats = modes_data.get('hybrid')
            mongo_stats = modes_data.get('mongodb_only')

            # Get encryption type (use first available operation)
            operation_with_mode = f"{base_name} (Hybrid)" if hybrid_stats else f"{base_name} (MongoDB-Only)"
            encryption_type = encryption_type_map.get(operation_with_mode, 'none')

            # Generate badge HTML
            if encryption_type and encryption_type != 'none':
                badge_class = f"badge-{encryption_type}"
                badge_html = f'<span class="encryption-badge {badge_class}">{encryption_type}</span>'
            else:
                badge_html = '<span class="encryption-badge badge-none">None</span>'

            html += f"<tr><td>{base_name}</td><td>{badge_html}</td>"

            # Hybrid mode columns
            if hybrid_stats:
                html += f"<td>{hybrid_stats['average']:.2f}</td><td>{hybrid_stats['median']:.2f}</td><td>{hybrid_stats['stddev']:.2f}</td>"
            else:
                html += "<td>-</td><td>-</td><td>-</td>"

            # MongoDB-Only mode columns
            if mongo_stats:
                html += f"<td>{mongo_stats['average']:.2f}</td><td>{mongo_stats['median']:.2f}</td><td>{mongo_stats['stddev']:.2f}</td>"
            else:
                html += "<td>-</td><td>-</td><td>-</td>"

            html += "</tr>"

        html += """
            </tbody>
        </table>
        """

        # Build test data from all test results (not just result size tests)
        # Group by base test name and collect data for both modes
        all_tests = {}
        for result in metrics.test_results:
            test_name = result.get('name', '')
            # Skip health check and other non-search tests
            if 'Health Check' in test_name:
                continue

            # Only include tests with explicit result size specification
            # This filters out Preview Feature Tests that don't have "- X results" pattern
            if " results " not in test_name and " record " not in test_name:
                continue  # Skip tests without explicit result size (e.g., Preview Feature Tests)

            # Extract base name and mode
            base_name = test_name.replace(" (Hybrid)", "").replace(" (MongoDB-Only)", "")
            mode = 'Hybrid' if '(Hybrid)' in test_name else 'MongoDB-Only'

            # Get timing data and test status
            test_details = result.get('details', {})
            test_metrics = test_details.get('metrics', {})
            total_time = test_metrics.get('total_ms', 0)

            # Only include tests that actually passed (not failed, not NA status)
            # Check if test passed AND returned expected number of records
            test_passed = result.get('passed', False)
            test_status = test_details.get('status', None)
            results_count = test_details.get('results_count', None)
            expected_count = test_details.get('expected_count', None)

            # Only include if:
            # 1. Test passed
            # 2. Status is not "NA" (insufficient data)
            # 3. If expected_count is specified, results_count must match it exactly
            if not test_passed:
                continue  # Skip failed tests
            if test_status == "NA":
                continue  # Skip tests with insufficient data
            if expected_count is not None and results_count != expected_count:
                continue  # Skip tests that didn't return exact expected count

            if base_name not in all_tests:
                all_tests[base_name] = {}

            all_tests[base_name][mode] = total_time

        # Generate Mode Comparison tables - split by result set size
        html += """
        <h2>Mode Comparison by Result Set Size</h2>
        <p>Performance comparison between Hybrid and MongoDB-Only modes across different result set sizes.</p>
        """

        # First, collect all unique test base names from BOTH all_tests AND grouped_results
        # This ensures ALL 9 tests appear in the comparison table, even if they don't have result-size variants
        all_base_names = set()

        # Add base names from all_tests (result-size variant tests)
        for test_name in all_tests.keys():
            # Extract base name by removing "- X results" if present
            if " - " in test_name and " results" in test_name:
                # This is a result-size variant test like "Category Search - 100 results"
                base = test_name.rsplit(" - ", 1)[0]  # Get "Category Search"
                all_base_names.add(base)
            else:
                # Regular test like "Category Equality Search"
                all_base_names.add(test_name)

        # IMPORTANT: Also add base names from grouped_results (Performance Metrics tests)
        # This ensures tests without result-size variants (like "Email Exact Match via Prefix") are included
        for base_name in grouped_results.keys():
            all_base_names.add(base_name)

        # Generate separate table for each result set size
        for count in [1, 100, 500, 1000]:
            record_label = "Record" if count == 1 else "Records"
            html += f"""
            <h3>{count} {record_label}</h3>
            <table class="comparison-table">
                <thead>
                    <tr>
                        <th>Test Type</th>
                        <th>Encryption Type</th>
                        <th>Hybrid (ms)</th>
                        <th>MongoDB (ms)</th>
                        <th>Diff (ms)</th>
                    </tr>
                </thead>
                <tbody>
            """

            # Generate rows for all unique base names (show ALL tests, even if no data)
            for base_name in sorted(all_base_names):
                # Get encryption type from encryption_type_map
                operation_with_mode = f"{base_name} (Hybrid)" if f"{base_name} (Hybrid)" in encryption_type_map else f"{base_name} (MongoDB-Only)"
                encryption_type = encryption_type_map.get(operation_with_mode, 'none')

                # Generate badge HTML
                if encryption_type and encryption_type != 'none':
                    badge_class = f"badge-{encryption_type}"
                    badge_html = f'<span class="encryption-badge {badge_class}">{encryption_type}</span>'
                else:
                    badge_html = '<span class="encryption-badge badge-none">-</span>'

                # Build test names for this specific result count
                test_with_count = f"{base_name} - {count} results"

                # Get times for this specific test variant
                hybrid_time = all_tests.get(test_with_count, {}).get('Hybrid', None)
                mongo_time = all_tests.get(test_with_count, {}).get('MongoDB-Only', None)

                # If no result-size variant exists and this is the first table (1 record),
                # try to use the regular test result (without "- X results")
                if hybrid_time is None and mongo_time is None and count == 1:
                    hybrid_time = all_tests.get(base_name, {}).get('Hybrid', None)
                    mongo_time = all_tests.get(base_name, {}).get('MongoDB-Only', None)

                # Show data if BOTH modes have valid data, otherwise show dashes
                if hybrid_time is not None and mongo_time is not None:
                    hybrid_val = hybrid_time
                    mongo_val = mongo_time
                    diff = mongo_val - hybrid_val

                    # Calculate percentage difference relative to Hybrid mode
                    if hybrid_val != 0:
                        percentage = (diff / hybrid_val) * 100
                    else:
                        percentage = 0

                    color = "color: red;" if diff > 0 else "color: green;"
                    html += f"""
                    <tr>
                        <td><strong>{base_name}</strong></td>
                        <td>{badge_html}</td>
                        <td>{hybrid_val:.2f}</td>
                        <td>{mongo_val:.2f}</td>
                        <td style='{color}'>{diff:+.2f} ({percentage:+.1f}%)</td>
                    </tr>
                    """
                else:
                    # Show test row with dashes for missing data
                    html += f"""
                    <tr>
                        <td><strong>{base_name}</strong></td>
                        <td>{badge_html}</td>
                        <td>-</td>
                        <td>-</td>
                        <td>-</td>
                    </tr>
                    """

            html += """
                </tbody>
            </table>
            """

        html += """
        <p style="margin-top: 10px; font-size: 12px; color: #666;">
            <strong>Note:</strong> Positive difference (red) means MongoDB-Only is slower.
            Hybrid mode benefits from splitting the workload: MongoDB handles encrypted search, while AlloyDB handles encrypted data retrieval.
            MongoDB-Only performs both encrypted search and data decryption.
        </p>
        """

    else:
        html += "<p>No performance tests run.</p>"

    html += """
    </div>
</body>
</html>
    """

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print_success(f"Report generated: {output_file}")

# ============================================================================
# TEST SUITE ORGANIZATION
# ============================================================================

def validate_data_availability():
    """Validate that sufficient test data exists before running tests"""
    print_header("Validating Test Data")

    try:
        # Check MongoDB via API health check
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            mongo_connected = health_data.get("mongodb") == "connected"
            encryption_keys = health_data.get("encryption_keys", 0)
            mongodb_count = health_data.get("mongodb_customers", 0)

            print(f"  MongoDB customer count: {Colors.OKCYAN}{mongodb_count}{Colors.ENDC}")
            print(f"  MongoDB status: {Colors.OKGREEN if mongo_connected else Colors.FAIL}{'connected' if mongo_connected else 'disconnected'}{Colors.ENDC}")
            print(f"  Encryption keys loaded: {Colors.OKGREEN if encryption_keys == 5 else Colors.FAIL}{encryption_keys}{Colors.ENDC}")

            if not mongo_connected:
                print(f"\n{Colors.FAIL}ERROR: MongoDB is not connected{Colors.ENDC}")
                print("Run: python deploy.py start")
                sys.exit(1)

            if encryption_keys != 5:
                print(f"\n{Colors.FAIL}ERROR: Expected 5 encryption keys, found {encryption_keys}{Colors.ENDC}")
                print("Run: python deploy.py clean && python deploy.py start")
                sys.exit(1)
        else:
            print(f"\n{Colors.FAIL}ERROR: API health check failed{Colors.ENDC}")
            sys.exit(1)

        # Validate minimum data count
        if mongodb_count < 100:
            print(f"\n{Colors.WARNING}WARNING: Only {mongodb_count} customers found (recommended: 10,000){Colors.ENDC}")
            print("Run: python deploy.py generate --count 10000")

            response = input("\nContinue with limited data? (yes/no): ")
            if response.lower() != 'yes':
                print("Test run cancelled")
                sys.exit(0)
        else:
            print(f"\n{Colors.OKGREEN}[OK] Data validation passed{Colors.ENDC}")

        return {
            "mongodb_count": mongodb_count,
            "encryption_keys": encryption_keys
        }

    except Exception as e:
        print(f"\n{Colors.FAIL}ERROR: Data validation failed: {e}{Colors.ENDC}")
        print("\nMake sure services are running:")
        print("  1. python deploy.py start")
        print("  2. python deploy.py generate --count 10000")
        sys.exit(1)

def run_test_for_both_modes(metrics, test_fn, field, value, base_name, **kwargs):
    """Run same test for both Hybrid and MongoDB-Only modes

    Args:
        metrics: TestMetrics instance
        test_fn: Test function to call (test_encrypted_search, test_prefix_search, etc.)
        field: Field name to search
        value: Search value
        base_name: Base test name (without mode suffix)
        **kwargs: Additional arguments to pass to test function (e.g., limit)
    """
    for mode in TEST_MODES:
        mode_label = "Hybrid" if mode == "hybrid" else "MongoDB-Only"
        test_name = f"{base_name} ({mode_label})"
        test_fn(metrics, field, value, test_name, mode, **kwargs)

def run_equality_tests(metrics):
    """Run equality query tests for both Hybrid and MongoDB-Only modes"""
    print_header("Equality Query Tests - Hybrid Mode")

    run_test_for_both_modes(metrics, test_encrypted_search, "phone", TEST_PHONE, "Phone Equality Search")
    run_test_for_both_modes(metrics, test_encrypted_search, "category", TEST_CATEGORY, "Category Equality Search")
    run_test_for_both_modes(metrics, test_encrypted_search, "status", TEST_STATUS, "Status Equality Search")

def run_result_size_test_for_both_modes(metrics, test_fn, field, value, base_name, limit):
    """Run result-size test for both modes

    Args:
        metrics: TestMetrics instance
        test_fn: Test function to call
        field: Field name to search
        value: Search value
        base_name: Base test name
        limit: Result limit
    """
    print_header(f"{base_name} - {limit} records")
    for mode in TEST_MODES:
        mode_label = "Hybrid" if mode == "hybrid" else "MongoDB-Only"
        test_name = f"{base_name} - {limit} results ({mode_label})"
        test_fn(metrics, field, value, test_name, mode, limit=limit)

def run_result_size_tests(metrics):
    """Run result set size performance tests"""
    print_header("Result Set Size Performance Tests")
    print_info("Testing how performance scales with different result set sizes")
    print_info("Using low-cardinality fields to control result counts")
    print()

    result_sizes = [1, 100, 500, 1000]

    # Define all test configurations: (test_fn, field, value, base_name)
    equality_tests = [
        (test_encrypted_search, "phone", TEST_PHONE, "Phone Equality Search"),
        (test_encrypted_search, "category", TEST_CATEGORY, "Category Equality Search"),
        (test_encrypted_search, "status", TEST_STATUS, "Status Equality Search"),
    ]

    # Equality tests
    for test_fn, field, value, base_name in equality_tests:
        for limit in result_sizes:
            run_result_size_test_for_both_modes(metrics, test_fn, field, value, base_name, limit)

    # Prefix tests
    print_header("Result Set Size Tests - Prefix Queries")
    prefix_tests = [
        (test_prefix_search, "email", TEST_EMAIL, "Email Exact Match via Prefix"),
        (test_prefix_search, "email", TEST_EMAIL.split('@')[0][:4], "Email Prefix Search - Username"),
    ]

    for test_fn, field, value, base_name in prefix_tests:
        for limit in result_sizes:
            run_result_size_test_for_both_modes(metrics, test_fn, field, value, base_name, limit)

    # Substring tests
    print_header("Result Set Size Tests - Substring Queries")
    substring_tests = [
        (test_substring_search, "name", TEST_NAME.split()[0], "Encrypted Name Search"),
        (test_substring_search, "name", TEST_NAME.split()[0], "Name Substring - First Name"),
        (test_substring_search, "name", TEST_NAME.split()[-1], "Name Substring - Last Name"),
        (test_substring_search, "name", TEST_NAME.split()[0][:3], "Name Substring - Partial Match"),
    ]

    for test_fn, field, value, base_name in substring_tests:
        for limit in result_sizes:
            run_result_size_test_for_both_modes(metrics, test_fn, field, value, base_name, limit)

def run_preview_feature_tests(metrics):
    """Run preview feature tests (prefix and substring queries)"""
    print_header("Preview Feature Tests - Prefix Queries")

    run_test_for_both_modes(metrics, test_prefix_search, "email", TEST_EMAIL, "Email Exact Match via Prefix")
    run_test_for_both_modes(metrics, test_prefix_search, "email", TEST_EMAIL.split('@')[0][:4], "Email Prefix Search - Username")

    print_header("Preview Feature Tests - Substring Queries")

    run_test_for_both_modes(metrics, test_substring_search, "name", TEST_NAME.split()[0], "Name Substring - First Name")
    run_test_for_both_modes(metrics, test_substring_search, "name", TEST_NAME.split()[-1], "Name Substring - Last Name")
    run_test_for_both_modes(metrics, test_substring_search, "name", TEST_NAME.split()[0][:3], "Name Substring - Partial Match")

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Run POC tests with real-time metrics")
    parser.add_argument('--iterations', type=int, default=100, help='Performance test iterations (default: 100)')
    parser.add_argument('--report', default='test_report.html', help='Output report file')
    parser.add_argument('--skip-validation', action='store_true', help='Skip data validation check')
    args = parser.parse_args()

    print_header("POC Test Suite")
    print_info(f"API Endpoint: {API_BASE_URL}")
    print_info(f"Test Mode: Full (Functional + Performance + Result-Size Variants)")

    # Validate data availability unless explicitly skipped
    if not args.skip_validation:
        data_stats = validate_data_availability()
    else:
        data_stats = {"alloydb_count": 0, "encryption_keys": 0}


    metrics = TestMetrics()
    perf_results = {}

    # Functional Tests
    print_header("Functional Tests")
    test_health_check(metrics)

    # Run all test suites
    run_equality_tests(metrics)
    run_result_size_tests(metrics)
    run_preview_feature_tests(metrics)













    # Performance Tests
    perf_results = run_performance_tests(metrics, args.iterations)

    # Add functional test duration to total benchmark duration
    metrics.total_benchmark_duration += metrics.total_duration

    # Generate Report
    print_header("Test Summary")

    summary = metrics.get_summary()

    print(f"{Colors.BOLD}Results:{Colors.ENDC}")
    print(f"  Total Tests:    {summary['total_tests']}")
    print(f"  Passed:         {Colors.OKGREEN}{summary['passed']}{Colors.ENDC}")
    print(f"  Failed:         {Colors.FAIL if summary['failed'] > 0 else Colors.OKGREEN}{summary['failed']}{Colors.ENDC}")
    print(f"  Pass Rate:      {summary['pass_rate']:.1f}%")
    print(f"  Total Duration: {metrics.total_benchmark_duration:.2f}s")

    # Generate HTML report
    generate_html_report(metrics, perf_results, args.report, data_stats, args.iterations)

    print()
    if summary['failed'] == 0:
        print(f"{Colors.OKGREEN}{Colors.BOLD}All tests passed!{Colors.ENDC}")
        sys.exit(0)
    else:
        print(f"{Colors.FAIL}{Colors.BOLD}[WARNING] {summary['failed']} test(s) failed{Colors.ENDC}")
        sys.exit(1)

if __name__ == "__main__":
    main()
