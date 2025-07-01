# app/services/calendar_service.py (修正後)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from typing import Optional, Dict, Any, List
from datetime import datetime, time, date, timezone, timedelta
import json
import traceback
from zoneinfo import ZoneInfo
from fastapi.concurrency import run_in_threadpool

# ★★★ FirestoreService クラスをインポート ★★★
from app.services.firestore_service import FirestoreService
from app.services.google_auth_service import refresh_access_token # トークンリフレッシュ関数
from app.core.config import settings
from app.utils.image_parser import ShiftInfo

# JSTタイムゾーンオブジェクトの初期化 (変更なし)
try:
    JST = ZoneInfo("Asia/Tokyo")
except Exception:
    print("WARNING_CAL_SERVICE: zoneinfo module not available. Using fixed +09:00 UTC offset.")
    JST = timezone(timedelta(hours=9))


async def get_calendar_service(
    db_service: FirestoreService, # ★ 引数を FirestoreService のインスタンスに変更
    line_user_id: str
) -> Optional[Resource]:
    """
    指定されたLINEユーザーの認証情報を使ってGoogle Calendar APIサービスオブジェクトを構築します。
    必要に応じてアクセストークンをリフレッシュし、Firestoreの情報を更新します。
    """
    if not db_service:
        print("ERROR_CAL_SERVICE: FirestoreService instance (db_service) not provided.")
        return None

    # ★★★ db_service のメソッドとして呼び出す ★★★
    auth_info = await db_service.get_google_credentials_for_user(line_user_id)
    if not auth_info or not auth_info.get('credentials_json'):
        print(f"ERROR_CAL_SERVICE: No Google credentials found in Firestore for user {line_user_id}.")
        return None

    current_credentials_json = auth_info['credentials_json']
    
    try:
        creds = Credentials.from_authorized_user_info(json.loads(current_credentials_json), scopes=settings.GOOGLE_CALENDAR_SCOPES.split())
    except Exception as e:
        print(f"ERROR_CAL_SERVICE: Failed to load credentials from Firestore JSON for user {line_user_id}: {e}")
        return None

    if not creds.valid or creds.expired:
        if creds.refresh_token:
            print(f"INFO_CAL_SERVICE: Token for {line_user_id} expired/invalid, attempting refresh.")
            updated_credentials_json = refresh_access_token(current_credentials_json)

            if updated_credentials_json:
                print(f"INFO_CAL_SERVICE: Token refreshed for {line_user_id}. Updating Firestore.")
                original_scopes = auth_info.get('scopes', settings.GOOGLE_CALENDAR_SCOPES.split())
                # ★★★ db_service のメソッドとして呼び出す ★★★
                await db_service.save_google_credentials_for_user(line_user_id, updated_credentials_json, original_scopes)
                
                try:
                    creds = Credentials.from_authorized_user_info(json.loads(updated_credentials_json), scopes=settings.GOOGLE_CALENDAR_SCOPES.split())
                except Exception as e:
                    print(f"ERROR_CAL_SERVICE: Failed to load refreshed credentials for user {line_user_id}: {e}")
                    return None
                
                if not creds.valid:
                    print(f"ERROR_CAL_SERVICE: Credentials still invalid after refresh for user {line_user_id}.")
                    return None
            else:
                print(f"ERROR_CAL_SERVICE: Token refresh failed for {line_user_id}. Cannot build calendar service.")
                return None
        else:
            print(f"ERROR_CAL_SERVICE: Credentials for {line_user_id} invalid/expired and no refresh token.")
            return None

    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        print(f"INFO_CAL_SERVICE: Google Calendar service client built successfully for user {line_user_id}.")
        return service
    except Exception as e:
        print(f"ERROR_CAL_SERVICE: Failed to build Google Calendar service for user {line_user_id}: {e}")
        traceback.print_exc()
        return None


async def create_calendar_event(
    db_service: FirestoreService, # ★ 引数を FirestoreService のインスタンスに変更
    line_user_id: str,
    shift_info: ShiftInfo
) -> Optional[str]:
    if shift_info.is_holiday or not shift_info.start_time or not shift_info.end_time:
        print(f"INFO_CAL_SERVICE: Skipping event creation (holiday/incomplete) for user {line_user_id}, date: {shift_info.date}")
        return None

    # ★★★ get_calendar_service に db_service を渡す ★★★
    service = await get_calendar_service(db_service, line_user_id)
    if not service:
        print(f"ERROR_CAL_SERVICE: Calendar service not available for user {line_user_id}. Cannot create event.")
        return None

    # --- 以降のイベント作成ロジックは変更なし ---
    start_datetime_naive = datetime.combine(shift_info.date, shift_info.start_time)
    end_datetime_naive = datetime.combine(shift_info.date, shift_info.end_time)

    start_datetime_aware = start_datetime_naive.replace(tzinfo=JST)
    end_datetime_aware = end_datetime_naive.replace(tzinfo=JST)
    
    if end_datetime_aware <= start_datetime_aware:
        print(f"INFO_CAL_SERVICE: End time {end_datetime_aware} is <= start time {start_datetime_aware}. Assuming next day for end time.")
        end_datetime_aware += timedelta(days=1)

    event_summary = f"アルバイト: {shift_info.name or 'シフト'}"
    if shift_info.role:
        event_summary += f" ({shift_info.role})"
    
    description_parts = []
    if shift_info.name: description_parts.append(f"氏名: {shift_info.name}")
    if shift_info.role: description_parts.append(f"担当: {shift_info.role}")
    if shift_info.memo: description_parts.append(f"メモ: {shift_info.memo}")
    event_description = "\n".join(description_parts)

    event_body = {
        'summary': event_summary,
        'description': event_description,
        'start': { 'dateTime': start_datetime_aware.isoformat() },
        'end': { 'dateTime': end_datetime_aware.isoformat() },
    }

    try:
        print(f"DEBUG_CAL_SERVICE: Creating calendar event for user {line_user_id} with body: {event_body}")
        created_event = await run_in_threadpool(
            service.events().insert(calendarId='primary', body=event_body).execute
        )
        event_id = created_event.get('id')
        print(f"INFO_CAL_SERVICE: Event created for user {line_user_id}: ID: {event_id}, Summary: {event_summary}")
        return event_id
    except HttpError as error:
        print(f"ERROR_CAL_SERVICE: HttpError creating event for {line_user_id}: {error.resp.status} - {error.resp.reason if error.resp else 'Unknown reason'}")
        try:
            error_content = json.loads(error.content.decode())
            if 'error' in error_content and 'message' in error_content['error']:
                error_details = error_content['error']['message']
                print(f"ERROR_DETAILS (HttpError): {error_details}")
        except:
            print(f"ERROR_DETAILS (HttpError): Could not parse error content. Raw: {error.content if hasattr(error, 'content') else 'No content'}")
        return None
    except Exception as e:
        print(f"ERROR_CAL_SERVICE: Unexpected error creating event for {line_user_id}: {e}")
        traceback.print_exc()
        return None