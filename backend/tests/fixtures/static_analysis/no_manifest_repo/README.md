# No Dependency Manifest Fixture

This synthetic test repository contains Python code but no dependency declaration files
(no `requirements.txt`, `pyproject.toml`, `Pipfile`, or `setup.py`).
PipAuditRunner should return `StaticAnalysisExecutionStatus.NOT_APPLICABLE`.
