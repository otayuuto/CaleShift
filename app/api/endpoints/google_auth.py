# app/api/endpoints/google_auth.py
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from typing import Optional

from app.services.google_auth_service import generate_auth_url, exchange_code_for_credentials
from app.core.config import settings
from app.api.dependencies import get_db_service
from app.services.firestore_service import FirestoreService
from app.services import google_auth_service

router = APIRouter()

@router.get("/login", summary="Start Google OAuth flow from LIFF")
async def start_login_from_liff(
    request: Request,
    line_id: Optional[str] = None,
    display_name: Optional[str] = None
):
    """
    LIFFから呼び出され、LINE User IDをセッションに保存し、
    Googleの認証ページへサーバーサイドでリダイレクトします。
    """
    if not line_id:
        raise HTTPException(status_code=400, detail="LINE User ID (line_id) is required.")
    
    # 1. 必要な情報をセッションに保存
    request.session['current_line_user_id_for_oauth'] = line_id
    if display_name:
        request.session['current_line_user_display_name_for_oauth'] = display_name
    print(f"INFO: Storing session data for OAuth. User ID: {line_id}")

    # 2. Google認証URLを生成
    #    この時点ではまだリダイレクトしない
    authorization_url, state = google_auth_service.generate_auth_url(request)
    
    # 3. CSRF対策のstateもセッションに保存
    request.session['oauth_state'] = state
    print(f"INFO: Generated Google Auth URL and stored CSRF state in session: {state}")

    # 4. サーバーからのリダイレクトレスポンスを返す
    #    これにより、ブラウザが直接Googleの認証ページに遷移する
    return RedirectResponse(url=authorization_url)
@router.get("/auth/callback", summary="Handle Google OAuth callback")
async def google_auth_callback(
    request: Request,
    db_service: FirestoreService = Depends(get_db_service),
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None
):
    # --- Inside google_auth_callback ---
    # デバッグ用の app.state.db チェックは不要になる (Dependsがチェックしてくれるため)
    # if hasattr(request.app.state, 'db_service') ... # ← このブロックは削除してOK

    if error:
        # ... (エラー処理)
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        # ... (エラー処理)
        raise HTTPException(status_code=400, detail="Missing authorization code from Google")
    
    session_state = request.session.pop('oauth_state', None)
    if not session_state or session_state != state:
        # ... (エラー処理)
        raise HTTPException(status_code=400, detail="OAuth state mismatch. Possible CSRF attack.")

    print(f"INFO: Received callback from Google. Code: {code[:20]}..., State: {state}")
    
    full_callback_url = str(request.url)
    
    credentials = exchange_code_for_credentials(request, full_callback_url, session_state)

    if not credentials:
        raise HTTPException(status_code=500, detail="Failed to obtain credentials from Google. Check server logs.")

    line_user_id = request.session.get('current_line_user_id_for_oauth')
    if not line_user_id:
        raise HTTPException(status_code=400, detail="LINE User ID for linking not found. Please start the process again.")

    print(f"INFO: Attempting to save Google credentials for LINE user: {line_user_id}")
    
    credentials_json = credentials.to_json()
    scopes_list = credentials.scopes if credentials.scopes else []

    # ★★★ 依存性注入で取得した db_service を使用 ★★★
    save_success = await db_service.save_google_credentials_for_user(
        line_user_id,
        credentials_json,
        scopes_list
    )

    if not save_success:
        raise HTTPException(status_code=500, detail="Failed to save Google credentials to database. Check server logs.")

    success_message = "Googleアカウント連携が完了しました！"
    print(f"INFO: Google OAuth successful for LINE user {line_user_id}. {success_message}")
    return {"message": success_message, "detail": "カレンダーへのシフト登録が可能になりました。このウィンドウを閉じてください。"}