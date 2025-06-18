# app/core/config.py
from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv
from typing import Optional, List # Optional をインポート

dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

class Settings(BaseSettings):
    PROJECT_NAME: str = "Default Project Name"
    API_V1_STR: str = "/api/v1"
    SESSION_SECRET_KEY: str # セッションキーは必須

    # LINE
    LINE_CHANNEL_SECRET: str
    LINE_CHANNEL_ACCESS_TOKEN: str

    # Google Service Account
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GCP_PROJECT_ID: str

    # Google OAuth Client
    GOOGLE_OAUTH_CLIENT_ID: str
    GOOGLE_OAUTH_CLIENT_SECRET: str
    GOOGLE_OAUTH_REDIRECT_URI: str # これはGCPコンソールに登録する主要なリダイレクトURI
    GOOGLE_CALENDAR_SCOPES: str = "https://www.googleapis.com/auth/calendar.events"

    # NGROK URL (オプショナル)
    NGROK_URL: Optional[str] = None  # <<<--- この行を追加 (オプショナルとして)

    # ENVIRONMENT (オプショナル、デフォルトは "local")
    ENVIRONMENT: str = "local" # get_google_oauth_flow で使用しているため

    # model_config などは必要に応じて
    # model_config = {
    #     "extra": "ignore"
    # }

settings = Settings()