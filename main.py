from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles # ★変更/追加箇所
from fastapi.templating import Jinja2Templates # ★変更/追加箇所
from pathlib import Path # ★変更/追加箇所

# 設定ファイルをインポート
from app.core.config import settings

# APIルーターをインポート (LINE WebhookなどバックエンドAPI用)
from app.api.routers import api_router

# LIFF関連のエンドポイントルーターをインポート
from app.api.endpoints import liff_settings # ★変更/追加箇所: liff_settings.py から router をインポート

# プロジェクトのベースディレクトリを取得
BASE_DIR = Path(__file__).resolve().parent # ★変更/追加箇所

# FastAPIアプリケーションのインスタンスを作成 (1回にまとめる)
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" # APIドキュメントのURL
)

# 1. 静的ファイルのマウント (staticディレクトリが存在する場合)
# ★変更/追加箇所: ここから静的ファイルとテンプレートの設定
if (BASE_DIR / "static").is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static"),
        name="static",
    )
else:
    print(f"Warning: Static directory not found at {BASE_DIR / 'static'}")

# 2. Jinja2テンプレートの設定 (templatesディレクトリが存在する場合)
if (BASE_DIR / "templates").is_dir():
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.state.templates = templates # app.stateに格納
else:
    print(f"Warning: Templates directory not found at {BASE_DIR / 'templates'}")
    app.state.templates = None
# ★変更/追加箇所: ここまで静的ファイルとテンプレートの設定

# 3. APIルーターのインクルード
# 既存のバックエンドAPI (例: LINE Webhook)
app.include_router(api_router, prefix=settings.API_V1_STR)

# LIFF関連のルーター (prefixなしで、liff_settings.py内のパスがそのまま使われる)
app.include_router(liff_settings.router) # ★変更/追加箇所

# ルートパス (既存の機能)
@app.get("/")
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}

# 設定値の確認用エンドポイント (既存の機能、OpenAPIスキーマから除外を推奨)
@app.get("/config-check", include_in_schema=False) # ★変更/追加箇所: include_in_schema=False
async def check_config():
    # 表示する内容は慎重に選ぶこと
    return {
        "project_name": settings.PROJECT_NAME,
        "api_v1_prefix": settings.API_V1_STR, # ★追加: 確認項目として
        "line_channel_secret_loaded": bool(settings.LINE_CHANNEL_SECRET and settings.LINE_CHANNEL_SECRET != "dummy_secret"),
        # ★追加: 今後必要になる設定の確認項目例
        "google_application_credentials_set": bool(settings.GOOGLE_APPLICATION_CREDENTIALS),
        "gcp_project_id_set": bool(settings.GCP_PROJECT_ID),
    }

# 開発用サーバー起動スクリプト (既存の機能)
# if __name__ == "__main__":
#     import uvicorn
#     # ポート番号も設定ファイルから取得できるようにするとより柔軟
#     port = getattr(settings, "PORT", 8000)
#     host = getattr(settings, "HOST", "0.0.0.0")
#     uvicorn.run("main:app", host=host, port=port, reload=True)