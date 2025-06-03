# app/services/calendar_service.py
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from datetime import datetime, time, date, timezone
from typing import Optional, List, Dict, Any
import json

from app.core.config import settings
# from app.services.google_auth_service import refresh_access_token # トークンリフレッシュ用
# from app.services.firestore_service import get_google_credentials_for_user, save_google_credentials_for_user # Firestore連携用

def get_calendar_service(credentials_json_str: str) -> Optional[Any]:
    """
    提供された認証情報 (JSON文字列) を使ってGoogle Calendar APIサービスクライアントを構築します。
    必要に応じてアクセストークンをリフレッシュします。
    """
    try:
        creds_info = json.loads(credentials_json_str)
        # scopes は credentials_json に含まれているが、明示的に渡すこともできる
        credentials = Credentials.from_authorized_user_info(info=creds_info, scopes=settings.GOOGLE_CALENDAR_SCOPES.split())

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                print("INFO (CalendarService): Access token expired, attempting to refresh.")
                # credentials.refresh() を呼び出す前に google.auth.transport.requests.Request が必要
                from google.auth.transport.requests import Request as GoogleAuthRequest # 名前衝突回避
                credentials.refresh(GoogleAuthRequest())
                print(f"INFO (CalendarService): Credentials refreshed. AccessToken valid: {credentials.valid}")
                
                # !!! 重要: リフレッシュされた認証情報をFirestoreに保存し直す必要がある !!!
                # line_user_id をどうやってこの関数に渡すかが課題。
                # この関数を呼び出す側 (例: APIエンドポイント) でリフレッシュ後の保存を行うか、
                # またはこのサービス関数に line_user_id を渡せるように設計する。
                # 例: updated_credentials_json = credentials.to_json()
                # await save_google_credentials_for_user(line_user_id, updated_credentials_json, credentials.scopes)
                # (上記は非同期なので、この関数もasyncにするか、同期的に呼び出す必要がある)
            else:
                print("ERROR (CalendarService): Invalid or expired credentials, and no refresh token.")
                return None
        
        service = build('calendar', 'v3', credentials=credentials, cache_discovery=False) # cache_discovery=False は開発中推奨
        print("INFO (CalendarService): Google Calendar service client built successfully.")
        return service
    except Exception as e:
        print(f"ERROR (CalendarService): Failed to build Google Calendar service: {e}")
        import traceback
        traceback.print_exc()
        return None

def create_calendar_event(service: Any, summary: str, start_datetime: datetime, end_datetime: datetime, description: Optional[str] = None, calendar_id: str = 'primary') -> Optional[str]:
    """
    Googleカレンダーに新しいイベントを作成します。
    :param service: Google Calendar APIサービスクライアント
    :param summary: イベントのタイトル
    :param start_datetime: 開始日時 (timezone aware datetime)
    :param end_datetime: 終了日時 (timezone aware datetime)
    :param description: イベントの説明 (オプション)
    :param calendar_id: 対象のカレンダーID (デフォルトは 'primary')
    :return: 作成されたイベントのID、またはエラーの場合はNone
    """
    try:
        event = {
            'summary': summary,
            'description': description or '',
            'start': {
                'dateTime': start_datetime.isoformat(), # ISO 8601 format (e.g., '2023-05-28T09:00:00-07:00')
                # 'timeZone': 'Asia/Tokyo', # 必要に応じてタイムゾーンを指定
            },
            'end': {
                'dateTime': end_datetime.isoformat(),
                # 'timeZone': 'Asia/Tokyo',
            },
            # 'reminders': { # 必要ならリマインダー設定
            # 'useDefault': False,
            # 'overrides': [
            # {'method': 'popup', 'minutes': 10},
            # ],
            # },
        }
        print(f"DEBUG (CalendarService): Creating event: {event}")
        created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
        event_id = created_event.get('id')
        print(f"INFO (CalendarService): Event created successfully. Event ID: {event_id}, HTML Link: {created_event.get('htmlLink')}")
        return event_id
    except Exception as e:
        print(f"ERROR (CalendarService): Failed to create calendar event: {e}")
        import traceback
        traceback.print_exc()
        return None

# (オプション) 他の関数: イベントの取得、更新、削除など