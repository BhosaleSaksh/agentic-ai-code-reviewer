"""API v1 router aggregator.

Collects and includes all v1 endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.findings import router as findings_router
from app.api.v1.health import router as health_router
from app.api.v1.pull_requests import router as pull_requests_router
from app.api.v1.repositories import router as repositories_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.webhooks import router as webhooks_router

v1_router = APIRouter()

# Include health routes directly under /api/v1 (e.g. /api/v1/health and /api/v1/health/ready)
v1_router.include_router(health_router)

# Include GitHub webhook receiver under /api/v1/webhooks/github
v1_router.include_router(webhooks_router)

# Phase 6 Review Dashboard read routers
v1_router.include_router(dashboard_router)
v1_router.include_router(repositories_router)
v1_router.include_router(pull_requests_router)
v1_router.include_router(reviews_router)
v1_router.include_router(findings_router)
v1_router.include_router(feedback_router)
