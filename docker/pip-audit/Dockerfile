FROM python:3.12-slim

# Create non-root user (UID 1000)
RUN useradd -u 1000 -m appuser

# Install pinned pip-audit and dependencies
RUN pip install --no-cache-dir pip-audit==2.7.3

USER 1000:1000
WORKDIR /workspace

ENTRYPOINT ["pip-audit"]
