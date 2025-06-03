# app/services/google_oauth_service.py
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials # 型ヒント用
from app.core.config import settings
from fastapi import Request, HTTPException # HTTPException をインポート

class GoogleOAuthService:
    def __init__(self):
        self.client_config = {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
            }
        }
        self.scopes = [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/calendar"
        ]

    def _get_base_url(self, request: Request) -> str:
        """
        リクエスト情報と設定に基づいてベースURL (例: https://xxx.ngrok-free.app) を取得します。
        """
        # ngrok URLが設定されていれば優先的に使用
        if settings.NGROK_URL and settings.NGROK_URL.startswith("https://"):
            return settings.NGROK_URL.rstrip("/")
        
        # X-Forwarded-Proto と X-Forwarded-Host ヘッダーを確認 (リバースプロキシ経由の場合)
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        
        # FastAPI 0.99.0以降では、request.base_urlがX-Forwardedヘッダを考慮するようになった
        # ただし、ngrok無料版などではX-Forwarded-Hostがlocalhostになる場合があるため、NGROK_URL設定を優先
        # return str(request.base_url).rstrip("/") # これでも良い場合がある

        return f"{proto}://{host}"


    def get_flow(self, request: Request, redirect_path_name: str) -> Flow:
        base_url = self._get_base_url(request)
        callback_url_path = request.url_for(redirect_path_name)
        redirect_uri = f"{base_url}{callback_url_path}"

        # redirect_uriがHTTPSであることを確認 (ローカル開発のHTTPは除く)
        if not redirect_uri.startswith("https://") and not ("127.0.0.1" in redirect_uri or "localhost" in redirect_uri):
            if settings.ENVIRONMENT == "local": # ローカル環境でngrokなどを使っている場合
                print(f"WARNING: redirect_uri '{redirect_uri}' is not HTTPS. Forcing to HTTPS based on NGROK_URL or proxy headers.")
                redirect_uri = redirect_uri.replace("http://", "https://", 1)
            else: # 本番環境でHTTPになっているのは問題
                raise HTTPException(status_code=500, detail=f"Critical: OAuth redirect_uri must be HTTPS in non-local environment. Got: {redirect_uri}")
        
        print(f"DEBUG: Generated redirect_uri for Flow: {redirect_uri}")
        
        flow = Flow.from_client_config(
            client_config=self.client_config,
            scopes=self.scopes
        )
        flow.redirect_uri = redirect_uri
        return flow

    async def get_authorization_url(self, request: Request, redirect_path_name: str = "auth_callback") -> tuple[str, str]:
        flow = self.get_flow(request, redirect_path_name)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent',
        )
        print(f"DEBUG: Generated authorization_url: {authorization_url}, state: {state}")
        return authorization_url, state

    async def exchange_code_for_credentials(self, request: Request, code: str, redirect_path_name: str = "auth_callback") -> Credentials:
        flow = self.get_flow(request, redirect_path_name)
        try:
            # fetch_token は response パラメータに完全なコールバックURLを期待することがある
            # または code パラメータで認証コードを直接渡す
            # stateの検証は呼び出し元で行う
            flow.fetch_token(code=code) 
            credentials = flow.credentials
            if not credentials or not credentials.valid:
                print("ERROR: Failed to fetch valid token or credentials not found in flow.")
                raise HTTPException(status_code=500, detail="Googleから有効なトークンを取得できませんでした。")
            
            if credentials.refresh_token:
                print("INFO: Refresh token obtained.")
            else:
                print("WARNING: Refresh token NOT obtained. User may need to re-consent or check 'prompt=consent'.")
            return credentials
        except Exception as e:
            print(f"ERROR: Failed to fetch token in GoogleOAuthService: {e}")
            # import traceback
            # print(traceback.format_exc()) # 詳細なエラーを確認したい場合
            raise HTTPException(status_code=500, detail=f"Googleトークン交換エラー: {str(e)}")

google_oauth_service = GoogleOAuthService()