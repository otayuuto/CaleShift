# app/api/endpoints/google_auth.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from typing import Optional

# google_auth_service から関数を直接インポート
from app.services.google_auth_service import generate_auth_url, exchange_code_for_credentials

from app.core.config import settings
# firestore_service から関数を直接インポート
from app.services.firestore_service import save_google_credentials_for_user
# from app.services.firestore_service import get_google_credentials_for_user # 必要なら

router = APIRouter()

@router.get("/login", summary="Redirect to Google OAuth consent screen")
async def login_via_google(request: Request, line_id: Optional[str] = None): # line_id をクエリパラメータとして受け取れるように変更
    """
    ユーザーをGoogleの認証ページにリダイレクトします。
    stateとLINE User IDをセッションに保存します。
    テスト用に /set-line-id-for-oauth エンドポイントも残すか、このエンドポイントで line_id を必須にするか検討。
    ここでは、クエリパラメータで line_id を受け取ることを優先。
    """
    line_user_id_to_store = line_id # クエリパラメータから取得
    if not line_user_id_to_store:
        # クエリパラメータがない場合、テスト用に固定値を設定 (本番ではエラーか、別の方法で取得)
        line_user_id_to_store = "test-line-user-for-google-oauth-12345" # フォールバック
        print(f"WARNING: 'line_id' query parameter not provided for /login. Using test ID: {line_user_id_to_store}")
    
    request.session['current_line_user_id_for_oauth'] = line_user_id_to_store
    print(f"DEBUG: Set 'current_line_user_id_for_oauth' to: {line_user_id_to_store} in session.")
            
    # generate_auth_url には request を渡す (google_auth_service.py の定義に合わせる)
    authorization_url, state = generate_auth_url(request) 
    
    request.session['oauth_state'] = state # CSRF対策のstate
    print(f"INFO: Redirecting to Google for user {line_user_id_to_store}. Session CSRF state set: {state}")
    return RedirectResponse(url=authorization_url)

@router.get("/auth/callback", summary="Handle Google OAuth callback")
async def google_auth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None):
    print("--- Inside google_auth_callback ---") # ★デバッグ開始
    if hasattr(request.app.state, 'db') and request.app.state.db is not None:
        db_client_in_callback = request.app.state.db
        print(f"DEBUG_CALLBACK: Firestore client in app.state.db found. Project ID: {db_client_in_callback.project}")
        print(f"DEBUG_CALLBACK: Firestore client type: {type(db_client_in_callback)}")
    else:
        print("CRITICAL_CALLBACK_ERROR: Firestore client (request.app.state.db) not found or is None!")
        # ここでエラーなら、startupでの設定がリクエスト処理時に引き継がれていない
        raise HTTPException(status_code=500, detail="Internal Server Error: DB client not configured.")

    if error:
        print(f"ERROR: Google OAuth Error: {error}")
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        print("ERROR: Missing authorization code from Google.")
        raise HTTPException(status_code=400, detail="Missing authorization code from Google")
    
    session_state = request.session.pop('oauth_state', None)
    if not session_state or session_state != state:
        print(f"ERROR: State mismatch. Session: {session_state}, Received: {state}")
        raise HTTPException(status_code=400, detail="OAuth state mismatch. Possible CSRF attack.")

    print(f"INFO: Received callback from Google. Code: {code[:20]}..., State: {state}")
    
    full_callback_url = str(request.url)
    
    # exchange_code_for_credentials には request を渡す (google_auth_service.py の定義に合わせる)
    credentials = exchange_code_for_credentials(request, full_callback_url, session_state)

    if not credentials:
        # exchange_code_for_credentials 内でエラーログは出力されているはず
        raise HTTPException(status_code=500, detail="Failed to obtain credentials from Google. Check server logs.")

    line_user_id = request.session.get('current_line_user_id_for_oauth')
    if not line_user_id:
        print("ERROR: LINE User ID not found in session during OAuth callback.")
        raise HTTPException(status_code=400, detail="LINE User ID for linking not found. Please start the process again from LINE or ensure session is maintained.")

    print(f"INFO: Attempting to save Google credentials for LINE user: {line_user_id}")
    
    credentials_json = credentials.to_json()
    scopes_list = credentials.scopes if credentials.scopes else []

    # ★★★ Firestoreクライアントを app.state から取得して渡す ★★★
    db_client = request.app.state.db 
    if not db_client:
        print("CRITICAL_ERROR: Firestore client not found in app.state during callback.")
        raise HTTPException(status_code=500, detail="Database connection not available. Please contact administrator.")

    save_success = await save_google_credentials_for_user(
        db_client, # ★ Firestoreクライアントを渡す
        line_user_id,
        credentials_json,
        scopes_list
    )

    if not save_success:
        # save_google_credentials_for_user 内でエラーログは出力されているはず
        raise HTTPException(status_code=500, detail="Failed to save Google credentials to database. Check server logs.")

    success_message = "Googleアカウント連携が完了しました！" # LIFFならここでliff.closeWindow()を促すなど
    print(f"INFO: Google OAuth successful for LINE user {line_user_id}. {success_message}")
    return {"message": success_message, "detail": "カレンダーへのシフト登録が可能になりました。このウィンドウを閉じてください。"}