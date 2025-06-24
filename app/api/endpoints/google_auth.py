# app/api/endpoints/google_auth.py
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from app.services.google_oauth_service import google_oauth_service
from app.services import firestore_service # firestore_service全体をインポート
from app.core.config import settings
from google.oauth2.credentials import Credentials # 型ヒント用

router = APIRouter()

# /set-line-id-for-oauth エンドポイントは前回と同様

@router.get("/set-line-id-for-oauth/{line_user_id}", summary="Test: Set LINE User ID in session for OAuth flow")
async def set_line_id_for_oauth(request: Request, line_user_id: str):
    request.session['current_line_user_id_for_oauth'] = line_user_id
    print(f"DEBUG: Test - Set 'current_line_user_id_for_oauth' to: {line_user_id} in session id: {request.session.get('_id', 'N/A')}")
    return RedirectResponse(url=request.url_for('google_login'))


@router.get("/login", name="google_login", summary="Redirect to Google OAuth consent screen")
async def google_login(request: Request):
    if 'current_line_user_id_for_oauth' not in request.session:
        print("WARNING: 'current_line_user_id_for_oauth' not found in session at /login.")
        return HTMLResponse(
            content="<html><body><h1>エラー</h1><p>LINEユーザーIDがセッションに見つかりません。連携プロセスを最初からやり直してください。</p>" \
                    "<p>テストの場合は、<code>/api/v1/google/set-line-id-for-oauth/{あなたのテスト用LINEID}</code> にアクセスしてください。</p></body></html>", 
            status_code=400
        )
    
    try:
        authorization_url, state = await google_oauth_service.get_authorization_url(request, redirect_path_name="auth_callback")
        request.session['oauth_state'] = state
        print(f"DEBUG: Stored 'oauth_state': {state} in session id: {request.session.get('_id', 'N/A')}")
        return RedirectResponse(url=authorization_url, status_code=307) # 307 Temporary Redirect
    except HTTPException as e: # google_oauth_service内で発生したHTTPExceptionをそのまま返す
        raise e
    except Exception as e:
        print(f"ERROR: Could not get authorization URL: {e}")
        raise HTTPException(status_code=500, detail=f"Google認証URLの取得に失敗しました: {str(e)}")


@router.get("/auth/callback", name="auth_callback", summary="Google OAuth2 Callback")
async def auth_callback(
    request: Request, 
    code: str | None = Query(None), 
    state: str | None = Query(None), 
    error: str | None = Query(None)
):
    print(f"DEBUG: Callback received. Session content: {dict(request.session)}")

    if error:
        print(f"ERROR: OAuth error from Google: {error}")
        return HTMLResponse(content=f"<html><body><h1>認証エラー</h1><p>Googleからエラーが返されました: {error}</p></body></html>", status_code=400)
    if not code:
        print("ERROR: No authorization code provided in callback.")
        return HTMLResponse(content="<html><body><h1>認証エラー</h1><p>認証コードがGoogleから提供されませんでした。</p></body></html>", status_code=400)

    session_state = request.session.pop('oauth_state', None)
    line_user_id = request.session.get('current_line_user_id_for_oauth') # まだpopしない

    if not state or state != session_state:
        print(f"ERROR: State mismatch. Session state: {session_state}, Received state: {state}")
        # セッションの内容を再確認
        print(f"DEBUG: Session content at state mismatch: {dict(request.session)}")
        return HTMLResponse(content="<html><body><h1>認証エラー</h1><p>不正なリクエストです (state mismatch)。ブラウザのCookie設定やシークレットウィンドウの影響を確認してください。</p></body></html>", status_code=400)

    if not line_user_id:
        print("ERROR: LINE User ID not found in session during callback.")
        return HTMLResponse(content="<html><body><h1>エラー</h1><p>セッションからLINEユーザーIDを取得できませんでした。最初からやり直してください。</p></body></html>", status_code=400)

    print(f"INFO: Callback - Processing for LINE User ID: {line_user_id} with state: {state}")

    try:
        credentials: Credentials = await google_oauth_service.exchange_code_for_credentials(
            request=request,
            code=code,
            redirect_path_name="auth_callback"
        )
        
        credentials_json = credentials.to_json() # CredentialsオブジェクトをJSON文字列に変換
        
        print(f"INFO: Attempting to save Google credentials for LINE user: {line_user_id}")
        success = await firestore_service.save_google_credentials_for_user(
            line_user_id=line_user_id,
            credentials_json=credentials_json,
            scopes=credentials.scopes # credentials.scopes はリストのはず
        )

        if success:
            # 連携完了後、不要であればセッションからIDを削除
            # request.session.pop('current_line_user_id_for_oauth', None)
            # print(f"DEBUG: Cleared 'current_line_user_id_for_oauth' from session for {line_user_id}")
            return HTMLResponse(content="<html><body><h1>Googleアカウント連携が完了しました！</h1><p>カレンダーにシフトを登録できるようになります。このウィンドウを閉じて、LINEに戻ってください。</p></body></html>")
        else:
            print(f"ERROR: Failed to save credentials to Firestore for {line_user_id}")
            return HTMLResponse(content="<html><body><h1>エラー</h1><p>Google認証情報のデータベースへの保存に失敗しました。システム管理者に連絡してください。</p></body></html>", status_code=500)

    except HTTPException as e: # google_oauth_service や firestore_service 内で発生したHTTPException
        raise e
    except Exception as e:
        print(f"ERROR: Critical error during token exchange or DB save: {e}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<html><body><h1>認証処理エラー</h1><p>予期せぬエラーが発生しました: {str(e)}</p></body></html>", status_code=500)