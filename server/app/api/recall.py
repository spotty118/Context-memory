"""
Context Memory recall API endpoint.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import structlog

from app.core.security import get_api_key
from app.db.session import get_db_dependency
from app.db.models import APIKey
from app.services.retrieval import ContextRetriever

router = APIRouter()
logger = structlog.get_logger(__name__)


class RecallRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID for context")
    purpose: str = Field(..., description="Purpose/query for recall")
    token_budget: Optional[int] = Field(None, description="Token budget for response")


class RecallResponse(BaseModel):
    thread_id: str
    globals: Dict[str, Any]
    focus_ids: List[str]
    artifact_refs: List[str]
    token_estimate: int


@router.post("/recall", response_model=RecallResponse)
async def recall_context(
    request: RecallRequest,
    api_key: APIKey = Depends(get_api_key),
    db: Session = Depends(get_db_dependency)
):
    """
    Recall relevant context based on purpose and scoring algorithm.
    
    Scoring: S = 0.28*TaskRel + 0.22*Decision + 0.16*Recency + 0.12*GraphDegree + 0.12*FailureImpact + 0.08*UsageFreq − 0.06*Redundancy
    """
    logger.info(
        "context_recall_requested",
        workspace_id=api_key.workspace_id,
        thread_id=request.thread_id,
        purpose=request.purpose,
        token_budget=request.token_budget,
    )
    
    try:
        # Initialize retrieval service
        retriever = ContextRetriever()
        
        # Perform context recall
        retrieval_result = await retriever.recall_context(
            thread_id=request.thread_id,
            purpose=request.purpose,
            token_budget=request.token_budget,
            db=db
        )
        
        logger.info(
            "context_recall_completed",
            workspace_id=api_key.workspace_id,
            thread_id=request.thread_id,
            focus_items_count=len(retrieval_result['focus_ids']),
            artifacts_count=len(retrieval_result['artifact_refs']),
            token_estimate=retrieval_result['token_estimate'],
        )
        
        return RecallResponse(
            thread_id=retrieval_result['thread_id'],
            globals=retrieval_result['globals'],
            focus_ids=retrieval_result['focus_ids'],
            artifact_refs=retrieval_result['artifact_refs'],
            token_estimate=retrieval_result['token_estimate']
        )
    
    except Exception as e:
        logger.error(
            "context_recall_failed",
            workspace_id=api_key.workspace_id,
            thread_id=request.thread_id,
            error=str(e)
        )
        # Return fallback response
        return RecallResponse(
            thread_id=request.thread_id,
            globals={
                "mission": "Unable to retrieve context - system error",
                "constraints": [],
                "runbook": {"steps": ["Check system status"], "summary": "Error occurred"}
            },
            focus_ids=[],
            artifact_refs=[],
            token_estimate=100
        )

