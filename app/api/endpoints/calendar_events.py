# app/api/endpoints/calendar_events.py (修正後)
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional
from datetime import datetime, time, date, timezone # timezone をインポート
from pydantic import BaseModel # ★ BaseModelをインポート

from app.utils.image_parser import ShiftInfo
from app.services import calendar_service

# --- インポートの修正 ---
# from app.services.firestore_service import get_google_credentials_for_user # ← この行を削除
from app.services.firestore_service import FirestoreService # ★ FirestoreServiceクラスをインポート
from app.api.dependencies import get_db_service # ★ 依存性注入ヘルパーをインポート

router = APIRouter()

# 認証済みLINEユーザーIDを取得する依存関係 (仮実装)
async def get_current_line_user_id(request: Request) -> str:
    # 実際の運用では、LIFFのIDトークン検証やセッションからLINE User IDを取得する
    line_user_id = request.session.get("current_line_user_id_for_oauth")
    if not line_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated or LINE User ID not found")
    return line_user_id


class CalendarEventRequest(BaseModel):
    shifts: List[ShiftInfo]

@router.post("/register", summary="Register parsed shifts to Google Calendar")
async def register_shifts_to_calendar(
    event_request: CalendarEventRequest,
    line_user_id: str = Depends(get_current_line_user_id),
    db_service: FirestoreService = Depends(get_db_service) # ★ db_serviceを依存性注入で取得
):
    print(f"INFO: Received request to register {len(event_request.shifts)} shifts for user {line_user_id}")

    registered_event_ids = []
    failed_registrations = []

    for shift in event_request.shifts:
        if shift.is_holiday or not shift.start_time:
            print(f"DEBUG: Skipping holiday or no-start-time shift for date {shift.date}")
            continue

        if not shift.date or not shift.start_time or not shift.end_time:
            print(f"WARNING: Incomplete shift data for {shift.date}, skipping.")
            failed_registrations.append({"date": str(shift.date), "reason": "Incomplete time info"})
            continue

        try:
            # ★★★ calendar_service.create_calendar_event を呼び出す ★★★
            # この関数は内部で get_calendar_service を呼び、トークンリフレッシュなども含めて処理してくれる
            event_id = await calendar_service.create_calendar_event(
                db_service=db_service, # ★ db_service を渡す
                line_user_id=line_user_id,
                shift_info=shift
            )
            
            if event_id:
                registered_event_ids.append({"date": str(shift.date), "event_id": event_id})
                # (オプション) Firestoreのshift_historyにcalendar_event_idを保存
                # workplace_id が必要になる
                # await db_service.log_shift_history(workplace_id, line_user_id, shift, event_id)
            else:
                failed_registrations.append({"date": str(shift.date), "reason": "API call to create event failed"})
        except Exception as e:
            print(f"ERROR: Failed to process or register shift for date {shift.date}: {e}")
            import traceback
            traceback.print_exc()
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