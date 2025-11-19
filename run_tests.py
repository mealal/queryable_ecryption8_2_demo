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

# Import Denodo wrapper (optional)
try:
    from denodo.denodo_wrapper import DenodoClient, license_limiter
    DENODO_AVAILABLE = True
except ImportError:
    DENODO_AVAILABLE = False
    license_limiter = None
    print("Warning: Denodo wrapper not found. Denodo tests will be skipped.")

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
DENODO_CLIENT = DenodoClient() if DENODO_AVAILABLE else None

# Test modes: hybrid, mongodb_only, denodo
TEST_MODES = ["hybrid", "mongodb_only"]
if DENODO_AVAILABLE:
    TEST_MODES.append("denodo")

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

def test_encrypted_search(metrics, field, value, test_name, mode="hybrid", limit=None):
    """Test encrypted search with configurable result limit"""
    print_test_start(test_name)

    endpoint_map = {
        "email": "email",
        "name": "name",
        "phone": "phone"
    }

    endpoint = endpoint_map.get(field, field)

    start = time.time()
    try:
        params = {field: value, "mode": mode}
        if limit is not None:
            params["limit"] = limit

        response = requests.get(
            f"{API_BASE_URL}/api/v1/customers/search/{endpoint}",
            params=params,
            timeout=10
        )
        duration = time.time() - start

        if response.status_code == 200:
            data = response.json()

            if data['success']:
                test_metrics = data['metrics']
                results_count = len(data['data'])
                api_total_time = test_metrics['total_ms']
                client_time = duration * 1000

                # Validate result count using centralized logic
                passed, should_count_perf, status_msg = validate_result_count(results_count, limit, test_name)

                if results_count > 0:
                    customer = data['data'][0]
                    print_success(f"Found customer: {customer.get('full_name')}")
                    print_metric("Results Returned", results_count, "records")

                    # Get appropriate MongoDB time based on mode
                    if mode == "hybrid":
                        mongodb_time = test_metrics['mongodb_search_ms']
                        print_metric("MongoDB Search", mongodb_time, "ms")
                        print_metric("AlloyDB Fetch", test_metrics.get('alloydb_fetch_ms', 0), "ms")
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
                            "error": "Validation failed"
                        })
                        return False

                    # Record result based on count validation
                    if passed:
                        print_success("Customer data validation passed")
                        test_details = {
                            "customer": customer,
                            "metrics": test_metrics,
                            "mode": mode,
                            "results_count": results_count,
                            "expected_count": limit
                        }
                        if status_msg:
                            test_details["status"] = status_msg

                        metrics.add_result(test_name, True, duration, test_details)

                        # Only add performance data if should_count_perf is True
                        if should_count_perf:
                            metrics.add_performance_data(f"Encrypted {field.title()} Search ({mode})", test_metrics)

                        return True
                    else:
                        print_error(status_msg)
                        metrics.add_result(test_name, False, duration, {
                            "customer": customer,
                            "metrics": test_metrics,
                            "mode": mode,
                            "results_count": results_count,
                            "expected_count": limit,
                            "error": status_msg
                        })
                        return False
                else:
                    # Zero results - always a failure
                    print_error(f"Query executed but returned 0 results - expected to find data")
                    print_metric("MongoDB Search", test_metrics['mongodb_search_ms'], "ms")
                    print_metric("Client Time", duration * 1000, "ms")
                    metrics.add_result(test_name, False, duration, {
                        "metrics": test_metrics,
                        "mode": mode,
                        "results_count": 0,
                        "expected_count": limit,
                        "error": "No results found"
                    })
                    return False
            else:
                print_error("API returned success=false")
                metrics.add_result(test_name, False, duration)
                return False
        else:
            print_error(f"Request failed: {response.status_code}")
            metrics.add_result(test_name, False, duration)
            return False

    except Exception as e:
        duration = time.time() - start
        print_error(f"Test failed: {e}")
        metrics.add_result(test_name, False, duration, {"error": str(e)})
        return False

