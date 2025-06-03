# main.py
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from app.api.api_v1.api import api_router as api_v1_router # google_auth ルータを含む
from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)

# SessionMiddleware の設定
# 重要: secret_keyは固定の文字列にしてください。
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    # session_cookie="your_app_session", # クッキー名を変更したい場合
    # max_age=14 * 24 * 60 * 60,  # セッションの有効期限 (秒)、デフォルトは2週間
    # path="/", # セッションクッキーが有効なパス
    # domain=None, # セッションクッキーが有効なドメイン
    # secure=True, # HTTPS経由でのみクッキーを送信 (本番推奨、ngrokはHTTPSなのでTrueでも可)
    # httponly=True, # JavaScriptからクッキーにアクセス不可 (推奨)
    # samesite="lax" # CSRF対策 (lax または strict)
)

app.include_router(api_v1_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {"message": f"{settings.PROJECT_NAME} is running!"}

# (必要であれば) api_v1_router に google_auth.router を含める設定を確認
# 例: app/api/api_v1/api.py
# from fastapi import APIRouter
# from app.api.endpoints import google_auth # , other_routers...
#
# api_router = APIRouter()
# api_router.include_router(google_auth.router, prefix="/google", tags=["google"])
# # api_router.include_router(other_routers.router, ...)