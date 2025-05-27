# app/api/routers.py
from fastapi import APIRouter
from app.api.endpoints import line_webhook # この行を追加または確認
from app.api.endpoints import google_auth # 今後のためにコメントアウトしておく等

api_router = APIRouter()

api_router.include_router(google_auth.router, prefix="/google", tags=["Google Authentication"])
api_router.include_router(line_webhook.router, prefix="/line", tags=["LINE Webhook"]) # この行を追加または確認
# api_router.include_router(google_auth.router, prefix="/google", tags=["Google Authentication"])