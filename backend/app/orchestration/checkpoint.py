"""Graph state checkpointing strategy and factory for review run persistence and resumption.

Implements checkpointing allowing review workflow recovery from mid-run failures
using review_run_id as the primary thread identifier per Section G and 14.
"""

from __future__ import annotations

import logging
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


def create_checkpointer(
    checkpointer_type: str = "memory",
) -> BaseCheckpointSaver:
    """Create and return a LangGraph CheckpointSaver instance.

    Defaults to MemorySaver for fast, isolated, and external-dependency-free execution.
    Can be extended to Redis or Postgres checkpoint savers in subsequent phases.
    """
    checkpointer_type_clean = checkpointer_type.strip().lower()

    if checkpointer_type_clean == "memory":
        logger.debug("Initialized in-memory LangGraph checkpointer")
        return MemorySaver()

    logger.warning(
        "Unsupported checkpointer type '%s'; falling back to MemorySaver",
        checkpointer_type,
    )
    return MemorySaver()


def get_thread_config(review_run_id: str) -> RunnableConfig:
    """Generate thread configuration mapping execution trace to a specific ReviewRun.

    Ensures that checkpoints are partitioned strictly by review_run_id, preventing
    cross-review interference and supporting resumption.
    """
    cleaned_id = str(review_run_id).strip()
    if not cleaned_id:
        raise ValueError("review_run_id cannot be blank when generating thread config")

    return cast(
        RunnableConfig,
        {
            "configurable": {
                "thread_id": cleaned_id,
            }
        },
    )
