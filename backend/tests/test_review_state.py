"""Unit tests for ReviewState creation, sanitization, and invariant enforcement."""

import pytest
from app.orchestration.state import (
    ReviewState,
    create_initial_review_state,
    extract_review_plan,
)
from app.schemas.enums import EvidenceType
from app.schemas.evidence import EvidenceModel
from app.schemas.review_plan import ReviewPlan


@pytest.fixture
def valid_evidence() -> EvidenceModel:
    return EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=10,
        end_line=12,
        snippet="token = os.environ.get('SECRET')",
        corroborating_tool="semgrep",
        rule_or_cve_id="python.lang.security.hardcoded-secret",
    )


def test_create_initial_review_state_valid(valid_evidence: EvidenceModel) -> None:
    """Verify that a valid ReviewState is created with expected defaults."""
    state = create_initial_review_state(
        review_run_id="run-1234-abcd",
        repository_id=42,
        repository_full_name="owner/repo",
        pr_number=7,
        commit_sha="a" * 40,
        base_sha="b" * 40,
        pr_title="Add Authentication",
        pr_author="octocat",
        pr_metadata={"branch": "feature/auth"},
        workspace_metadata={"workspace_id": "ws-1", "size_bytes": 1024},
        evidence_items=[valid_evidence],
    )

    assert state["review_run_id"] == "run-1234-abcd"
    assert state["repository_id"] == 42
    assert state["repository_full_name"] == "owner/repo"
    assert state["pr_number"] == 7
    assert state["commit_sha"] == "a" * 40
    assert state["base_sha"] == "b" * 40
    assert state["pr_title"] == "Add Authentication"
    assert state["status"] == "PENDING"
    assert state["review_plan"] is None
    assert len(state["evidence_items"]) == 1
    assert state["evidence_items"][0]["file_path"] == "backend/app/auth.py"


def test_create_initial_review_state_invalid_id() -> None:
    """Verify that blank review_run_id is rejected."""
    with pytest.raises(ValueError, match="review_run_id cannot be blank"):
        create_initial_review_state(
            review_run_id="   ",
            repository_id=1,
            repository_full_name="owner/repo",
            pr_number=1,
            commit_sha="a" * 40,
        )


def test_create_initial_review_state_invalid_sha() -> None:
    """Verify that non-40-hex commit SHA is rejected."""
    with pytest.raises(ValueError, match="Invalid commit_sha format"):
        create_initial_review_state(
            review_run_id="run-1",
            repository_id=1,
            repository_full_name="owner/repo",
            pr_number=1,
            commit_sha="not-a-valid-sha",
        )


def test_create_initial_review_state_invalid_repo() -> None:
    """Verify that invalid repository metadata is rejected."""
    with pytest.raises(ValueError, match="repository_id must be positive"):
        create_initial_review_state(
            review_run_id="run-1",
            repository_id=0,
            repository_full_name="owner/repo",
            pr_number=1,
            commit_sha="a" * 40,
        )

    with pytest.raises(ValueError, match="repository_full_name must be 'owner/repo'"):
        create_initial_review_state(
            review_run_id="run-1",
            repository_id=1,
            repository_full_name="invalid-repo-format",
            pr_number=1,
            commit_sha="a" * 40,
        )


def test_create_initial_review_state_invalid_pr_number() -> None:
    """Verify that non-positive pr_number is rejected."""
    with pytest.raises(ValueError, match="pr_number must be positive"):
        create_initial_review_state(
            review_run_id="run-1",
            repository_id=1,
            repository_full_name="owner/repo",
            pr_number=0,
            commit_sha="a" * 40,
        )


