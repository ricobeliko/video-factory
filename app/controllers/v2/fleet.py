"""Fleet operations summary endpoints for Web UI V2 (Missão C)."""

from fastapi import Depends, Request

from app.controllers import base
from app.controllers.v2.base import new_router
from app.services import operator_console
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


@router.get(
    "/fleet/summary",
    summary="Get fleet operational summary",
)
def get_fleet_summary(request: Request):
    summary = operator_console.get_fleet_summary()
    return utils.get_response(200, summary)
