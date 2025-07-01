# CaleShift/main.py

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware # ★ CORSMiddlewareをインポート

# 設定ファイルをインポート
from app.core.config import settings

# APIルーターをインポート (LINE WebhookなどバックエンドAPI用)
from app.api.routers import api_router

# LIFF関連のエンドポイントルーターをインポート
from app.api.endpoints import liff_settings # liff_settings.py から router をインポート

# プロジェクトのベースディレクトリを取得
BASE_DIR = Path(__file__).resolve().parent

# FastAPIアプリケーションのインスタンスを作成
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" # APIドキュメントのURL
)

# ★★★ CORSミドルウェアの設定を追加 ★★★
# LIFFアプリのオリジンと、ngrokのドメインを許可リストに追加します。
# !!! 注意: "https://your-current-ngrok-url.ngrok-free.app" の部分は、
# !!! あなたが実際に使用しているngrokのURLに置き換える必要があります。
# !!! settings.html の API_BASE_URL と同じ値を設定してください。
origins = [
    "https://liff.line.me",
    "https://miniapp.line.me",
    "https://f806-223-29-247-221.ngrok-free.app", # ★★★ あなたの現在のngrokのURLに置き換えてください ★★★
    # ローカル開発時にPCブラウザから直接アクセスする場合 (必要に応じて)
    # "http://localhost:8000",
    # "http://127.0.0.1:8000",
]
# settings.html の API_BASE_URL に設定した ngrok のドメインを動的に追加する場合の例 (もし settings から取得できるなら)
# if settings.API_BASE_URL and settings.API_BASE_URL not in origins:
#    origins.append(settings.API_BASE_URL)


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # 許可するオリジンのリスト
    allow_credentials=True, # Cookieの共有を許可するかどうか (LIFFでは通常不要だが念のため)
    allow_methods=["*"],    # 全てのHTTPメソッドを許可
    allow_headers=["*"],    # 全てのHTTPヘッダーを許可
)
# ★★★ CORSミドルウェアの設定ここまで ★★★


# 1. 静的ファイルのマウント (staticディレクトリが存在する場合)
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
    app.state.templates = templates
else:
    print(f"Warning: Templates directory not found at {BASE_DIR / 'templates'}")
    app.state.templates = None


# 3. APIルーターのインクルード
app.include_router(api_router, prefix=settings.API_V1_STR) # 既存のAPIルーター
app.include_router(liff_settings.router) # LIFF関連のルーター


# ルートパス
@app.get("/")
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}


# 設定値の確認用エンドポイント
@app.get("/config-check", include_in_schema=False)
async def check_config():
    return {
        "project_name": settings.PROJECT_NAME,
        "api_v1_prefix": settings.API_V1_STR,
        "line_channel_secret_loaded": bool(settings.LINE_CHANNEL_SECRET and settings.LINE_CHANNEL_SECRET != "dummy_secret"),
        "google_application_credentials_set": bool(settings.GOOGLE_APPLICATION_CREDENTIALS),
        "gcp_project_id_set": bool(settings.GCP_PROJECT_ID),
    }

# 開発用サーバー起動スクリプト (通常は uvicorn コマンドで直接起動)
# if __name__ == "__main__":
#     import uvicorn
#     port = getattr(settings, "PORT", 8000)
#     host = getattr(settings, "HOST", "0.0.0.0")
#     uvicorn.run("main:app", host=host, port=port, reload=True)