def test_create_initial_review_state_sanitizes_secrets() -> None:
    """Verify that secret keys and tokens are stripped from state metadata."""
    state = create_initial_review_state(
        review_run_id="run-1",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=1,
        commit_sha="a" * 40,
        pr_metadata={
            "safe_key": "safe_value",
            "github_token": "ghp_secrettoken123",
            "api_key": "sk-12345",
            "nested": {"nested_secret": "xyz", "ok": "val"},
        },
        workspace_metadata={
            "workspace_id": "ws-1",
            "password": "supersecretpassword",
            "authorization_header": "Bearer abc",
            "files": ["file1.py", "file2.py"],  # Raw files must be removed
            "file_contents": {"file1.py": "content"},
        },
    )

    pr_meta = state["pr_metadata"]
    assert "safe_key" in pr_meta
    assert "github_token" not in pr_meta
    assert "api_key" not in pr_meta
    assert "nested_secret" not in pr_meta["nested"]
    assert pr_meta["nested"]["ok"] == "val"

    ws_meta = state["workspace_metadata"]
    assert "workspace_id" in ws_meta
    assert "password" not in ws_meta
    assert "authorization_header" not in ws_meta
    assert "files" not in ws_meta
    assert "file_contents" not in ws_meta


def test_extract_review_plan() -> None:
    """Verify helper extracts ReviewPlan from dict or returns existing."""
    state: ReviewState = {"status": "PENDING"}
    assert extract_review_plan(state) is None

    plan = ReviewPlan(review_scope="FULL", active_agents=["security_agent"])
    state["review_plan"] = plan.model_dump()

    extracted = extract_review_plan(state)
    assert extracted is not None
    assert isinstance(extracted, ReviewPlan)
    assert extracted.review_scope == "FULL"
    assert extracted.active_agents == ["security_agent"]

    # When already an instance
    state["review_plan"] = plan
    extracted_again = extract_review_plan(state)
    assert extracted_again is plan


def test_create_initial_review_state_invalid_evidence_item_type() -> None:
    """Verify passing an unsupported type in evidence_items raises TypeError."""
    with pytest.raises(TypeError, match="Expected EvidenceModel or dict"):
        create_initial_review_state(
            review_run_id="run-1",
            repository_id=1,
            repository_full_name="owner/repo",
            pr_number=1,
            commit_sha="a" * 40,
            evidence_items=["invalid_string_evidence"],  # type: ignore[list-item]
        )


def test_checkpoint_factory_and_thread_config() -> None:
    """Verify checkpointer factory fallbacks and thread config generation."""
    from app.orchestration.checkpoint import create_checkpointer, get_thread_config

    cp = create_checkpointer("unsupported_type")
    assert cp is not None

    cfg = get_thread_config("test-thread-id")
    assert cfg["configurable"]["thread_id"] == "test-thread-id"

    with pytest.raises(ValueError, match="review_run_id cannot be blank"):
        get_thread_config("   ")


def test_workflow_errors_and_retryability() -> None:
    """Verify error serialization and retry classification."""
    from app.orchestration.errors import (
        ContextPreparationError,
        InvalidPlannerOutputError,
        LLMProviderError,
        LLMTimeoutError,
        WorkflowConfigurationError,
        WorkflowError,
        WorkflowErrorCategory,
        is_retryable_error,
    )

    err = WorkflowError(
        message="Workflow failed",
        category=WorkflowErrorCategory.WORKFLOW_EXECUTION_FAILURE,
        retryable=False,
        details={"step": 1},
    )
    err_dict = err.to_dict()
    assert err_dict["error_type"] == "WorkflowError"
    assert err_dict["message"] == "Workflow failed"
    assert err_dict["category"] == "WORKFLOW_EXECUTION_FAILURE"
    assert is_retryable_error(err) is False

    timeout_err = LLMTimeoutError("Timeout", timeout_seconds=10.0, provider="mock")
    assert is_retryable_error(timeout_err) is True
    assert timeout_err.category == WorkflowErrorCategory.LLM_TIMEOUT

    prov_err = LLMProviderError("503", provider="mock", status_code=503)
    assert is_retryable_error(prov_err) is True

    plan_err = InvalidPlannerOutputError("Schema invalid", raw_output="{}")
    assert is_retryable_error(plan_err) is False

    ctx_err = ContextPreparationError("Context prep failed", details={"file": "test"})
    assert is_retryable_error(ctx_err) is False

    cfg_err = WorkflowConfigurationError("Config missing", parameter="KEY")
    assert is_retryable_error(cfg_err) is False
    assert is_retryable_error(RuntimeError("unknown")) is False
