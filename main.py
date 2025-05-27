# main.py
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
import os # osモジュールは secret_key の生成に使用

from app.api.routers import api_router
from app.core.config import settings # config.py から settings オブジェクトをインポート

# FastAPIアプリケーションインスタンスの作成 (1回だけ)
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" # OpenAPIのURLも設定しておく
)

# セッションミDLEウェアを追加 (CSRF対策のstate保存などに使用)
# secret_keyはアプリケーション起動ごとに変わらないように、固定値または環境変数から読み込むのが望ましい
# ここでは開発用として起動ごとにランダムなキーを生成する例のままにしておくが、
# 本番環境では固定キーにすること。
# 例: settings.SESSION_SECRET_KEY などとして .env から読み込む
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET_KEY)
# または、より安全な固定キーの例 (実際のキーはもっとランダムなものに)
# app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET_KEY or "a_very_strong_random_secret_key_here")


# APIルーターをアプリケーションに含める
app.include_router(api_router, prefix=settings.API_V1_STR)


# (オプション) アプリケーション起動時のイベントハンドラ
@app.on_event("startup")
async def startup_event():
    print("Application startup...")
    # ここに起動時処理を記述
    pass

# (オプション) アプリケーション終了時のイベントハンドラ
@app.on_event("shutdown")
async def shutdown_event():
    print("Application shutdown...")
    # ここに終了時処理を記述
    pass


# ルートパスへの簡単なエンドポイント (動作確認用)
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}

# 設定値確認用エンドポイント (デバッグ用)
@app.get("/config-check", tags=["Utility"])
async def check_config():
    # .envから読み込んだシークレットなどを確認（本番では公開しないように注意）
    return {
        "project_name": settings.PROJECT_NAME,
        "line_channel_secret_set": bool(settings.LINE_CHANNEL_SECRET and settings.LINE_CHANNEL_SECRET != "dummy_secret"),
        "google_oauth_client_id_set": bool(settings.GOOGLE_OAUTH_CLIENT_ID),
        "redirect_uri_for_oauth": settings.GOOGLE_OAUTH_REDIRECT_URI
    }

# Uvicornで実行するための設定 (主に開発時)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)