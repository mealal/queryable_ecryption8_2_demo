"""
Denodo REST API Wrapper
Provides API-compatible interface to Denodo REST Web Services
Handles license limitations: MaxSimultaneousRequests=3, MaxRowsPerQuery=10000
"""

import requests
import json
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import threading

# Denodo Express License Limitations
MAX_SIMULTANEOUS_REQUESTS = 3
MAX_ROWS_PER_QUERY = 10000

# Semaphore to enforce concurrent request limit
request_semaphore = threading.Semaphore(MAX_SIMULTANEOUS_REQUESTS)

class DenodoLicenseLimiter:
    """Tracks Denodo license usage during test execution"""

    def __init__(self):
        self.total_requests = 0
        self.concurrent_requests = 0
        self.max_concurrent_reached = 0
        self.throttled_requests = 0
        self.requests_over_limit = []
        self.lock = threading.Lock()

    def acquire(self):
        """Acquire request slot, tracking concurrent usage"""
        acquired = request_semaphore.acquire(timeout=30)

        with self.lock:
            if not acquired:
                self.throttled_requests += 1
                return False

            self.concurrent_requests += 1
            self.total_requests += 1

            if self.concurrent_requests > self.max_concurrent_reached:
                self.max_concurrent_reached = self.concurrent_requests

            if self.concurrent_requests > MAX_SIMULTANEOUS_REQUESTS:
                self.requests_over_limit.append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'concurrent': self.concurrent_requests
                })

        return True

    def release(self):
        """Release request slot"""
        with self.lock:
            self.concurrent_requests = max(0, self.concurrent_requests - 1)
        request_semaphore.release()

    def get_stats(self) -> Dict[str, Any]:
        """Get license usage statistics"""
        with self.lock:
            return {
                'total_requests': self.total_requests,
                'max_concurrent_requests': self.max_concurrent_reached,
                'throttled_requests': self.throttled_requests,
                'license_violations': len(self.requests_over_limit),
                'max_allowed_concurrent': MAX_SIMULTANEOUS_REQUESTS,
                'max_rows_per_query': MAX_ROWS_PER_QUERY
            }

    def reset(self):
        """Reset statistics"""
        with self.lock:
            self.total_requests = 0
            self.concurrent_requests = 0
            self.max_concurrent_reached = 0
            self.throttled_requests = 0
            self.requests_over_limit = []

# Global license limiter instance
license_limiter = DenodoLicenseLimiter()


