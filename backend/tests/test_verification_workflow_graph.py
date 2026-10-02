"""Integration tests for verification routing, parallel Critic fan-out, and finding persistence."""

from __future__ import annotations

import uuid
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.bug_logic import BugLogicAgent
from app.agents.critic import CriticAgent
from app.agents.planner import PlannerAgent
from app.agents.security import SecurityAgent
from app.database.models.review_run import ReviewRun
from app.orchestration.checkpoint import get_thread_config
from app.orchestration.errors import LLMTimeoutError
from app.orchestration.review_graph import (
    create_review_graph,
    execute_review_graph,
)
from app.orchestration.state import (
    ReviewState,
    create_initial_review_state,
    extract_candidate_findings,
    extract_rejected_findings,
    extract_verification_results,
    extract_verified_findings,
)
from app.schemas.diff import (
    DiffFile,
    DiffHunk,
    DiffLine,
    FileChangeType,
    ParsedDiff,
)
from app.schemas.enums import (
    DiffLineType,
    EvidenceType,
    FindingSide,
    IssueType,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.review_plan import ReviewPlan
from app.schemas.verification import CriticStructuredOutput
from app.services.evidence_persistence_service import (
    CommitMismatchError,
    ReviewRunNotFoundError,
)
from app.services.finding_persistence_service import (
    FindingPersistenceError,
    FindingPersistenceService,
)
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def sample_parsed_diff() -> ParsedDiff:
    """Standard parsed diff containing added lines in backend/app/auth.py."""
    return ParsedDiff(
        files=[
            DiffFile(
                old_path="backend/app/auth.py",
                new_path="backend/app/auth.py",
                status=FileChangeType.MODIFIED,
                hunks=[
                    DiffHunk(
                        old_start=1,
                        old_count=5,
                        new_start=1,
                        new_count=8,
                        header="@@ -1,5 +1,8 @@",
                        lines=[
                            DiffLine(
                                line_type=DiffLineType.CONTEXT,
                                content="import os",
                                raw_line=" import os",
                                old_line_number=1,
                                new_line_number=1,
                            ),
                            DiffLine(
                                line_type=DiffLineType.ADDED,
                                content="token = os.environ.get('SECRET')",
                                raw_line="+token = os.environ.get('SECRET')",
                                old_line_number=None,
                                new_line_number=2,
                            ),
                            DiffLine(
                                line_type=DiffLineType.ADDED,
                                content="os.system(f'run {cmd}')",
                                raw_line="+os.system(f'run {cmd}')",
                                old_line_number=None,
                                new_line_number=3,
                            ),
                            DiffLine(
                                line_type=DiffLineType.ADDED,
                                content="except Exception as e: pass",
                                raw_line="+except Exception as e: pass",
                                old_line_number=None,
                                new_line_number=4,
                            ),
                        ],
                    )
                ],
            )
        ]
    )


@pytest.fixture
def base_review_state(sample_parsed_diff: ParsedDiff) -> ReviewState:
    commit_sha = "a" * 40
    ev = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=2,
        end_line=2,
        snippet="token = os.environ.get('SECRET')",
        corroborating_tool="semgrep",
        rule_or_cve_id="hardcoded-secret",
    )
    state = create_initial_review_state(
        review_run_id="run-verif-01",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=10,
        commit_sha=commit_sha,
        base_sha="b" * 40,
        pr_title="Add Auth Layer",
        pr_author="octocat",
        changed_files=["backend/app/auth.py"],
        evidence_items=[ev],
    )
    # inject prepared_context mock with parsed_diff
    state["parsed_diff"] = sample_parsed_diff.model_dump()
    state["execution_metadata"]["prepared_context"] = {
        "formatted_diff": "diff content",
        "changed_files": ["backend/app/auth.py"],
        "evidence_items": [ev.model_dump()],
        "parsed_diff": sample_parsed_diff.model_dump(),
        "diff_truncated": False,
    }
    return state


def make_finding(
    file_path: str,
    line: int,
    title: str,
    issue_type: IssueType = IssueType.SECURITY,
    agent_name: str = "security_agent",
) -> ReviewFinding:
    return ReviewFinding(
        issue_type=issue_type,
        severity=Severity.HIGH,
        affected_file=file_path,
        line_number=line,
        side=FindingSide.RIGHT,
        title=title,
        explanation=f"Finding explanation for {title}",
        recommendation="Fix the issue",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path=file_path,
                start_line=line,
                end_line=line,
                snippet=f"code at line {line}",
            )
        ],
        agent_name=agent_name,
        raw_confidence=0.8,
    )


