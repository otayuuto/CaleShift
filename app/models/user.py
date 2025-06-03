# app/models/user.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime # datetime をインポート

class GoogleAuthInfo(BaseModel):
    credentials_json: str
    scopes: List[str] = []
    last_authenticated_at: Optional[datetime] = None

class User(BaseModel):
    user_id: str # LINE User ID (もしフィールドとして持つ場合)
    name: Optional[str] = None
    email: Optional[str] = None # (もし収集するなら)
    calendar_connected: bool = False
    google_auth_info: Optional[GoogleAuthInfo] = None # Google認証情報
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # workplaces_ids: List[str] = [] # もしユーザーが複数の勤務地を持つなら

    # FirestoreのドキュメントIDとして user_id を使う場合は、
    # Pydanticモデルのフィールドとしては不要になることも。
    # その場合は、FirestoreService側でドキュメントIDを扱う。