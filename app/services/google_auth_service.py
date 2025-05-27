# app/services/google_auth_service.py
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request # Request は google.auth.transport.requests から
import os
from typing import Optional, Tuple, Dict # Dict を追加
import traceback # traceback をインポート

from app.core.config import settings

def get_google_oauth_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "project_id": settings.GCP_PROJECT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uris": [
                settings.GOOGLE_OAUTH_REDIRECT_URI,
                # もしローカルテスト用のリダイレクトURIもGCPに登録していれば、ここにも追加できます
                # (例: "http://localhost:8000/api/v1/google/auth/callback")
            ],
            "javascript_origins": [] # 通常ウェブアプリでは不要
        }
    }
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=settings.GOOGLE_CALENDAR_SCOPES.split(), # スコープは文字列をスペースで分割してリストにする
    )
    # 実際に使用するリダイレクトURIを明示的に設定
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    return flow

def generate_auth_url() -> Tuple[str, str]:
    """Google認証URLとstateを生成する"""
    flow = get_google_oauth_flow()
    # CSRF対策のためのstateを生成
    state = os.urandom(16).hex()
    authorization_url, generated_state = flow.authorization_url(
        access_type='offline',  # リフレッシュトークンを取得するため
        prompt='consent',       # 毎回同意画面を出す（開発中は便利、本番では再同意が不要な場合は 'select_account' など）
        state=state             # 生成したstateを渡す
    )
    print(f"INFO: Generated Auth URL: {authorization_url}, State: {state}")
    return authorization_url, state

def exchange_code_for_credentials(authorization_response_url: str, original_state_from_session: str) -> Optional[Credentials]:
    """
    認可コードを認証情報（アクセストークン、リフレッシュトークン）に交換します。
    stateの検証は呼び出し元 (エンドポイント) で行うことを前提としています。
    """
    flow = get_google_oauth_flow()
    try:
        print(f"DEBUG: Attempting to fetch token with authorization_response_url: {authorization_response_url}")
        
        # `google-auth-oauthlib` の `fetch_token` は、渡された `authorization_response` URL から
        # `code` を自動的にパースしてくれます。
        # `state` の検証は、この関数を呼び出すエンドポイント側で行われている必要があります。
        # (コールバックで受け取った state とセッションの original_state_from_session の比較)

        flow.fetch_token(authorization_response=authorization_response_url)
        credentials = flow.credentials # 認証情報を取得

        print(f"INFO: Credentials obtained. AccessToken valid: {credentials.valid}")
        if credentials.token:
            print(f"INFO: Access token obtained: {credentials.token[:30]}...") # 先頭部分のみ表示
        if credentials.refresh_token:
            print(f"INFO: Refresh token obtained: {credentials.refresh_token[:30]}...") # 先頭部分のみ表示
        else:
            print("WARNING: No refresh token was obtained. Check 'access_type=offline' and consent screen configuration.")
        
        # 取得した認証情報を検証 (オプションだが推奨)
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                print("INFO: Credentials expired, attempting to refresh.")
                credentials.refresh(Request())
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

def refresh_access_token(credentials_json_str: str) -> Optional[str]:
    """
    保存された認証情報 (JSON文字列) からリフレッシュトークンを使ってアクセストークンを更新します。
    更新された認証情報をJSON文字列で返します。
    """
    try:
        # JSON文字列からCredentialsオブジェクトを復元
        credentials = Credentials.from_authorized_user_info(info=json.loads(credentials_json_str), scopes=settings.GOOGLE_CALENDAR_SCOPES.split())
        
        if credentials and credentials.expired and credentials.refresh_token:
            print("INFO: Access token expired, attempting to refresh.")
            credentials.refresh(Request()) # google.auth.transport.requests.Request オブジェクトが必要
            print("INFO: Access token refreshed successfully.")
            return credentials.to_json() # 更新された認証情報をJSON文字列で返す
        elif credentials and not credentials.expired:
            print("INFO: Access token is still valid, no refresh needed.")
            return credentials.to_json() # 現在の認証情報をそのまま返す
        else:
            print("WARNING: No valid credentials or no refresh token available to refresh access token.")
            return None
    except Exception as e:
        print(f"ERROR in refresh_access_token: Type: {type(e)}, Message: {str(e)}")
        traceback.print_exc()
        return None

# refresh_access_token を呼び出す際は、Firestoreなどから保存された認証情報 (JSON形式) を取得して渡す想定
# そのJSON文字列をパースするために json モジュールが必要
import json