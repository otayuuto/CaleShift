# main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import os # osモジュールは不要になるかも (settings.SESSION_SECRET_KEY を使うため)

# 設定ファイルをインポート
from app.core.config import settings

# APIルーターをインポート (LINE Webhook, Google OAuthなどバックエンドAPI用)
from app.api.routers import api_router

# LIFF関連のエンドポイントルーターをインポート (liff_settings.py から router をインポート)
from app.api.endpoints import liff_settings # liff_settings.py が存在し、routerが定義されている前提

# プロジェクトのベースディレクトリを取得
BASE_DIR = Path(__file__).resolve().parent

# FastAPIアプリケーションインスタンスの作成 (1回だけ)
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" # OpenAPIのURLも設定しておく
)

# 1. セッションミドルウェアを追加 (LIFFとバックエンドAPIで共通して使用)
#    secret_keyは settings から読み込む固定値を使用
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET_KEY)

# 2. 静的ファイルのマウント (staticディレクトリが存在する場合)
static_dir = BASE_DIR / "static"
if static_dir.is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=static_dir),
        name="static",
    )
    print(f"INFO: Static files mounted from {static_dir}")
else:
    print(f"WARNING: Static directory not found at {static_dir}, /static endpoint will not be available.")

# 3. Jinja2テンプレートの設定 (templatesディレクトリが存在する場合)
templates_dir = BASE_DIR / "templates"
if templates_dir.is_dir():
    templates = Jinja2Templates(directory=templates_dir)
    app.state.templates = templates # app.stateに格納してどこからでもアクセスできるようにする
    print(f"INFO: Templates configured from {templates_dir}")
else:
    print(f"WARNING: Templates directory not found at {templates_dir}, templating will not be available via app.state.templates.")
    app.state.templates = None


# 4. APIルーターのインクルード
# バックエンドAPI (LINE Webhook, Google OAuthなど)
app.include_router(api_router, prefix=settings.API_V1_STR)

# LIFF関連のルーター (prefixなし、またはLIFF専用のprefixを設定することも可能)
# liff_settings.router が app.api.endpoints.liff_settings 内で定義されていること
app.include_router(liff_settings.router, tags=["LIFF"]) # tagsを追加してOpenAPIでの分類を明確に


# 5. アプリケーション起動・終了イベントハンドラ (オプション)
@app.on_event("startup")
async def startup_event():
    print(f"INFO: Application startup complete for {settings.PROJECT_NAME}.")
    # ここに起動時処理を記述 (例: データベース接続確認など)
    pass

@app.on_event("shutdown")
async def shutdown_event():
    print(f"INFO: Application shutdown for {settings.PROJECT_NAME}.")
    # ここに終了時処理を記述 (例: データベース接続クローズなど)
    pass


# 6. ルートパスへの簡単なエンドポイント (動作確認用)
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}

# 7. 設定値確認用エンドポイント (デバッグ用)
@app.get("/config-check", tags=["Utility"], include_in_schema=False) # OpenAPIスキーマから除外
async def check_config():
    # .envから読み込んだシークレットなどを確認（本番では公開しないように注意）
    return {
        "project_name": settings.PROJECT_NAME,
        "api_v1_prefix": settings.API_V1_STR,
        "line_channel_secret_set": bool(settings.LINE_CHANNEL_SECRET and settings.LINE_CHANNEL_SECRET != "dummy_secret"),
        "google_oauth_client_id_set": bool(settings.GOOGLE_OAUTH_CLIENT_ID),
        "google_application_credentials_set": bool(settings.GOOGLE_APPLICATION_CREDENTIALS),
        "gcp_project_id_set": bool(settings.GCP_PROJECT_ID),
        "session_secret_key_is_set_and_not_default": bool(settings.SESSION_SECRET_KEY and settings.SESSION_SECRET_KEY != "a_very_strong_default_secret_key_if_not_set"), # デフォルトキーを使っていないか
        "redirect_uri_for_oauth": settings.GOOGLE_OAUTH_REDIRECT_URI
    }

# 8. Uvicornで実行するための設定 (主に開発時)
if __name__ == "__main__":
    import uvicorn
    # ポート番号やホストも設定ファイルから取得できるようにするとより柔軟
    # settings.py に HOST: str = "0.0.0.0", PORT: int = 8000 のように定義しておくと良い
    host = getattr(settings, "HOST", "0.0.0.0")
    port = getattr(settings, "PORT", 8000) # デフォルトは8000

    print(f"INFO: Starting Uvicorn server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)