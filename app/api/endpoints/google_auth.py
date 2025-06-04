# app/api/endpoints/google_auth.py (呼び出し側の修正)
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from typing import Optional

# ↓↓↓ 関数を直接インポートする形に変更 ↓↓↓
from app.services.google_auth_service import generate_auth_url, exchange_code_for_credentials
# from app.services.google_auth_service import google_oauth_service # これは使わない

from app.core.config import settings
from app.services.firestore_service import save_google_credentials_for_user # 非同期関数のはず
# ...

router = APIRouter()

@router.get("/login", summary="Redirect to Google OAuth consent screen")
async def login_via_google(request: Request): # request はFastAPIが自動で渡してくれる
    # ... (テスト用のLINE User ID設定など)
    test_line_user_id = "test-line-user-for-google-oauth-12345"
    request.session['current_line_user_id_for_oauth'] = test_line_user_id
    print(f"DEBUG: [TEST] Set 'current_line_user_id_for_oauth' to: {test_line_user_id} in session.")
            
    # ↓↓↓ 関数を直接呼び出し、requestを渡す ↓↓↓
    authorization_url, state = generate_auth_url(request) 
    
    request.session['oauth_state'] = state
    print(f"Redirecting to Google. Session state set: {state}")
    return RedirectResponse(url=authorization_url)

@router.get("/auth/callback", summary="Handle Google OAuth callback")
async def google_auth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None):
    # ... (state検証、codeチェックはそのまま) ...
    if error:
        print(f"Google OAuth Error: {error}")
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code from Google")
    
    session_state = request.session.pop('oauth_state', None)
    if not session_state or session_state != state:
        print(f"State mismatch. Session: {session_state}, Received: {state}")
        raise HTTPException(status_code=400, detail="OAuth state mismatch. Possible CSRF attack.")

    print(f"Received callback from Google. Code: {code[:20]}..., State: {state}")
    
    full_callback_url = str(request.url) # これを fetch_token に渡す
    
    # ↓↓↓ 関数を直接呼び出し、requestを渡す ↓↓↓
    credentials = exchange_code_for_credentials(request, full_callback_url, session_state)

    if not credentials:
        # exchange_code_for_credentials 内でエラーログは出力されているはず
        raise HTTPException(status_code=500, detail="Failed to obtain credentials from Google")

    line_user_id = request.session.get('current_line_user_id_for_oauth')
    if not line_user_id:
        print("ERROR: LINE User ID not found in session during OAuth callback.")
        raise HTTPException(status_code=400, detail="LINE User ID for linking not found. Please start the process again.")

    print(f"INFO: Attempting to save Google credentials for LINE user: {line_user_id}")
    
    credentials_json = credentials.to_json()
    scopes_list = credentials.scopes if credentials.scopes else []

    # firestore_service の関数が async def なら await が必要
    save_success = await save_google_credentials_for_user(line_user_id, credentials_json, scopes_list)

    if not save_success:
        raise HTTPException(status_code=500, detail="Failed to save Google credentials to database.")

    success_message = "Googleアカウント連携が完了しました！"
    print(success_message)
    return {"message": success_message, "detail": "You can now close this window."}