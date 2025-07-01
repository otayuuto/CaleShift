# main.py (統合・修正後)
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware # ★ from origin/aoshi
from starlette.middleware.sessions import SessionMiddleware # ★ from HEAD
from pathlib import Path
import traceback

# 設定ファイルをインポート
from app.core.config import settings

# APIルーターをインポート
from app.api.routers import api_router
from app.api.endpoints import liff_settings

# ★★★ FirestoreService クラスをインポート ★★★
# firestore_service.py をクラスベースに統一するため、クラスをインポート
from app.services.firestore_service import FirestoreService

# プロジェクトのベースディレクトリを取得
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# ★★★ アプリケーション起動・終了イベント ★★★
@app.on_event("startup")
async def startup_event():
    # FirestoreServiceのインスタンスを app.state に格納し、アプリケーション全体で共有
    app.state.db_service = FirestoreService()
    print(f"INFO: FirestoreService initialized and stored in app.state.db_service.")
    print(f"INFO: Application startup complete for {settings.PROJECT_NAME}.")

@app.on_event("shutdown")
async def shutdown_event():
    # Firestore AsyncClient には明示的な close() メソッドがある
    if hasattr(app.state, 'db_service') and app.state.db_service:
        await app.state.db_service.close_client()
        print("INFO: Firestore async client closed.")
    print(f"INFO: Application shutdown complete for {settings.PROJECT_NAME}.")


# ★★★ ミドルウェアの設定 (CORS -> Session の順) ★★★
# CORSミドルウェア
origins = [
    "https://liff.line.me",
    "https://miniapp.line.me",
]
if settings.NGROK_URL: # .env に設定されたngrokのURLを動的に追加
    origins.append(settings.NGROK_URL)
# 必要に応じてローカル開発用のオリジンも追加
# origins.append("http://localhost:8000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
print(f"INFO: CORS middleware configured with origins: {origins}")

# セッションミドルウェア
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET_KEY)
print("INFO: Session middleware configured.")


# ★★★ 静的ファイルとテンプレートの設定 ★★★
# 静的ファイルのマウント
static_dir = BASE_DIR / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    print(f"INFO: Static files mounted from {static_dir}")
else:
    print(f"WARNING: Static directory not found at {static_dir}.")

# Jinja2テンプレートの設定
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


# ★★★ ルートとデバッグエンドポイント ★★★
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}

@app.get("/config-check", tags=["Utility"], include_in_schema=False)
async def check_config():
    db_status = "Not initialized or error"
    if hasattr(app.state, 'db_service') and app.state.db_service and app.state.db_service.db_async:
        db_status = f"Initialized (Project: {app.state.db_service.db_async.project}, DB: {app.state.db_service.db_async.database})"
    return {
        "project_name": settings.PROJECT_NAME,
        # ... (他の設定確認項目はそのまま) ...
        "gcp_project_id_set": bool(settings.GCP_PROJECT_ID),
        "session_secret_key_is_set": bool(settings.SESSION_SECRET_KEY),
        "firestore_db_status_in_app_state": db_status
    }

# ★★★ Uvicorn起動スクリプト ★★★
if __name__ == "__main__":
    import uvicorn
    host = getattr(settings, "HOST", "0.0.0.0")
    port = getattr(settings, "PORT", 8000)
    print(f"INFO: Starting Uvicorn server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)