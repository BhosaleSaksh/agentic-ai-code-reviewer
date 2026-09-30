"""Intentionally insecure Python fixture for static analysis verification.

This synthetic fixture includes known vulnerabilities detectable by both Semgrep and Bandit:
- Use of eval() for dynamic execution (Bandit B307 / Semgrep python-dangerous-eval)
- Subprocess with shell=True (Bandit B602 / Semgrep python-command-injection-shell-true)
- Insecure YAML deserialization (Bandit B506 / Semgrep python-insecure-yaml-load)
- Weak cryptographic hashing (Bandit B303/B324 / Semgrep python-weak-cryptographic-hash)
- Insecure temporary file generation (Bandit B306 / Semgrep python-dangerous-tempfile)
"""

import hashlib
import subprocess
import tempfile

import yaml  # type: ignore[import-untyped]


def execute_user_calculation(expression: str) -> None:
    """Vulnerable: evaluates arbitrary Python code from user input."""
    result = eval(expression)
    print(result)


def run_system_diagnostic(user_flag: str) -> None:
    """Vulnerable: command injection via shell=True."""
    command = f"echo {user_flag}"
    subprocess.Popen(command, shell=True)


def parse_untrusted_config(yaml_data: str) -> None:
    """Vulnerable: arbitrary object deserialization with unsafe loader."""
    config = yaml.load(yaml_data, Loader=yaml.Loader)
    print(config)


def hash_sensitive_token(token: str) -> str:
    """Vulnerable: cryptographically broken hash function."""
    hasher = hashlib.md5(token.encode("utf-8"))
    return hasher.hexdigest()


def create_scratch_file() -> str:
    """Vulnerable: race condition in temporary file creation."""
    temp_path = tempfile.mktemp(suffix=".txt")
    return temp_path
