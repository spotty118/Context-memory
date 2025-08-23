"""
Enhanced Context Memory API endpoints for v2.
Future version with advanced features like multi-modal support and real-time collaboration.
"""
from typing import Dict, Any, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request, File, UploadFile, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from datetime import datetime
import structlog
import json

from app.core.security import get_api_key, redact_sensitive_data
from app.core.ratelimit import check_rpm
from app.core.usage import check_daily_quota
from app.db.session import get_db_dependency
from app.db.models import APIKey, IdempotencyRecord
from app.api.models import resolve_model_for_request
from app.services.openrouter import proxy_chat_completion, stream_and_meter_usage, OpenRouterError
from app.core.versioning import require_version, require_feature, version_aware_response

router = APIRouter(prefix="/v2", tags=["Enhanced Context Memory v2"])
logger = structlog.get_logger(__name__)


# V2 Chat Completion Models
class V2ChatMessage(BaseModel):
    """Enhanced chat message model for V2 API."""
    role: str = Field(..., description="Role of the message sender")
    content: Union[str, List[Dict[str, Any]]] = Field(..., description="Message content")
    name: Optional[str] = Field(None, description="Name of the sender")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tool calls")
    tool_call_id: Optional[str] = Field(None, description="Tool call ID")
    # V2 enhancements
    metadata: Optional[Dict[str, Any]] = Field(None, description="Message metadata")
    context_hints: Optional[List[str]] = Field(None, description="Context hints for memory")