def test_prefix_search(metrics, field, prefix, test_name, mode="hybrid", limit=None):
    """Test encrypted prefix search (Preview Feature)"""
    print_test_start(test_name)

    start_time = time.time()
    try:
        params = {field.replace("_", ""): prefix} if "_" in field else {"prefix": prefix}
        params["mode"] = mode
        if limit is not None:
            params["limit"] = limit

        response = requests.get(
            f"{API_BASE_URL}/api/v1/customers/search/{field}/prefix",
            params=params,
            timeout=30
        )

        duration = time.time() - start_time

        if response.status_code == 200:
            data = response.json()
            if data['success']:
                results_count = len(data['data'])
                api_total_time = data['metrics']['total_ms']
                client_time = duration * 1000

                # Validate result count using centralized logic
                passed, should_count_perf, status_msg = validate_result_count(results_count, limit, test_name)

                # Get appropriate MongoDB time based on mode
                if mode == "hybrid":
                    mongodb_time = data['metrics']['mongodb_search_ms']
                    alloydb_time = data['metrics'].get('alloydb_fetch_ms', 0)
                else:  # mongodb_only
                    mongodb_time = data['metrics'].get('mongodb_decrypt_ms', 0)
                    alloydb_time = 0

                print_success(f"{test_name} - Found {results_count} results")
                if mode == "hybrid":
                    print_info(f"  MongoDB Search: {mongodb_time:.2f}ms | AlloyDB: {alloydb_time:.2f}ms | API Total: {api_total_time:.2f}ms | Client: {client_time:.2f}ms")
                else:
                    print_info(f"  MongoDB Decrypt: {mongodb_time:.2f}ms | API Total: {api_total_time:.2f}ms | Client: {client_time:.2f}ms")

                # Handle zero results
                if results_count == 0:
                    print_error(f"{test_name} - Found 0 results (expected data)")
                    metrics.add_result(test_name, False, duration, {
                        "mode": mode,
                        "results_count": 0,
                        "expected_count": limit,
                        "error": "No results",
                        "metrics": data['metrics']
                    })
                    return False

                # Validate customer response
                if not validate_customer_response(data['data'][0], mode):
                    print_error("Customer data validation failed")
                    metrics.add_result(test_name, False, duration, {
                        "mode": mode,
                        "results_count": results_count,
                        "expected_count": limit,
                        "error": "Validation failed",
                        "metrics": data['metrics']
                    })
                    return False

                # Record result based on count validation
                if passed:
                    print_success("Customer data validation passed")
                    test_details = {
                        "mode": mode,
                        "results_count": results_count,
                        "expected_count": limit,
                        "metrics": data['metrics']
                    }
                    if status_msg:
                        test_details["status"] = status_msg

                    metrics.add_result(test_name, True, duration, test_details)

                    # Only add performance data if should_count_perf is True
                    if should_count_perf:
                        metrics.add_performance_data(test_name, data['metrics'])

                    return True
                else:
                    print_error(status_msg)
                    metrics.add_result(test_name, False, duration, {
                        "mode": mode,
                        "results_count": results_count,
                        "expected_count": limit,
                        "error": status_msg,
                        "metrics": data['metrics']
                    })
                    return False
            else:
                print_error(f"{test_name} - API returned success=false")
                metrics.add_result(test_name, False, duration)
                return False
        else:
            print_error(f"{test_name} - HTTP {response.status_code}")
            metrics.add_result(test_name, False, duration)
            return False

    except Exception as e:
        duration = time.time() - start_time
        print_error(f"{test_name} - Exception: {str(e)}")
        metrics.add_result(test_name, False, duration)
        return False

def test_suffix_search(metrics, field, suffix, test_name, mode="hybrid"):
    """Test encrypted suffix search (Preview Feature)"""
    print_test_start(test_name)

    start_time = time.time()
    try:
        params = {field.replace("_", ""): suffix} if "_" in field else {"suffix": suffix}
        params["mode"] = mode

        response = requests.get(
            f"{API_BASE_URL}/api/v1/customers/search/{field}/suffix",
            params=params,
            timeout=30
        )

        duration = time.time() - start_time

        if response.status_code == 200:
            data = response.json()
            if data['success']:
                results_count = len(data['data'])
                mongodb_time = data['metrics']['mongodb_search_ms']
                alloydb_time = data['metrics'].get('alloydb_fetch_ms', 0)

                print_success(f"{test_name} - Found {results_count} results")
                if mode == "hybrid":
                    print_info(f"  MongoDB: {mongodb_time:.2f}ms | AlloyDB: {alloydb_time:.2f}ms | Total: {duration*1000:.2f}ms")
                else:
                    print_info(f"  MongoDB: {mongodb_time:.2f}ms | Total: {duration*1000:.2f}ms")

                # Validate first customer - require at least one result
                if not data['data']:
                    print_error(f"{test_name} - Found 0 results (expected data)")
                    metrics.add_result(test_name, False, duration, {"mode": mode, "error": "No results"})
                    return False

                if validate_customer_response(data['data'][0], mode):
                    print_success("Customer data validation passed")
                    metrics.add_result(test_name, True, duration, {"mode": mode})
                    return True
                else:
                    print_error("Customer data validation failed")
                    metrics.add_result(test_name, False, duration, {"mode": mode, "error": "Validation failed"})
                    return False
            else:
                print_error(f"{test_name} - API returned success=false")
                metrics.add_result(test_name, False, duration)
                return False
        else:
            print_error(f"{test_name} - HTTP {response.status_code}")
            metrics.add_result(test_name, False, duration)
            return False

    except Exception as e:
        duration = time.time() - start_time
        print_error(f"{test_name} - Exception: {str(e)}")
        metrics.add_result(test_name, False, duration)
        return False

