# app/core/config.py
from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

# .envファイルが存在する場所からロード
# プロジェクトルートにあることを想定
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)
# print(f"Loading .env from: {dotenv_path}") # デバッグ用

class Settings(BaseSettings):
    PROJECT_NAME: str = "Default Project Name"
    # .envファイルから読み込みたい他の変数もここに追加
    LINE_CHANNEL_SECRET: str = "dummy_secret" # .envから読み込めないとこれが使われる
    # ... 他の設定 ...

    class Config:
         # Pydantic V2以降ではenv_fileは推奨されなくなり、load_dotenvを使うか、
         # 環境変数として直接設定する方が一般的。
         # BaseSettingsが自動で環境変数を読み込む。
         # env_file = "../../.env" # ルートからの相対パス。load_dotenvを使わない場合。
         # env_file_encoding = 'utf-8'
         extra = 'ignore'

settings = Settings()
# print(f"Loaded Settings: {settings.dict()}") # デバッグ用