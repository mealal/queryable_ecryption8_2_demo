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

import requests
import json
import time
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
import statistics

# Import Denodo wrapper
try:
    from denodo.denodo_wrapper import DenodoClient, format_denodo_response, license_limiter
    DENODO_AVAILABLE = True
except ImportError:
    DENODO_AVAILABLE = False
    license_limiter = None
    print("Warning: Denodo wrapper not found. Denodo tests will be skipped.")

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# Test configuration
API_BASE_URL = "http://localhost:8000"
DENODO_CLIENT = DenodoClient() if DENODO_AVAILABLE else None

# Test modes: hybrid, mongodb_only, denodo
TEST_MODES = ["hybrid", "mongodb_only"]
if DENODO_AVAILABLE:
    TEST_MODES.append("denodo")

# Fetch real test data from API
def get_test_data():
    """Fetch real customer values from API for testing

    This is NOT part of performance testing - it's just to get valid test data.
    We fetch a few customers from the API and extract searchable field values.
    """
    try:
        # Fetch some customers from AlloyDB to get real values
        # Using AlloyDB endpoint to get unencrypted data for test setup
        # Note: category and status are MongoDB-only fields (in metadata), not in AlloyDB
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="alloydb_poc",
            user="postgres",
            password="postgres_password"
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, email, phone, tier, category, status
            FROM customers
            ORDER BY RANDOM()
            LIMIT 1
        """)
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            return {
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "phone": row[3],
                "tier": row[4] or "gold",
                "category": row[5],
                "status": row[6]
            }
    except Exception as e:
        print(f"Warning: Could not fetch test data from database: {e}")
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

class TestMetrics:
    """Track test metrics in real-time"""

    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.total_duration = 0
        self.total_benchmark_duration = 0
        self.test_results = []
        self.performance_data = []

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

def test_encrypted_search(metrics, field, value, test_name, mode="hybrid"):
    """Test encrypted search"""
    print_test_start(test_name)

    endpoint_map = {
        "email": "email",
        "name": "name",
        "phone": "phone"
    }

    endpoint = endpoint_map.get(field, field)

    start = time.time()
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/v1/customers/search/{endpoint}",
            params={field: value, "mode": mode},
            timeout=10
        )
        duration = time.time() - start

        if response.status_code == 200:
            data = response.json()

            if data['success']:
                test_metrics = data['metrics']
                results_count = len(data['data'])

                if data['data']:
                    customer = data['data'][0]
                    print_success(f"Found customer: {customer.get('full_name')}")
                    print_metric("MongoDB Search", test_metrics['mongodb_search_ms'], "ms")

                    # AlloyDB fetch only in hybrid mode
                    if mode == "hybrid":
                        print_metric("AlloyDB Fetch", test_metrics.get('alloydb_fetch_ms', 0), "ms")

                    print_metric("Total Time", test_metrics['total_ms'], "ms")
                    print_metric("Client Time", duration * 1000, "ms")

                    # Validate customer response
                    if validate_customer_response(customer, mode):
                        print_success("Customer data validation passed")
                        metrics.add_result(test_name, True, duration, {
                            "customer": customer,
                            "metrics": test_metrics,
                            "mode": mode
                        })
                    else:
                        print_error("Customer data validation failed")
                        metrics.add_result(test_name, False, duration, {
                            "customer": customer,
                            "metrics": test_metrics,
                            "mode": mode,
                            "error": "Validation failed"
                        })
                        return False
                else:
                    print_error(f"Query executed but returned 0 results - expected to find data")
                    print_metric("MongoDB Search", test_metrics['mongodb_search_ms'], "ms")
                    print_metric("Client Time", duration * 1000, "ms")
                    metrics.add_result(test_name, False, duration, {
                        "metrics": test_metrics,
                        "mode": mode,
                        "error": "No results found"
                    })
                    return False

                metrics.add_performance_data(f"Encrypted {field.title()} Search ({mode})", test_metrics)
                return True
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

def test_prefix_search(metrics, field, prefix, test_name, mode="hybrid"):
    """Test encrypted prefix search (Preview Feature)"""
    print_test_start(test_name)

    start_time = time.time()
    try:
        params = {field.replace("_", ""): prefix} if "_" in field else {"prefix": prefix}
        params["mode"] = mode

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

def test_substring_search(metrics, field, substring, test_name, mode="hybrid"):
    """Test encrypted substring search (Preview Feature)"""
    print_test_start(test_name)

    start_time = time.time()
    try:
        params = {field.replace("_", ""): substring} if "_" in field else {"substring": substring}
        params["mode"] = mode

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


def run_performance_tests(metrics, iterations=10):
    """Run performance tests with multiple iterations for all encrypted and AlloyDB operations"""
    print_header("Performance Testing")
    print_info(f"Running {iterations} iterations per test...")

    # Define all tests: (name, endpoint_type, field, query_type, param_name, value, mode)
    # endpoint_type: "search", "direct", "tier"
    # query_type: "equality", "prefix", "substring" (only for search)
    # param_name: the query parameter name to use in the URL
    # mode: "hybrid" or "mongodb_only"

    base_tests = [
        # Equality searches (phone, category, status)
        ("Phone Equality Search", "search", "phone", "equality", "phone", TEST_PHONE),
        ("Category Equality Search", "search", "category", "equality", "category", TEST_CATEGORY),
        ("Status Equality Search", "search", "status", "equality", "status", TEST_STATUS),

        # Prefix searches (email) - parameter name is always "prefix"
        ("Email Exact Match via Prefix", "search", "email", "prefix", "prefix", TEST_EMAIL),
        ("Email Prefix Search - Username", "search", "email", "prefix", "prefix", TEST_EMAIL.split('@')[0]),

        # Substring searches (name) - parameter name is always "substring"
        ("Encrypted Name Search", "search", "name", "substring", "substring", TEST_NAME[:10] if len(TEST_NAME) > 10 else TEST_NAME),
        ("Name Substring - First Name", "search", "name", "substring", "substring", TEST_NAME.split()[0][:10] if ' ' in TEST_NAME else TEST_NAME[:5]),
        ("Name Substring - Last Name", "search", "name", "substring", "substring", TEST_NAME.split()[-1][:10] if ' ' in TEST_NAME else TEST_NAME[-5:]),
        ("Name Substring - Partial Match", "search", "name", "substring", "substring", TEST_NAME[:4] if len(TEST_NAME) >= 4 else TEST_NAME[:2])
    ]

    # Duplicate tests for both modes
    tests = []
    for test_name, endpoint_type, field, query_type, param_name, test_value in base_tests:
        # Add hybrid mode version
        tests.append((f"{test_name} (Hybrid)", endpoint_type, field, query_type, param_name, test_value, "hybrid"))
        # Add mongodb_only mode version
        tests.append((f"{test_name} (MongoDB-Only)", endpoint_type, field, query_type, param_name, test_value, "mongodb_only"))

    results = {}

    for test_name, endpoint_type, field, query_type, param_name, test_value, mode in tests:
        print(f"\n{Colors.BOLD}{test_name}:{Colors.ENDC}")
        times = []

        for i in range(iterations):
            start = time.time()

            try:
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

def generate_html_report(metrics, perf_results, output_file, data_stats=None):
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

        <h2>Performance Metrics</h2>
    """

    if perf_results:
        html += """
        <table>
            <thead>
                <tr>
                    <th>Operation</th>
                    <th>Mode</th>
                    <th>Encryption Type</th>
                    <th>Average (ms)</th>
                    <th>Median (ms)</th>
                    <th>Min (ms)</th>
                    <th>Max (ms)</th>
                    <th>Std Dev</th>
                    <th>Samples</th>
                </tr>
            </thead>
            <tbody>
        """

        # Build encryption type lookup from performance_data
        encryption_type_map = {}
        for perf_data in metrics.performance_data:
            encryption_type_map[perf_data['operation']] = perf_data.get('encryption_type')

        for operation, stats in perf_results.items():
            mode_display = stats.get('mode', 'hybrid').replace('_', ' ').title()
            encryption_type = encryption_type_map.get(operation)

            # Generate badge HTML
            if encryption_type:
                badge_class = f"badge-{encryption_type}"
                badge_html = f'<span class="encryption-badge {badge_class}">{encryption_type}</span>'
            else:
                badge_html = '<span class="encryption-badge badge-none">None</span>'

            html += f"""
                <tr>
                    <td>{operation}</td>
                    <td>{mode_display}</td>
                    <td>{badge_html}</td>
                    <td>{stats['average']:.2f}</td>
                    <td>{stats['median']:.2f}</td>
                    <td>{stats['min']:.2f}</td>
                    <td>{stats['max']:.2f}</td>
                    <td>{stats['stddev']:.2f}</td>
                    <td>{stats['samples']}</td>
                </tr>
            """

        html += """
            </tbody>
        </table>

        <h2>Mode Comparison</h2>
        <p>This section shows side-by-side performance comparison between Hybrid and MongoDB-Only modes.</p>
        <table>
            <thead>
                <tr>
                    <th>Operation</th>
                    <th>Hybrid Avg (ms)</th>
                    <th>MongoDB-Only Avg (ms)</th>
                    <th>Difference (ms)</th>
                    <th>% Change</th>
                </tr>
            </thead>
            <tbody>
        """

        # Group results by base operation name
        comparisons = {}
        for operation, stats in perf_results.items():
            # Extract base name by removing mode suffix
            base_name = operation.replace(" (Hybrid)", "").replace(" (MongoDB-Only)", "")
            if base_name not in comparisons:
                comparisons[base_name] = {}
            if "(Hybrid)" in operation:
                comparisons[base_name]['hybrid'] = stats['average']
            elif "(MongoDB-Only)" in operation:
                comparisons[base_name]['mongodb_only'] = stats['average']

        # Generate comparison rows
        for base_name, modes in comparisons.items():
            if 'hybrid' in modes and 'mongodb_only' in modes:
                hybrid_avg = modes['hybrid']
                mongo_avg = modes['mongodb_only']
                diff = mongo_avg - hybrid_avg
                pct_change = (diff / hybrid_avg * 100) if hybrid_avg > 0 else 0

                # Color code based on performance
                color_style = ""
                if diff < 0:
                    color_style = "style='background-color: #d4edda;'"  # Green for faster
                elif diff > hybrid_avg * 0.1:  # More than 10% slower
                    color_style = "style='background-color: #f8d7da;'"  # Red for significantly slower

                html += f"""
                    <tr {color_style}>
                        <td>{base_name}</td>
                        <td>{hybrid_avg:.2f}</td>
                        <td>{mongo_avg:.2f}</td>
                        <td>{diff:+.2f}</td>
                        <td>{pct_change:+.1f}%</td>
                    </tr>
                """

        html += """
            </tbody>
        </table>
        <p style="margin-top: 10px; font-size: 12px; color: #666;">
            <strong>Note:</strong> Green rows indicate MongoDB-Only is faster. Red rows indicate MongoDB-Only is significantly slower (>10%).
            Positive values mean MongoDB-Only took longer; negative values mean it was faster.
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

def validate_data_availability():
    """Validate that sufficient test data exists before running tests"""
    import psycopg2

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
    import subprocess
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

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Run POC tests with real-time metrics")
    parser.add_argument('--quick', action='store_true', help='Run quick tests only')
    parser.add_argument('--performance', action='store_true', help='Run performance tests only')
    parser.add_argument('--iterations', type=int, default=100, help='Performance test iterations (default: 100)')
    parser.add_argument('--report', default='test_report.html', help='Output report file')
    parser.add_argument('--skip-validation', action='store_true', help='Skip data validation check')
    args = parser.parse_args()

    print_header("POC Test Suite")
    print_info(f"API Endpoint: {API_BASE_URL}")
    print_info(f"Test Mode: {'Quick' if args.quick else 'Performance' if args.performance else 'Full'}")

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

    # Quick/Functional Tests
    if not args.performance:
        print_header("Functional Tests")

        # Test 1: Health Check
        test_health_check(metrics)

        print_header("Equality Query Tests - Hybrid Mode")

        # Test 2: Phone Equality Search (Hybrid)
        test_encrypted_search(metrics, "phone", TEST_PHONE, "Phone Equality Search (Hybrid)", "hybrid")

        # Test 3: Category Equality Search (Hybrid)
        test_encrypted_search(metrics, "category", TEST_CATEGORY, "Category Equality Search (Hybrid)", "hybrid")

        # Test 4: Status Equality Search (Hybrid)
        test_encrypted_search(metrics, "status", TEST_STATUS, "Status Equality Search (Hybrid)", "hybrid")

        print_header("Equality Query Tests - MongoDB-Only Mode")

        # Test 5: Phone Equality Search (MongoDB-Only)
        test_encrypted_search(metrics, "phone", TEST_PHONE, "Phone Equality Search (MongoDB-Only)", "mongodb_only")

        # Test 6: Category Equality Search (MongoDB-Only)
        test_encrypted_search(metrics, "category", TEST_CATEGORY, "Category Equality Search (MongoDB-Only)", "mongodb_only")

        # Test 7: Status Equality Search (MongoDB-Only)
        test_encrypted_search(metrics, "status", TEST_STATUS, "Status Equality Search (MongoDB-Only)", "mongodb_only")

        print_header("Preview Feature Tests - Prefix Queries (Hybrid Mode)")

        # Test 8: Email Exact Match (full-value prefix) - Hybrid
        test_prefix_search(metrics, "email", TEST_EMAIL, "Email Exact Match via Prefix (Hybrid)", "hybrid")

        # Test 9: Email Partial Prefix (username search) - Hybrid
        test_prefix_search(metrics, "email", TEST_EMAIL.split('@')[0][:4], "Email Prefix Search - Username (Hybrid)", "hybrid")

        print_header("Preview Feature Tests - Prefix Queries (MongoDB-Only Mode)")

        # Test 10: Email Exact Match (full-value prefix) - MongoDB-Only
        test_prefix_search(metrics, "email", TEST_EMAIL, "Email Exact Match via Prefix (MongoDB-Only)", "mongodb_only")

        # Test 11: Email Partial Prefix (username search) - MongoDB-Only
        test_prefix_search(metrics, "email", TEST_EMAIL.split('@')[0][:4], "Email Prefix Search - Username (MongoDB-Only)", "mongodb_only")

        print_header("Preview Feature Tests - Substring Queries (Hybrid Mode)")

        # Test 12: Name First Name Search - Hybrid
        test_substring_search(metrics, "name", TEST_NAME.split()[0], "Name Substring - First Name (Hybrid)", "hybrid")

        # Test 13: Name Last Name Search - Hybrid
        test_substring_search(metrics, "name", TEST_NAME.split()[-1], "Name Substring - Last Name (Hybrid)", "hybrid")

        # Test 14: Name Partial Search - Hybrid
        test_substring_search(metrics, "name", TEST_NAME.split()[0][:3], "Name Substring - Partial Match (Hybrid)", "hybrid")

        print_header("Preview Feature Tests - Substring Queries (MongoDB-Only Mode)")

        # Test 15: Name First Name Search - MongoDB-Only
        test_substring_search(metrics, "name", TEST_NAME.split()[0], "Name Substring - First Name (MongoDB-Only)", "mongodb_only")

        # Test 16: Name Last Name Search - MongoDB-Only
        test_substring_search(metrics, "name", TEST_NAME.split()[-1], "Name Substring - Last Name (MongoDB-Only)", "mongodb_only")

        # Test 17: Name Partial Search - MongoDB-Only
        test_substring_search(metrics, "name", TEST_NAME.split()[0][:3], "Name Substring - Partial Match (MongoDB-Only)", "mongodb_only")

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
    if not args.quick:
        perf_results = run_performance_tests(metrics, args.iterations)

    # Generate Report
    print_header("Test Summary")

    summary = metrics.get_summary()

    print(f"{Colors.BOLD}Results:{Colors.ENDC}")
    print(f"  Total Tests:    {summary['total_tests']}")
    print(f"  Passed:         {Colors.OKGREEN}{summary['passed']}{Colors.ENDC}")
    print(f"  Failed:         {Colors.FAIL if summary['failed'] > 0 else Colors.OKGREEN}{summary['failed']}{Colors.ENDC}")
    print(f"  Pass Rate:      {summary['pass_rate']:.1f}%")
    print(f"  Total Duration: {summary['total_duration']:.2f}s")

    # Generate HTML report
    generate_html_report(metrics, perf_results, args.report, data_stats)

    print()
    if summary['failed'] == 0:
        print(f"{Colors.OKGREEN}{Colors.BOLD}All tests passed!{Colors.ENDC}")
        sys.exit(0)
    else:
        print(f"{Colors.FAIL}{Colors.BOLD}[WARNING] {summary['failed']} test(s) failed{Colors.ENDC}")
        sys.exit(1)

if __name__ == "__main__":
    main()
