"""Evaluation and benchmark reporting endpoints.

Provides comprehensive empirical results, confusion matrices, category breakdowns,
comparative baseline analysis, live PR telemetry, and test case details.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models.pull_request import PullRequest
from app.database.models.review_run import ReviewRun
from app.database.session import get_db_session
from app.schemas.enums import PublishStatus, VerificationStatus

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])

# Base paths
EVAL_RESULTS_DIR = Path(__file__).resolve().parents[4] / "evaluation" / "results"
DATASETS_DIR = Path(__file__).resolve().parents[4] / "evaluation" / "datasets"

PROPOSED_RUN_ID = "3b8d2539-07a3-40b5-9533-072b87debf93"
SINGLE_LLM_RUN_ID = "a1f820b7-c0ac-461e-a419-160919491cdc"
NO_CRITIC_RUN_ID = "80467945-6c02-4f49-a2c9-f92cb8a23a9b"
STATIC_ONLY_RUN_ID = "e130978a-1728-4f3e-903a-e58867070e9b"

_DATASET_CACHE: dict[str, dict[str, Any]] | None = None


def _load_dataset_metadata() -> dict[str, dict[str, Any]]:
    global _DATASET_CACHE
    if _DATASET_CACHE is not None:
        return _DATASET_CACHE
    meta = {}
    if DATASETS_DIR.is_dir():
        for f in DATASETS_DIR.rglob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    content = json.load(fp)
                    if isinstance(content, dict) and "case_id" in content:
                        meta[content["case_id"]] = {
                            "title": content.get("title", ""),
                            "description": content.get("description", ""),
                            "affected_file": content.get("affected_file", ""),
                        }
            except Exception:
                continue
    _DATASET_CACHE = meta
    return _DATASET_CACHE


def _read_json_file(file_path: Path) -> dict[str, Any] | list[Any] | None:
    if not file_path.is_file():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


@router.get(
    "/summary",
    summary="Get Evaluation Benchmark Summary",
    description="Returns aggregate scientific evaluation metrics, confusion matrix, and category performance.",
)
async def get_evaluation_summary() -> dict[str, Any]:
    """Retrieve the authoritative evaluation summary and confusion matrix for the proposed agentic framework."""
    summary_path = EVAL_RESULTS_DIR / PROPOSED_RUN_ID / "summary.json"
    data = _read_json_file(summary_path)
    if not data or not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation summary benchmark data not found",
        )
    return data


@router.get(
    "/cases",
    summary="List Evaluation Test Cases and PR Defect Detection",
    description="Returns detailed per-case telemetry, ground truth matching, line distances, and token usage.",
)
async def get_evaluation_cases(
    category: str | None = Query(None, description="Filter by category (BUG_LOGIC, SECURITY, ERROR_HANDLING, TEST_ADEQUACY)"),
) -> list[dict[str, Any]]:
    """Retrieve all test case results enriched with PR title and affected file."""
    cases_path = EVAL_RESULTS_DIR / PROPOSED_RUN_ID / "cases.json"
    cases = _read_json_file(cases_path)
    if not cases or not isinstance(cases, list):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation test cases data not found",
        )

    meta = _load_dataset_metadata()
    enriched_cases = []
    for c in cases:
        cid = c.get("case_id", "")
        m = meta.get(cid, {})
        tp = c.get("true_positives", 0)
        fp = c.get("false_positives", 0)
        fn = c.get("false_negatives", 0)

        if tp > 0 and fp == 0 and fn == 0:
            classification = "TRUE_POSITIVE"
        elif fn > 0:
            classification = "FALSE_NEGATIVE"
        elif fp > 0:
            classification = "FALSE_POSITIVE"
        else:
            classification = "TRUE_NEGATIVE"

        matched_pairs = c.get("matched_pairs", [])
        primary_match = matched_pairs[0] if matched_pairs else {}
        unmatched_gt = c.get("unmatched_ground_truth", [])
        primary_unmatched = unmatched_gt[0] if unmatched_gt else {}

        affected_file = (
            m.get("affected_file")
            or primary_unmatched.get("affected_file")
            or ""
        )
        ground_truth_id = (
            primary_match.get("ground_truth_id")
            or primary_unmatched.get("defect_id")
            or ""
        )
        explanation = (
            primary_match.get("explanation")
            or primary_unmatched.get("description")
            or "Ground truth defect evaluated"
        )

        enriched = {
            **c,
            "title": m.get("title") or f"Evaluation PR Case {cid}",
            "description": m.get("description") or "",
            "affected_file": affected_file,
            "classification": classification,
            "semantic_score": float(primary_match.get("semantic_score", 0.0)) if primary_match else 0.0,
            "line_distance": primary_match.get("line_distance") if primary_match else None,
            "ground_truth_defect_id": ground_truth_id,
            "match_explanation": explanation,
        }
        enriched_cases.append(enriched)

    if category and category.upper() != "ALL":
        enriched_cases = [c for c in enriched_cases if c.get("category") == category.upper()]
    return enriched_cases


@router.get(
    "/baselines",
    summary="Compare Proposed Architecture Against Baselines",
    description="Returns comparative metrics comparing Agentic Critic vs Single LLM vs No-Critic vs Static Analysis.",
)
async def get_baseline_comparison() -> list[dict[str, Any]]:
    """Retrieve comparative metrics across all evaluation baselines."""
    baselines_config = [
        {"name": "Agentic Critic (Ours)", "key": "agentic_critic_full", "dir": PROPOSED_RUN_ID},
        {"name": "Single Prompt LLM", "key": "single_llm_reviewer", "dir": SINGLE_LLM_RUN_ID},
        {"name": "Agentic (No Critic)", "key": "agentic_no_critic", "dir": NO_CRITIC_RUN_ID},
        {"name": "Static Analysis Only", "key": "static_analysis_only", "dir": STATIC_ONLY_RUN_ID},
    ]

    results = []
    for b in baselines_config:
        s_path = EVAL_RESULTS_DIR / b["dir"] / "summary.json"
        data = _read_json_file(s_path)
        if data and isinstance(data, dict):
            om = data.get("overall_metrics", {})
            results.append({
                "name": b["name"],
                "key": b["key"],
                "model": data.get("model", "qwen3:4b-instruct"),
                "total_cases": data.get("total_cases", 23),
                "true_positives": om.get("true_positives", 0),
                "false_positives": om.get("false_positives", 0),
                "true_negatives": om.get("true_negatives", 0),
                "false_negatives": om.get("false_negatives", 0),
                "precision": om.get("precision", 0.0),
                "recall": om.get("recall", 0.0),
                "f1_score": om.get("f1_score", 0.0),
                "false_positive_rate": om.get("false_positive_rate", 0.0),
                "false_negative_rate": om.get("false_negative_rate", 0.0),
                "defect_detection_rate": om.get("defect_detection_rate", 0.0),
            })
    return results


@router.get(
    "/live-prs",
    summary="List Live Pull Requests with Review & Confusion Metrics",
    description="Returns live ingested GitHub pull requests from the database with verified findings, critic-rejected counts, and filter efficiency.",
)
async def get_live_pr_reviews(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict[str, Any]]:
    """Retrieve review runs and confusion metrics for live pull requests."""
    stmt = (
        select(PullRequest)
        .options(
            selectinload(PullRequest.repository),
            selectinload(PullRequest.review_runs).selectinload(ReviewRun.findings),
        )
        .order_by(PullRequest.created_at.desc())
    )
    result = await session.execute(stmt)
    prs = result.scalars().all()

    output = []
    for pr in prs:
        latest_run = pr.review_runs[-1] if pr.review_runs else None
        findings = latest_run.findings if latest_run and latest_run.findings else []
        verified = sum(
            1 for f in findings if f.verification_status == VerificationStatus.VERIFIED.value
        )
        rejected = sum(
            1
            for f in findings
            if f.verification_status
            in (
                VerificationStatus.REJECTED.value,
                VerificationStatus.SUPPRESSED_FALSE_POSITIVE.value,
                VerificationStatus.DROPPED_LOW_CONFIDENCE.value,
                "REJECTED_BY_CRITIC",
            )
        )
        published = sum(1 for f in findings if f.publish_status == PublishStatus.PUBLISHED.value)
        total_findings = len(findings)
        critic_filter_rate = round((rejected / total_findings * 100), 1) if total_findings > 0 else 0.0

        output.append({
            "pr_id": str(pr.id),
            "pr_number": pr.pr_number,
            "title": pr.title,
            "author": pr.author,
            "state": pr.state,
            "repository_name": pr.repository.full_name if pr.repository else "Unknown",
            "additions": pr.additions,
            "deletions": pr.deletions,
            "changed_files_count": pr.changed_files_count,
            "created_at": pr.created_at.isoformat() if pr.created_at else None,
            "review_run_id": str(latest_run.id) if latest_run else None,
            "review_status": latest_run.status if latest_run else "PENDING",
            "latency_seconds": float(latest_run.latency_seconds) if latest_run and latest_run.latency_seconds else None,
            "total_findings": total_findings,
            "verified_findings": verified,
            "critic_rejected_findings": rejected,
            "critic_filter_rate": critic_filter_rate,
            "published_findings": published,
        })
    return output
