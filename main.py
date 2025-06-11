# main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
# import os # settings.SESSION_SECRET_KEY を使うので、直接osモジュールは不要になることが多い

# 設定ファイルをインポート
from app.core.config import settings

# APIルーターをインポート (LINE Webhook, Google OAuthなどバックエンドAPI用)
from app.api.routers import api_router

# LIFF関連のエンドポイントルーターをインポート (liff_settings.py から router をインポート)
from app.api.endpoints import liff_settings # liff_settings.py が存在し、routerが定義されている前提

# ★★★ Firestoreクライアントとtracebackをインポート ★★★
from google.cloud import firestore
import traceback

# プロジェクトのベースディレクトリを取得
BASE_DIR = Path(__file__).resolve().parent

# FastAPIアプリケーションインスタンスの作成 (1回だけ)
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" # OpenAPIのURLも設定しておく
)

# --- ★★★ Firestoreクライアントの初期化をstartupイベントで行う ★★★ ---
@app.on_event("startup")
async def startup_app_resources(): # 関数名をより具体的に (DB以外も含む可能性を考慮)
    print(f"INFO: Application startup process begins for {settings.PROJECT_NAME}...")
    # Firestoreクライアントの初期化
    try:
        database_id_to_use = "caleshiftdb" # ★★★ ここにデータベースIDを指定 ★★★
        print(f"DEBUG_FIRESTORE (startup): Attempting to initialize Firestore client with project_id: '{settings.GCP_PROJECT_ID}' and database_id: '{database_id_to_use}'")
        
        if not settings.GCP_PROJECT_ID:
            print("CRITICAL_FIRESTORE_ERROR (startup): GCP_PROJECT_ID is not set in settings.")
            app.state.db = None # dbが存在しないことを明確にする
            return # ここで処理を中断

        # ↓↓↓ database パラメータを追加 ↓↓↓
        app.state.db = firestore.Client(project=settings.GCP_PROJECT_ID, database=database_id_to_use)
        print(f"INFO_FIRESTORE (startup): Firestore client initialized successfully for database '{database_id_to_use}' and stored in app.state.db.")
    except Exception as e:
        print(f"CRITICAL_FIRESTORE_ERROR (startup): Failed to initialize Firestore client for database '{database_id_to_use}': {e}")
        traceback.print_exc()
        app.state.db = None # エラー時もNoneをセット

    # 他の起動時処理があればここに追加 (例: 他のDB接続、モデルのロードなど)
    print(f"INFO: Application resources (like DB client) initialized.")


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
    templates_instance = Jinja2Templates(directory=templates_dir) # 変数名を変更
    app.state.templates = templates_instance # app.stateに格納してどこからでもアクセスできるようにする
    print(f"INFO: Templates configured from {templates_dir}")
else:
    print(f"WARNING: Templates directory not found at {templates_dir}, templating will not be available via app.state.templates.")
    app.state.templates = None


# 4. APIルーターのインクルード
# バックエンドAPI (LINE Webhook, Google OAuthなど)
app.include_router(api_router, prefix=settings.API_V1_STR)

# LIFF関連のルーター
app.include_router(liff_settings.router, tags=["LIFF Pages"]) # タグ名を統一


# 5. アプリケーション終了イベントハンドラ (オプション)
@app.on_event("shutdown")
async def shutdown_app_resources(): # 関数名をより具体的に
    print(f"INFO: Application shutdown process begins for {settings.PROJECT_NAME}.")
    # ここに終了時処理を記述 (例: データベース接続クローズなど)
    if hasattr(app.state, 'db') and app.state.db:
        # Firestoreクライアントには明示的なclose()メソッドは通常不要だが、
        # 他のDB接続などでは必要になることがある
        print("INFO: Firestore client does not require explicit closing typically.")
    print(f"INFO: Application resources cleanup complete.")


# 6. ルートパスへの簡単なエンドポイント (動作確認用)
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}

# 7. 設定値確認用エンドポイント (デバッグ用)
@app.get("/config-check", tags=["Utility"], include_in_schema=False)
async def check_config():
    db_status = "Not initialized or error"
    if hasattr(app.state, 'db'): # app.stateにdb属性があるかチェック
        db_status = "Initialized successfully" if app.state.db else "Initialization failed or None"
    
    return {
        "project_name": settings.PROJECT_NAME,
        "api_v1_prefix": settings.API_V1_STR,
        "line_channel_secret_set": bool(settings.LINE_CHANNEL_SECRET and settings.LINE_CHANNEL_SECRET != "dummy_secret"),
        "google_oauth_client_id_set": bool(settings.GOOGLE_OAUTH_CLIENT_ID),
        "google_application_credentials_set": bool(settings.GOOGLE_APPLICATION_CREDENTIALS),
        "gcp_project_id_set": bool(settings.GCP_PROJECT_ID),
        "session_secret_key_is_set": bool(settings.SESSION_SECRET_KEY),
        "redirect_uri_for_oauth": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "firestore_db_status_in_app_state": db_status # ★ Firestoreクライアントの状態を追加
    }

# 8. Uvicornで実行するための設定 (主に開発時)
if __name__ == "__main__":
    import uvicorn
    host = getattr(settings, "HOST", "0.0.0.0")
    port = getattr(settings, "PORT", 8000)

    print(f"INFO: Starting Uvicorn server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)