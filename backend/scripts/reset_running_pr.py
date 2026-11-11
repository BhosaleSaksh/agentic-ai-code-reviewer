"""Utility script to reset PR #325 back to RUNNING state for live demo presentation."""

import asyncio
from sqlalchemy import select, delete
from app.database.session import async_session_factory
from app.database.models.review_run import ReviewRun
from app.database.models.pull_request import PullRequest
from app.database.models.finding import Finding
from app.database.models.publication import ReviewPublication
from app.schemas.enums import PublishStatus


async def reset_pr_325() -> None:
    async with async_session_factory() as session:
        # 1. Fetch PR 325
        pr_stmt = select(PullRequest).where(PullRequest.pr_number == 325)
        pr_res = await session.execute(pr_stmt)
        pr = pr_res.scalar_one_or_none()
        if not pr:
            print("PR #325 not found in database.")
            return

        # 2. Fetch ReviewRun
        run_stmt = select(ReviewRun).where(ReviewRun.pull_request_id == pr.id)
        run_res = await session.execute(run_stmt)
        run = run_res.scalar_one_or_none()
        if not run:
            print("ReviewRun for PR #325 not found.")
            return

        run.status = "RUNNING"
        run.completed_at = None
        run.latency_seconds = None

        # 3. Reset findings to UNPUBLISHED
        find_stmt = select(Finding).where(Finding.review_run_id == run.id)
        find_res = await session.execute(find_stmt)
        findings = find_res.scalars().all()
        for f in findings:
            f.publish_status = PublishStatus.UNPUBLISHED.value
            f.github_comment_id = None

        # 4. Remove publications for this run
        del_pub_stmt = delete(ReviewPublication).where(ReviewPublication.review_run_id == run.id)
        await session.execute(del_pub_stmt)

        await session.commit()
        print(f"Successfully reset ReviewRun {run.id} back to RUNNING state!")


if __name__ == "__main__":
    asyncio.run(reset_pr_325())
