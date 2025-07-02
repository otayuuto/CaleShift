from fastapi import APIRouter, Depends, HTTPException, status, Path as FastApiPath
from typing import List
from app.api.dependencies import get_db_service
from app.models.shift_history import ShiftUpdatePayload
from app.services import calendar_service
from app.services.firestore_service import FirestoreService
from app.api.dependencies import get_db_service
from app.models.shift import RegisterShiftsPayload

router = APIRouter(prefix="/api/v1", tags=["Shift Management API"])

@router.put("/workplaces/{workplace_id}/shifts/{history_id}")
async def update_shift(
    workplace_id: str,
    history_id: str,
    payload: ShiftUpdatePayload,
    db_service: FirestoreService = Depends(get_db_service),
    # line_user_id: str = Depends(get_current_line_user_id_from_liff) # ★ 認証が必要
):
    """シフト情報を更新 (カレンダーとFirestoreの両方)"""
    # TODO: 認証: リクエスト元のユーザーがこのシフト履歴を編集する権限があるか確認
    
    # 1. Firestoreから現在のシフト履歴を取得
    history_item = await db_service.get_shift_history_item(workplace_id, history_id)
    if not history_item:
        raise HTTPException(status_code=404, detail="Shift history not found.")
    
    line_user_id = history_item.get("user_id")
    event_id = history_item.get("calendar_event_id")
    if not line_user_id or not event_id:
        raise HTTPException(status_code=500, detail="Shift history data is corrupted.")

    # 2. Googleカレンダーを更新
    updated_event = await calendar_service.update_calendar_event(db_service, line_user_id, event_id, payload)
    if not updated_event:
        raise HTTPException(status_code=500, detail="Failed to update Google Calendar event.")

    # 3. Firestoreを更新
    # payloadからFirestoreに保存する形式の辞書を作成
    update_fs_data = payload.model_dump(exclude_unset=True) # 値がセットされたフィールドのみ
    success = await db_service.update_shift_history(workplace_id, history_id, update_fs_data)
    if not success:
        # カレンダーは更新されたがDB更新に失敗した場合のハンドリング (警告ログなど)
        print(f"WARNING: Calendar event {event_id} was updated, but failed to update Firestore history {history_id}.")

    return {"message": "Shift updated successfully", "event": updated_event}

# 保留中シフト情報を取得
@router.get("/pending-shifts/{pending_id}", tags=["Pending Shifts"])
async def get_pending_shift_data(
    pending_id: str = FastApiPath(..., description="保留中シフトの一時ID"),
    db_service: FirestoreService = Depends(get_db_service),
    # line_user_id: str = Depends(get_current_line_user_id_from_liff) # ★ 本来は認証が必要
):
    """
    指定されたIDの保留中シフト情報を取得します。LIFFの確認画面から呼び出されます。
    """
    if not db_service:
        raise HTTPException(status_code=500, detail="Database connection not available.")

    try:
        pending_data = await db_service.get_pending_shifts(pending_id)
        if not pending_data:
            raise HTTPException(status_code=404, detail="Pending shift data not found or expired.")
        
        # ★ セキュリティチェック (重要): リクエスト元のユーザーが、このデータの所有者か確認
        # liff_user_id = line_user_id # 依存性注入で取得したユーザーID
        # if pending_data.get("line_user_id") != liff_user_id:
        #     raise HTTPException(status_code=403, detail="You are not authorized to view this data.")

        return pending_data # Firestoreから取得したデータをそのまま返す
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"ERROR: Error getting pending shifts for ID {pending_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to retrieve pending shift data.")

@router.delete("/workplaces/{workplace_id}/shifts/{history_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(
    workplace_id: str,
    history_id: str,
    db_service: FirestoreService = Depends(get_db_service),
    # line_user_id: str = Depends(get_current_line_user_id_from_liff) # ★ 認証が必要
):
    """シフト情報を削除 (カレンダーとFirestoreの両方)"""
    # TODO: 認証: リクエスト元のユーザーがこのシフト履歴を削除する権限があるか確認

    # 1. Firestoreから現在のシフト履歴を取得して、event_idとline_user_idを得る
    history_item = await db_service.get_shift_history_item(workplace_id, history_id)
    if not history_item:
        # 既にないので、成功したことにして返す (べき等性)
        return

    line_user_id = history_item.get("user_id")
    event_id = history_item.get("calendar_event_id")

    # 2. Googleカレンダーから削除
    if line_user_id and event_id:
        cal_delete_success = await calendar_service.delete_calendar_event(db_service, line_user_id, event_id)
        if not cal_delete_success:
            # 失敗しても処理を継続し、DBからの削除を試みる
            print(f"WARNING: Failed to delete Google Calendar event {event_id}, but proceeding to delete from Firestore.")
    
    # 3. Firestoreから削除
    fs_delete_success = await db_service.delete_shift_history(workplace_id, history_id)
    if not fs_delete_success:
        raise HTTPException(status_code=500, detail="Failed to delete shift history from database.")
    
@router.post("/shifts/register", status_code=status.HTTP_200_OK, tags=["Shift Registration"])
async def register_confirmed_shifts(
    payload: RegisterShiftsPayload, # ★ リクエストボディを受け取る
    db_service: FirestoreService = Depends(get_db_service)
    # line_user_id_from_token: str = Depends(get_current_line_user_id_from_liff) # ★ 本来は認証が必要
):
    """
    LIFF確認画面から送信された、ユーザーが確定したシフト情報を
    GoogleカレンダーとFirestoreのシフト履歴に登録します。
    """
    if not db_service:
        raise HTTPException(status_code=500, detail="Database connection not available.")

    # ★ セキュリティチェック (重要)
    # if payload.line_user_id != line_user_id_from_token:
    #     raise HTTPException(status_code=403, detail="User ID mismatch. Not authorized.")

    created_events_count = 0
    failed_events_count = 0
    results_detail = []

    print(f"INFO: Received request to register {len(payload.shifts_to_register)} shifts for user {payload.line_user_id}")

    for shift_info in payload.shifts_to_register:
        try:
            # カレンダーイベント作成
            event_id = await calendar_service.create_calendar_event(db_service, payload.line_user_id, shift_info)

            if event_id:
                # 履歴保存
                await db_service.log_shift_history(
                    workplace_id=payload.workplace_id,
                    line_user_id=payload.line_user_id,
                    shift_info=shift_info,
                    calendar_event_id=event_id,
                    status="created"
                )
                created_events_count += 1
                results_detail.append(f"OK: {shift_info.date.strftime('%m/%d')}のシフト")
            else:
                failed_events_count += 1
                results_detail.append(f"NG: {shift_info.date.strftime('%m/%d')}のシフト (カレンダー登録失敗)")

        except Exception as e:
            failed_events_count += 1
            error_msg = f"NG: {shift_info.date.strftime('%m/%d')}のシフト (サーバーエラー: {e})"
            results_detail.append(error_msg)
            print(f"ERROR: Failed to process a shift for user {payload.line_user_id}: {e}")
            import traceback
            traceback.print_exc()

    # (オプション) pending_shifts のステータスを更新するか、削除する
    # await db_service.update_pending_shift_status(payload.pending_id, "confirmed")

    return {
        "message": f"処理が完了しました。成功: {created_events_count}件, 失敗: {failed_events_count}件",
        "created_count": created_events_count,
        "failed_count": failed_events_count,
        "details": results_detail
    }