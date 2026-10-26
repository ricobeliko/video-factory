"""Production overview endpoints for Web UI V2 (Missão P1)."""

from typing import Optional
from fastapi import Depends, Query, Request

from app.controllers import base
from app.controllers.v2.base import new_router
from app.services import production_overview
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


@router.get(
    "/production/overview",
    summary="Get production overview (ready stock, scheduled queue, recent runs)",
)
def get_production_overview(
    request: Request,
    profile_id: Optional[str] = Query(default=None, description="Filtra por canal / profile_id específico"),
    limit_per_section: int = Query(default=20, ge=1, le=100, description="Limite máximo de itens por seção"),
):
    overview = production_overview.get_production_overview(
        profile_id=profile_id,
        limit_per_section=limit_per_section,
    )
    return utils.get_response(200, overview)
