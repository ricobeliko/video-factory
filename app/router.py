"""Application configuration - root APIRouter

Defines all FastAPI application endpoints.

Resources:
    1. https://fastapi.tiangolo.com/tutorial/bigger-applications

"""

from fastapi import APIRouter

from app.controllers import ping
from app.controllers.v1 import llm, video
from app.controllers.v2 import fleet as fleet_v2
from app.controllers.v2 import operations as operations_v2
from app.controllers.v2 import review as review_v2

root_api_router = APIRouter()
root_api_router.include_router(ping.router)

# v1
root_api_router.include_router(video.router)
root_api_router.include_router(llm.router)

# v2
root_api_router.include_router(operations_v2.router)
root_api_router.include_router(review_v2.router)
root_api_router.include_router(fleet_v2.router)
