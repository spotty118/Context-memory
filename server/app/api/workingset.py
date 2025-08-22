"""
Context Memory working set API endpoint.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from app.core.security import get_api_key
from app.db.session import get_db_dependency
from app.db.models import APIKey
from app.services.workingset import WorkingSetBuilder

router = APIRouter()
logger = structlog.get_logger(__name__)


class WorkingSetRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID for context")
    retrieval: Dict[str, Any] = Field(..., description="Retrieval data from recall")
    token_budget: Optional[int] = Field(None, description="Token budget for working set")


class WorkingSetResponse(BaseModel):
    mission: str
    constraints: List[str]
    focus_decisions: List[Dict[str, Any]]
    focus_tasks: List[Dict[str, Any]]
    runbook: Dict[str, Any]
    artifacts: List[str]
    citations: List[str]
    open_questions: List[str]
    token_estimate: int


@router.post("/workingset", response_model=WorkingSetResponse)
async def create_working_set(
    request: WorkingSetRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency)
):
    """
    Create a compact working set from retrieval data.
    
    Returns structured JSON with mission, constraints, focus items, runbook, artifacts, etc.
    """
    logger.info(
        "working_set_requested",
        workspace_id=api_key.workspace_id,
        thread_id=request.thread_id,
        token_budget=request.token_budget,
    )
    
    try:
        # Initialize working set builder
        builder = WorkingSetBuilder()
        
        # Create working set from retrieval data
        working_set = builder.create_working_set(
            retrieval_data=request.retrieval,
            token_budget=request.token_budget
        )
        
        logger.info(
            "working_set_created",
            workspace_id=api_key.workspace_id,
            thread_id=request.thread_id,
            focus_decisions_count=len(working_set['focus_decisions']),
            focus_tasks_count=len(working_set['focus_tasks']),
            artifacts_count=len(working_set['artifacts']),
            token_estimate=working_set['token_estimate'],
        )
        
        return WorkingSetResponse(
            mission=working_set['mission'],
            constraints=working_set['constraints'],
            focus_decisions=working_set['focus_decisions'],
            focus_tasks=working_set['focus_tasks'],
            runbook=working_set['runbook'],
            artifacts=working_set['artifacts'],
            citations=working_set['citations'],
            open_questions=working_set['open_questions'],
            token_estimate=working_set['token_estimate']
        )
    
    except Exception as e:
        logger.error(
            "working_set_creation_failed",
            workspace_id=api_key.workspace_id,
            thread_id=request.thread_id,
            error=str(e)
        )
        
        # Return fallback working set
        return WorkingSetResponse(
            mission="Unable to create working set - system error",
            constraints=["System error occurred"],
            focus_decisions=[{
                "id": "ERROR",
                "title": "System error - unable to process context",
                "status": "error",
                "impact": "high"
            }],
            focus_tasks=[{
                "id": "ERROR_TASK",
                "title": "Check system logs and resolve error",
                "status": "urgent",
                "priority": "high"
            }],
            runbook={
                "steps": ["Check system status", "Review error logs", "Contact support"],
                "summary": "Error recovery runbook"
            },
            artifacts=["No artifacts available"],
            citations=["ERROR"],
            open_questions=["What caused the system error?"],
            token_estimate=200
        )

