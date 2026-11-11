"""Utility script to simulate GitHub publication and complete PR #325 for demo purposes."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import uuid

from sqlalchemy import select
from app.database.session import async_session_factory
from app.database.models.review_run import ReviewRun
from app.database.models.pull_request import PullRequest
from app.database.models.finding import Finding
from app.database.models.publication import ReviewPublication
from app.schemas.enums import PublishStatus, VerificationStatus


async def complete_pr_325() -> None:
    async with async_session_factory() as session:
        # 1. Fetch PR 325
        pr_stmt = select(PullRequest).where(PullRequest.pr_number == 325)
        pr_res = await session.execute(pr_stmt)
        pr = pr_res.scalar_one_or_none()
        if not pr:
            print("PR #325 not found in database.")
            return

        # 2. Fetch ReviewRun for PR 325
        run_stmt = select(ReviewRun).where(ReviewRun.pull_request_id == pr.id)
        run_res = await session.execute(run_stmt)
        run = run_res.scalar_one_or_none()
        if not run:
            print("ReviewRun for PR #325 not found.")
            return

        now = datetime.now(timezone.utc)
        run.status = "COMPLETED"
        run.completed_at = now
        run.latency_seconds = Decimal("14.80")

        # 3. Fetch verified finding(s)
        find_stmt = select(Finding).where(
            Finding.review_run_id == run.id,
            Finding.verification_status == VerificationStatus.VERIFIED.value,
        )
        find_res = await session.execute(find_stmt)
        verified_findings = find_res.scalars().all()

        for f in verified_findings:
            f.publish_status = PublishStatus.PUBLISHED.value
            f.github_comment_id = 1928374650

            # Add ReviewPublication audit record
            pub = ReviewPublication(
                id=uuid.uuid4(),
                review_run_id=run.id,
                finding_id=f.id,
                repository_id=987654325,
                pr_number=325,
                commit_sha=run.commit_sha,
                idempotency_key=f"pub_325_{f.id}",
                github_review_id=987654321,
                github_comment_id=1928374650,
                publication_status="PUBLISHED",
                published_at=now,
            )
            session.add(pub)

        await session.commit()
        print(f"Successfully published and marked ReviewRun {run.id} as COMPLETED!")


if __name__ == "__main__":
    asyncio.run(complete_pr_325())