@pytest.mark.asyncio
async def test_verification_routing_zero_candidate_findings(
    base_review_state: ReviewState,
) -> None:
    """When specialist execution yields zero candidates, verify Critic fan-out is skipped cleanly."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        focus_areas=["Security check"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    # Specialist yields empty list
    sec_provider = MockLLMProvider(default_response=[])
    critic_provider = MockLLMProvider()

    critic_agent = CriticAgent(llm_service=LLMService(provider=critic_provider))

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_provider)),
        critic_agent=critic_agent,
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            base_review_state,
            config=get_thread_config(base_review_state["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    # Critic should never have been invoked because 0 candidate findings
    assert critic_provider.call_count == 0
    assert len(extract_candidate_findings(final_state)) == 0
    assert len(extract_verified_findings(final_state)) == 0
    assert len(extract_rejected_findings(final_state)) == 0


@pytest.mark.asyncio
async def test_verification_single_finding_verified(
    base_review_state: ReviewState,
) -> None:
    """Test single candidate finding verified by Critic and upgraded to VERIFIED."""
    finding = make_finding("backend/app/auth.py", 2, "Command Injection")

    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        focus_areas=["Security check"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_provider = MockLLMProvider(default_response=[finding])

    critic_output = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.92,
        evidence_sufficiency=True,
        contradiction_detected=False,
        verification_reasons=[
            "Command injection verified via diff hunk and static analysis"
        ],
        rejection_reasons=[],
        verifier_notes="Robust evidence present in added line.",
    )
    critic_provider = MockLLMProvider(default_response=critic_output)

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_provider)),
        critic_agent=CriticAgent(llm_service=LLMService(provider=critic_provider)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            base_review_state,
            config=get_thread_config(base_review_state["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    assert critic_provider.call_count == 1

    verified = extract_verified_findings(final_state)
    rejected = extract_rejected_findings(final_state)
    results = extract_verification_results(final_state)

    assert len(verified) == 1
    assert len(rejected) == 0
    assert len(results) == 1

    v_finding = verified[0]
    assert v_finding.verification_status == VerificationStatus.VERIFIED
    assert (
        v_finding.confidence_score == 1.0
    )  # Base 0.92 + 0.05 (changed line) + 0.10 (static evidence) capped at 1.0
    assert v_finding.is_verified is True
    assert v_finding.is_rejected is False

    result = results[0]
    assert result.verification_status == VerificationStatus.VERIFIED
    assert result.confidence_score == 1.0
    assert result.evidence_sufficiency is True


@pytest.mark.asyncio
async def test_verification_single_finding_rejected_by_llm(
    base_review_state: ReviewState,
) -> None:
    """Test candidate finding rejected by Critic due to contradiction or insufficient evidence."""
    finding = make_finding("backend/app/auth.py", 2, "Hallucinated Buffer Overflow")

    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        focus_areas=["Security check"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_provider = MockLLMProvider(default_response=[finding])

    critic_output = CriticStructuredOutput(
        decision="REJECTED",
        calibrated_confidence=0.0,
        evidence_sufficiency=False,
        contradiction_detected=True,
        verification_reasons=[],
        rejection_reasons=[
            "Python memory management prevents buffer overflow in this context"
        ],
        verifier_notes="Speculative finding contradicted by code semantics.",
    )
    critic_provider = MockLLMProvider(default_response=critic_output)

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_provider)),
        critic_agent=CriticAgent(llm_service=LLMService(provider=critic_provider)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            base_review_state,
            config=get_thread_config(base_review_state["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    verified = extract_verified_findings(final_state)
    rejected = extract_rejected_findings(final_state)

    assert len(verified) == 0
    assert len(rejected) == 1

    r_finding = rejected[0]
    assert r_finding.verification_status == VerificationStatus.REJECTED
    assert r_finding.confidence_score == 0.0
    assert r_finding.is_rejected is True
    assert r_finding.rejection_reason is not None
    assert (
        "Buffer overflow" in r_finding.rejection_reason
        or "Python" in r_finding.rejection_reason
        or "Contradiction" in r_finding.rejection_reason
    )


@pytest.mark.asyncio
async def test_verification_deterministic_rejection(
    base_review_state: ReviewState,
) -> None:
    """Test candidate finding citing a nonexistent file is deterministically rejected before LLM."""
    invalid_finding = make_finding("nonexistent/file.py", 99, "Invalid Finding")

    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        focus_areas=["Security check"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_provider = MockLLMProvider(default_response=[invalid_finding])
    critic_provider = MockLLMProvider()

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_provider)),
        critic_agent=CriticAgent(llm_service=LLMService(provider=critic_provider)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            base_review_state,
            config=get_thread_config(base_review_state["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    # LLM should NOT be invoked for deterministically invalid finding
    assert critic_provider.call_count == 0

    verified = extract_verified_findings(final_state)
    rejected = extract_rejected_findings(final_state)

    assert len(verified) == 0
    assert len(rejected) == 1
    assert rejected[0].verification_status == VerificationStatus.REJECTED
    assert "does not exist in PR diff" in (rejected[0].rejection_reason or "")


@pytest.mark.asyncio
async def test_verification_parallel_fan_out_multiple_candidates(
    base_review_state: ReviewState,
) -> None:
    """Test dynamic parallel fan-out verifying multiple findings independently."""
    finding_1 = make_finding("backend/app/auth.py", 2, "Finding 1 Verified")
    finding_2 = make_finding("backend/app/auth.py", 3, "Finding 2 Rejected")
    finding_3 = make_finding("nonexistent/other.py", 5, "Finding 3 Det Rejected")

    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        focus_areas=["Security check"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_provider = MockLLMProvider(default_response=[finding_1, finding_2, finding_3])

    # Critic provider responses for finding 1 and 2
    out_1 = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.90,
        evidence_sufficiency=True,
        contradiction_detected=False,
        verification_reasons=["Verified by diff"],
        rejection_reasons=[],
    )
    out_2 = CriticStructuredOutput(
        decision="REJECTED",
        calibrated_confidence=0.0,
        evidence_sufficiency=False,
        contradiction_detected=True,
        verification_reasons=[],
        rejection_reasons=["Speculative defect"],
    )
    critic_provider = MockLLMProvider(response_sequence=[out_1, out_2])

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_provider)),
        critic_agent=CriticAgent(llm_service=LLMService(provider=critic_provider)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            base_review_state,
            config=get_thread_config(base_review_state["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"

    verified = extract_verified_findings(final_state)
    rejected = extract_rejected_findings(final_state)
    results = extract_verification_results(final_state)

    assert len(verified) == 1
    assert len(rejected) == 2
    assert len(results) == 3

    verified_titles = [f.title for f in verified]
    rejected_titles = [f.title for f in rejected]

    assert "Finding 1 Verified" in verified_titles
    assert "Finding 2 Rejected" in rejected_titles
    assert "Finding 3 Det Rejected" in rejected_titles


@pytest.mark.asyncio
async def test_verification_failure_isolation(
    base_review_state: ReviewState,
) -> None:
    """Test failure isolation: one candidate failure records error, other candidate verifies."""
    finding_1 = make_finding("backend/app/auth.py", 2, "Finding Good")
    finding_2 = make_finding("backend/app/auth.py", 3, "Finding Timeout")

    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        focus_areas=["Security check"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_provider = MockLLMProvider(default_response=[finding_1, finding_2])

    out_good = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.88,
        evidence_sufficiency=True,
        contradiction_detected=False,
        verification_reasons=["Valid finding"],
        rejection_reasons=[],
    )
    # finding_2 triggers LLMTimeoutError
    timeout_err = LLMTimeoutError(message="Critic timeout", timeout_seconds=5.0)
    critic_provider = MockLLMProvider(response_sequence=[out_good, timeout_err])

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_provider)),
        critic_agent=CriticAgent(llm_service=LLMService(provider=critic_provider)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            base_review_state,
            config=get_thread_config(base_review_state["review_run_id"]),
        ),
    )

    # Workflow level status MUST remain COMPLETED despite single finding failure
    assert final_state["status"] == "COMPLETED"

    verified = extract_verified_findings(final_state)
    assert len(verified) == 1
    assert verified[0].title == "Finding Good"

    # Verification errors recorded
    verif_errors = final_state.get("verification_errors", [])
    assert len(verif_errors) == 1
    assert verif_errors[0]["finding_id"] == str(finding_2.finding_id)


@pytest.mark.asyncio
async def test_end_to_end_planner_specialists_critic_workflow(
    base_review_state: ReviewState,
) -> None:
    """Full workflow test: Planner -> Security & BugLogic -> Candidate Aggregation -> Critic -> Verification Aggregation."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
        focus_areas=["Audit"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)

    sec_f = make_finding(
        "backend/app/auth.py", 2, "Security Issue", IssueType.SECURITY, "security_agent"
    )
    bug_f = make_finding(
        "backend/app/auth.py", 4, "Bug Issue", IssueType.BUG_LOGIC, "bug_logic_agent"
    )

    sec_p = MockLLMProvider(default_response=[sec_f])
    bug_p = MockLLMProvider(default_response=[bug_f])

    out_sec = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.91,
        evidence_sufficiency=True,
        contradiction_detected=False,
        verification_reasons=["Security issue verified"],
        rejection_reasons=[],
    )
    out_bug = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.85,
        evidence_sufficiency=True,
        contradiction_detected=False,
        verification_reasons=["Bug logic verified"],
        rejection_reasons=[],
    )
    critic_p = MockLLMProvider(response_sequence=[out_sec, out_bug])

    final_state = await execute_review_graph(
        initial_state=base_review_state,
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_p)),
        bug_logic_agent=BugLogicAgent(llm_service=LLMService(provider=bug_p)),
        critic_agent=CriticAgent(llm_service=LLMService(provider=critic_p)),
    )

    assert final_state["status"] == "COMPLETED"
    assert len(extract_candidate_findings(final_state)) == 2
    assert len(extract_verified_findings(final_state)) == 2
    assert len(extract_rejected_findings(final_state)) == 0


