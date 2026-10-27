"""Production diagnostics endpoints for Web UI V2 (Missão SIS3)."""

from typing import Optional
from fastapi import Depends, Query, Request

from app.controllers import base
from app.controllers.v2.base import new_router
from app.services import production_diagnostics
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


@router.get(
    "/diagnostics/overview",
    summary="Get production diagnostics overview",
)
def get_diagnostics_overview(
    request: Request,
    profile_id: Optional[str] = Query(default=None, description="Filtra por canal / profile_id específico"),
):
    overview = production_diagnostics.get_diagnostics_overview(
        profile_id=profile_id,
    )
    return utils.get_response(200, overview)
