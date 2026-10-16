"""Read-only operational endpoints for Web UI V2 (Fase R5A)."""

from typing import Optional

from fastapi import Depends, Query, Request
from pydantic import BaseModel

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


@router.post(
    "/factory/pause",
    summary="Pause factory operations non-destructively",
)
def pause_factory(request: Request):
    request_id = base.get_task_id(request)
    try:
        operator_console.pause_factory()
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change factory operational state",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error pausing factory",
        )

    state = operator_console.get_factory_state()
    return utils.get_response(
        200,
        {
            "factory_state": state,
            "is_paused": operator_console.is_factory_paused(),
        },
        message="Factory paused successfully",
    )


@router.post(
    "/factory/resume",
    summary="Resume factory operations",
)
def resume_factory(request: Request):
    request_id = base.get_task_id(request)
    try:
        operator_console.resume_factory()
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change factory operational state",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error resuming factory",
        )

    state = operator_console.get_factory_state()
    return utils.get_response(
        200,
        {
            "factory_state": state,
            "is_paused": operator_console.is_factory_paused(),
        },
        message="Factory resumed successfully",
    )


class RunCycleRequest(BaseModel):
    profile_id: Optional[str] = None
    channel_id: Optional[str] = None
    force: bool = True
    one_shot: bool = True


@router.post(
    "/factory/run-cycle",
    summary="Trigger a supervised factory autonomous run cycle",
)
def run_factory_cycle(
    request: Request,
    body: Optional[RunCycleRequest] = None,
    profile_id: Optional[str] = Query(
        default=None, description="Optional profile ID filter"
    ),
):
    request_id = base.get_task_id(request)
    target_profile_id = (body.profile_id if body and body.profile_id else None) or profile_id
    target_channel_id = body.channel_id if body and body.channel_id else None
    force = body.force if body is not None else True
    one_shot = body.one_shot if body is not None else True

    try:
        result = operator_console.run_autonomous_cycle_op(
            force=force,
            one_shot=one_shot,
            profile_id=target_profile_id,
            channel_id=target_channel_id,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can trigger a factory run cycle",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error running factory cycle",
        )

    if not isinstance(result, dict):
        result = {"status": "completed", "result": result}

    if result.get("status") == "busy" or result.get("reason") == "cycle_in_progress":
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message="Operation blocked: a production cycle is already in progress",
            data=result,
        )

    if result.get("reason") == "factory_paused":
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message="Operation blocked: factory is paused",
            data=result,
        )

    if result.get("reason") == "secondary_view_only":
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can trigger a factory run cycle",
            data=result,
        )

    return utils.get_response(
        200,
        result,
        message="Autonomous production cycle executed successfully",
    )


@router.get(
    "/profiles",
    summary="List operational profiles overview",
)
def list_profiles(request: Request):
    profiles = operator_console.get_profile_operations_overview()
    return utils.get_response(200, {"profiles": profiles, "total": len(profiles)})


@router.get(
    "/channels",
    summary="Get channels overview for Web UI V2",
)
def get_channels_overview(request: Request):
    profile_overviews = operator_console.get_profile_operations_overview()
    channels_data = []
    for p in profile_overviews:
        pid = p.get("profile_id", "")
        settings = profile_manager.get_profile_settings(pid)
        channels = profile_manager.list_channels(profile_id=pid)
        yt_channel = next((c for c in channels if c.get("platform") == "youtube"), None)
        is_auto = autonomous_production.is_profile_autonomous_mode_enabled(pid)
        target_stock = autonomous_production.get_target_ready_stock(pid)

        channels_data.append({
            "channel_id": pid,
            "profile_id": pid,
            "name": p.get("name"),
            "slug": p.get("slug"),
            "niche": p.get("niche") or "—",
            "language": p.get("language") or "pt-BR",
            "region": p.get("region") or "BR",
            "growth_mode": p.get("growth_mode") or "WARMUP",
            "is_active": p.get("is_active", True),
            "is_active_profile": p.get("is_active_profile", False),
            "autonomous_enabled": is_auto,
            "target_stock": target_stock,
            "ready_stock": p.get("ready_stock", 0),
            "pending_processing": p.get("pending_processing", 0),
            "scheduled": p.get("scheduled", 0),
            "failed": p.get("failed", 0),
            "channels_count": p.get("channels_count", len(channels)),
            "channels_enabled": p.get("channels_enabled", 0),
            "channels": channels,
            "youtube_channel": yt_channel,
            "settings": settings.model_dump(),
        })

    return utils.get_response(200, {"channels": channels_data, "total": len(channels_data)})


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


class UpdateGrowthModeRequest(BaseModel):
    growth_mode: str


class UpdateAutonomousRequest(BaseModel):
    enabled: bool


@router.patch(
    "/channels/{profile_id}/growth-mode",
    summary="Update channel Growth Mode (WARMUP / SCALE)",
)
@router.patch(
    "/profiles/{profile_id}/growth-mode",
    summary="Update profile Growth Mode (WARMUP / SCALE)",
)
def update_profile_growth_mode(
    request: Request,
    profile_id: str,
    body: UpdateGrowthModeRequest,
):
    request_id = base.get_task_id(request)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )

    try:
        updated = profile_manager.update_profile(
            profile_id=profile_id,
            growth_mode=body.growth_mode,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change growth mode",
        )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error updating growth mode",
        )

    clean_mode = updated.get("growth_mode", body.growth_mode)
    return utils.get_response(
        200,
        {
            "profile_id": profile_id,
            "growth_mode": clean_mode,
        },
        message=f"Growth mode for profile '{profile_id}' updated to {clean_mode.upper()}",
    )


@router.patch(
    "/channels/{profile_id}/autonomous",
    summary="Enable or pause autonomous production for a channel",
)
@router.patch(
    "/profiles/{profile_id}/autonomous",
    summary="Enable or pause autonomous production for a profile",
)
def update_profile_autonomous_mode(
    request: Request,
    profile_id: str,
    body: UpdateAutonomousRequest,
):
    request_id = base.get_task_id(request)
    clean_p = str(profile_id or "").strip()
    if clean_p != profile_manager.DEFAULT_PROFILE_ID and clean_p != "default":
        profile = profile_manager.get_profile(clean_p)
        if not profile:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"Profile '{profile_id}' not found",
            )

    try:
        operator_console.set_autonomous_mode_enabled_op(
            enabled=body.enabled,
            profile_id=clean_p,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change autonomous mode",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error updating autonomous mode",
        )

    is_auto = autonomous_production.is_profile_autonomous_mode_enabled(clean_p)
    return utils.get_response(
        200,
        {
            "profile_id": clean_p,
            "autonomous_enabled": is_auto,
        },
        message=f"Autonomous mode for profile '{clean_p}' {'enabled' if is_auto else 'disabled'}",
    )


@router.post(
    "/channels/{profile_id}/autonomous/enable",
    summary="Enable autonomous production for a channel",
)
def enable_profile_autonomous(request: Request, profile_id: str):
    return update_profile_autonomous_mode(request, profile_id, UpdateAutonomousRequest(enabled=True))


@router.post(
    "/channels/{profile_id}/autonomous/disable",
    summary="Disable autonomous production for a channel",
)
def disable_profile_autonomous(request: Request, profile_id: str):
    return update_profile_autonomous_mode(request, profile_id, UpdateAutonomousRequest(enabled=False))


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

