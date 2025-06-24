# app/api/endpoints/google_auth.py
from fastapi import APIRouter, Request, HTTPException, status, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from typing import Optional

# サービス層の関数をインポート
from app.services.google_auth_service import generate_auth_url, exchange_code_for_credentials
from app.services.firestore_service import save_google_credentials_for_user
from app.core.config import settings
from google.oauth2.credentials import Credentials # 型ヒント用
import traceback # エラー時の詳細表示用
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# このテスト用エンドポイントは、開発初期には便利ですが、
# 本番では削除するか、認証などで保護することを推奨します。
@router.get("/set-line-id-for-oauth/{line_user_id}", summary="[Dev Only] Set LINE User ID in session for OAuth flow")
async def set_line_id_for_oauth(request: Request, line_user_id: str):
    """開発用: 指定されたLINE User IDをセッションに保存し、Googleログインページへリダイレクト。"""
    request.session['current_line_user_id_for_oauth'] = line_user_id
    # display_name もテスト用にダミーで設定する場合
    # request.session['current_line_user_display_name_for_oauth'] = f"TestUser-{line_user_id[:5]}"
    logger.debug(f"Set 'current_line_user_id_for_oauth' to: {line_user_id} in session (ID: {request.session.get('_id', 'N/A')})")
    
    # google_login エンドポイントのURLを名前で解決 (main.pyでのrouter登録時にname="google_login"が必要)
    # もし名前解決しない場合は、パスを直接指定: "/api/v1/google/login" (settings.API_V1_STR を使う)
    try:
        login_url = request.url_for('google_login_endpoint') # ★ name="google_login_endpoint" を@router.get("/login",...)に設定
    except Exception: # 名前解決に失敗した場合のフォールバック
        login_url = f"{settings.API_V1_STR}/google/login"
        logger.warning(f"Could not resolve URL for 'google_login_endpoint', using hardcoded path: {login_url}")
    return RedirectResponse(url=login_url)


