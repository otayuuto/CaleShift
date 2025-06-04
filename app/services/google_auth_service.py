# app/services/google_auth_service.py (関数ベースのまま、request を引数に追加)
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest # 名前衝突回避
import os
from typing import Optional, Tuple, Dict
import traceback
import json
from fastapi import Request # Request をインポート

from app.core.config import settings

def get_google_oauth_flow(request: Optional[Request] = None) -> Flow: # request をオプション引数に
    # リダイレクトURIを動的に決定 (もしrequestがあれば)
    # settings.GOOGLE_OAUTH_REDIRECT_URI を基本としつつ、
    # NGROK_URL があればそれを使うなど、以前のクラスベースの _get_base_url のようなロジックが必要になる場合も。
    # ここでは簡単のため settings.GOOGLE_OAUTH_REDIRECT_URI を使う。
    # もし request から動的に生成したい場合は、そのロジックをここに記述。
    redirect_uri_to_use = settings.GOOGLE_OAUTH_REDIRECT_URI
    
    # --- NGROK_URL や X-Forwarded ヘッダーを考慮したリダイレクトURI生成ロジック (クラスベースから移植する場合) ---
    if request and settings.NGROK_URL and settings.NGROK_URL.startswith("https://"):
        base_url = settings.NGROK_URL.rstrip("/")
        # コールバックパス名をどこかで定義しておく (例: "google_auth_callback")
        # もし FastAPI の request.url_for を使いたいなら、この関数が request を受け取る必要がある
        # ここでは仮に settings.API_V1_STR + "/google/auth/callback" とする
        callback_path = f"{settings.API_V1_STR}/google/auth/callback" 
        redirect_uri_to_use = f"{base_url}{callback_path}"
        print(f"DEBUG: Using dynamic redirect_uri based on NGROK_URL: {redirect_uri_to_use}")
    elif request:
        # X-Forwarded ヘッダーを考慮 (リバースプロキシ経由の場合)
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        base_url = f"{proto}://{host}"
        callback_path = f"{settings.API_V1_STR}/google/auth/callback"
        redirect_uri_to_use = f"{base_url}{callback_path}"
        print(f"DEBUG: Using dynamic redirect_uri based on X-Forwarded headers: {redirect_uri_to_use}")

    # redirect_uri_to_use が HTTPS であることのチェック (ローカル開発以外)
    if not redirect_uri_to_use.startswith("https://") and \
       not ("127.0.0.1" in redirect_uri_to_use or "localhost" in redirect_uri_to_use) and \
       settings.ENVIRONMENT != "local": # settings に ENVIRONMENT を追加
        print(f"CRITICAL: OAuth redirect_uri must be HTTPS in non-local environment. Got: {redirect_uri_to_use}")
        # ここで例外を発生させるか、デフォルトのHTTPSのURIを使うなどのフォールバックが必要
        # raise ValueError("OAuth redirect_uri must be HTTPS in non-local environment.")


    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "project_id": settings.GCP_PROJECT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uris": [
                settings.GOOGLE_OAUTH_REDIRECT_URI, # GCPコンソールに登録した主要なもの
                redirect_uri_to_use # 動的に生成したものもリストに含める (GCPにも登録が必要)
            ]
        }
    }
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=settings.GOOGLE_CALENDAR_SCOPES.split(),
    )
    flow.redirect_uri = redirect_uri_to_use # 実際に使うリダイレクトURI
    return flow

def generate_auth_url(request: Request) -> Tuple[str, str]: # request を引数に追加
    """Google認証URLとstateを生成する"""
    flow = get_google_oauth_flow(request) # request を渡す
    state = os.urandom(16).hex()
    authorization_url, generated_state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=state
    )
    print(f"INFO: Generated Auth URL: {authorization_url}, State: {state}")
    return authorization_url, state

def exchange_code_for_credentials(request: Request, authorization_response_url: str, original_state_from_session: str) -> Optional[Credentials]: # request を引数に追加
    """認可コードを認証情報に交換する"""
    flow = get_google_oauth_flow(request) # request を渡す
    try:
        # ... (以降の処理は変更なし、ただし flow の redirect_uri が request に基づいて設定される)
        print(f"DEBUG: Attempting to fetch token with authorization_response_url: {authorization_response_url}")
        print(f"DEBUG: Using redirect_uri in flow for fetch_token: {flow.redirect_uri}")

        flow.fetch_token(authorization_response=authorization_response_url) # ここで redirect_uri が検証される
        credentials = flow.credentials
        # ... (以降の処理)
        print(f"INFO: Credentials obtained. AccessToken valid: {credentials.valid}")
        if credentials.token:
            print(f"INFO: Access token obtained: {credentials.token[:30]}...")
        if credentials.refresh_token:
            print(f"INFO: Refresh token obtained: {credentials.refresh_token[:30]}...")
        else:
            print("WARNING: No refresh token was obtained. Check 'access_type=offline' and consent screen configuration.")
        
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                print("INFO: Credentials expired, attempting to refresh.")
                credentials.refresh(GoogleAuthRequest())
                print(f"INFO: Credentials refreshed. AccessToken valid: {credentials.valid}")
            else:
                print("ERROR: Failed to obtain valid credentials or refresh them.")
                return None
        
        return credentials
    except Exception as e:
        print(f"CRITICAL_ERROR in exchange_code_for_credentials: Type: {type(e)}, Message: {str(e)}")
        print("--- Full Traceback for exchange_code_for_credentials ---")
        traceback.print_exc()
        print("------------------------------------------------------")
        return None

# refresh_access_token は request に依存しないので変更なし
def refresh_access_token(credentials_json_str: str) -> Optional[str]:
    # ... (変更なし)
    pass