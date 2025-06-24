# app/api/api_v1/api.py

from fastapi import APIRouter

# 他のエンドポイントモジュールからのルーターをインポート
from app.api.endpoints import google_auth
# 例: もし他のエンドポイントがあれば (例: line_webhook, users, items など)
# from app.api.endpoints import line_webhook
# from app.api.endpoints import users
# from app.api.endpoints import items

# このapi_routerインスタンスが、バージョン1のAPIエンドポイント全体を束ねます。
api_router = APIRouter()

# google_auth.py で定義されたルーターをインクルード
# /api/v1/google というパスでアクセスできるようになります。
api_router.include_router(
    google_auth.router,  # google_auth.py 内で定義された APIRouter インスタンス
    prefix="/google",    # このルーター内のエンドポイントは "/google" というプレフィックスを持つ
    tags=["Google Authentication"] # FastAPIのドキュメント (Swagger UI) でのグルーピング用タグ
)

# --- 他のエンドポイントのルーターも同様にインクルード ---
# 例: LINE Webhook関連のエンドポイント
# api_router.include_router(
#     line_webhook.router,
#     prefix="/line",
#     tags=["LINE Webhook"]
# )

# 例: ユーザー関連のエンドポイント
# api_router.include_router(
#     users.router,
#     prefix="/users",
#     tags=["Users"]
# )

# 例: アイテム関連のエンドポイント
# api_router.include_router(
#     items.router,
#     prefix="/items",
#     tags=["Items"]
# )

# ---------------------------------------------------------

# 必要であれば、このapi_routerに直接エンドポイントを定義することも可能です。
# @api_router.get("/health", tags=["Health Check"])
# async def health_check():
#     return {"status": "ok"}