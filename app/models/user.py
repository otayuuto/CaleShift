# app/models/user.py (再掲)
from pydantic import BaseModel, Field
from typing import Optional, List, Dict # Dict は不要かも
from datetime import datetime

class GoogleAuthInfo(BaseModel):
    credentials_json: str
    scopes: List[str] = []
    last_authenticated_at: Optional[datetime] = None

# User モデルも必要に応じて定義
# class User(BaseModel):
#     user_id: str # LINE User ID
#     name: Optional[str] = None
#     calendar_connected: bool = False
#     google_auth_info: Optional[GoogleAuthInfo] = None
#     created_at: Optional[datetime] = None
#     updated_at: Optional[datetime] = None