# app/api/routers.py
from fastapi import APIRouter
from app.api.endpoints import line_webhook # この行を追加または確認
from app.api.endpoints import google_auth
from app.api.endpoints import calendar_events

api_router = APIRouter()

api_router.include_router(google_auth.router, prefix="/google", tags=["Google Authentication"])
api_router.include_router(line_webhook.router, prefix="/line", tags=["LINE Webhook"])
api_router.include_router(calendar_events.router, prefix="/calendar", tags=["Calendar Events"])