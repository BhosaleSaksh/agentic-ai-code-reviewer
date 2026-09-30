"""Synthetic fixture for Semgrep-specific rule detection.

Contains:
- Hardcoded authentication token / API key
- Direct os.system command invocation
"""

import os

# Vulnerable: hardcoded API secret key
API_KEY = "api_key=sk_live_99887766554433221100aabbccddeeff"


def ping_host(host_ip: str) -> int:
    """Vulnerable: direct OS command execution without sanitization."""
    return os.system("ping -c 1 " + host_ip)
