from fastapi import APIRouter

from backend.app.protokflow.api.router import v1 as protokflow_v1

router = APIRouter()

router.include_router(protokflow_v1)
