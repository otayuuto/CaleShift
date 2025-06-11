# app/services/google_auth_service.py
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
import os
from typing import Optional, Tuple, Dict
import traceback
import json
from fastapi import Request # Request をインポート

from app.core.config import settings

def get_effective_redirect_uri(request: Optional[Request] = None) -> str:
    """
    現在のリクエストや環境設定に基づいて、有効なリダイレクトURIを決定します。
    """
    # 1. .env の GOOGLE_OAUTH_REDIRECT_URI を最優先 (ngrok URLが固定の場合や本番用)
    primary_redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI

    # 2. NGROK_URL 環境変数があれば、それを使って動的に生成 (開発時のngrok用)
    #    注意: この動的に生成したURIもGCPコンソールに登録されている必要がある。
    if settings.ENVIRONMENT == "local" and settings.NGROK_URL and settings.NGROK_URL.startswith("https://"):
        base_url = settings.NGROK_URL.rstrip("/")
        # コールバックパスは固定 (例: /api/v1/google/auth/callback)
        # このパスは FastAPI のルーター設定と一致させる
        callback_path = f"{settings.API_V1_STR}/google/auth/callback"
        dynamic_ngrok_uri = f"{base_url}{callback_path}"
        print(f"DEBUG: Dynamic NGROK redirect_uri candidate: {dynamic_ngrok_uri}")
        # ここで、GCPに登録済みのURIと照合するなどのロジックも入れられるが、
        # 基本的にはGCPに登録されている主要なURIを使うか、
        # NGROK_URLから生成したものをGCPにも登録しておく。
        # ここでは、NGROK_URLがあればそれを優先的に使ってみる例。
        # ただし、この動的生成URIがGCPにないと mismatch エラーになる。
        # 安全なのは、常に settings.GOOGLE_OAUTH_REDIRECT_URI を使うこと。
        # ここでは、もし NGROK_URL が .env の GOOGLE_OAUTH_REDIRECT_URI と異なる場合に
        # NGROK_URL を優先するかどうかという問題。
        # 簡単のため、settings.GOOGLE_OAUTH_REDIRECT_URI を正として使う。
        # もし動的にしたいなら、settings.GOOGLE_OAUTH_REDIRECT_URI を上書きするロジックをconfig.pyに入れるか、
        # この関数が返す値を settings.GOOGLE_OAUTH_REDIRECT_URI と比較して選択する。
        # 今回はシンプルに settings.GOOGLE_OAUTH_REDIRECT_URI を使う。
        # もし、NGROK_URL が設定されていて、それが settings.GOOGLE_OAUTH_REDIRECT_URI と異なり、
        # かつGCPにNGROK_URLベースのものが登録されているなら、そちらを使う、という判断も可能。
        # print(f"DEBUG: Using primary redirect_uri from settings: {primary_redirect_uri}")
        return primary_redirect_uri # settingsの値を信頼する

    elif request: # リバースプロキシ環境などを考慮する場合
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        if host: # hostが取得できた場合のみ
            base_url = f"{proto}://{host}"
            callback_path = f"{settings.API_V1_STR}/google/auth/callback"
            dynamic_header_uri = f"{base_url}{callback_path}"
            print(f"DEBUG: Dynamic redirect_uri candidate from headers: {dynamic_header_uri}")
            # これもGCPに登録されている必要がある。
            # settings.GOOGLE_OAUTH_REDIRECT_URI と比較して選択するなどのロジック。
            # ここでは settings.GOOGLE_OAUTH_REDIRECT_URI を優先。
            return primary_redirect_uri

    return primary_redirect_uri


def get_google_oauth_flow(request: Optional[Request] = None) -> Flow:
    redirect_uri_to_use = get_effective_redirect_uri(request)
    print(f"DEBUG: get_google_oauth_flow will use redirect_uri: {redirect_uri_to_use}")

    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "project_id": settings.GCP_PROJECT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uris": [ # GCPコンソールに登録されている可能性のあるものをリストアップ
                settings.GOOGLE_OAUTH_REDIRECT_URI, # .env で定義された主要なもの
                # "http://localhost:8000/api/v1/google/auth/callback" # ローカルテスト用など
            ],
        }
    }
    # javascript_origins は通常ウェブサーバーフローでは不要
    if "javascript_origins" in client_config["web"]:
        del client_config["web"]["javascript_origins"]


    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=settings.GOOGLE_CALENDAR_SCOPES.split(),
    )
    # 実際にこのフローインスタンスで使用するリダイレクトURIを設定
    flow.redirect_uri = redirect_uri_to_use
    return flow

