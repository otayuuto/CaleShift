# app/services/calendar_service.py
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build, Resource # Resource をインポート
from googleapiclient.errors import HttpError
from typing import Optional, Dict, Any, List
from datetime import datetime, time, date, timezone # timezone をインポート
import json

# from app.models.user import GoogleAuthInfo # Firestoreから取得するデータ構造に合わせて
from app.services.firestore_service import get_google_credentials_for_user, save_google_credentials_for_user # Firestore連携
# from app.services.google_auth_service import refresh_access_token # これは古い refresh_google_access_token_for_user を使う
from app.services.firestore_service import refresh_google_access_token_for_user # Firestoreと連携するリフレッシュ関数

from app.utils.image_parser import ShiftInfo # パースされたシフト情報の型


async def get_calendar_service(line_user_id: str) -> Optional[Resource]:
    """
    指定されたLINEユーザーの認証情報を使ってGoogle Calendar APIサービスオブジェクトを構築します。
    必要に応じてアクセストークンをリフレッシュします。
    """
    google_auth_data = await get_google_credentials_for_user(line_user_id)
    if not google_auth_data or not google_auth_data.get('credentials_json'):
        print(f"ERROR: No Google credentials found for user {line_user_id}.")
        return None

    credentials_json_str = google_auth_data['credentials_json']
    
    try:
        # JSON文字列からCredentialsオブジェクトを復元
        creds = Credentials.from_authorized_user_info(json.loads(credentials_json_str))

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print(f"INFO: Calendar service - Access token for {line_user_id} expired, attempting to refresh.")
                # Firestoreと連携するリフレッシュ関数を呼び出す
                refresh_success = await refresh_google_access_token_for_user(line_user_id)
                if refresh_success:
                    # リフレッシュ成功後、再度認証情報を取得
                    refreshed_auth_data = await get_google_credentials_for_user(line_user_id)
                    if refreshed_auth_data and refreshed_auth_data.get('credentials_json'):
                        creds = Credentials.from_authorized_user_info(json.loads(refreshed_auth_data['credentials_json']))
                    else:
                        print(f"ERROR: Failed to load credentials after refresh for {line_user_id}.")
                        return None
                else:
                    print(f"ERROR: Token refresh failed for {line_user_id}.")
                    return None
            else:
                print(f"ERROR: Invalid or expired credentials without refresh token for {line_user_id}.")
                return None
        
        # APIクライアントを構築
        service = build('calendar', 'v3', credentials=creds)
        print(f"INFO: Google Calendar service client built successfully for user {line_user_id}.")
        return service
    except Exception as e:
        print(f"ERROR: Failed to build Google Calendar service for user {line_user_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


async def create_calendar_event(line_user_id: str, shift_info: ShiftInfo) -> Optional[str]:
    """
    Googleカレンダーに新しいイベント（シフト）を作成します。
    :param line_user_id: LINEユーザーID
    :param shift_info: 解析されたシフト情報 (ShiftInfoオブジェクト)
    :return: 作成されたイベントのID、またはエラーの場合はNone
    """
    if shift_info.is_holiday or not shift_info.start_time or not shift_info.end_time:
        print(f"INFO: Skipping calendar event creation for holiday or incomplete shift for user {line_user_id}: {shift_info.date}")
        return None # 休みや開始/終了時刻がない場合はイベントを作成しない (または別の処理)

    service = await get_calendar_service(line_user_id)
    if not service:
        return None

    # datetimeオブジェクトを作成 (日付と時刻を結合)
    # Google Calendar APIはRFC3339形式のタイムスタンプを期待 (タイムゾーン情報付き)
    # ここではJST (+09:00) を仮定。ユーザーのタイムゾーン設定に応じて変更が必要。
    # FastAPIサーバーが動作する環境のタイムゾーンに依存しないように、明示的に指定するのが良い。
    # start_datetime = datetime.combine(shift_info.date, shift_info.start_time, tzinfo=timezone.utc).astimezone(pytz.timezone('Asia/Tokyo'))
    # end_datetime = datetime.combine(shift_info.date, shift_info.end_time, tzinfo=timezone.utc).astimezone(pytz.timezone('Asia/Tokyo'))
    # pytz を使う場合は pip install pytz が必要

    # datetime.timezone を使う場合 (Python 3.9+)
    # JST = timezone(timedelta(hours=9)) # これはdatetime.timezoneの簡単な作り方ではない
    # from dateutil import tz # pip install python-dateutil
    # JST = tz.gettz('Asia/Tokyo')
    # start_datetime_naive = datetime.combine(shift_info.date, shift_info.start_time)
    # end_datetime_naive = datetime.combine(shift_info.date, shift_info.end_time)
    # start_datetime_aware = start_datetime_naive.astimezone(JST) if JST else start_datetime_naive.astimezone()
    # end_datetime_aware = end_datetime_naive.astimezone(JST) if JST else end_datetime_naive.astimezone()

    # 一旦、日付と時刻を naive datetime として結合し、ISOフォーマットでタイムゾーンを指定する
    # Google Calendar API は通常、タイムゾーンID (例: 'Asia/Tokyo') を指定できる
    start_dt_str = datetime.combine(shift_info.date, shift_info.start_time).isoformat()
    end_dt_str = datetime.combine(shift_info.date, shift_info.end_time).isoformat()
    
    # タイムゾーン (カレンダーのデフォルトタイムゾーンが使われるか、明示的に指定)
    # ユーザーのカレンダーのタイムゾーンを取得して使うのが最も正確
    # ここでは日本のユーザーを想定して 'Asia/Tokyo' をハードコード (推奨はしない)
    event_timezone = 'Asia/Tokyo' # 将来的にはユーザー設定やカレンダー設定から取得

    event_summary = f"アルバイト ({shift_info.name or '自分'})"
    if shift_info.role:
        event_summary += f" - {shift_info.role}"
    
    description_parts = []
    if shift_info.name:
        description_parts.append(f"氏名: {shift_info.name}")
    if shift_info.role:
        description_parts.append(f"担当: {shift_info.role}")
    if shift_info.memo:
        description_parts.append(f"メモ: {shift_info.memo}")
    event_description = "\n".join(description_parts)


    event = {
        'summary': event_summary,
        'location': '', # 勤務地の情報を入れられると良い (workplacesコレクションと連携)
        'description': event_description,
        'start': {
            'dateTime': start_dt_str,
            'timeZone': event_timezone,
        },
        'end': {
            'dateTime': end_dt_str,
            'timeZone': event_timezone,
        },
        # 'reminders': { # 必要ならリマインダー設定
        #     'useDefault': False,
        #     'overrides': [
        #         {'method': 'popup', 'minutes': 30},
        #     ],
        # },
    }

    try:
        print(f"DEBUG: Creating calendar event for user {line_user_id}: {event}")
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        event_id = created_event.get('id')
        print(f"INFO: Event created for user {line_user_id}: ID: {event_id}, Summary: {event['summary']}")
        return event_id
    except HttpError as error:
        print(f"ERROR: An API error occurred while creating event for user {line_user_id}: {error}")
        # エラーレスポンスの詳細を取得
        error_details = error.resp.reason if hasattr(error.resp, 'reason') else str(error)
        if hasattr(error, '_get_reason'): # More detailed error for some cases
            try:
                error_content = json.loads(error.content.decode())
                if 'error' in error_content and 'message' in error_content['error']:
                     error_details = error_content['error']['message']
            except:
                 pass
        print(f"ERROR_DETAILS: {error_details}")

        # トークンが無効/期限切れの場合、リフレッシュを試みるべきだったが、
        # get_calendar_service 内で既に行っているはず。
        # それでもエラーなら、他の原因 (権限不足、APIリミットなど) の可能性。
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error creating calendar event for user {line_user_id}: {e}")
        traceback.print_exc()
        return None