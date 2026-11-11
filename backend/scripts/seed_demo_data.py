"""Seed a rich, presentation-grade demonstration dataset for the Review Observability Dashboard.

Populates multiple repositories, pull requests, review executions (completed and active),
verified and critic-rejected findings, static analysis evidence (Bandit, Semgrep, pip-audit),
publication audit trails, and developer feedback events.
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import delete
from app.database.models.evidence_item import EvidenceItem
from app.database.models.feedback import ReviewFeedback
from app.database.models.finding import Finding
from app.database.models.publication import ReviewPublication
from app.database.models.pull_request import PullRequest
from app.database.models.repository import Repository
from app.database.models.review_run import ReviewRun
from app.database.session import get_db_session
from app.schemas.enums import (
    EvidenceType,
    FeedbackSource,
    FeedbackType,
    FindingSide,
    IssueType,
    PublishStatus,
    Severity,
    VerificationStatus,
)


async def seed_presentation_dataset() -> None:
    now = datetime.now(UTC)

    async for session in get_db_session():
        print("Clearing previous demo records...")
        # Cascade deletion through Repository
        await session.execute(delete(ReviewFeedback))
        await session.execute(delete(ReviewPublication))
        await session.execute(delete(EvidenceItem))
        await session.execute(delete(Finding))
        await session.execute(delete(ReviewRun))
        await session.execute(delete(PullRequest))
        await session.execute(delete(Repository))
        await session.flush()

        print("Seeding 5 repositories...")
        # 1. Repositories
        repo_core = Repository(
            id=uuid.uuid4(),
            github_repo_id=987654321,
            full_name="enterprise-ai/core-services",
            default_branch="main",
            is_active=True,
            created_at=now - timedelta(days=60),
        )
        repo_payment = Repository(
            id=uuid.uuid4(),
            github_repo_id=987654322,
            full_name="enterprise-ai/payment-gateway",
            default_branch="main",
            is_active=True,
            created_at=now - timedelta(days=45),
        )
        repo_data = Repository(
            id=uuid.uuid4(),
            github_repo_id=987654323,
            full_name="enterprise-ai/data-pipeline",
            default_branch="main",
            is_active=True,
            created_at=now - timedelta(days=30),
        )
        repo_auth = Repository(
            id=uuid.uuid4(),
            github_repo_id=987654324,
            full_name="enterprise-ai/auth-service",
            default_branch="main",
            is_active=True,
            created_at=now - timedelta(days=40),
        )
        repo_frontend = Repository(
            id=uuid.uuid4(),
            github_repo_id=987654325,
            full_name="enterprise-ai/web-frontend",
            default_branch="main",
            is_active=True,
            created_at=now - timedelta(days=20),
        )
        session.add_all([repo_core, repo_payment, repo_data, repo_auth, repo_frontend])
        await session.flush()

        print("Seeding pull requests...")
        # 2. Pull Requests
        # Core Services PRs
        pr_auth_jwt = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_core.id,
            pr_number=104,
            title="feat(auth): migrate token generation to asymmetric JWT keys",
            author="octocat",
            base_sha="a1b2c3d4e5f60000000000000000000000000001",
            head_sha="a1b2c3d4e5f60000000000000000000000000002",
            state="open",
            additions=142,
            deletions=28,
            changed_files_count=4,
            created_at=now - timedelta(hours=36),
        )
        pr_db_optimize = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_core.id,
            pr_number=89,
            title="refactor(db): optimize user query with composite index & connection pooling",
            author="sarah-dev",
            base_sha="b2c3d4e5f6a10000000000000000000000000001",
            head_sha="b2c3d4e5f6a10000000000000000000000000002",
            state="open",
            additions=84,
            deletions=35,
            changed_files_count=3,
            created_at=now - timedelta(days=2),
        )

        # Payment Gateway PRs
        pr_idempotency = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_payment.id,
            pr_number=218,
            title="fix(payment): prevent race condition during idempotency validation",
            author="alex-chen",
            base_sha="c3d4e5f6a1b20000000000000000000000000001",
            head_sha="c3d4e5f6a1b20000000000000000000000000002",
            state="open",
            additions=215,
            deletions=42,
            changed_files_count=5,
            created_at=now - timedelta(hours=18),
        )
        pr_stripe = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_payment.id,
            pr_number=405,
            title="feat(billing): integrate stripe webhook signature verification",
            author="alex-chen",
            base_sha="d4e5f6a1b2c30000000000000000000000000001",
            head_sha="d4e5f6a1b2c30000000000000000000000000002",
            state="open",
            additions=96,
            deletions=12,
            changed_files_count=2,
            created_at=now - timedelta(days=3),
        )

        # Data Pipeline PRs
        pr_batch = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_data.id,
            pr_number=163,
            title="perf(pipeline): batch database writes in streaming consumer",
            author="marcus-k",
            base_sha="e5f6a1b2c3d40000000000000000000000000001",
            head_sha="e5f6a1b2c3d40000000000000000000000000002",
            state="open",
            additions=320,
            deletions=75,
            changed_files_count=6,
            created_at=now - timedelta(hours=28),
        )
        pr_redis_worker = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_data.id,
            pr_number=77,
            title="fix(worker): handle deserialization error on malformed redis payload",
            author="marcus-k",
            base_sha="f6a1b2c3d4e50000000000000000000000000001",
            head_sha="f6a1b2c3d4e50000000000000000000000000002",
            state="open",
            additions=62,
            deletions=18,
            changed_files_count=2,
            created_at=now - timedelta(days=4),
        )

        # Auth Service PRs
        pr_rbac = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_auth.id,
            pr_number=92,
            title="feat(rbac): implement fine-grained role-based access control",
            author="priya-sharma",
            base_sha="a2b3c4d5e6f10000000000000000000000000001",
            head_sha="a2b3c4d5e6f10000000000000000000000000002",
            state="open",
            additions=480,
            deletions=64,
            changed_files_count=8,
            created_at=now - timedelta(hours=14),
        )
        pr_replay = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_auth.id,
            pr_number=115,
            title="test(security): add regression tests for replay attack prevention",
            author="priya-sharma",
            base_sha="b3c4d5e6f1a20000000000000000000000000001",
            head_sha="b3c4d5e6f1a20000000000000000000000000002",
            state="open",
            additions=175,
            deletions=20,
            changed_files_count=4,
            created_at=now - timedelta(hours=48),
        )
        pr_deps = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_auth.id,
            pr_number=120,
            title="chore(deps): bump cryptographic libraries to remediate CVE-2024-34064",
            author="dependabot[bot]",
            base_sha="c4d5e6f1a2b30000000000000000000000000001",
            head_sha="c4d5e6f1a2b30000000000000000000000000002",
            state="open",
            additions=14,
            deletions=14,
            changed_files_count=2,
            created_at=now - timedelta(days=5),
        )

        # Frontend PRs
        pr_xss = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_frontend.id,
            pr_number=312,
            title="fix(ui): sanitize user comment rendering in markdown parser",
            author="dev-jordan",
            base_sha="d5e6f1a2b3c40000000000000000000000000001",
            head_sha="d5e6f1a2b3c40000000000000000000000000002",
            state="open",
            additions=45,
            deletions=18,
            changed_files_count=3,
            created_at=now - timedelta(hours=6),
        )
        pr_stream = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo_frontend.id,
            pr_number=325,
            title="feat(dashboard): add real-time websocket metrics stream",
            author="dev-jordan",
            base_sha="e6f1a2b3c4d50000000000000000000000000001",
            head_sha="e6f1a2b3c4d50000000000000000000000000002",
            state="open",
            additions=195,
            deletions=22,
            changed_files_count=5,
            created_at=now - timedelta(minutes=45),
        )

        session.add_all([
            pr_auth_jwt, pr_db_optimize, pr_idempotency, pr_stripe,
            pr_batch, pr_redis_worker, pr_rbac, pr_replay, pr_deps,
            pr_xss, pr_stream
        ])
        await session.flush()

        print("Seeding review runs...")
        # 3. Review Runs
        run1 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_auth_jwt.id,
            commit_sha=pr_auth_jwt.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=2450,
            total_cost_usd=Decimal("0.0049"),
            latency_seconds=Decimal("8.20"),
            review_plan={"focus": "security_and_logic", "specialists": ["security", "bug_logic", "error_handling"]},
            started_at=now - timedelta(hours=35, minutes=50),
            completed_at=now - timedelta(hours=35, minutes=42),
            created_at=now - timedelta(hours=35, minutes=50),
        )
        run2 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_idempotency.id,
            commit_sha=pr_idempotency.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=3820,
            total_cost_usd=Decimal("0.0076"),
            latency_seconds=Decimal("11.40"),
            review_plan={"focus": "concurrency_and_data_integrity", "specialists": ["bug_logic", "security", "test_adequacy"]},
            started_at=now - timedelta(hours=17, minutes=45),
            completed_at=now - timedelta(hours=17, minutes=34),
            created_at=now - timedelta(hours=17, minutes=45),
        )
        run3 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_rbac.id,
            commit_sha=pr_rbac.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=4210,
            total_cost_usd=Decimal("0.0084"),
            latency_seconds=Decimal("12.10"),
            review_plan={"focus": "authorization_and_access_control", "specialists": ["security", "bug_logic", "test_adequacy"]},
            started_at=now - timedelta(hours=13, minutes=30),
            completed_at=now - timedelta(hours=13, minutes=18),
            created_at=now - timedelta(hours=13, minutes=30),
        )
        run4 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_batch.id,
            commit_sha=pr_batch.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=3120,
            total_cost_usd=Decimal("0.0062"),
            latency_seconds=Decimal("9.60"),
            review_plan={"focus": "resource_management_and_io", "specialists": ["performance", "bug_logic", "error_handling"]},
            started_at=now - timedelta(hours=27, minutes=20),
            completed_at=now - timedelta(hours=27, minutes=10),
            created_at=now - timedelta(hours=27, minutes=20),
        )
        run5 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_xss.id,
            commit_sha=pr_xss.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=2100,
            total_cost_usd=Decimal("0.0042"),
            latency_seconds=Decimal("6.40"),
            review_plan={"focus": "xss_sanitization_and_ui", "specialists": ["security", "maintainability"]},
            started_at=now - timedelta(hours=5, minutes=50),
            completed_at=now - timedelta(hours=5, minutes=44),
            created_at=now - timedelta(hours=5, minutes=50),
        )
        run6 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_redis_worker.id,
            commit_sha=pr_redis_worker.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=1450,
            total_cost_usd=Decimal("0.0029"),
            latency_seconds=Decimal("4.90"),
            review_plan={"focus": "deserialization_safety", "specialists": ["security", "error_handling"]},
            started_at=now - timedelta(days=3, hours=22),
            completed_at=now - timedelta(days=3, hours=21, minutes=55),
            created_at=now - timedelta(days=3, hours=22),
        )
        run7 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_stripe.id,
            commit_sha=pr_stripe.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=2240,
            total_cost_usd=Decimal("0.0045"),
            latency_seconds=Decimal("7.80"),
            review_plan={"focus": "webhook_signature_integrity", "specialists": ["security", "bug_logic"]},
            started_at=now - timedelta(days=2, hours=20),
            completed_at=now - timedelta(days=2, hours=19, minutes=52),
            created_at=now - timedelta(days=2, hours=20),
        )
        run8 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_replay.id,
            commit_sha=pr_replay.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=1850,
            total_cost_usd=Decimal("0.0037"),
            latency_seconds=Decimal("5.80"),
            review_plan={"focus": "test_adequacy_replay", "specialists": ["test_adequacy", "security"]},
            started_at=now - timedelta(hours=47, minutes=30),
            completed_at=now - timedelta(hours=47, minutes=24),
            created_at=now - timedelta(hours=47, minutes=30),
        )
        run9 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_db_optimize.id,
            commit_sha=pr_db_optimize.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=1680,
            total_cost_usd=Decimal("0.0033"),
            latency_seconds=Decimal("5.10"),
            review_plan={"focus": "database_connection_safety", "specialists": ["bug_logic", "performance"]},
            started_at=now - timedelta(days=1, hours=22),
            completed_at=now - timedelta(days=1, hours=21, minutes=55),
            created_at=now - timedelta(days=1, hours=22),
        )
        run10 = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_deps.id,
            commit_sha=pr_deps.head_sha,
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=1100,
            total_cost_usd=Decimal("0.0022"),
            latency_seconds=Decimal("4.20"),
            review_plan={"focus": "dependency_audit", "specialists": ["security"]},
            started_at=now - timedelta(days=4, hours=23),
            completed_at=now - timedelta(days=4, hours=22, minutes=56),
            created_at=now - timedelta(days=4, hours=23),
        )
        # Active Review Run (shows "1 active / running" on the dashboard!)
        run_active = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr_stream.id,
            commit_sha=pr_stream.head_sha,
            status="RUNNING",
            trigger_type="WEBHOOK",
            total_tokens=1950,
            total_cost_usd=Decimal("0.0039"),
            latency_seconds=None,
            review_plan={"focus": "streaming_websocket_concurrency", "specialists": ["security", "bug_logic", "performance"]},
            started_at=now - timedelta(minutes=15),
            completed_at=None,
            created_at=now - timedelta(minutes=15),
        )

        session.add_all([
            run1, run2, run3, run4, run5, run6, run7, run8, run9, run10, run_active
        ])
        await session.flush()

        print("Seeding findings, evidence, publications, and feedback...")
        # 4. Findings & Evidence
        # --- Run 1 (JWT Auth) ---
        f1 = Finding(
            id=uuid.uuid4(),
            review_run_id=run1.id,
            agent_name="SecurityAgent",
            issue_type=IssueType.SECURITY.value,
            severity=Severity.HIGH.value,
            file_path="app/auth/tokens.py",
            line_number=14,
            side=FindingSide.RIGHT.value,
            title="Hardcoded JWT Secret Key (CWE-321)",
            explanation="Cryptographic token signing key is hardcoded directly in repository source code, compromising confidentiality.",
            recommendation="Load secret from environment variable (`os.environ['JWT_SECRET_KEY']`) or external secret vault.",
            confidence_score=0.96,
            raw_confidence=0.94,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98711223,
            created_at=run1.started_at + timedelta(seconds=4),
        )
        f2 = Finding(
            id=uuid.uuid4(),
            review_run_id=run1.id,
            agent_name="ErrorHandlingAgent",
            issue_type=IssueType.ERROR_HANDLING.value,
            severity=Severity.LOW.value,
            file_path="app/auth/utils.py",
            line_number=42,
            side=FindingSide.RIGHT.value,
            title="Missing generic Exception catch handler",
            explanation="Broad except block suggested for rare I/O errors.",
            recommendation="Catch specific exceptions instead of broad pass.",
            confidence_score=0.45,
            raw_confidence=0.55,
            verification_status=VerificationStatus.REJECTED.value,
            rejection_reason="Suppressed by Critic: catching specific exceptions is already handled in caller context.",
            publish_status=PublishStatus.UNPUBLISHED.value,
            created_at=run1.started_at + timedelta(seconds=6),
        )
        session.add_all([f1, f2])
        await session.flush()

        ev1 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run1.id,
            finding_id=f1.id,
            evidence_type=EvidenceType.STATIC_ANALYSIS.value,
            file_path="app/auth/tokens.py",
            start_line=13,
            end_line=15,
            content_snippet="SECRET_KEY = 'hardcoded_jwt_secret_key_12345'",
            rule_or_cve_id="bandit.B105.hardcoded_password_string",
            corroborating_tool="bandit",
            created_at=run1.started_at + timedelta(seconds=5),
        )
        pub1 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run1.id,
            finding_id=f1.id,
            repository_id=repo_core.github_repo_id,
            pr_number=pr_auth_jwt.pr_number,
            commit_sha=run1.commit_sha,
            idempotency_key=f"{repo_core.github_repo_id}:{pr_auth_jwt.pr_number}:{f1.id}:{run1.commit_sha}",
            github_comment_id=98711223,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run1.completed_at,
            created_at=run1.completed_at,
        )
        fb1 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f1.id,
            review_run_id=run1.id,
            repository_id=repo_core.github_repo_id,
            pr_number=pr_auth_jwt.pr_number,
            feedback_type=FeedbackType.REACTION_POSITIVE.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="octocat",
            comment_body="Great catch! Removed the hardcoded secret.",
            created_at=run1.completed_at + timedelta(minutes=12),
        )
        session.add_all([ev1, pub1, fb1])

        # --- Run 2 (Payment Gateway Concurrency & Race Condition) ---
        f3 = Finding(
            id=uuid.uuid4(),
            review_run_id=run2.id,
            agent_name="BugLogicAgent",
            issue_type=IssueType.BUG_LOGIC.value,
            severity=Severity.CRITICAL.value,
            file_path="services/payment/processor.py",
            line_number=88,
            side=FindingSide.RIGHT.value,
            title="TOCTOU Race Condition in Idempotency Check (CWE-367)",
            explanation="Idempotency key query and subsequent charge creation are not atomic. Concurrent duplicate requests bypass validation, leading to double charging.",
            recommendation="Wrap the validation in an atomic transaction with `SELECT ... FOR UPDATE` or acquire a distributed Redis lock using `SETNX` before processing.",
            confidence_score=0.98,
            raw_confidence=0.95,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98720101,
            created_at=run2.started_at + timedelta(seconds=7),
        )
        f4 = Finding(
            id=uuid.uuid4(),
            review_run_id=run2.id,
            agent_name="TestAdequacyAgent",
            issue_type=IssueType.TEST_ADEQUACY.value,
            severity=Severity.MEDIUM.value,
            file_path="tests/test_processor.py",
            line_number=145,
            side=FindingSide.RIGHT.value,
            title="Missing Concurrency Test for Double-Spend Prevention",
            explanation="PR touches sensitive payment execution path without regression tests asserting mutual exclusion under concurrent requests.",
            recommendation="Add parameterized `pytest-asyncio` test executing 10 concurrent requests with identical idempotency key, verifying only one charge succeeds.",
            confidence_score=0.91,
            raw_confidence=0.88,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98720102,
            created_at=run2.started_at + timedelta(seconds=8),
        )
        f5 = Finding(
            id=uuid.uuid4(),
            review_run_id=run2.id,
            agent_name="ErrorHandlingAgent",
            issue_type=IssueType.ERROR_HANDLING.value,
            severity=Severity.HIGH.value,
            file_path="services/payment/client.py",
            line_number=54,
            side=FindingSide.RIGHT.value,
            title="Catching BaseException Suppresses Process Termination (CWE-396)",
            explanation="Catching `BaseException` intercepts `KeyboardInterrupt` and `SystemExit`, preventing graceful orchestration shutdown.",
            recommendation="Narrow exception handler to `except Exception:` or catch explicit `PaymentGatewayError` hierarchy.",
            confidence_score=0.94,
            raw_confidence=0.92,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98720103,
            created_at=run2.started_at + timedelta(seconds=9),
        )
        f6 = Finding(
            id=uuid.uuid4(),
            review_run_id=run2.id,
            agent_name="MaintainabilityAgent",
            issue_type=IssueType.MAINTAINABILITY.value,
            severity=Severity.LOW.value,
            file_path="services/payment/models.py",
            line_number=31,
            side=FindingSide.RIGHT.value,
            title="Redundant type annotation on local variable",
            explanation="Variable type is explicitly inferrable from right-hand assignment.",
            recommendation="Remove redundant type annotation.",
            confidence_score=0.38,
            raw_confidence=0.45,
            verification_status=VerificationStatus.REJECTED.value,
            rejection_reason="Suppressed by Critic: stylistic nitpick with zero impact on correctness or security.",
            publish_status=PublishStatus.UNPUBLISHED.value,
            created_at=run2.started_at + timedelta(seconds=10),
        )
        session.add_all([f3, f4, f5, f6])
        await session.flush()

        ev2 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run2.id,
            finding_id=f3.id,
            evidence_type=EvidenceType.AST_CONTEXT.value,
            file_path="services/payment/processor.py",
            start_line=85,
            end_line=92,
            content_snippet="if not db.has_key(idem_key):\n    # Gap allows concurrent thread here\n    db.insert_record(idem_key)\n    charge_card(amount)",
            rule_or_cve_id="ast.race_condition.toctou",
            corroborating_tool="ast_analyzer",
            created_at=run2.started_at + timedelta(seconds=8),
        )
        ev3 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run2.id,
            finding_id=f5.id,
            evidence_type=EvidenceType.STATIC_ANALYSIS.value,
            file_path="services/payment/client.py",
            start_line=53,
            end_line=56,
            content_snippet="except BaseException as e:\n    logger.error('Failed call: %s', e)\n    return None",
            rule_or_cve_id="bandit.B110.try_except_pass",
            corroborating_tool="bandit",
            created_at=run2.started_at + timedelta(seconds=9),
        )
        pub2 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run2.id,
            finding_id=f3.id,
            repository_id=repo_payment.github_repo_id,
            pr_number=pr_idempotency.pr_number,
            commit_sha=run2.commit_sha,
            idempotency_key=f"{repo_payment.github_repo_id}:{pr_idempotency.pr_number}:{f3.id}:{run2.commit_sha}",
            github_comment_id=98720101,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run2.completed_at,
            created_at=run2.completed_at,
        )
        fb2 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f3.id,
            review_run_id=run2.id,
            repository_id=repo_payment.github_repo_id,
            pr_number=pr_idempotency.pr_number,
            feedback_type=FeedbackType.COMMENT_RESOLVED.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="alex-chen",
            comment_body="Resolved: switched to Redis SETNX distributed lock with 30s TTL.",
            created_at=run2.completed_at + timedelta(minutes=24),
        )
        session.add_all([ev2, ev3, pub2, fb2])

        # --- Run 3 (RBAC Auth) ---
        f7 = Finding(
            id=uuid.uuid4(),
            review_run_id=run3.id,
            agent_name="SecurityAgent",
            issue_type=IssueType.SECURITY.value,
            severity=Severity.HIGH.value,
            file_path="app/security/rbac.py",
            line_number=112,
            side=FindingSide.RIGHT.value,
            title="Insecure Direct Object Reference (IDOR) on Tenant Scoping (CWE-639)",
            explanation="Endpoint queries resources using user-supplied query string `org_id` without verifying current user possesses membership in that organization.",
            recommendation="Enforce tenant isolation by retrieving authorized organization IDs directly from authenticated context `request.state.current_user.org_id`.",
            confidence_score=0.97,
            raw_confidence=0.96,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98740020,
            created_at=run3.started_at + timedelta(seconds=8),
        )
        f8 = Finding(
            id=uuid.uuid4(),
            review_run_id=run3.id,
            agent_name="TestAdequacyAgent",
            issue_type=IssueType.TEST_ADEQUACY.value,
            severity=Severity.MEDIUM.value,
            file_path="tests/test_rbac.py",
            line_number=80,
            side=FindingSide.RIGHT.value,
            title="Missing Negative Permission Assertions for READ_ONLY Roles",
            explanation="RBAC suite only verifies permitted access. No test verifies that unauthorized operations return HTTP 403 Forbidden.",
            recommendation="Add tests confirming that non-admin roles cannot invoke write/delete mutations.",
            confidence_score=0.89,
            raw_confidence=0.86,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98740021,
            created_at=run3.started_at + timedelta(seconds=9),
        )
        session.add_all([f7, f8])
        await session.flush()

        ev4 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run3.id,
            finding_id=f7.id,
            evidence_type=EvidenceType.STATIC_ANALYSIS.value,
            file_path="app/security/rbac.py",
            start_line=110,
            end_line=115,
            content_snippet="async def get_records(org_id: int):\n    return await db.query(Record).filter(Record.org_id == org_id).all()",
            rule_or_cve_id="semgrep.python.fastapi.security.unvalidated-tenant-access",
            corroborating_tool="semgrep",
            created_at=run3.started_at + timedelta(seconds=9),
        )
        pub3 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run3.id,
            finding_id=f7.id,
            repository_id=repo_auth.github_repo_id,
            pr_number=pr_rbac.pr_number,
            commit_sha=run3.commit_sha,
            idempotency_key=f"{repo_auth.github_repo_id}:{pr_rbac.pr_number}:{f7.id}:{run3.commit_sha}",
            github_comment_id=98740020,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run3.completed_at,
            created_at=run3.completed_at,
        )
        fb3 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f7.id,
            review_run_id=run3.id,
            repository_id=repo_auth.github_repo_id,
            pr_number=pr_rbac.pr_number,
            feedback_type=FeedbackType.FINDING_ACCEPTED.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="priya-sharma",
            comment_body="Crucial catch. Fixed in latest commit using token claims.",
            created_at=run3.completed_at + timedelta(minutes=45),
        )
        session.add_all([ev4, pub3, fb3])

        # --- Run 4 (Data Pipeline Batching & Buffer Leak) ---
        f9 = Finding(
            id=uuid.uuid4(),
            review_run_id=run4.id,
            agent_name="BugLogicAgent",
            issue_type=IssueType.BUG_LOGIC.value,
            severity=Severity.HIGH.value,
            file_path="pipeline/consumers/batch_writer.py",
            line_number=72,
            side=FindingSide.RIGHT.value,
            title="Unbounded In-Memory Buffer Overflow Risk (CWE-400)",
            explanation="Batching consumer appends incoming records to a Python list without a maximum limit, causing Out-Of-Memory termination under write latency spikes.",
            recommendation="Introduce a `max_buffer_size=5000` threshold that triggers an immediate synchronous flush or backpressure pause.",
            confidence_score=0.93,
            raw_confidence=0.90,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98730015,
            created_at=run4.started_at + timedelta(seconds=7),
        )
        f10 = Finding(
            id=uuid.uuid4(),
            review_run_id=run4.id,
            agent_name="PerformanceAgent",
            issue_type=IssueType.PERFORMANCE.value,
            severity=Severity.LOW.value,
            file_path="pipeline/consumers/batch_writer.py",
            line_number=104,
            side=FindingSide.RIGHT.value,
            title="Speculative CPU Bottleneck Assertion",
            explanation="Suggested converting list comprehension to generator expression for micro-optimizing memory.",
            recommendation="Use generator expressions everywhere.",
            confidence_score=0.42,
            raw_confidence=0.50,
            verification_status=VerificationStatus.REJECTED.value,
            rejection_reason="Suppressed by Critic: uncorroborated speculative micro-optimization without profiler justification.",
            publish_status=PublishStatus.UNPUBLISHED.value,
            created_at=run4.started_at + timedelta(seconds=8),
        )
        session.add_all([f9, f10])
        await session.flush()

        ev5 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run4.id,
            finding_id=f9.id,
            evidence_type=EvidenceType.DIFF_HUNK.value,
            file_path="pipeline/consumers/batch_writer.py",
            start_line=70,
            end_line=75,
            content_snippet="+ self._buffer.append(message.value)\n+ if time.time() - self._last_flush > 60:\n+     self.flush()",
            rule_or_cve_id="diff.unbounded_buffer",
            corroborating_tool="ast_analyzer",
            created_at=run4.started_at + timedelta(seconds=8),
        )
        pub4 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run4.id,
            finding_id=f9.id,
            repository_id=repo_data.github_repo_id,
            pr_number=pr_batch.pr_number,
            commit_sha=run4.commit_sha,
            idempotency_key=f"{repo_data.github_repo_id}:{pr_batch.pr_number}:{f9.id}:{run4.commit_sha}",
            github_comment_id=98730015,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run4.completed_at,
            created_at=run4.completed_at,
        )
        fb4 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f9.id,
            review_run_id=run4.id,
            repository_id=repo_data.github_repo_id,
            pr_number=pr_batch.pr_number,
            feedback_type=FeedbackType.REACTION_POSITIVE.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="marcus-k",
            comment_body="Added high-watermark check at 5,000 items.",
            created_at=run4.completed_at + timedelta(hours=1),
        )
        session.add_all([ev5, pub4, fb4])

        # --- Run 5 (Frontend XSS) ---
        f11 = Finding(
            id=uuid.uuid4(),
            review_run_id=run5.id,
            agent_name="SecurityAgent",
            issue_type=IssueType.SECURITY.value,
            severity=Severity.HIGH.value,
            file_path="src/components/MarkdownViewer.tsx",
            line_number=35,
            side=FindingSide.RIGHT.value,
            title="Cross-Site Scripting (XSS) via dangerouslySetInnerHTML (CWE-79)",
            explanation="Unsanitized markdown string is rendered into DOM using `dangerouslySetInnerHTML`, allowing script injection from malicious review comments.",
            recommendation="Pass rendered HTML through `DOMPurify.sanitize(html)` before rendering or use `react-markdown` with strict schema.",
            confidence_score=0.96,
            raw_confidence=0.95,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98750012,
            created_at=run5.started_at + timedelta(seconds=5),
        )
        session.add(f11)
        await session.flush()

        ev6 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run5.id,
            finding_id=f11.id,
            evidence_type=EvidenceType.STATIC_ANALYSIS.value,
            file_path="src/components/MarkdownViewer.tsx",
            start_line=34,
            end_line=36,
            content_snippet="<div dangerouslySetInnerHTML={{ __html: parsedMarkdown }} />",
            rule_or_cve_id="semgrep.typescript.react.security.dangerouslysetinnerhtml",
            corroborating_tool="semgrep",
            created_at=run5.started_at + timedelta(seconds=5),
        )
        pub5 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run5.id,
            finding_id=f11.id,
            repository_id=repo_frontend.github_repo_id,
            pr_number=pr_xss.pr_number,
            commit_sha=run5.commit_sha,
            idempotency_key=f"{repo_frontend.github_repo_id}:{pr_xss.pr_number}:{f11.id}:{run5.commit_sha}",
            github_comment_id=98750012,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run5.completed_at,
            created_at=run5.completed_at,
        )
        fb5 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f11.id,
            review_run_id=run5.id,
            repository_id=repo_frontend.github_repo_id,
            pr_number=pr_xss.pr_number,
            feedback_type=FeedbackType.COMMENT_RESOLVED.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="dev-jordan",
            comment_body="Integrated DOMPurify. Verified XSS test vector is stripped.",
            created_at=run5.completed_at + timedelta(minutes=15),
        )
        session.add_all([ev6, pub5, fb5])

        # --- Run 6 (Redis Deserialization) ---
        f12 = Finding(
            id=uuid.uuid4(),
            review_run_id=run6.id,
            agent_name="SecurityAgent",
            issue_type=IssueType.SECURITY.value,
            severity=Severity.CRITICAL.value,
            file_path="workers/deserializer.py",
            line_number=28,
            side=FindingSide.RIGHT.value,
            title="Insecure Deserialization via pickle.loads (CWE-502)",
            explanation="Untrusted Redis queue payloads are deserialized using `pickle.loads`, permitting arbitrary remote code execution on the worker instance.",
            recommendation="Replace pickle serialization with JSON (`pydantic.BaseModel` or `msgpack`) which does not execute arbitrary object code during decoding.",
            confidence_score=0.99,
            raw_confidence=0.98,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98730101,
            created_at=run6.started_at + timedelta(seconds=4),
        )
        session.add(f12)
        await session.flush()

        ev7 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run6.id,
            finding_id=f12.id,
            evidence_type=EvidenceType.STATIC_ANALYSIS.value,
            file_path="workers/deserializer.py",
            start_line=27,
            end_line=29,
            content_snippet="payload = pickle.loads(raw_bytes)",
            rule_or_cve_id="bandit.B301.pickle",
            corroborating_tool="bandit",
            created_at=run6.started_at + timedelta(seconds=4),
        )
        pub6 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run6.id,
            finding_id=f12.id,
            repository_id=repo_data.github_repo_id,
            pr_number=pr_redis_worker.pr_number,
            commit_sha=run6.commit_sha,
            idempotency_key=f"{repo_data.github_repo_id}:{pr_redis_worker.pr_number}:{f12.id}:{run6.commit_sha}",
            github_comment_id=98730101,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run6.completed_at,
            created_at=run6.completed_at,
        )
        fb6 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f12.id,
            review_run_id=run6.id,
            repository_id=repo_data.github_repo_id,
            pr_number=pr_redis_worker.pr_number,
            feedback_type=FeedbackType.FINDING_ACCEPTED.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="marcus-k",
            comment_body="Critical vulnerability caught before deployment! Replaced with Pydantic JSON.",
            created_at=run6.completed_at + timedelta(minutes=30),
        )
        session.add_all([ev7, pub6, fb6])

        # --- Run 7 (Stripe Webhook Signature) ---
        f13 = Finding(
            id=uuid.uuid4(),
            review_run_id=run7.id,
            agent_name="SecurityAgent",
            issue_type=IssueType.SECURITY.value,
            severity=Severity.HIGH.value,
            file_path="services/billing/webhook.py",
            line_number=45,
            side=FindingSide.RIGHT.value,
            title="Excessive Webhook Timestamp Tolerance Window (CWE-345)",
            explanation="Webhook signature tolerance is set to 86,400 seconds (24 hours), exposing the service to replay attacks.",
            recommendation="Set webhook timestamp tolerance to 300 seconds (5 minutes) per security best practices.",
            confidence_score=0.92,
            raw_confidence=0.89,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98720210,
            created_at=run7.started_at + timedelta(seconds=6),
        )
        session.add(f13)
        await session.flush()

        ev8 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run7.id,
            finding_id=f13.id,
            evidence_type=EvidenceType.STATIC_ANALYSIS.value,
            file_path="services/billing/webhook.py",
            start_line=44,
            end_line=46,
            content_snippet="stripe.Webhook.construct_event(payload, sig, secret, tolerance=86400)",
            rule_or_cve_id="semgrep.python.stripe.excessive-tolerance",
            corroborating_tool="semgrep",
            created_at=run7.started_at + timedelta(seconds=6),
        )
        pub7 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run7.id,
            finding_id=f13.id,
            repository_id=repo_payment.github_repo_id,
            pr_number=pr_stripe.pr_number,
            commit_sha=run7.commit_sha,
            idempotency_key=f"{repo_payment.github_repo_id}:{pr_stripe.pr_number}:{f13.id}:{run7.commit_sha}",
            github_comment_id=98720210,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run7.completed_at,
            created_at=run7.completed_at,
        )
        fb7 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f13.id,
            review_run_id=run7.id,
            repository_id=repo_payment.github_repo_id,
            pr_number=pr_stripe.pr_number,
            feedback_type=FeedbackType.REACTION_POSITIVE.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="alex-chen",
            comment_body="Tightened tolerance to 300s.",
            created_at=run7.completed_at + timedelta(minutes=10),
        )
        session.add_all([ev8, pub7, fb7])

        # --- Run 8 (Replay Tests) ---
        f14 = Finding(
            id=uuid.uuid4(),
            review_run_id=run8.id,
            agent_name="TestAdequacyAgent",
            issue_type=IssueType.TEST_ADEQUACY.value,
            severity=Severity.MEDIUM.value,
            file_path="tests/test_nonce_cache.py",
            line_number=62,
            side=FindingSide.RIGHT.value,
            title="Mocking Redis Nonce Cache Bypasses Real TTL Eviction Behavior",
            explanation="Unit tests mock Redis client entirely, failing to test what happens when nonces expire during high network latency.",
            recommendation="Test against `fakeredis` with simulated clock advancement to verify TTL enforcement.",
            confidence_score=0.88,
            raw_confidence=0.85,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98740110,
            created_at=run8.started_at + timedelta(seconds=5),
        )
        session.add(f14)
        await session.flush()

        pub8 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run8.id,
            finding_id=f14.id,
            repository_id=repo_auth.github_repo_id,
            pr_number=pr_replay.pr_number,
            commit_sha=run8.commit_sha,
            idempotency_key=f"{repo_auth.github_repo_id}:{pr_replay.pr_number}:{f14.id}:{run8.commit_sha}",
            github_comment_id=98740110,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run8.completed_at,
            created_at=run8.completed_at,
        )
        session.add(pub8)

        # --- Run 9 (Database Optimization) ---
        f15 = Finding(
            id=uuid.uuid4(),
            review_run_id=run9.id,
            agent_name="BugLogicAgent",
            issue_type=IssueType.BUG_LOGIC.value,
            severity=Severity.MEDIUM.value,
            file_path="app/database/connection.py",
            line_number=48,
            side=FindingSide.RIGHT.value,
            title="Connection Pool Missing pool_pre_ping Health Check",
            explanation="Without `pool_pre_ping=True`, stale or severed connections in pool lead to unhandled OperationalError on subsequent queries.",
            recommendation="Enable `pool_pre_ping=True` and configure `pool_recycle=1800`.",
            confidence_score=0.90,
            raw_confidence=0.87,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98711340,
            created_at=run9.started_at + timedelta(seconds=4),
        )
        session.add(f15)
        await session.flush()

        pub9 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run9.id,
            finding_id=f15.id,
            repository_id=repo_core.github_repo_id,
            pr_number=pr_db_optimize.pr_number,
            commit_sha=run9.commit_sha,
            idempotency_key=f"{repo_core.github_repo_id}:{pr_db_optimize.pr_number}:{f15.id}:{run9.commit_sha}",
            github_comment_id=98711340,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run9.completed_at,
            created_at=run9.completed_at,
        )
        fb8 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f15.id,
            review_run_id=run9.id,
            repository_id=repo_core.github_repo_id,
            pr_number=pr_db_optimize.pr_number,
            feedback_type=FeedbackType.REACTION_POSITIVE.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="sarah-dev",
            comment_body="Added pool_pre_ping=True.",
            created_at=run9.completed_at + timedelta(hours=2),
        )
        session.add_all([pub9, fb8])

        # --- Run 10 (Dependency Vulnerability) ---
        f16 = Finding(
            id=uuid.uuid4(),
            review_run_id=run10.id,
            agent_name="SecurityAgent",
            issue_type=IssueType.SECURITY.value,
            severity=Severity.HIGH.value,
            file_path="pyproject.toml",
            line_number=22,
            side=FindingSide.RIGHT.value,
            title="Known Vulnerability in Cryptography Library (CVE-2024-34064)",
            explanation="Package `cryptography` version 41.0.7 is vulnerable to a null-pointer dereference in PKCS#12 decoding.",
            recommendation="Upgrade `cryptography` to version `>=42.0.8`.",
            confidence_score=0.99,
            raw_confidence=0.99,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=98740205,
            created_at=run10.started_at + timedelta(seconds=3),
        )
        session.add(f16)
        await session.flush()

        ev9 = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run10.id,
            finding_id=f16.id,
            evidence_type=EvidenceType.DEPENDENCY.value,
            file_path="pyproject.toml",
            start_line=20,
            end_line=24,
            content_snippet='cryptography = "==41.0.7"',
            rule_or_cve_id="CVE-2024-34064",
            corroborating_tool="pip-audit",
            created_at=run10.started_at + timedelta(seconds=3),
        )
        pub10 = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run10.id,
            finding_id=f16.id,
            repository_id=repo_auth.github_repo_id,
            pr_number=pr_deps.pr_number,
            commit_sha=run10.commit_sha,
            idempotency_key=f"{repo_auth.github_repo_id}:{pr_deps.pr_number}:{f16.id}:{run10.commit_sha}",
            github_comment_id=98740205,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=run10.completed_at,
            created_at=run10.completed_at,
        )
        fb9 = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=f16.id,
            review_run_id=run10.id,
            repository_id=repo_auth.github_repo_id,
            pr_number=pr_deps.pr_number,
            feedback_type=FeedbackType.FINDING_ACCEPTED.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="dependabot[bot]",
            comment_body="Bumped cryptography to 42.0.8.",
            created_at=run10.completed_at + timedelta(minutes=5),
        )
        session.add_all([ev9, pub10, fb9])

        # --- Active Run 11 (Streaming WebSocket - IN PROGRESS) ---
        f17 = Finding(
            id=uuid.uuid4(),
            review_run_id=run_active.id,
            agent_name="BugLogicAgent",
            issue_type=IssueType.BUG_LOGIC.value,
            severity=Severity.MEDIUM.value,
            file_path="src/services/websocket.ts",
            line_number=65,
            side=FindingSide.RIGHT.value,
            title="WebSocket Reconnection Loop Lacks Exponential Backoff",
            explanation="Instant reconnect on socket drop causes connection flooding to backend server under transient network outages.",
            recommendation="Implement randomized exponential backoff starting at 1000ms with jitter up to 30000ms max.",
            confidence_score=0.92,
            raw_confidence=0.89,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.UNPUBLISHED.value,
            created_at=run_active.started_at + timedelta(seconds=12),
        )
        f18 = Finding(
            id=uuid.uuid4(),
            review_run_id=run_active.id,
            agent_name="PerformanceAgent",
            issue_type=IssueType.PERFORMANCE.value,
            severity=Severity.LOW.value,
            file_path="src/services/websocket.ts",
            line_number=90,
            side=FindingSide.RIGHT.value,
            title="Frequent JSON Parse in Main UI Thread",
            explanation="High-frequency incoming telemetry parsing could benefit from web worker offloading.",
            recommendation="Consider web worker deserialization if packet rate exceeds 1,000 msg/sec.",
            confidence_score=0.48,
            raw_confidence=0.52,
            verification_status=VerificationStatus.REJECTED.value,
            rejection_reason="Suppressed by Critic: premature optimization for current telemetry message rates.",
            publish_status=PublishStatus.UNPUBLISHED.value,
            created_at=run_active.started_at + timedelta(seconds=14),
        )
        session.add_all([f17, f18])

        await session.commit()
        print("Presentation dataset successfully seeded!")


if __name__ == "__main__":
    asyncio.run(seed_presentation_dataset())
