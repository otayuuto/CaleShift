# main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

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

# 1. 静的ファイルのマウント (staticディレクトリが存在する場合)
# これにより /static/css/style.css などにアクセス可能になる
# HTMLから <link rel="stylesheet" href="/static/css/your_style.css"> のように参照
if (BASE_DIR / "static").is_dir(): # staticディレクトリの存在を確認
    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static"),
        name="static",
    )
else:
    print(f"Warning: Static directory not found at {BASE_DIR / 'static'}")


# 2. Jinja2テンプレートの設定 (templatesディレクトリが存在する場合)
# これによりHTMLテンプレートをレンダリングできる
if (BASE_DIR / "templates").is_dir(): # templatesディレクトリの存在を確認
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.state.templates = templates # app.stateに格納して他のモジュールからアクセス可能にする
else:
    print(f"Warning: Templates directory not found at {BASE_DIR / 'templates'}")
    app.state.templates = None # templatesがない場合はNoneを設定しておくなど


# 3. APIルーターのインクルード
# 既存のバックエンドAPI (例: LINE Webhook) は settings.API_V1_STR のprefixを付ける
app.include_router(api_router, prefix=settings.API_V1_STR)

# LIFF関連のルーターは、prefixなし (または独自の短いprefix) でインクルード
# これにより、liff_settings.py で定義したパスがそのまま使われる
# (例: /liff/settings, /api/v1/users/... など)
app.include_router(liff_settings.router)


# ルートパス (簡単な動作確認用)
@app.get("/")
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}


# 設定値の確認用エンドポイント (開発時のみ、本番では削除または保護)
@app.get("/config-check", include_in_schema=False) # OpenAPIスキーマに含めない
async def check_config():
    # .envから読み込んだシークレットなどを確認（本番では公開しないように注意）
    # 表示する内容は慎重に選ぶこと
    return {
        "project_name": settings.PROJECT_NAME,
        "api_v1_prefix": settings.API_V1_STR,
        "line_channel_secret_loaded": bool(settings.LINE_CHANNEL_SECRET and settings.LINE_CHANNEL_SECRET != "dummy_secret"),
        "google_application_credentials_set": bool(settings.GOOGLE_APPLICATION_CREDENTIALS),
        "gcp_project_id_set": bool(settings.GCP_PROJECT_ID),
    }

# 開発時に `python main.py` で直接実行するためのUvicorn起動設定
# 本番環境では、`uvicorn main:app --host 0.0.0.0 --port 8000` のようにコマンドラインから起動することが一般的
# if __name__ == "__main__":
#     import uvicorn
#     # ポート番号も設定ファイルから取得できるようにするとより柔軟
#     port = getattr(settings, "PORT", 8000)
#     host = getattr(settings, "HOST", "0.0.0.0")
#     uvicorn.run("main:app", host=host, port=port, reload=True)
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
