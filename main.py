# CaleShift/main.py

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import traceback
from google.oauth2 import service_account # ★ インポート追加
import json # ★ インポート追加
import os # ★ インポート追加
from google.cloud import firestore # startup_eventで使うのでインポート

# 設定ファイルをインポート
from app.core.config import settings
from app.api.routers import api_router
from app.api.endpoints import liff_settings
from app.api.endpoints import shift_management # shift_managementもインポート

# FirestoreService クラスをインポート
from app.services.firestore_service import FirestoreService

BASE_DIR = Path(__file__).resolve().parent

# FastAPIアプリケーションインスタンスの作成
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# --- アプリケーション起動・終了イベント ---
@app.on_event("startup")
async def startup_event():
    """
    アプリケーション起動時に実行される処理。
    FirestoreServiceのインスタンスを生成し、app.stateに格納します。
    認証情報の解決はFirestoreServiceの__init__内で行われます。
    """
    print(f"INFO: Application startup process begins for {settings.PROJECT_NAME}...")
    try:
        # ★★★ FirestoreService() を引数なしで呼び出すだけ ★★★
        # FirestoreServiceの__init__が環境変数を元に自動で認証します
        app.state.db_service = FirestoreService()
        
        if app.state.db_service and app.state.db_service.db_async:
             print(f"INFO: FirestoreService initialized successfully and stored in app.state.db_service.")
        else:
             print("CRITICAL_ERROR: FirestoreService initialization failed. Check logs from firestore_service.py.")
    except Exception as e:
        print(f"CRITICAL_ERROR: An unhandled exception occurred during startup: {e}")
        traceback.print_exc()
        app.state.db_service = None
    
    print(f"INFO: Application startup complete.")

@app.on_event("shutdown")
async def shutdown_event():
    """アプリケーション終了時に実行される処理。"""
    print(f"INFO: Application shutdown process begins...")
    if hasattr(app.state, 'db_service') and app.state.db_service:
        await app.state.db_service.close_client()
    print(f"INFO: Application shutdown complete.")


# --- ミドルウェアの設定 (CORS -> Session の順) ---

# CORSミドルウェア
origins = [
    "https://liff.line.me",
    "https://miniapp.line.me",
    "https://caleshift-service-822292825577.asia-northeast1.run.app", # Cloud RunのURL
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
# .env や env.yaml で設定された SERVICE_URL を許可オリジンに追加
if settings.SERVICE_URL:
    origins.append(settings.SERVICE_URL)
# ローカル開発用に localhost:3000 を追加 (もしフロントエンドを別で開発する場合)
# origins.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
print(f"INFO: CORS middleware configured with origins: {origins}")

app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET_KEY)
print("INFO: Session middleware configured.")


# --- 静的ファイルとテンプレートの設定 ---

# 静的ファイルのマウント
static_dir = BASE_DIR / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    print(f"INFO: Static files mounted from {static_dir}")
else:
    print(f"WARNING: Static directory not found at {static_dir}.")

templates_dir = BASE_DIR / "templates"
if templates_dir.is_dir():
    app.state.templates = Jinja2Templates(directory=templates_dir)
    print(f"INFO: Templates configured from {templates_dir}")
else:
    print(f"WARNING: Templates directory not found at {templates_dir}.")
    app.state.templates = None

# ★★★ APIルーターのインクルード ★★★
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(liff_settings.router, tags=["LIFF"])
#app.include_router(liff_settings.router)
app.include_router(shift_management.router)

# ★★★ ルートエンドポイント (起動エラーチェック機能付き) ★★★
@app.get("/", response_class=Response, include_in_schema=False)
async def read_root():
    if hasattr(app.state, 'startup_error') and app.state.startup_error:
        content = "--- APPLICATION STARTUP FAILED ---\n\n" + app.state.startup_error
        return Response(content=content, media_type="text/plain", status_code=503)
    return Response(content="Welcome! CaleShift application is running.", media_type="text/plain")

# ★★★ デバッグエンドポイント ★★★
@app.get("/config-check", tags=["Utility"], include_in_schema=False)
async def check_config():
    db_status = "Not available in app.state"
    if hasattr(app.state, 'db_service') and app.state.db_service:
        db_client = app.state.db_service.db_async
        if db_client:
            db_status = f"Initialized (Project: {db_client.project}, DB: {db_client.database})"
        else:
            db_status = "Initialization failed (client is None)"

    return {
        "project_name": settings.PROJECT_NAME,
        "api_v1_prefix": settings.API_V1_STR,
        "service_url": settings.SERVICE_URL,
        "gcp_project_id": settings.GCP_PROJECT_ID,
        "firestore_database_id": settings.DATABASE_ID,
        "firestore_client_status": db_status,
        "openai_model": settings.OPENAI_MODEL_NAME
    }

# --- Uvicorn起動スクリプト ---

if __name__ == "__main__":
    import uvicorn
    import os
    
    # Cloud Runが提供するPORT環境変数を尊重する。なければ8000をデフォルトに。
    port = int(os.environ.get("PORT", 8000))
    # host は 0.0.0.0 を基本とする (コンテナ環境では必須)
    host = getattr(settings, "HOST", "0.0.0.0")
    print(f"INFO: Starting Uvicorn server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)