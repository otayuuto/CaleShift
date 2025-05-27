# app/core/config.py
from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

# .envファイルが存在する場所からロード
# プロジェクトルートにあることを想定
# config.py が app/core/ にあるので、2階層上がる
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path, override=True)
# print(f"DEBUG: Loading .env from: {dotenv_path}") # デバッグ用
# print(f"DEBUG: LINE_CHANNEL_ACCESS_TOKEN from env: {os.getenv('LINE_CHANNEL_ACCESS_TOKEN')}") # デバッグ用

class Settings(BaseSettings):
    PROJECT_NAME: str = "Default Project Name"
    API_V1_STR: str = "/api/v1"

    # LINE
    LINE_CHANNEL_SECRET: str
    LINE_CHANNEL_ACCESS_TOKEN: str # <<<--- この行が正しく存在するか確認！型も str か確認！

    # Google
    # GOOGLE_APPLICATION_CREDENTIALS: Union[str, None] = None # pydantic v1 の書き方
    GOOGLE_APPLICATION_CREDENTIALS: str | None = None # Python 3.10+ の書き方、または from typing import Union
    GOOGLE_OAUTH_CLIENT_ID: str
    GOOGLE_OAUTH_CLIENT_SECRET: str
    GOOGLE_OAUTH_REDIRECT_URI: str
    GCP_PROJECT_ID: str

    GOOGLE_CALENDAR_SCOPES: str = "https://www.googleapis.com/auth/calendar.events"

    # model_config は Pydantic V2 の書き方
    # class Config:
    #     env_file = "../../.env" # load_dotenv を使わない場合
    #     env_file_encoding = 'utf-8'
    #     extra = 'ignore'

    SESSION_SECRET_KEY: str

settings = Settings()
# print(f"DEBUG: Loaded Settings LINE_CHANNEL_ACCESS_TOKEN: {settings.LINE_CHANNEL_ACCESS_TOKEN if hasattr(settings, 'LINE_CHANNEL_ACCESS_TOKEN') else 'Not found'}") # デバッグ用