def test_substring_search(metrics, field, substring, test_name, mode="hybrid", limit=None):
    """Test encrypted substring search (Preview Feature)"""
    print_test_start(test_name)

    start_time = time.time()
    try:
        params = {field.replace("_", ""): substring} if "_" in field else {"substring": substring}
        params["mode"] = mode
        if limit is not None:
            params["limit"] = limit

        response = requests.get(
            f"{API_BASE_URL}/api/v1/customers/search/{field}/substring",
            params=params,
            timeout=30
        )

        duration = time.time() - start_time

        if response.status_code == 200:
            data = response.json()
            if data['success']:
                results_count = len(data['data'])
                api_total_time = data['metrics']['total_ms']
                client_time = duration * 1000

                # Get appropriate MongoDB time based on mode
                if mode == "hybrid":
                    mongodb_time = data['metrics']['mongodb_search_ms']
                    alloydb_time = data['metrics'].get('alloydb_fetch_ms', 0)
                else:  # mongodb_only
                    mongodb_time = data['metrics'].get('mongodb_decrypt_ms', 0)
                    alloydb_time = 0

                test_metrics = {
                    'mongodb_search_ms' if mode == "hybrid" else 'mongodb_decrypt_ms': mongodb_time,
                    'alloydb_fetch_ms': alloydb_time,
                    'total_ms': api_total_time,
                    'client_ms': client_time
                }

                # Validate result count using centralized logic
                passed, should_count_perf, status_msg = validate_result_count(results_count, limit, test_name)

                if results_count > 0:
                    customer = data['data'][0]
                    print_success(f"{test_name} - Found {results_count} results")
                    if mode == "hybrid":
                        print_info(f"  MongoDB Search: {mongodb_time:.2f}ms | AlloyDB: {alloydb_time:.2f}ms | API Total: {api_total_time:.2f}ms | Client: {client_time:.2f}ms")
                    else:
                        print_info(f"  MongoDB Decrypt: {mongodb_time:.2f}ms | API Total: {api_total_time:.2f}ms | Client: {client_time:.2f}ms")

                    # Validate customer response
                    if not validate_customer_response(customer, mode):
                        print_error("Customer data validation failed")
                        metrics.add_result(test_name, False, duration, {"mode": mode, "error": "Validation failed"})
                        return False

                    # Record result based on count validation
                    if passed:
                        print_success("Customer data validation passed")
                        test_details = {
                            "customer": customer,
                            "metrics": test_metrics,
                            "mode": mode,
                            "results_count": results_count,
                            "expected_count": limit
                        }
                        if status_msg:
                            test_details["status"] = status_msg

                        metrics.add_result(test_name, True, duration, test_details)

                        # Only add performance data if should_count_perf is True
                        if should_count_perf:
                            metrics.add_performance_data(f"Encrypted {field.title()} Substring Search ({mode})", test_metrics)

                        return True
                    else:
                        print_error(status_msg)
                        metrics.add_result(test_name, False, duration, {
                            "customer": customer,
                            "metrics": test_metrics,
                            "mode": mode,
                            "results_count": results_count,
                            "expected_count": limit,
                            "error": status_msg
                        })
                        return False
                else:
                    # Zero results
                    print_error(f"{test_name} - Found 0 results (expected data)")
                    metrics.add_result(test_name, False, duration, {
                        "mode": mode,
                        "results_count": 0,
                        "expected_count": limit,
                        "error": "No results"
                    })
                    return False
            else:
                print_error(f"{test_name} - API returned success=false")
                metrics.add_result(test_name, False, duration)
                return False
        else:
            print_error(f"{test_name} - HTTP {response.status_code}")
            metrics.add_result(test_name, False, duration)
            return False

    except Exception as e:
        duration = time.time() - start_time
        print_error(f"{test_name} - Exception: {str(e)}")
        metrics.add_result(test_name, False, duration)
        return False


