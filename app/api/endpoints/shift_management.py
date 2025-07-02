from fastapi import APIRouter, Depends, HTTPException, status, Path as FastApiPath
from app.api.dependencies import get_db_service
from app.models.shift_history import ShiftUpdatePayload
from app.services import calendar_service
from app.services.firestore_service import FirestoreService

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