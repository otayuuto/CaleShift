# CaleShift/main.py

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import traceback

from app.core.config import settings
from app.api.routers import api_router
from app.api.endpoints import liff_settings
from app.services.firestore_service import FirestoreService

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# ★★★ アプリケーション起動・終了イベントを修正 ★★★
#@app.on_event("startup")
#async def startup_event():
    
    #app.state.startup_error = None
    #try:
        # FirestoreServiceのインスタンスを一度だけ生成
        #db_service = FirestoreService()
        # app.stateに格納して、依存性注入で再利用できるようにする
        #app.state.db_service = db_service
        #print("INFO: FirestoreService instance created and stored in app.state.")
        
        # 起動時にFirestoreへの接続をヘルスチェック
        # usersコレクションへのクエリを試みる
        #await db_service.db_async.collection('users').limit(1).get()
        #print("INFO: Firestore health check successful.")
        
    #except Exception as e:
        # 起動に失敗した場合、エラーを記録
     #   error_traceback = traceback.format_exc()
      #  app.state.startup_error = error_traceback
       # print("\n--- CRITICAL STARTUP FAILED ---")
       # print(error_traceback)
       # print("--- END CRITICAL STARTUP FAILED ---\n")

#@app.on_event("shutdown")
#async def shutdown_event():
    #"""アプリケーション終了時にFirestoreクライアントを閉じる"""
    #if hasattr(app.state, 'db_service') and app.state.db_service:
        #await app.state.db_service.close_client()
        #print("INFO: Firestore async client closed.")

# ★★★ ミドルウェアの設定 ★★★
origins = [
    "https://liff.line.me",
    "https://miniapp.line.me",
    "https://caleshift-service-822292825577.asia-northeast1.run.app", # Cloud RunのURL
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
if settings.NGROK_URL and settings.NGROK_URL not in origins:
    origins.append(settings.NGROK_URL)

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

# ★★★ 静的ファイルとテンプレートの設定 ★★★
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
app.include_router(liff_settings.router) # liff_settings.py 内で /api/v1 などのパスを定義


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
    db_status = "Not initialized or error during startup."
    if hasattr(app.state, 'startup_error') and app.state.startup_error:
        db_status = f"Startup failed. See logs for details. Error starts with: {app.state.startup_error[:200]}..."
    elif hasattr(app.state, 'db_service') and app.state.db_service and app.state.db_service.db_async:
        db_status = f"Initialized (Project: {app.state.db_service.db_async.project}, DB: {app.state.db_service.db_async.database})"
    
    return {
        "project_name": settings.PROJECT_NAME,
        "gcp_project_id_from_settings": settings.GCP_PROJECT_ID,
        "session_secret_key_is_set": bool(settings.SESSION_SECRET_KEY),
        "firestore_db_status_in_app_state": db_status
    }

if __name__ == "__main__":
    import uvicorn
    host = getattr(settings, "HOST", "0.0.0.0")
    port = getattr(settings, "PORT", "8000")
    print(f"INFO: Starting Uvicorn server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)