def test_denodo_search(metrics, search_type, search_param, test_name, data_source="hybrid"):
    """
    Test Denodo search with license limitation tracking

    Args:
        metrics: Test metrics collector
        search_type: Type of search (phone, email_prefix, etc.)
        search_param: Search parameter value
        test_name: Test name for reporting
        data_source: Data source mode ('hybrid' = MongoDB search + AlloyDB data, 'mongodb' = MongoDB-only)
    """
    if not DENODO_AVAILABLE or not DENODO_CLIENT:
        print_warning(f"Denodo not available - skipping {test_name}")
        return False

    print_test_start(test_name)

    start = time.time()
    try:
        # Call appropriate Denodo search method with data_source parameter
        # data_source: 'hybrid' = MongoDB search + AlloyDB data
        #             'mongodb' = MongoDB search + decrypt (no AlloyDB)
        if search_type == "email_prefix":
            results, duration_ms, throttled = DENODO_CLIENT.search_by_email_prefix(search_param, data_source)
        elif search_type == "name_substring":
            results, duration_ms, throttled = DENODO_CLIENT.search_by_name_substring(search_param, data_source)
        elif search_type == "phone":
            results, duration_ms, throttled = DENODO_CLIENT.search_by_phone(search_param, data_source)
        elif search_type == "category":
            results, duration_ms, throttled = DENODO_CLIENT.search_by_category(search_param, data_source)
        elif search_type == "status":
            results, duration_ms, throttled = DENODO_CLIENT.search_by_status(search_param, data_source)
        else:
            print_error(f"Unknown search type: {search_type}")
            return False

        total_duration = time.time() - start
        mode = f"denodo_{data_source}"

        if throttled:
            print_warning("Request throttled due to license limits (MaxSimultaneousRequests=3)")
            metrics.add_result(test_name, False, total_duration, {"throttled": True, "mode": mode})
            return False

        if results:
            customer = results[0] if isinstance(results, list) else results
            print_success(f"Found customer: {customer.get('full_name', 'N/A')}")
            print_metric("Denodo Query", duration_ms, "ms")
            print_metric("Client Time", total_duration * 1000, "ms")
            print_metric("Data Source", data_source.upper(), "")
            print_info(f"License: {license_limiter.concurrent_requests}/{license_limiter.max_concurrent_reached} concurrent")

            metrics.add_result(test_name, True, total_duration, {
                "customer": customer,
                "metrics": {
                    "denodo_query_ms": duration_ms,
                    "total_ms": duration_ms,
                    "results_count": len(results) if isinstance(results, list) else 1,
                    "mode": mode,
                    "data_source": data_source
                },
                "mode": mode
            })

            metrics.add_performance_data(f"Denodo {search_type.replace('_', ' ').title()} ({data_source})", {
                "denodo_query_ms": duration_ms,
                "total_ms": duration_ms,
                "mode": mode
            })
            return True
        else:
            print_error(f"No results found - endpoint may not exist or returned empty data")
            metrics.add_result(test_name, False, total_duration, {"results": 0, "mode": mode})
            return False

    except Exception as e:
        duration = time.time() - start
        mode = f"denodo_{data_source}"
        print_error(f"Denodo search failed: {e}")
        metrics.add_result(test_name, False, duration, {"error": str(e), "mode": mode})
        return False