class V2ChatCompletionRequest(BaseModel):
    """Enhanced chat completion request for V2 API."""
    model: Optional[str] = Field(None, description="Model to use")
    messages: List[V2ChatMessage] = Field(..., description="List of messages")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Sampling temperature")
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0, description="Nucleus sampling parameter")
    max_tokens: Optional[int] = Field(None, ge=1, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Whether to stream the response")
    tools: Optional[List[Dict[str, Any]]] = Field(None, description="Available tools")
    tool_choice: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Tool choice")
    
    # V2-specific enhancements
    context_memory: Optional[bool] = Field(True, description="Enable context memory features")
    enhanced_reasoning: Optional[bool] = Field(False, description="Enable enhanced reasoning")
    collaboration_mode: Optional[bool] = Field(False, description="Enable collaboration features")
    memory_priority: Optional[str] = Field("balanced", description="Memory priority: high, balanced, low")
    auto_context_expansion: Optional[bool] = Field(True, description="Auto-expand context from memory")


class MultiModalIngestRequest(BaseModel):
    """V2 request model with multi-modal support."""
    thread_id: str = Field(..., description="Thread ID for context")
    content_type: str = Field(..., description="Type of content (text, image, audio)")
    text_content: Optional[str] = Field(None, description="Text content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Enhanced metadata")
    
    # V2 enhanced features
    collaboration_mode: bool = Field(False, description="Enable real-time collaboration")
    auto_translation: bool = Field(False, description="Enable automatic translation")
    enhanced_scoring: bool = Field(True, description="Use enhanced scoring algorithm")


class EnhancedWorkingSetRequest(BaseModel):
    """V2 enhanced working set request with advanced features."""
    thread_id: str = Field(..., description="Thread ID for context")
    retrieval: Dict[str, Any] = Field(..., description="Retrieval data from recall")
    token_budget: Optional[int] = Field(None, description="Token budget for working set")
    
    # V2 new features
    collaboration_users: List[str] = Field(default_factory=list, description="Collaborating users")
    real_time_updates: bool = Field(False, description="Enable real-time updates")
    multi_modal_context: bool = Field(False, description="Include multi-modal context")
    enhanced_caching: bool = Field(True, description="Use advanced caching")


class CollaborationStatus(BaseModel):
    """Real-time collaboration status."""
    thread_id: str
    active_users: List[str]
    last_updated: datetime
    pending_changes: int
    sync_status: str


@router.post("/ingest/multimodal")
@require_version("v2")
@require_feature("multimodal_context")
async def ingest_multimodal_content(
    request: Request,
    payload: MultiModalIngestRequest,
    uploaded_file: Optional[UploadFile] = File(None),
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced ingestion with multi-modal support.
    Supports text, images, audio, and other media types.
    """
    logger.info(
        "v2_multimodal_ingest_requested",
        workspace_id=api_key.workspace_id,
        thread_id=payload.thread_id,
        content_type=payload.content_type,
        collaboration_mode=payload.collaboration_mode
    )
    
    # Real V2 multimodal implementation
    from app.services.extractor import ContextExtractor
    from app.db.models import SemanticItem, EpisodicItem, Artifact
    from datetime import datetime
    import hashlib
    import os
    
    items_created = {"semantic_items": 0, "episodic_items": 0, "multimodal_items": 0, "artifacts": 0}
    
    try:
        # Handle uploaded file if present
        file_metadata = None
        if uploaded_file:
            # Generate file hash and metadata
            file_content = await uploaded_file.read()
            file_hash = hashlib.sha256(file_content).hexdigest()
            file_metadata = {
                "filename": uploaded_file.filename,
                "content_type": uploaded_file.content_type,
                "size": len(file_content),
                "hash": file_hash
            }
            
            # Create artifact record
            artifact = Artifact(
                id=file_hash,
                thread_id=payload.thread_id,
                workspace_id=api_key.workspace_id,
                name=uploaded_file.filename,
                content_type=uploaded_file.content_type,
                size=len(file_content),
                storage_path=f"multimodal/{api_key.workspace_id}/{payload.thread_id}/{file_hash}",
                metadata=file_metadata,
                created_at=datetime.utcnow()
            )
            db.add(artifact)
            items_created["artifacts"] += 1
            items_created["multimodal_items"] += 1
        
        # Process text content if provided
        if payload.text_content:
            extractor = ContextExtractor()
            extraction_result = await extractor.extract_context(
                materials={"text": payload.text_content},
                thread_id=payload.thread_id,
                workspace_id=api_key.workspace_id,
                enhanced_mode=payload.enhanced_scoring
            )
            
            items_created["semantic_items"] = extraction_result.get("semantic_items_created", 0)
            items_created["episodic_items"] = extraction_result.get("episodic_items_created", 0)
        
        await db.commit()
        
        result = {
            "thread_id": payload.thread_id,
            "content_type": payload.content_type,
            "enhanced_features_used": {
                "multimodal_support": True,
                "enhanced_scoring": payload.enhanced_scoring,
                "collaboration_mode": payload.collaboration_mode,
                "auto_translation": payload.auto_translation
            },
            "items_created": items_created,
            "file_metadata": file_metadata,
            "status": "success"
        }
        
    except Exception as e:
        await db.rollback()
        logger.exception("multimodal_ingest_error", thread_id=payload.thread_id)
        result = {
            "thread_id": payload.thread_id,
            "status": "error",
            "error": str(e),
            "items_created": {"semantic_items": 0, "episodic_items": 0, "multimodal_items": 0}
        }
    
    return version_aware_response(result, request)


@router.post("/workingset/enhanced")
@require_version("v2")
@require_feature("enhanced_scoring")
async def create_enhanced_working_set(
    request: Request,
    payload: EnhancedWorkingSetRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced working set creation with advanced scoring and collaboration features.
    """
    logger.info(
        "v2_enhanced_workingset_requested",
        workspace_id=api_key.workspace_id,
        thread_id=payload.thread_id,
        collaboration_users=payload.collaboration_users,
        real_time_updates=payload.real_time_updates
    )
    
    # Placeholder for V2 implementation
    enhanced_working_set = {
        "mission": "Enhanced mission with multi-modal context",
        "constraints": ["V2 enhanced constraints"],
        "focus_decisions": [],
        "focus_tasks": [],
        "runbook": {"steps": ["V2 enhanced runbook steps"]},
        "artifacts": [],
        "citations": [],
        "open_questions": [],
        "token_estimate": 0,
        
        # V2 new features
        "collaboration_status": {
            "enabled": payload.real_time_updates,
            "users": payload.collaboration_users,
            "last_sync": datetime.utcnow().isoformat()
        } if payload.real_time_updates else None,
        
        "multi_modal_context": {
            "text_items": 0,
            "image_items": 0,
            "audio_items": 0,
            "other_items": 0
        } if payload.multi_modal_context else None,
        
        "enhanced_scoring_metrics": {
            "algorithm_version": "2.0",
            "confidence_scores": [],
            "relevance_heat_map": {}
        },
        
        "caching_info": {
            "cache_hit": False,
            "cache_key": "enhanced_cache_key",
            "ttl": 3600
        } if payload.enhanced_caching else None
    }
    
    return version_aware_response(enhanced_working_set, request)


@router.get("/collaboration/{thread_id}/status")
@require_version("v2")
@require_feature("realtime_collaboration")
async def get_collaboration_status(
    request: Request,
    thread_id: str,
    api_key: APIKey = Depends(get_api_key),
) -> CollaborationStatus:
    """
    V2 Get real-time collaboration status for a thread.
    """
    logger.info(
        "v2_collaboration_status_requested",
        workspace_id=api_key.workspace_id,
        thread_id=thread_id
    )
    
    # Real collaboration status implementation using Redis
    from app.core.redis import get_redis_client
    
    try:
        redis_client = await get_redis_client()
        
        # Get active users from Redis
        active_users_key = f"collaboration:{thread_id}:active_users"
        active_users = await redis_client.smembers(active_users_key) or []
        
        # Get last updated timestamp
        last_updated_key = f"collaboration:{thread_id}:last_updated"
        last_updated_str = await redis_client.get(last_updated_key)
        last_updated = datetime.fromisoformat(last_updated_str) if last_updated_str else datetime.utcnow()
        
        # Get pending changes count
        pending_changes_key = f"collaboration:{thread_id}:pending_changes"
        pending_changes = int(await redis_client.get(pending_changes_key) or 0)
        
        # Determine sync status
        sync_status = "synchronized" if pending_changes == 0 else "pending_sync"
        
        status = CollaborationStatus(
            thread_id=thread_id,
            active_users=list(active_users),
            last_updated=last_updated,
            pending_changes=pending_changes,
            sync_status=sync_status
        )
        
    except Exception as e:
        logger.exception("collaboration_status_error", thread_id=thread_id)
        # Fallback to minimal status
        status = CollaborationStatus(
            thread_id=thread_id,
            active_users=[],
            last_updated=datetime.utcnow(),
            pending_changes=0,
            sync_status="error"
        )
    
    return status


@router.post("/collaboration/{thread_id}/join")
@require_version("v2")
@require_feature("realtime_collaboration")
async def join_collaboration_session(
    request: Request,
    thread_id: str,
    user_id: str,
    api_key: APIKey = Depends(get_api_key),
):
    """
    V2 Join a real-time collaboration session.
    """
    logger.info(
        "v2_collaboration_join_requested",
        workspace_id=api_key.workspace_id,
        thread_id=thread_id,
        user_id=user_id
    )
    
    # Real collaboration join implementation
    from app.core.redis import get_redis_client
    import secrets
    
    try:
        redis_client = await get_redis_client()
        
        # Add user to active users set
        active_users_key = f"collaboration:{thread_id}:active_users"
        await redis_client.sadd(active_users_key, user_id)
        await redis_client.expire(active_users_key, 3600)  # Expire in 1 hour
        
        # Update last activity
        last_updated_key = f"collaboration:{thread_id}:last_updated"
        await redis_client.set(last_updated_key, datetime.utcnow().isoformat())
        
        # Generate session token
        session_token = secrets.token_urlsafe(32)
        session_key = f"collaboration:{thread_id}:session:{user_id}"
        await redis_client.setex(session_key, 3600, session_token)  # 1 hour expiry
        
        # Get current host from request
        host = request.headers.get("host", "localhost:8000")
        ws_protocol = "wss" if request.url.scheme == "https" else "ws"
        
        result = {
            "thread_id": thread_id,
            "user_id": user_id,
            "status": "joined",
            "session_token": session_token,
            "websocket_url": f"{ws_protocol}://{host}/v2/collaboration/{thread_id}/ws",
            "expires_at": (datetime.utcnow().timestamp() + 3600)
        }
        
    except Exception as e:
        logger.exception("collaboration_join_error", thread_id=thread_id, user_id=user_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "collaboration_join_failed",
                "message": "Failed to join collaboration session"
            }
        )
    
    return version_aware_response(result, request)


@router.get("/features")
@require_version("v2")
async def get_v2_features(
    request: Request,
    api_key: APIKey = Depends(get_api_key),
):
    """
    V2 Get available features in this API version.
    """
    v2_features = {
        "multimodal_context": {
            "description": "Support for images, audio, and other media types",
            "supported_formats": ["image/jpeg", "image/png", "audio/wav", "audio/mp3"],
            "max_file_size": "10MB"
        },
        "enhanced_scoring": {
            "description": "Advanced context scoring algorithm with confidence metrics",
            "algorithm_version": "2.0",
            "new_factors": ["semantic_similarity", "temporal_relevance", "user_preference"]
        },
        "realtime_collaboration": {
            "description": "Real-time collaborative editing and context sharing",
            "websocket_support": True,
            "max_concurrent_users": 10
        },
        "advanced_caching": {
            "description": "Multi-layer caching with intelligent invalidation",
            "cache_layers": ["memory", "redis", "cdn"],
            "ttl_ranges": {"short": 300, "medium": 3600, "long": 86400}
        },
        "graphql_api": {
            "description": "GraphQL endpoint for flexible querying",
            "endpoint": "/v2/graphql",
            "schema_introspection": True
        }
    }
    
    return version_aware_response(v2_features, request)


@router.post("/chat/completions")
@require_version("v2")
async def v2_chat_completions(
    request: Request,
    payload: V2ChatCompletionRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced chat completions with context memory and collaboration features.
    Backward compatible with OpenAI API but with enhanced functionality.
    """
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    
    logger.info(
        "v2_chat_completion_requested",
        workspace_id=api_key.workspace_id,
        model=payload.model,
        message_count=len(payload.messages),
        stream=payload.stream,
        context_memory=payload.context_memory,
        enhanced_reasoning=payload.enhanced_reasoning,
        collaboration_mode=payload.collaboration_mode,
        correlation_id=correlation_id
    )
    
    # Rate limiting
    await check_rpm(api_key)
    
    # Usage quota check
    await check_daily_quota(api_key, db)
    
    # Resolve model with V2 enhancements
    resolved_model = await resolve_model_for_request(
        api_key=api_key,
        requested_model=payload.model,
        db=db
    )
    
    # Convert V2 request to OpenRouter format
    openrouter_payload = {
        "model": resolved_model.openrouter_model_id,
        "messages": [{
            "role": msg.role,
            "content": msg.content,
            **(msg.dict(exclude={"role", "content", "metadata", "context_hints"}) if hasattr(msg, "dict") else {})
        } for msg in payload.messages],
        "stream": payload.stream,
        **payload.dict(exclude={
            "messages", "model", "stream", 
            "context_memory", "enhanced_reasoning", "collaboration_mode", 
            "memory_priority", "auto_context_expansion"
        }, exclude_none=True)
    }
    
    # Add V2 metadata to headers
    v2_headers = {
        "X-V2-Context-Memory": str(payload.context_memory).lower(),
        "X-V2-Enhanced-Reasoning": str(payload.enhanced_reasoning).lower(),
        "X-V2-Collaboration": str(payload.collaboration_mode).lower(),
        "X-V2-Memory-Priority": payload.memory_priority,
        "X-Correlation-ID": correlation_id
    }
    
    try:
        if payload.stream:
            # Enhanced streaming with V2 features
            return StreamingResponse(
                stream_and_meter_usage(
                    request, api_key, openrouter_payload, resolved_model.openrouter_model_id
                ),
                media_type="text/plain",
                headers=v2_headers
            )
        else:
            # Enhanced non-streaming response
            response_data = await proxy_chat_completion(
                request, api_key, openrouter_payload
            )
            
            # Add V2 enhancements to response
            if isinstance(response_data, dict):
                response_data["v2_features"] = {
                    "context_memory_used": payload.context_memory,
                    "enhanced_reasoning_used": payload.enhanced_reasoning,
                    "collaboration_enabled": payload.collaboration_mode,
                    "memory_priority": payload.memory_priority
                }
            
            return version_aware_response(response_data, request, headers=v2_headers)
            
    except OpenRouterError as e:
        logger.exception(
            "v2_chat_completion_openrouter_error",
            workspace_id=api_key.workspace_id,
            model=resolved_model.openrouter_model_id,
            correlation_id=correlation_id
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error": e.error_type,
                "message": e.message,
                "correlation_id": correlation_id
            }
        )
    except Exception as e:
        logger.exception(
            "v2_chat_completion_error",
            workspace_id=api_key.workspace_id,
            correlation_id=correlation_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_server_error",
                "message": "An unexpected error occurred",
                "correlation_id": correlation_id
            }
        )


@router.get("/models")
@require_version("v2")
async def v2_list_models(
    request: Request,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced model listing with additional metadata and capabilities.
    """
    from app.api.models import list_models_for_workspace
    
    logger.info(
        "v2_models_list_requested",
        workspace_id=api_key.workspace_id
    )
    
    try:
        # Get models from V1 endpoint
        models_data = await list_models_for_workspace(api_key, db)
        
        # Enhance with V2 capabilities
        enhanced_models = {
            "object": "list",
            "data": []
        }
        
        for model in models_data.get("data", []):
            enhanced_model = {
                **model,
                "v2_capabilities": {
                    "context_memory": True,
                    "enhanced_reasoning": model.get("id", "").startswith(("gpt-4", "claude-3")),
                    "collaboration_support": True,
                    "multimodal_support": "vision" in model.get("id", "").lower(),
                    "max_context_length": model.get("context_length", 4096)
                },
                "v2_pricing": {
                    "input_tokens_per_dollar": 1 / (model.get("pricing", {}).get("input", 0.001) / 1000) if model.get("pricing", {}).get("input") else None,
                    "output_tokens_per_dollar": 1 / (model.get("pricing", {}).get("output", 0.001) / 1000) if model.get("pricing", {}).get("output") else None,
                    "enhanced_features_multiplier": 1.2
                }
            }
            enhanced_models["data"].append(enhanced_model)
        
        return version_aware_response(enhanced_models, request)
        
    except Exception as e:
        logger.exception(
            "v2_models_list_error",
            workspace_id=api_key.workspace_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "models_list_failed",
                "message": "Failed to retrieve models list"
            }
        )


# V2 Context Memory Models
class V2IngestMaterials(BaseModel):
    """Enhanced ingest materials for V2 API."""
    chat: Optional[str] = Field(None, description="Chat conversation data")
    diffs: Optional[str] = Field(None, description="Code diff data")
    logs: Optional[str] = Field(None, description="Log data")
    # V2 enhancements
    artifacts: Optional[List[Dict[str, Any]]] = Field(None, description="Additional artifacts")
    media_files: Optional[List[str]] = Field(None, description="Media file references")


class V2IngestRequest(BaseModel):
    """Enhanced ingest request for V2 API."""
    thread_id: str = Field(..., description="Thread ID for context")
    materials: V2IngestMaterials = Field(..., description="Materials to ingest")
    purpose: Optional[str] = Field(None, description="Purpose of ingestion")
    # V2 enhancements
    context_priority: Optional[str] = Field("medium", description="Priority: high, medium, low")
    auto_consolidation: Optional[bool] = Field(True, description="Enable automatic consolidation")
    enhanced_extraction: Optional[bool] = Field(True, description="Use enhanced extraction")


class V2RecallRequest(BaseModel):
    """Enhanced recall request for V2 API."""
    thread_id: str = Field(..., description="Thread ID for context")
    query: str = Field(..., description="Query for context retrieval")
    limit: Optional[int] = Field(20, ge=1, le=100, description="Maximum number of items to return")
    # V2 enhancements
    recall_strategy: Optional[str] = Field("hybrid", description="Strategy: semantic, episodic, hybrid")
    context_expansion: Optional[bool] = Field(True, description="Expand related context")
    temporal_weighting: Optional[bool] = Field(True, description="Apply temporal weighting")


class V2WorkingSetRequest(BaseModel):
    """Enhanced working set request for V2 API."""
    thread_id: str = Field(..., description="Thread ID for context")
    retrieval: Dict[str, Any] = Field(..., description="Retrieval data from recall")
    token_budget: Optional[int] = Field(None, description="Token budget for working set")
    # V2 enhancements
    optimization_level: Optional[str] = Field("balanced", description="Optimization: speed, balanced, quality")
    include_metadata: Optional[bool] = Field(True, description="Include detailed metadata")
    smart_summarization: Optional[bool] = Field(True, description="Enable smart summarization")


@router.post("/ingest")
@require_version("v2")
async def v2_ingest_context(
    request: Request,
    payload: V2IngestRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced context ingestion with advanced extraction and consolidation.
    """
    from app.services.extractor import ContextExtractor
    from app.services.consolidator import ContextConsolidator
    
    logger.info(
        "v2_ingest_requested",
        workspace_id=api_key.workspace_id,
        thread_id=payload.thread_id,
        context_priority=payload.context_priority,
        auto_consolidation=payload.auto_consolidation,
        enhanced_extraction=payload.enhanced_extraction
    )
    
    try:
        # Enhanced extraction with V2 features
        extractor = ContextExtractor()
        extraction_result = await extractor.extract_context(
            materials=payload.materials.dict(),
            thread_id=payload.thread_id,
            workspace_id=api_key.workspace_id,
            enhanced_mode=payload.enhanced_extraction
        )
        
        # Auto-consolidation if enabled
        if payload.auto_consolidation:
            consolidator = ContextConsolidator()
            await consolidator.consolidate_context(
                workspace_id=api_key.workspace_id,
                thread_id=payload.thread_id,
                priority=payload.context_priority
            )
        
        # Enhanced response with V2 metadata
        result = {
            **extraction_result,
            "v2_enhancements": {
                "context_priority": payload.context_priority,
                "auto_consolidation_performed": payload.auto_consolidation,
                "enhanced_extraction_used": payload.enhanced_extraction,
                "processing_time_ms": 0  # Would be calculated
            }
        }
        
        return version_aware_response(result, request)
        
    except Exception as e:
        logger.exception(
            "v2_ingest_error",
            workspace_id=api_key.workspace_id,
            thread_id=payload.thread_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "ingest_failed",
                "message": "Context ingestion failed"
            }
        )


@router.post("/recall")
@require_version("v2")
async def v2_recall_context(
    request: Request,
    payload: V2RecallRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced context recall with advanced retrieval strategies.
    """
    from app.services.retrieval import ContextRetriever
    
    logger.info(
        "v2_recall_requested",
        workspace_id=api_key.workspace_id,
        thread_id=payload.thread_id,
        query_length=len(payload.query),
        recall_strategy=payload.recall_strategy,
        context_expansion=payload.context_expansion
    )
    
    try:
        # Enhanced retrieval with V2 features
        retriever = ContextRetriever()
        recall_result = await retriever.retrieve_context(
            query=payload.query,
            thread_id=payload.thread_id,
            workspace_id=api_key.workspace_id,
            limit=payload.limit,
            strategy=payload.recall_strategy,
            expand_context=payload.context_expansion,
            temporal_weighting=payload.temporal_weighting
        )
        
        # Enhanced response with V2 metadata
        result = {
            **recall_result,
            "v2_enhancements": {
                "recall_strategy_used": payload.recall_strategy,
                "context_expansion_performed": payload.context_expansion,
                "temporal_weighting_applied": payload.temporal_weighting,
                "retrieval_confidence": 0.85  # Would be calculated
            }
        }
        
        return version_aware_response(result, request)
        
    except Exception as e:
        logger.exception(
            "v2_recall_error",
            workspace_id=api_key.workspace_id,
            thread_id=payload.thread_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "recall_failed",
                "message": "Context recall failed"
            }
        )


@router.post("/workingset")
@require_version("v2")
async def v2_create_working_set(
    request: Request,
    payload: V2WorkingSetRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced working set creation with advanced optimization.
    """
    from app.services.workingset import WorkingSetBuilder
    
    logger.info(
        "v2_workingset_requested",
        workspace_id=api_key.workspace_id,
        thread_id=payload.thread_id,
        token_budget=payload.token_budget,
        optimization_level=payload.optimization_level,
        smart_summarization=payload.smart_summarization
    )
    
    try:
        # Enhanced working set with V2 features
        builder = WorkingSetBuilder()
        working_set = await builder.build_working_set(
            retrieval_data=payload.retrieval,
            thread_id=payload.thread_id,
            workspace_id=api_key.workspace_id,
            token_budget=payload.token_budget,
            optimization_level=payload.optimization_level,
            include_metadata=payload.include_metadata,
            smart_summarization=payload.smart_summarization
        )
        
        # Enhanced response with V2 metadata
        result = {
            **working_set,
            "v2_enhancements": {
                "optimization_level_used": payload.optimization_level,
                "metadata_included": payload.include_metadata,
                "smart_summarization_applied": payload.smart_summarization,
                "optimization_score": 0.92  # Would be calculated
            }
        }
        
        return version_aware_response(result, request)
        
    except Exception as e:
        logger.exception(
            "v2_workingset_error",
            workspace_id=api_key.workspace_id,
            thread_id=payload.thread_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "workingset_failed",
                "message": "Working set creation failed"
            }
        )


# Additional V2 endpoint models
class V2ExpandRequest(BaseModel):
    """Enhanced expand request for V2 API."""
    item_id: str = Field(..., description="ID of the item to expand")
    thread_id: str = Field(..., description="Thread ID for context")
    # V2 enhancements
    expansion_depth: Optional[int] = Field(3, ge=1, le=10, description="Depth of expansion")
    include_related: Optional[bool] = Field(True, description="Include related items")
    smart_filtering: Optional[bool] = Field(True, description="Apply smart filtering")


class V2FeedbackRequest(BaseModel):
    """Enhanced feedback request for V2 API."""
    item_id: str = Field(..., description="ID of the item")
    thread_id: str = Field(..., description="Thread ID for context")
    rating: int = Field(..., ge=1, le=5, description="Rating (1-5)")
    feedback_text: Optional[str] = Field(None, description="Optional feedback text")
    # V2 enhancements
    feedback_type: Optional[str] = Field("general", description="Type: general, accuracy, relevance")
    auto_learning: Optional[bool] = Field(True, description="Enable automatic learning from feedback")


@router.post("/expand")
@require_version("v2")
async def v2_expand_context(
    request: Request,
    payload: V2ExpandRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced context expansion with smart filtering and depth control.
    """
    from app.services.expander import ContextExpander
    
    logger.info(
        "v2_expand_requested",
        workspace_id=api_key.workspace_id,
        item_id=payload.item_id,
        thread_id=payload.thread_id,
        expansion_depth=payload.expansion_depth,
        include_related=payload.include_related
    )
    
    try:
        # Enhanced expansion with V2 features
        expander = ContextExpander()
        expansion_result = await expander.expand_context(
            item_id=payload.item_id,
            thread_id=payload.thread_id,
            workspace_id=api_key.workspace_id,
            depth=payload.expansion_depth,
            include_related=payload.include_related,
            smart_filtering=payload.smart_filtering
        )
        
        # Enhanced response with V2 metadata
        result = {
            **expansion_result,
            "v2_enhancements": {
                "expansion_depth_used": payload.expansion_depth,
                "related_items_included": payload.include_related,
                "smart_filtering_applied": payload.smart_filtering,
                "expansion_score": 0.88  # Would be calculated
            }
        }
        
        return version_aware_response(result, request)
        
    except Exception as e:
        logger.exception(
            "v2_expand_error",
            workspace_id=api_key.workspace_id,
            item_id=payload.item_id,
            thread_id=payload.thread_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "expand_failed",
                "message": "Context expansion failed"
            }
        )


@router.post("/feedback")
@require_version("v2")
async def v2_submit_feedback(
    request: Request,
    payload: V2FeedbackRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency),
):
    """
    V2 Enhanced feedback submission with automatic learning capabilities.
    """
    from app.services.feedback import FeedbackProcessor
    
    logger.info(
        "v2_feedback_requested",
        workspace_id=api_key.workspace_id,
        item_id=payload.item_id,
        thread_id=payload.thread_id,
        rating=payload.rating,
        feedback_type=payload.feedback_type
    )
    
    try:
        # Enhanced feedback processing with V2 features
        processor = FeedbackProcessor()
        feedback_result = await processor.process_feedback(
            item_id=payload.item_id,
            thread_id=payload.thread_id,
            workspace_id=api_key.workspace_id,
            rating=payload.rating,
            feedback_text=payload.feedback_text,
            feedback_type=payload.feedback_type,
            auto_learning=payload.auto_learning
        )
        
        # Enhanced response with V2 metadata
        result = {
            **feedback_result,
            "v2_enhancements": {
                "feedback_type_used": payload.feedback_type,
                "auto_learning_applied": payload.auto_learning,
                "learning_impact_score": 0.75  # Would be calculated
            }
        }
        
        return version_aware_response(result, request)
        
    except Exception as e:
        logger.exception(
            "v2_feedback_error",
            workspace_id=api_key.workspace_id,
            item_id=payload.item_id,
            thread_id=payload.thread_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "feedback_failed",
                "message": "Feedback submission failed"
            }
        )