@router.get("/login", name="google_login_endpoint", summary="Redirect to Google OAuth consent screen") # ★ name を追加
async def google_login(request: Request, line_id: Optional[str] = None, display_name: Optional[str] = None):
    """
    ユーザーをGoogleの認証ページにリダイレクトします。
    LIFFから渡されたline_idとdisplay_name、またはセッション内のIDを優先して使用します。
    """
    line_user_id_to_store = line_id or request.session.get('current_line_user_id_for_oauth')
    display_name_to_store = display_name or request.session.get('current_line_user_display_name_for_oauth')

    if not line_user_id_to_store:
        logger.warning("'current_line_user_id_for_oauth' not found in session or query params at /login.")
        return HTMLResponse(
            content="<html><head><meta charset='UTF-8'><title>エラー</title></head><body><h1>エラー</h1><p>LINEユーザーIDが特定できませんでした。連携プロセスを最初から（LINEアプリ内から）やり直してください。</p>" \
                    "<p><small>開発者向け: /set-line-id-for-oauth/{test_line_id} でテストできます。</small></p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # セッションに確実に保存
    request.session['current_line_user_id_for_oauth'] = line_user_id_to_store
    if display_name_to_store:
        request.session['current_line_user_display_name_for_oauth'] = display_name_to_store
    
    logger.info(f"Preparing Google OAuth for LINE User ID: {line_user_id_to_store} (Display Name: {display_name_to_store})")

    try:
        # generate_auth_url に request を渡すのは、google_auth_service.py の実装に依存
        # (リダイレクトURIを動的に生成する場合など)
        authorization_url, state = generate_auth_url(request)
        request.session['oauth_state'] = state # CSRF対策のstate
        logger.info(f"Redirecting to Google. Session CSRF state set: {state} for session ID: {request.session.get('_id', 'N/A')}")
        return RedirectResponse(url=authorization_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    except HTTPException as e:
        logger.error(f"HTTPException during auth URL generation: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Could not get authorization URL: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Google認証URLの取得に失敗しました。")


@router.get("/auth/callback", name="auth_callback", summary="Google OAuth2 Callback")
async def google_auth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None) # Googleが返すエラー詳細
):
    logger.info(f"Callback received. Session content hint (keys): {list(request.session.keys())}")

    if error:
        logger.error(f"OAuth error from Google: {error}, Description: {error_description}")
        return HTMLResponse(
            content=f"<html><head><meta charset='UTF-8'><title>認証エラー</title></head><body><h1>認証エラー</h1><p>Googleからエラーが返されました: {error}</p><p>{error_description or ''}</p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not code:
        logger.error("No authorization code provided in callback.")
        return HTMLResponse(
            content="<html><head><meta charset='UTF-8'><title>認証エラー</title></head><body><h1>認証エラー</h1><p>認証コードがGoogleから提供されませんでした。</p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    session_state = request.session.pop('oauth_state', None)
    line_user_id = request.session.get('current_line_user_id_for_oauth') # Firestore保存用に保持、ここではpopしない

    logger.debug(f"Callback - Session state: {session_state}, Received state: {state}, LINE User ID from session: {line_user_id}")

    if not state or state != session_state:
        logger.error(f"State mismatch. Session state: {session_state}, Received state: {state}")
        return HTMLResponse(
            content="<html><head><meta charset='UTF-8'><title>認証エラー</title></head><body><h1>認証エラー</h1><p>不正なリクエストです (state mismatch)。ブラウザのCookieが有効になっているか確認し、再度お試しください。</p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not line_user_id:
        logger.error("LINE User ID not found in session during callback.")
        return HTMLResponse(
            content="<html><head><meta charset='UTF-8'><title>エラー</title></head><body><h1>エラー</h1><p>セッションからLINEユーザーIDを取得できませんでした。お手数ですが、連携プロセスを最初からやり直してください。</p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    logger.info(f"Callback - Processing for LINE User ID: {line_user_id} with received state: {state}")

    db_client = request.app.state.db
    if not db_client:
        logger.critical("Firestore client not found in app.state during callback.")
        return HTMLResponse(content="<html><head><meta charset='UTF-8'><title>サーバーエラー</title></head><body><h1>サーバーエラー</h1><p>データベース接続が利用できません。システム管理者に連絡してください。</p></body></html>", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        # exchange_code_for_credentials に request を渡すのは、google_auth_service.py の実装に依存
        credentials: Optional[Credentials] = exchange_code_for_credentials(
            request=request,
            authorization_response_url=str(request.url), # コールバックURL全体
            original_state_from_session=session_state # 検証済みのstate (実際には使わないかも)
        )
        
        if not credentials:
            logger.error(f"Failed to obtain credentials from Google for LINE user {line_user_id}.")
            return HTMLResponse(content="<html><head><meta charset='UTF-8'><title>認証エラー</title></head><body><h1>認証エラー</h1><p>Googleからの認証情報の取得に失敗しました。詳細はサーバーログを確認してください。</p></body></html>", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        credentials_json = credentials.to_json()
        scopes_list = credentials.scopes if credentials.scopes else [] # スコープはリストのはず
        
        logger.info(f"Attempting to save Google credentials for LINE user: {line_user_id}")
        save_success = await save_google_credentials_for_user(
            db_client=db_client,
            line_user_id=line_user_id,
            credentials_json=credentials_json,
            scopes=scopes_list
        )

        if save_success:
            # 連携完了後、必要であればセッションからIDをクリア (ただし、他の連携で使うなら保持)
            # request.session.pop('current_line_user_id_for_oauth', None)
            # request.session.pop('current_line_user_display_name_for_oauth', None)
            logger.info(f"Google OAuth and Firestore save successful for LINE user {line_user_id}.")
            return HTMLResponse(content="<html><head><meta charset='UTF-8'><title>連携完了</title></head><body><h1>Googleアカウント連携が完了しました！</h1><p>カレンダーにシフトを登録できるようになります。このウィンドウを閉じて、LINEアプリに戻ってください。</p></body></html>")
        else:
            logger.error(f"Failed to save credentials to Firestore for LINE user {line_user_id}")
            return HTMLResponse(content="<html><head><meta charset='UTF-8'><title>データベースエラー</title></head><body><h1>データベースエラー</h1><p>Google認証情報のデータベースへの保存に失敗しました。システム管理者に連絡してください。</p></body></html>", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except HTTPException as e: # サービス層からのHTTPExceptionを再送出
        logger.error(f"HTTPException during callback processing for {line_user_id}: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Critical error during token exchange or DB save for {line_user_id}: {e}", exc_info=True)
        return HTMLResponse(content=f"<html><head><meta charset='UTF-8'><title>認証処理エラー</title></head><body><h1>認証処理エラー</h1><p>予期せぬエラーが発生しました。しばらくしてから再度お試しください。</p></body></html>", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)