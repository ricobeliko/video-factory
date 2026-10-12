"""Read-only operational endpoints for Web UI V2 (Fase R5A)."""

from typing import Optional

from fastapi import Depends, Query, Request

from app.controllers import base
from app.controllers.v2.base import new_router
from app.models.exception import HttpException
from app.services import autonomous_production, operator_console, profile_manager
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


@router.get(
    "/system/status",
    summary="Get consolidated system status",
)
def get_system_status(
    request: Request,
    profile_id: Optional[str] = Query(
        default=None, description="Optional profile ID filter"
    ),
):
    status = operator_console.get_system_status(profile_id=profile_id)
    return utils.get_response(200, status)


@router.get(
    "/profiles",
    summary="List operational profiles overview",
)
def list_profiles(request: Request):
    profiles = operator_console.get_profile_operations_overview()
    return utils.get_response(200, {"profiles": profiles, "total": len(profiles)})


@router.get(
    "/profiles/{profile_id}/status",
    summary="Get status snapshot for a single profile",
)
def get_profile_status(request: Request, profile_id: str):
    request_id = base.get_task_id(request)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )

    pid = profile.get("id", profile_id)
    auto_status = autonomous_production.get_autonomous_status(profile_id=pid)
    ready_stock = operator_console.get_canonical_ready_stock(profile_id=pid)
    channels = profile_manager.list_channels(profile_id=pid)
    youtube_channel_id = autonomous_production.resolve_autonomous_youtube_channel(pid)

    data = {
        "profile": profile,
        "growth_mode": profile.get("growth_mode", "WARMUP"),
        "is_active": profile.get("is_active", True),
        "autonomous_status": auto_status,
        "ready_stock": ready_stock,
        "youtube_channel_id": youtube_channel_id,
        "channels": channels,
    }
    return utils.get_response(200, data)


@router.get(
    "/scheduler/posts",
    summary="Get scheduler queue summary",
)
def get_scheduler_posts(
    request: Request,
    profile_id: Optional[str] = Query(
        default=None, description="Optional profile ID filter"
    ),
    limit: int = Query(
        default=50, ge=1, le=100, description="Max upcoming posts to inspect"
    ),
):
    summary = operator_console.get_scheduler_queue_summary(limit=limit)
    if profile_id:
        summary["upcoming_posts"] = [
            p for p in summary.get("upcoming_posts", [])
            if p.get("profile_id") == profile_id
        ]
    return utils.get_response(200, summary)


@router.get(
    "/publications",
    summary="List recent publication events",
)
def list_publications(
    request: Request,
    profile_id: Optional[str] = Query(
        default=None, description="Filter by profile ID"
    ),
    limit: int = Query(
        default=20, ge=1, le=100, description="Number of events to return"
    ),
):
    items = operator_console.get_recent_publications(limit=limit, profile_id=profile_id)
    return utils.get_response(200, {"publications": items, "total": len(items)})


@router.get(
    "/providers/health",
    summary="Get passive provider health summary",
)
def get_provider_health(request: Request):
    health = operator_console.get_provider_health_summary()
    return utils.get_response(200, health)


@router.get(
    "/executions/live",
    summary="Get live multi-channel execution overview (UI-005)",
)
def get_live_executions(request: Request):
    overview = operator_console.get_live_execution_overview()
    return utils.get_response(200, overview)


@router.get(
    "/executions/{task_id}",
    summary="Get execution trace detail for a specific task (UI-005)",
)
def get_task_execution(request: Request, task_id: str):
    request_id = base.get_task_id(request)
    detail = operator_console.get_execution_detail(task_id)
    if not detail:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Execution for task '{task_id}' not found",
        )
    return utils.get_response(200, detail)


@router.get(
    "/agent-ops",
    summary="Get Agent Ops live observability snapshot (Agent Ops V1.1)",
)
def get_agent_ops(request: Request):
    from app.services import agent_ops
    snapshot = agent_ops.get_agent_ops_snapshot()
    return utils.get_response(200, snapshot)

