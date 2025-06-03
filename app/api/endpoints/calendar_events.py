# app/api/endpoints/calendar_events.py
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List
from datetime import datetime, time, date, timezone # timezone をインポート

# from app.models.shift import ShiftInfo # image_parser.py から ShiftInfo をインポートするか、別途定義
from app.utils.image_parser import ShiftInfo # image_parser.py で定義した ShiftInfo を使う場合
from app.services import calendar_service
from app.services.firestore_service import get_google_credentials_for_user # Firestoreから認証情報を取得
# from app.services.firestore_service import save_shift_to_history # シフト履歴保存用 (後で)

router = APIRouter()

# 認証済みLINEユーザーIDを取得する依存関係 (仮実装、セッションなどから取得)
async def get_current_line_user_id(request: Request) -> str:
    # 実際の運用では、LIFFのIDトークン検証やセッションからLINE User IDを取得する
    # ここではテスト用にセッションから取得する例
    line_user_id = request.session.get("current_line_user_id_for_oauth") # OAuth時に保存したIDを流用
    if not line_user_id:
        # LIFFからAPIを叩く場合、リクエストヘッダーにLINEのIDトークンを含め、
        # FastAPI側でデコード・検証してユーザーIDを取得するのが一般的
        raise HTTPException(status_code=401, detail="Not authenticated or LINE User ID not found in session")
    return line_user_id


class CalendarEventRequest(BaseModel):
    shifts: List[ShiftInfo] # 解析済みのシフト情報リスト
    # calendar_id: Optional[str] = 'primary' # どのカレンダーに登録するか (オプション)

@router.post("/register", summary="Register parsed shifts to Google Calendar")
async def register_shifts_to_calendar(
    event_request: CalendarEventRequest,
    line_user_id: str = Depends(get_current_line_user_id) # 認証済みユーザーIDを取得
):
    print(f"INFO: Received request to register {len(event_request.shifts)} shifts for user {line_user_id}")

    # 1. FirestoreからユーザーのGoogle認証情報を取得
    user_creds_map = await get_google_credentials_for_user(line_user_id)
    if not user_creds_map or 'credentials_json' not in user_creds_map:
        raise HTTPException(status_code=403, detail="Google account not linked or credentials not found. Please link your Google account first.")

    credentials_json_str = user_creds_map['credentials_json']

    # 2. Calendar APIサービスクライアントを取得 (トークンリフレッシュも内部で行われる)
    cal_service = calendar_service.get_calendar_service(credentials_json_str)
    if not cal_service:
        # ここで、もしget_calendar_serviceがリフレッシュ後の認証情報を返せるなら、それをFirestoreに保存し直す処理を挟む
        # (get_calendar_service の設計による)
        raise HTTPException(status_code=503, detail="Failed to connect to Google Calendar service. Credentials might be invalid or revoked.")

    registered_event_ids = []
    failed_registrations = []

    for shift in event_request.shifts:
        if shift.is_holiday or not shift.start_time: # 休みか開始時間がなければスキップ
            print(f"DEBUG: Skipping holiday or no-start-time shift for date {shift.date}")
            continue

        # ShiftInfoのdateとtimeからdatetimeオブジェクトを生成
        # 日本時間を仮定 (実際のユーザーのタイムゾーンに合わせて調整が必要)
        # JST = timezone(timedelta(hours=+9)) # これはPython 3.9+ の zoneinfo がないと使えない
        # tz_jst = pytz.timezone('Asia/Tokyo') # pytz を使う場合 (pip install pytz)
        # 簡単のため、ここでは naive datetime を使い、Calendar APIがデフォルトのタイムゾーンで解釈するのに任せるか、
        # ISOフォーマットでタイムゾーンオフセット (+09:00) を付与する。
        # Google Calendar APIは通常UTCか、RFC3339形式のタイムゾーン付き日時を期待する。

        if not shift.date or not shift.start_time or not shift.end_time:
            print(f"WARNING: Incomplete shift data for {shift.date}, skipping.")
            failed_registrations.append({"date": str(shift.date), "reason": "Incomplete time info"})
            continue

        try:
            # datetimeオブジェクトに変換 (ここではローカルタイムゾーンを仮定し、API側でUTC変換されることを期待するか、明示的にUTCにする)
            # タイムゾーンを考慮する場合、ShiftInfo.date が dateオブジェクト、start_time/end_time が timeオブジェクトなので結合
            start_dt_naive = datetime.combine(shift.date, shift.start_time)
            end_dt_naive = datetime.combine(shift.date, shift.end_time)

            # 終了時刻が開始時刻より早い場合 (例: 16:00 - 00:00)、終了日は翌日と解釈
            if end_dt_naive <= start_dt_naive:
                from datetime import timedelta
                end_dt_naive += timedelta(days=1)
                print(f"DEBUG: End time is on or before start time, assuming next day for end: {end_dt_naive}")

            # Google Calendar APIは通常RFC3339形式を期待 (YYYY-MM-DDTHH:MM:SS[+-]HH:MM)
            # タイムゾーンを付与する (例: Asia/Tokyo)
            # ここでは簡単のため、タイムゾーン情報を付与せずにISOフォーマットで渡す
            # サーバーのタイムゾーン設定やカレンダーのデフォルトタイムゾーンに依存する可能性あり
            # より堅牢にするには、pytzやdateutilで適切なタイムゾーンを付与する

            # イベントのタイトル (例: "バイト (フロント)")
            event_summary = f"アルバイト ({shift.role})" if shift.role else "アルバイト"
            if shift.name and shift.name != "氏名不明": # 氏名があれば追加
                event_summary += f" - {shift.name}"


            event_id = calendar_service.create_calendar_event(
                service=cal_service,
                summary=event_summary,
                start_datetime=start_dt_naive, # Naive datetime (ローカルタイムゾーンと仮定)
                end_datetime=end_dt_naive,   # Naive datetime
                description=shift.memo or ""
            )
            if event_id:
                registered_event_ids.append({"date": str(shift.date), "event_id": event_id})
                # (オプション) Firestoreのshift_historyにcalendar_event_idを保存
                # await save_shift_to_history(line_user_id, shift, event_id)
            else:
                failed_registrations.append({"date": str(shift.date), "reason": "API call failed"})
        except Exception as e:
            print(f"ERROR: Failed to process or register shift for date {shift.date}: {e}")
            failed_registrations.append({"date": str(shift.date), "reason": str(e)})

    if not registered_event_ids and not failed_registrations and event_request.shifts:
        return {"message": "送信されたシフトは登録対象外（休みなど）でした。", "registered": [], "failed": []}
    if not registered_event_ids and failed_registrations:
        raise HTTPException(status_code=500, detail=f"Failed to register any shifts. Errors: {failed_registrations}")

    return {
        "message": f"Shift registration process complete. {len(registered_event_ids)} events registered.",
        "registered_events": registered_event_ids,
        "failed_registrations": failed_registrations
    }