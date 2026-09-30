"""API v1 router aggregator.

Collects and includes all v1 endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.webhooks import router as webhooks_router

v1_router = APIRouter()

# Include health routes directly under /api/v1 (e.g. /api/v1/health and /api/v1/health/ready)
v1_router.include_router(health_router)

# Include GitHub webhook receiver under /api/v1/webhooks/github
v1_router.include_router(webhooks_router)