def generate_auth_url(request: Request) -> Tuple[str, str]:
    flow = get_google_oauth_flow(request)
    state = os.urandom(16).hex()
    authorization_url, generated_state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=state
    )
    print(f"INFO: Generated Auth URL: {authorization_url}, State: {state}")
    return authorization_url, state

def exchange_code_for_credentials(request: Request, authorization_response_url: str, original_state_from_session: str) -> Optional[Credentials]:
    flow = get_google_oauth_flow(request) # request を渡して正しい redirect_uri が flow に設定されるようにする
    try:
        print(f"DEBUG: Attempting to fetch token with authorization_response_url: {authorization_response_url}")
        print(f"DEBUG: Using redirect_uri in flow for fetch_token: {flow.redirect_uri}")

        flow.fetch_token(authorization_response=authorization_response_url)
        credentials = flow.credentials
        print(f"INFO: Credentials obtained. AccessToken valid: {credentials.valid}")
        if credentials.token:
            print(f"INFO: Access token obtained: {credentials.token[:30]}...")
        if credentials.refresh_token:
            print(f"INFO: Refresh token obtained: {credentials.refresh_token[:30]}...")
        else:
            print("WARNING: No refresh token was obtained. Check 'access_type=offline' and consent screen configuration.")
        
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                print("INFO: Credentials expired, attempting to refresh (in exchange_code).")
                credentials.refresh(GoogleAuthRequest())
                print(f"INFO: Credentials refreshed (in exchange_code). AccessToken valid: {credentials.valid}")
            else:
                print("ERROR: Failed to obtain valid credentials or refresh them (in exchange_code).")
                return None
        
        return credentials
    except Exception as e:
        print(f"CRITICAL_ERROR in exchange_code_for_credentials: Type: {type(e)}, Message: {str(e)}")
        print("--- Full Traceback for exchange_code_for_credentials ---")
        traceback.print_exc()
        print("------------------------------------------------------")
        return None

def refresh_access_token(credentials_json_str: str) -> Optional[str]:
    """
    保存された認証情報 (JSON文字列) からリフレッシュトークンを使ってアクセストークンを更新します。
    更新された認証情報をJSON文字列で返します。
    """
    try:
        creds_info = json.loads(credentials_json_str)
        # スコープ情報は Credentials.from_authorized_user_info には必須ではないことが多い
        # もしエラーになる場合は、元のスコープを渡す必要があるかもしれない
        # creds_info['scopes'] = settings.GOOGLE_CALENDAR_SCOPES.split() のように
        credentials = Credentials.from_authorized_user_info(info=creds_info)
        
        if credentials and credentials.refresh_token: # リフレッシュトークンがあることが重要
            if credentials.expired:
                print("INFO: Access token (from DB) expired, attempting to refresh.")
                auth_req = GoogleAuthRequest() # google.auth.transport.requests.Request
                credentials.refresh(auth_req)
                print("INFO: Access token refreshed successfully via refresh_access_token.")
                return credentials.to_json() # 更新された認証情報をJSON文字列で返す
            else:
                print("INFO: Access token (from DB) is still valid, no refresh needed now.")
                return credentials.to_json() # 現在の認証情報をそのまま返す
        elif credentials and not credentials.refresh_token:
            print("WARNING: No refresh token found in stored credentials. Cannot refresh.")
            return credentials.to_json() # リフレッシュできないが、現在のものを返す
        else:
            print("WARNING: No valid credentials available to refresh access token.")
            return None
    except Exception as e:
        print(f"ERROR in refresh_access_token: Type: {type(e)}, Message: {str(e)}")
        traceback.print_exc()
        return None