class DenodoClient:
    """Client for Denodo REST API"""

    def __init__(self, base_url: str = "http://localhost:9090/denodo-restfulws/poc_integration/views"):
        self.base_url = base_url
        self.session = requests.Session()
        # Denodo Basic Auth (default admin credentials)
        self.session.auth = ('admin', 'admin')
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })

    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> tuple[List[Dict], float, bool]:
        """
        Make request to Denodo REST API with license enforcement

        Returns:
            tuple: (results, duration_ms, throttled)
        """
        # Enforce concurrent request limit
        throttled = not license_limiter.acquire()

        if throttled:
            return [], 0.0, True

        try:
            start_time = time.time()

            # Denodo RESTful Web Service doesn't use $limit parameter
            # License limit enforcement happens at concurrent request level
            if params is None:
                params = {}

            # Request JSON format via headers (more reliable than $format param)
            headers = {'Accept': 'application/json'}

            response = self.session.get(
                f"{self.base_url}/{endpoint}",
                params=params,
                headers=headers,
                timeout=30
            )

            duration_ms = (time.time() - start_time) * 1000

            response.raise_for_status()

            # Parse Denodo REST API response
            data = response.json()

            # Denodo RESTful Web Service returns: {"name": "view_name", "elements": [...], "links": [...]}
            if isinstance(data, dict) and 'elements' in data:
                results = data['elements']
                # Apply max rows limit client-side
                if len(results) > MAX_ROWS_PER_QUERY:
                    results = results[:MAX_ROWS_PER_QUERY]
            elif isinstance(data, list):
                results = data[:MAX_ROWS_PER_QUERY]
            else:
                results = []

            return results, duration_ms, False

        except requests.exceptions.Timeout:
            raise TimeoutError("Denodo request timed out")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise ValueError(f"Denodo endpoint not found (404): {endpoint}. Views or REST services may not be created.")
            raise RuntimeError(f"Denodo HTTP error {e.response.status_code}: {e}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Denodo request error: {e}")
        finally:
            license_limiter.release()

    def search_by_email_prefix(self, prefix: str, data_source: str = "hybrid") -> tuple[List[Dict], float, bool]:
        """
        Search customers by email prefix

        Args:
            prefix: Email prefix to search for
            data_source: 'hybrid' (MongoDB search + AlloyDB data) or 'mongodb' (MongoDB-only)
        """
        # Query base view directly - Denodo filters by field equality
        # For prefix search, filter client-side since Denodo doesn't support LIKE in REST params
        results, duration, throttled = self._make_request(
            'bv_alloydb_customers',
            params={}  # Get all, filter client-side
        )
        # Client-side prefix filtering
        if results:
            results = [r for r in results if r.get('email', '').startswith(prefix)]
        return results, duration, throttled

    def search_by_name_substring(self, substring: str, data_source: str = "hybrid") -> tuple[List[Dict], float, bool]:
        """
        Search customers by name substring

        Args:
            substring: Name substring to search for
            data_source: 'hybrid' (MongoDB search + AlloyDB data) or 'mongodb' (MongoDB-only)
        """
        # Query base view directly - filter client-side for substring
        results, duration, throttled = self._make_request(
            'bv_alloydb_customers',
            params={}  # Get all, filter client-side
        )
        # Client-side substring filtering
        if results:
            results = [r for r in results if substring.lower() in r.get('full_name', '').lower()]
        return results, duration, throttled

    def search_by_phone(self, phone: str, data_source: str = "hybrid") -> tuple[List[Dict], float, bool]:
        """
        Search customers by exact phone match

        Args:
            phone: Phone number to search for
            data_source: 'hybrid' (MongoDB search + AlloyDB data) or 'mongodb' (MongoDB-only)
        """
        # Query base view directly with phone filter - Denodo supports exact field matching
        results, duration, throttled = self._make_request(
            'bv_alloydb_customers',
            params={'phone': phone}
        )
        return results, duration, throttled

    def search_by_category(self, category: str, data_source: str = "hybrid") -> tuple[List[Dict], float, bool]:
        """
        Search customers by category

        Args:
            category: Category to search for
            data_source: 'hybrid' (MongoDB search + AlloyDB data) or 'mongodb' (MongoDB-only)
        """
        endpoint_suffix = '_mongodb' if data_source == 'mongodb' else ''
        results, duration, throttled = self._make_request(
            f'category_search{endpoint_suffix}',
            params={'category': category}
        )
        return results, duration, throttled

    def search_by_status(self, status: str, data_source: str = "hybrid") -> tuple[List[Dict], float, bool]:
        """
        Search customers by status

        Args:
            status: Status to search for
            data_source: 'hybrid' (MongoDB search + AlloyDB data) or 'mongodb' (MongoDB-only)
        """
        endpoint_suffix = '_mongodb' if data_source == 'mongodb' else ''
        results, duration, throttled = self._make_request(
            f'status_search{endpoint_suffix}',
            params={'status': status}
        )
        return results, duration, throttled

    def get_customer(self, customer_id: str) -> tuple[Optional[Dict], float, bool]:
        """Get customer by ID"""
        results, duration, throttled = self._make_request(
            'get_customer',
            params={'customer_id': customer_id}
        )

        if results and len(results) > 0:
            return results[0], duration, throttled
        return None, duration, throttled

    def health_check(self) -> Dict[str, Any]:
        """Check Denodo service health"""
        try:
            # Use admin ping endpoint
            response = self.session.get(
                "http://localhost:9090/denodo-restfulws/admin/ping",
                timeout=5
            )

            if response.status_code == 200:
                return {
                    'status': 'healthy',
                    'denodo': 'connected',
                    'license_stats': license_limiter.get_stats()
                }
            else:
                return {
                    'status': 'unhealthy',
                    'denodo': 'error',
                    'error': f'HTTP {response.status_code}'
                }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'denodo': 'disconnected',
                'error': str(e)
            }


def format_denodo_response(results: List[Dict], duration_ms: float, throttled: bool, data_source: str = "hybrid") -> Dict[str, Any]:
    """
    Format Denodo results to match existing API response structure

    Args:
        results: Denodo query results
        duration_ms: Query duration in milliseconds
        throttled: Whether request was throttled
        data_source: 'hybrid' (MongoDB+AlloyDB) or 'mongodb' (MongoDB-only)
    """

    customers = []
    for row in results:
        # Parse JSON fields if they're strings
        address = row.get('address')
        if isinstance(address, str):
            try:
                address = json.loads(address)
            except:
                pass

        preferences = row.get('preferences')
        if isinstance(preferences, str):
            try:
                preferences = json.loads(preferences)
            except:
                pass

        customer = {
            'customer_id': row.get('customer_id'),
            'full_name': row.get('full_name'),
            'email': row.get('email'),
            'phone': row.get('phone'),
            'address': address,
            'preferences': preferences,
            'tier': row.get('tier'),
            'loyalty_points': row.get('loyalty_points'),
            'last_purchase_date': row.get('last_purchase_date'),
            'lifetime_value': float(row.get('lifetime_value', 0))
        }
        customers.append(customer)

    return {
        'success': not throttled,
        'data': customers,
        'metrics': {
            'denodo_query_ms': duration_ms,
            'total_ms': duration_ms,
            'results_count': len(customers),
            'mode': 'denodo',
            'data_source': data_source.upper(),
            'throttled': throttled,
            'license_warning': len(customers) >= MAX_ROWS_PER_QUERY
        },
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