# ============================================================================
# PERFORMANCE TESTING
# ============================================================================

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

        for i in range(iterations):
            # Add small delay between iterations to prevent MongoDB driver overload
            # This is especially important for MongoDB-only mode with high iteration counts
            if i > 0:
                time.sleep(0.05)  # 50ms delay between iterations

            start = time.time()

            try:
                # Get test value for this iteration
                if test_pool and pool_key in test_pool and test_pool[pool_key]:
                    # If pool is big enough, use sequential values; otherwise pick randomly
                    if len(test_pool[pool_key]) >= iterations:
                        test_value = test_pool[pool_key][i % len(test_pool[pool_key])]
                    else:
                        # Pool too small, pick randomly
                        test_value = random.choice(test_pool[pool_key])

                    # Special processing for certain test types
                    if "Last Name" in test_name and ' ' in test_value:
                        test_value = test_value.split()[-1][:10]  # Extract last name substring
                    elif "Partial Match" in test_name and len(test_value) > 4:
                        test_value = test_value[:4]  # Take first 4 chars for partial match
                else:
                    # Fallback to static test value
                    if "Phone" in test_name:
                        test_value = TEST_PHONE
                    elif "Email" in test_name and "Username" in test_name:
                        test_value = TEST_EMAIL.split('@')[0][:4]
                    elif "Email" in test_name:
                        test_value = TEST_EMAIL
                    elif "Category" in test_name:
                        test_value = TEST_CATEGORY
                    elif "Status" in test_name:
                        test_value = TEST_STATUS
                    else:
                        test_value = TEST_NAME[:10]

                # Build appropriate request based on endpoint type
                if endpoint_type == "search":
                    if query_type == "equality":
                        # Equality search: /api/v1/customers/search/{field}?{param}={value}&mode={mode}
                        response = requests.get(
                            f"{API_BASE_URL}/api/v1/customers/search/{field}",
                            params={param_name: test_value, "mode": mode},
                            timeout=10
                        )
                    elif query_type == "prefix":
                        # Prefix search: /api/v1/customers/search/{field}/prefix?{param}={value}&mode={mode}
                        response = requests.get(
                            f"{API_BASE_URL}/api/v1/customers/search/{field}/prefix",
                            params={param_name: test_value, "mode": mode},
                            timeout=10
                        )
                    elif query_type == "substring":
                        # Substring search: /api/v1/customers/search/{field}/substring?{param}={value}&mode={mode}
                        response = requests.get(
                            f"{API_BASE_URL}/api/v1/customers/search/{field}/substring",
                            params={param_name: test_value, "mode": mode},
                            timeout=10
                        )
                    else:
                        print(f"  Iteration {i+1:2d}: UNKNOWN query type")
                        continue
                else:
                    print(f"  Iteration {i+1:2d}: UNKNOWN endpoint type")
                    continue

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

    # Denodo license statistics removed permanently per user request
    denodo_stats_html = ""

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

        {denodo_stats_html}

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
    # Build test data from all test results
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

        # Generate Mode Comparison table with header
        html += """
        <h2>Mode Comparison by Result Set Size</h2>
        <p>Performance comparison between Hybrid and MongoDB-Only modes across different result set sizes.</p>

        <table style="margin-bottom: 30px;">
            <thead>
                <tr>
                    <th rowspan="2">Test Type</th>
                    <th rowspan="2">Encryption Type</th>
                    <th colspan="3">1 Record</th>
                    <th colspan="3">100 Records</th>
                    <th colspan="3">500 Records</th>
                    <th colspan="3">1000 Records</th>
                </tr>
                <tr>
                    <th>Hybrid (ms)</th>
                    <th>MongoDB (ms)</th>
                    <th>Diff (ms)</th>
                    <th>Hybrid (ms)</th>
                    <th>MongoDB (ms)</th>
                    <th>Diff (ms)</th>
                    <th>Hybrid (ms)</th>
                    <th>MongoDB (ms)</th>
                    <th>Diff (ms)</th>
                    <th>Hybrid (ms)</th>
                    <th>MongoDB (ms)</th>
                    <th>Diff (ms)</th>
                </tr>
            </thead>
            <tbody>
            """

        # First, collect all unique test base names from all_tests
        # This includes both regular tests and result-size variant tests
        all_base_names = set()
        for test_name in all_tests.keys():
            # Extract base name by removing "- X results" if present
            if " - " in test_name and " results" in test_name:
                # This is a result-size variant test like "Category Search - 100 results"
                base = test_name.rsplit(" - ", 1)[0]  # Get "Category Search"
                all_base_names.add(base)
            else:
                # Regular test like "Category Equality Search"
                all_base_names.add(test_name)

        # Generate rows for all unique base names
        for base_name in sorted(all_base_names):
            # Get encryption type from encryption_type_map
            # Try to find it using the base_name with (Hybrid) or (MongoDB-Only) suffix
            operation_with_mode = f"{base_name} (Hybrid)" if f"{base_name} (Hybrid)" in encryption_type_map else f"{base_name} (MongoDB-Only)"
            encryption_type = encryption_type_map.get(operation_with_mode, 'none')

            # Generate badge HTML
            if encryption_type and encryption_type != 'none':
                badge_class = f"badge-{encryption_type}"
                badge_html = f'<span class="encryption-badge {badge_class}">{encryption_type}</span>'
            else:
                badge_html = '<span class="encryption-badge badge-none">-</span>'

            html += f"<tr><td><strong>{base_name}</strong></td><td>{badge_html}</td>"

            # For each result count column (1, 100, 500, 1000)
            for count in [1, 100, 500, 1000]:
                # Build test names for this specific result count
                test_with_count = f"{base_name} - {count} results"

                # Get times for this specific test variant
                hybrid_time = all_tests.get(test_with_count, {}).get('Hybrid', None)
                mongo_time = all_tests.get(test_with_count, {}).get('MongoDB-Only', None)

                # If no result-size variant exists and this is the first column (1 record),
                # try to use the regular test result (without "- X results")
                if hybrid_time is None and mongo_time is None and count == 1:
                    hybrid_time = all_tests.get(base_name, {}).get('Hybrid', None)
                    mongo_time = all_tests.get(base_name, {}).get('MongoDB-Only', None)

                # Only show data if BOTH modes have valid data
                # If either mode is missing (failed or NA), show dashes for the entire column
                if hybrid_time is not None and mongo_time is not None:
                    hybrid_val = hybrid_time
                    mongo_val = mongo_time
                    diff = mongo_val - hybrid_val

                    html += f"<td>{hybrid_val:.2f}</td>"
                    html += f"<td>{mongo_val:.2f}</td>"
                    color = "color: red;" if diff > 0 else "color: green;"
                    html += f"<td style='{color}'>{diff:+.2f}</td>"
                else:
                    # This test doesn't have valid data for both modes
                    html += "<td>-</td><td>-</td><td>-</td>"

            html += "</tr>"

        html += """
            </tbody>
        </table>
            """

        html += """
        <p style="margin-top: 10px; font-size: 12px; color: #666;">
            <strong>Note:</strong> Positive difference (red) means MongoDB-Only is slower.
            Hybrid mode benefits from AlloyDB's plaintext storage, while MongoDB-Only decrypts all fields.
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

def check_denodo_running():
    """Check if Denodo Docker container is running"""
    try:
        result = subprocess.run(
            "docker ps --filter name=poc_denodo --format '{{.Names}}'",
            shell=True,
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0 and 'poc_denodo' in result.stdout
    except Exception:
        return False

def check_denodo_endpoints():
    """Check if Denodo REST endpoints are available"""
    # First check if Denodo container is running
    if not check_denodo_running():
        return False

    if not DENODO_AVAILABLE or not DENODO_CLIENT:
        return False

    print_header("Checking Denodo Endpoints")

    try:
        # Try a simple test query to verify endpoints exist
        # Use a test phone that doesn't need to match actual data
        test_results, test_duration, throttled = DENODO_CLIENT.search_by_phone("+1-555-0000", data_source="hybrid")

        # If we get here without exception, endpoints exist (even if 0 results)
        print_info(f"Denodo REST endpoints are accessible")
        print_info(f"Test query completed in {test_duration:.2f}ms")
        return True

    except ValueError as e:
        # 404 error - endpoints don't exist
        print_error(f"Denodo endpoints not available: {e}")
        print_info("")
        print_info("Denodo data sources exist but REST views/services are not created.")
        print_info("To create views and REST services:")
        print_info("  1. Open http://localhost:9090 (admin/admin)")
        print_info("  2. Navigate to 'poc_integration' database")
        print_info("  3. Create base views and derived views")
        print_info("  4. Create REST web services")
        print_info("")
        print_info("Or use VQL scripts to automate view creation.")
        return False

    except Exception as e:
        print_error(f"Denodo check failed: {e}")
        return False

def run_equality_tests(metrics):
    """Run equality query tests for both Hybrid and MongoDB-Only modes"""
    print_header("Equality Query Tests - Hybrid Mode")

    test_encrypted_search(metrics, "phone", TEST_PHONE, "Phone Equality Search (Hybrid)", "hybrid")
    test_encrypted_search(metrics, "category", TEST_CATEGORY, "Category Equality Search (Hybrid)", "hybrid")
    test_encrypted_search(metrics, "status", TEST_STATUS, "Status Equality Search (Hybrid)", "hybrid")

    print_header("Equality Query Tests - MongoDB-Only Mode")

    test_encrypted_search(metrics, "phone", TEST_PHONE, "Phone Equality Search (MongoDB-Only)", "mongodb_only")
    test_encrypted_search(metrics, "category", TEST_CATEGORY, "Category Equality Search (MongoDB-Only)", "mongodb_only")
    test_encrypted_search(metrics, "status", TEST_STATUS, "Status Equality Search (MongoDB-Only)", "mongodb_only")

def run_result_size_tests(metrics):
    """Run result set size performance tests"""
    print_header("Result Set Size Performance Tests")
    print_info("Testing how performance scales with different result set sizes")
    print_info("Using low-cardinality fields to control result counts")
    print()

    result_sizes = [1, 100, 500, 1000]
    result_size_tests = [
        ("phone", TEST_PHONE, "Phone Equality Search"),
        ("category", TEST_CATEGORY, "Category Equality Search"),
        ("status", TEST_STATUS, "Status Equality Search"),
    ]

    for field, value, base_name in result_size_tests:
        for limit in result_sizes:
            print_header(f"{base_name} - {limit} records")
            test_encrypted_search(metrics, field, value, f"{base_name} - {limit} results (Hybrid)", "hybrid", limit=limit)
            test_encrypted_search(metrics, field, value, f"{base_name} - {limit} results (MongoDB-Only)", "mongodb_only", limit=limit)

    # Add result size variants for Prefix queries
    print_header("Result Set Size Tests - Prefix Queries")
    prefix_username = TEST_EMAIL.split('@')[0][:4]

    for limit in result_sizes:
        print_header(f"Email Prefix Search - Username - {limit} records")
        test_prefix_search(metrics, "email", prefix_username, f"Email Prefix Search - Username - {limit} results (Hybrid)", "hybrid", limit=limit)
        test_prefix_search(metrics, "email", prefix_username, f"Email Prefix Search - Username - {limit} results (MongoDB-Only)", "mongodb_only", limit=limit)

    # Add result size variants for Substring queries
    print_header("Result Set Size Tests - Substring Queries")
    name_first = TEST_NAME.split()[0]
    name_last = TEST_NAME.split()[-1]
    name_partial = TEST_NAME.split()[0][:3]

    for limit in result_sizes:
        print_header(f"Name Substring - First Name - {limit} records")
        test_substring_search(metrics, "name", name_first, f"Name Substring - First Name - {limit} results (Hybrid)", "hybrid", limit=limit)
        test_substring_search(metrics, "name", name_first, f"Name Substring - First Name - {limit} results (MongoDB-Only)", "mongodb_only", limit=limit)

    for limit in result_sizes:
        print_header(f"Name Substring - Last Name - {limit} records")
        test_substring_search(metrics, "name", name_last, f"Name Substring - Last Name - {limit} results (Hybrid)", "hybrid", limit=limit)
        test_substring_search(metrics, "name", name_last, f"Name Substring - Last Name - {limit} results (MongoDB-Only)", "mongodb_only", limit=limit)

    for limit in result_sizes:
        print_header(f"Name Substring - Partial Match - {limit} records")
        test_substring_search(metrics, "name", name_partial, f"Name Substring - Partial Match - {limit} results (Hybrid)", "hybrid", limit=limit)
        test_substring_search(metrics, "name", name_partial, f"Name Substring - Partial Match - {limit} results (MongoDB-Only)", "mongodb_only", limit=limit)

def run_preview_feature_tests(metrics):
    """Run preview feature tests (prefix and substring queries)"""
    print_header("Preview Feature Tests - Prefix Queries (Hybrid Mode)")

    test_prefix_search(metrics, "email", TEST_EMAIL, "Email Exact Match via Prefix (Hybrid)", "hybrid")
    test_prefix_search(metrics, "email", TEST_EMAIL.split('@')[0][:4], "Email Prefix Search - Username (Hybrid)", "hybrid")

    print_header("Preview Feature Tests - Prefix Queries (MongoDB-Only Mode)")

    test_prefix_search(metrics, "email", TEST_EMAIL, "Email Exact Match via Prefix (MongoDB-Only)", "mongodb_only")
    test_prefix_search(metrics, "email", TEST_EMAIL.split('@')[0][:4], "Email Prefix Search - Username (MongoDB-Only)", "mongodb_only")

    print_header("Preview Feature Tests - Substring Queries (Hybrid Mode)")

    test_substring_search(metrics, "name", TEST_NAME.split()[0], "Name Substring - First Name (Hybrid)", "hybrid")
    test_substring_search(metrics, "name", TEST_NAME.split()[-1], "Name Substring - Last Name (Hybrid)", "hybrid")
    test_substring_search(metrics, "name", TEST_NAME.split()[0][:3], "Name Substring - Partial Match (Hybrid)", "hybrid")

    print_header("Preview Feature Tests - Substring Queries (MongoDB-Only Mode)")

    test_substring_search(metrics, "name", TEST_NAME.split()[0], "Name Substring - First Name (MongoDB-Only)", "mongodb_only")
    test_substring_search(metrics, "name", TEST_NAME.split()[-1], "Name Substring - Last Name (MongoDB-Only)", "mongodb_only")
    test_substring_search(metrics, "name", TEST_NAME.split()[0][:3], "Name Substring - Partial Match (MongoDB-Only)", "mongodb_only")

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

    # Check if Denodo endpoints are available
    denodo_running = check_denodo_running()
    denodo_endpoints_available = check_denodo_endpoints() if denodo_running else False
    if denodo_running and not denodo_endpoints_available:
        print_info("\nDenodo tests will be skipped - endpoints not available")

    metrics = TestMetrics()
    perf_results = {}

    # Functional Tests
    print_header("Functional Tests")
    test_health_check(metrics)

    # Run all test suites
    run_equality_tests(metrics)
    run_result_size_tests(metrics)
    run_preview_feature_tests(metrics)

    # Denodo Mode Tests (if available)
    if DENODO_AVAILABLE and denodo_endpoints_available:
        print_header("Denodo Tests - Hybrid Mode")
        print_info("Testing Denodo Hybrid: MongoDB encrypted search + AlloyDB data fetch")
        print_warning(f"License Limits: MaxSimultaneousRequests={3}, MaxRowsPerQuery={10000}")

        # Reset license limiter stats
        license_limiter.reset()

        # Test 18: Phone Search via Denodo-Hybrid
        test_denodo_search(metrics, "phone", TEST_PHONE, "Phone Search (Denodo-Hybrid)", "hybrid")

        # Test 19: Category Search via Denodo-Hybrid
        test_denodo_search(metrics, "category", TEST_CATEGORY, "Category Search (Denodo-Hybrid)", "hybrid")

        # Test 20: Status Search via Denodo-Hybrid
        test_denodo_search(metrics, "status", TEST_STATUS, "Status Search (Denodo-Hybrid)", "hybrid")

        # Test 21: Email Prefix Search via Denodo-Hybrid
        test_denodo_search(metrics, "email_prefix", TEST_EMAIL.split('@')[0], "Email Prefix Search (Denodo-Hybrid)", "hybrid")

        # Test 22: Name Substring Search via Denodo-Hybrid
        test_denodo_search(metrics, "name_substring", TEST_NAME.split()[0], "Name Substring Search (Denodo-Hybrid)", "hybrid")

        print_header("Denodo Tests - MongoDB-Only Mode")
        print_info("Testing Denodo MongoDB-Only: MongoDB search + decrypt (no AlloyDB)")

        # Test 23: Phone Search via Denodo-MongoDB
        test_denodo_search(metrics, "phone", TEST_PHONE, "Phone Search (Denodo-MongoDB)", "mongodb")

        # Test 24: Category Search via Denodo-MongoDB
        test_denodo_search(metrics, "category", TEST_CATEGORY, "Category Search (Denodo-MongoDB)", "mongodb")

        # Test 25: Status Search via Denodo-MongoDB
        test_denodo_search(metrics, "status", TEST_STATUS, "Status Search (Denodo-MongoDB)", "mongodb")

        # Test 26: Email Prefix Search via Denodo-MongoDB
        test_denodo_search(metrics, "email_prefix", TEST_EMAIL.split('@')[0], "Email Prefix Search (Denodo-MongoDB)", "mongodb")

        # Test 27: Name Substring Search via Denodo-MongoDB
        test_denodo_search(metrics, "name_substring", TEST_NAME.split()[0], "Name Substring Search (Denodo-MongoDB)", "mongodb")

        # Display license usage summary
        license_stats = license_limiter.get_stats()
        print()
        print(f"{Colors.BOLD}Denodo License Usage:{Colors.ENDC}")
        print(f"  Total Requests:       {license_stats['total_requests']}")
        print(f"  Max Concurrent:       {license_stats['max_concurrent_requests']}/{license_stats['max_allowed_concurrent']}")
        print(f"  Throttled Requests:   {license_stats['throttled_requests']}")
        print(f"  License Violations:   {license_stats['license_violations']}")

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
