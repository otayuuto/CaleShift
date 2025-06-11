# app/services/calendar_service.py
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from typing import Optional, Dict, Any, List
from datetime import datetime, time, date, timezone, timedelta # timedelta を追加
import json
import traceback # traceback をインポート

from app.services.firestore_service import get_google_credentials_for_user, save_google_credentials_for_user # Firestore連携
from app.services.google_auth_service import refresh_access_token # google_auth_serviceからリフレッシュ関数
from app.core.config import settings # settings をインポート
from app.utils.image_parser import ShiftInfo


async def get_calendar_service(line_user_id: str) -> Optional[Resource]:
    """
    指定されたLINEユーザーの認証情報を使ってGoogle Calendar APIサービスオブジェクトを構築します。
    必要に応じてアクセストークンをリフレッシュし、Firestoreの情報を更新します。
    """
    auth_info = await get_google_credentials_for_user(line_user_id)
    if not auth_info or not auth_info.get('credentials_json'):
        print(f"ERROR: No Google credentials found in Firestore for user {line_user_id}.")
        return None

    current_credentials_json = auth_info['credentials_json']
    
    # まず現在の認証情報でCredentialsオブジェクトを作成してみる
    try:
        creds = Credentials.from_authorized_user_info(json.loads(current_credentials_json))
    except Exception as e:
        print(f"ERROR: Failed to load credentials from Firestore JSON for user {line_user_id}: {e}")
        return None

    # アクセストークンが有効か、期限切れならリフレッシュが必要か確認
    # creds.valid はアクセストークンの有効性をチェックするが、リフレッシュが必要かの判断は creds.expired も見る
    if not creds.valid or creds.expired:
        if creds.refresh_token:
            print(f"INFO: Calendar service - Token for {line_user_id} is invalid/expired. Attempting refresh.")
            
            # google_auth_service の refresh_access_token を呼び出す
            # この関数は更新された credentials_json (文字列) を返す想定
            updated_credentials_json = refresh_access_token(current_credentials_json) # 同期関数呼び出し

            if updated_credentials_json:
                print(f"INFO: Token refreshed for {line_user_id}. Updating Firestore.")
                # Firestoreの認証情報を更新
                # save_google_credentials_for_user は scopes も要求するので、元のスコープ情報が必要
                original_scopes = auth_info.get('scopes', settings.GOOGLE_CALENDAR_SCOPES.split())
                await save_google_credentials_for_user(line_user_id, updated_credentials_json, original_scopes)
                
                # 更新された情報で再度Credentialsオブジェクトを作成
                try:
                    creds = Credentials.from_authorized_user_info(json.loads(updated_credentials_json))
                except Exception as e:
                    print(f"ERROR: Failed to load refreshed credentials for user {line_user_id}: {e}")
                    return None
            else:
                print(f"ERROR: Token refresh failed for {line_user_id}. Cannot build calendar service.")
                return None
        else:
            print(f"ERROR: Credentials for {line_user_id} are invalid/expired and no refresh token is available.")
            return None

    # 有効なCredentialsオブジェクトを使ってAPIクライアントを構築
    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False) # cache_discovery=False を試す
        print(f"INFO: Google Calendar service client built successfully for user {line_user_id}.")
        return service
    except Exception as e:
        print(f"ERROR: Failed to build Google Calendar service for user {line_user_id} with active credentials: {e}")
        traceback.print_exc()
        return None


async def create_calendar_event(line_user_id: str, shift_info: ShiftInfo) -> Optional[str]:
    if shift_info.is_holiday or not shift_info.start_time or not shift_info.end_time:
        print(f"INFO: Skipping calendar event: holiday or incomplete time for user {line_user_id}, date: {shift_info.date}")
        return None

    service = await get_calendar_service(line_user_id)
    if not service:
        print(f"ERROR: Calendar service not available for user {line_user_id}. Cannot create event.")
        return None

    # JSTタイムゾーンオブジェクトの取得 (Python 3.9+ の zoneinfo を推奨)
    try:
        from zoneinfo import ZoneInfo
        JST = ZoneInfo("Asia/Tokyo")
    except ImportError:
        # フォールバック (簡易的、夏時間非対応)
        JST = timezone(timedelta(hours=9))
        print("WARNING: zoneinfo module not found, using fixed +09:00 timezone. For DST, install backports.zoneinfo or use Python 3.9+.")


    # naive datetimeオブジェクトを作成
    start_datetime_naive = datetime.combine(shift_info.date, shift_info.start_time)
    end_datetime_naive = datetime.combine(shift_info.date, shift_info.end_time)

    # aware datetimeオブジェクトに変換
    start_datetime_aware = start_datetime_naive.replace(tzinfo=JST)
    end_datetime_aware = end_datetime_naive.replace(tzinfo=JST)
    
    # 終了時刻が開始時刻より早い場合 (例: 22:00 - 02:00)、日付をまたぐと解釈
    if end_datetime_aware < start_datetime_aware:
        print(f"INFO: End time {end_datetime_aware} is before start time {start_datetime_aware}. Assuming next day for end time.")
        end_datetime_aware += timedelta(days=1)


    event_summary = f"アルバイト: {shift_info.name or 'シフト'}"
    if shift_info.role:
        event_summary += f" ({shift_info.role})"
    
    description_parts = []
    if shift_info.name:
        description_parts.append(f"氏名: {shift_info.name}")
    if shift_info.role:
        description_parts.append(f"担当: {shift_info.role}")
    if shift_info.memo:
        description_parts.append(f"メモ: {shift_info.memo}")
    event_description = "\n".join(description_parts)

    event_body = {
        'summary': event_summary,
        'description': event_description,
        'start': {
            'dateTime': start_datetime_aware.isoformat(),
            # 'timeZone': 'Asia/Tokyo', # aware datetime を使えば timeZone は不要なことが多い
        },
        'end': {
            'dateTime': end_datetime_aware.isoformat(),
            # 'timeZone': 'Asia/Tokyo',
        },
    }

    try:
        print(f"DEBUG: Creating calendar event for user {line_user_id} with body: {event_body}")
        created_event = service.events().insert(calendarId='primary', body=event_body).execute()
        event_id = created_event.get('id')
        print(f"INFO: Event created for user {line_user_id}: ID: {event_id}, Summary: {event_summary}")
        
        # (オプション) 作成したイベントIDをFirestoreのshift_historyなどに保存する
        # await firestore_service.log_shift_to_history(line_user_id, shift_info, event_id)

        return event_id
    except HttpError as error:
        print(f"ERROR: An API error occurred while creating event for user {line_user_id}: {error.resp.status} - {error.resp.reason}")
        try:
            error_content = json.loads(error.content.decode())
            if 'error' in error_content and 'message' in error_content['error']:
                error_details = error_content['error']['message']
                print(f"ERROR_DETAILS (HttpError): {error_details}")
        except:
            print(f"ERROR_DETAILS (HttpError): Could not parse error content. Raw: {error.content}")
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error creating calendar event for user {line_user_id}: {e}")
        traceback.print_exc()
        return None