# ---------------------------------------------------------------------------
# FindingPersistenceService Unit Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finding_persistence_service_success() -> None:
    """Verify persisting batch of verified and rejected findings into database."""
    run_id = uuid.uuid4()
    commit_sha = "c" * 40
    mock_run = MagicMock(spec=ReviewRun)
    mock_run.id = run_id
    mock_run.commit_sha = commit_sha

    session = AsyncMock(spec=AsyncSession)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = mock_run
    session.execute.return_value = mock_exec_result

    finding_1 = make_finding("backend/app/auth.py", 2, "Verified Finding")
    finding_1.verification_status = VerificationStatus.VERIFIED
    finding_1.confidence_score = 0.90

    finding_2 = make_finding("backend/app/auth.py", 3, "Rejected Finding")
    finding_2.verification_status = VerificationStatus.REJECTED
    finding_2.confidence_score = 0.0
    finding_2.rejection_reason = "Contradicted by diff"

    service = FindingPersistenceService()
    results = await service.persist_findings_batch(
        session=session,
        review_run_id=run_id,
        expected_commit_sha=commit_sha,
        findings=[finding_1, finding_2],
    )

    assert len(results) == 2
    session.add_all.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_finding_persistence_service_commit_mismatch() -> None:
    """Verify commit SHA mismatch raises CommitMismatchError and aborts."""
    run_id = uuid.uuid4()
    mock_run = MagicMock(spec=ReviewRun)
    mock_run.id = run_id
    mock_run.commit_sha = "actual" + "a" * 34

    session = AsyncMock(spec=AsyncSession)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = mock_run
    session.execute.return_value = mock_exec_result

    service = FindingPersistenceService()
    with pytest.raises(CommitMismatchError):
        await service.persist_findings_batch(
            session=session,
            review_run_id=run_id,
            expected_commit_sha="expected" + "b" * 32,
            findings=[],
        )
    session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_finding_persistence_service_not_found() -> None:
    """Verify non-existent review run raises ReviewRunNotFoundError."""
    run_id = uuid.uuid4()
    session = AsyncMock(spec=AsyncSession)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_exec_result

    service = FindingPersistenceService()
    with pytest.raises(ReviewRunNotFoundError):
        await service.persist_findings_batch(
            session=session,
            review_run_id=run_id,
            expected_commit_sha="c" * 40,
            findings=[],
        )
    session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_finding_persistence_service_db_error() -> None:
    """Verify SQLAlchemyError triggers rollback and wraps into FindingPersistenceError."""
    run_id = uuid.uuid4()
    commit_sha = "c" * 40
    mock_run = MagicMock(spec=ReviewRun)
    mock_run.id = run_id
    mock_run.commit_sha = commit_sha

    session = AsyncMock(spec=AsyncSession)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = mock_run
    session.execute.return_value = mock_exec_result
    session.commit.side_effect = SQLAlchemyError("Connection lost")

    finding = make_finding("backend/app/auth.py", 2, "Test")
    service = FindingPersistenceService()
    with pytest.raises(FindingPersistenceError):
        await service.persist_findings_batch(
            session=session,
            review_run_id=run_id,
            expected_commit_sha=commit_sha,
            findings=[finding],
        )
    session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_finding_persistence_service_empty_findings() -> None:
    """Verify empty findings list commits and returns empty list cleanly."""
    run_id = uuid.uuid4()
    commit_sha = "c" * 40
    mock_run = MagicMock(spec=ReviewRun)
    mock_run.id = run_id
    mock_run.commit_sha = commit_sha

    session = AsyncMock(spec=AsyncSession)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = mock_run
    session.execute.return_value = mock_exec_result

    service = FindingPersistenceService()
    results = await service.persist_findings_batch(
        session=session,
        review_run_id=run_id,
        expected_commit_sha=commit_sha,
        findings=[],
    )
    assert results == []
    session.commit.assert_called_once()
