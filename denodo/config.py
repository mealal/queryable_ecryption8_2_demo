"""
Denodo Configuration
Centralized configuration for Denodo integration
"""

import os
from pathlib import Path

# Denodo License Configuration
DENODO_LICENSE_FILE = os.getenv('DENODO_LICENSE_FILE', 'denodo-express-lic-9-202511.lic')
DENODO_LICENSE_PATH = Path(__file__).parent.parent / DENODO_LICENSE_FILE

# Denodo Connection Settings
DENODO_HOST = os.getenv('DENODO_HOST', 'localhost')
DENODO_REST_PORT = int(os.getenv('DENODO_REST_PORT', '9090'))
DENODO_VDP_PORT = int(os.getenv('DENODO_VDP_PORT', '9999'))
DENODO_USER = os.getenv('DENODO_USER', 'admin')
DENODO_PASSWORD = os.getenv('DENODO_PASSWORD', 'admin')

# REST API Configuration
DENODO_BASE_URL = f"http://{DENODO_HOST}:{DENODO_REST_PORT}/denodo-restfulws/poc_integration"
DENODO_ADMIN_URL = f"http://{DENODO_HOST}:{DENODO_REST_PORT}/denodo-restfulws/admin"

# License Limitations (read from license file if needed)
MAX_SIMULTANEOUS_REQUESTS = int(os.getenv('DENODO_MAX_CONCURRENT', '3'))
MAX_ROWS_PER_QUERY = int(os.getenv('DENODO_MAX_ROWS', '10000'))

def get_license_info():
    """Extract license information from license file"""
    if not DENODO_LICENSE_PATH.exists():
        return None

    try:
        with open(DENODO_LICENSE_PATH, 'r') as f:
            content = f.read()

        info = {}
        for line in content.split('\n'):
            if '=' in line and not line.startswith('Signature'):
                key, value = line.split('=', 1)
                info[key.strip()] = value.strip()

        return info
    except Exception as e:
        print(f"Warning: Could not read license file: {e}")
        return None

def validate_license():
    """Validate license file exists and is readable"""
    if not DENODO_LICENSE_PATH.exists():
        raise FileNotFoundError(
            f"Denodo license file not found: {DENODO_LICENSE_PATH}\n"
            f"Set DENODO_LICENSE_FILE environment variable to specify a different file."
        )

    return True

# Export configuration
__all__ = [
    'DENODO_LICENSE_FILE',
    'DENODO_LICENSE_PATH',
    'DENODO_HOST',
    'DENODO_REST_PORT',
    'DENODO_VDP_PORT',
    'DENODO_USER',
    'DENODO_PASSWORD',
    'DENODO_BASE_URL',
    'DENODO_ADMIN_URL',
    'MAX_SIMULTANEOUS_REQUESTS',
    'MAX_ROWS_PER_QUERY',
    'get_license_info',
    'validate_license',
]
