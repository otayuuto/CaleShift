# app/api/endpoints/google_auth.py
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
# from fastapi.templating import Jinja2Templates
from starlette.datastructures import URL
from typing import Optional # <<<--- この行を追加

from app.services import google_auth_service
from app.core.config import settings
# from app.services.firestore_service import save_user_google_credentials
# from app.models.user import UserGoogleCredentials
# from starlette.middleware.sessions import SessionMiddleware

router = APIRouter()
# templates = Jinja2Templates(directory="templates")

@router.get("/login", summary="Redirect to Google OAuth consent screen")
async def login_via_google(request: Request):
    # ... (変更なし) ...
    auth_url, state = google_auth_service.generate_auth_url()
    request.session['oauth_state'] = state
    print(f"Redirecting to Google. Session state set: {state}")
    return RedirectResponse(url=auth_url)

@router.get("/auth/callback", summary="Handle Google OAuth callback")
async def google_auth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None):
    # ... (関数の残りは変更なし) ...
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
    
    full_callback_url = str(request.url)
    
    credentials = google_auth_service.exchange_code_for_credentials(full_callback_url, session_state)

    if not credentials:
        raise HTTPException(status_code=500, detail="Failed to obtain credentials from Google")

    success_message = "Googleアカウント連携が完了しました！カレンダーにシフトを登録できるようになります。"
    print(success_message)
    return {"message": success_message, "detail": "You can now close this window."}