# app/api/endpoints/liff_settings.py
from datetime import datetime
from fastapi import APIRouter, Request, Depends, HTTPException, status, Body, Path as FastApiPath
from fastapi.responses import HTMLResponse
import traceback
from typing import List, Optional

from app.models.setting import (
    WorkplaceCreatePayload, WorkplaceResponse,
    MyWorkplaceSettingCreatePayload, MyWorkplaceSettingResponse
)
from app.services.firestore_service import FirestoreService
from app.api.dependencies import get_db_service # ★ 依存関係関数をインポート
from urllib.parse import urlparse, parse_qs # ★ URLパース用のライブラリをインポート

router = APIRouter()

# ==============================================================================
# LIFFページを返すエンドポイント群
# ==============================================================================

@router.get("/liff/settings", response_class=HTMLResponse, tags=["LIFF Pages"])
async def get_liff_workplace_settings_page(request: Request):
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not found.")
    return templates.TemplateResponse("settings.html", {"request": request})

@router.get("/liff/google-calendar-auth", response_class=HTMLResponse, tags=["LIFF Pages"])
async def liff_google_calendar_auth_page(request: Request):
    """(Googleカレンダー連携用) LIFFページ (liff_google_calendar_auth.html) を表示します。"""
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Server configuration error: Template engine not found.")
    return templates.TemplateResponse("liff_google_calendar_auth.html", {"request": request})

@router.get("/liff/shifts/list", response_class=HTMLResponse, tags=["LIFF Pages"])
async def liff_shift_list_page(request: Request):
    """(シフト履歴一覧用) LIFFページ (liff_shift_list.html) を表示します。"""
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Server configuration error: Template engine not found.")
    return templates.TemplateResponse("liff_shift_list.html", {"request": request})

# シフト登録確認・編集用LIFFページ
@router.get("/liff/shifts/confirm", response_class=HTMLResponse, tags=["LIFF Pages"])
async def liff_shift_confirm_page(request: Request): # ★ 引数を request のみに変更
    """
    シフト登録確認・編集用LIFFページ (liff_shift_confirm.html) を表示します。
    liff.state を考慮して、クエリパラメータを堅牢にパースします。
    """
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Server configuration error: Template engine not found.")

    # --- パラメータ取得ロジック ---
    query_params = request.query_params
    print(f"DEBUG: Received query parameters: {query_params}") # ★ 実際に届いたクエリパラメータをログに出力

    pending_id = query_params.get("pending_id")

    if not pending_id:
        # liff.state を確認
        liff_state = query_params.get("liff.state")
        if liff_state:
            print(f"DEBUG: 'pending_id' not found directly. Parsing liff.state: '{liff_state}'")
            # liff.state の値はURLエンコードされている (例: %3Fpending_id%3Dxxxx)
            # FastAPIがデコードしてくれるので、中身のクエリ文字列 (?pending_id=xxxx) をパースする
            query_in_liff_state = liff_state
            if query_in_liff_state.startswith("?"):
                query_in_liff_state = query_in_liff_state[1:]
            
            parsed_params = parse_qs(query_in_liff_state)
            if 'pending_id' in parsed_params:
                pending_id = parsed_params['pending_id'][0]
                print(f"DEBUG: Extracted pending_id from liff.state: '{pending_id}'")

    if not pending_id:
        print(f"CRITICAL_ERROR: Could not extract 'pending_id' from query params. Full query: {query_params}")
        # ユーザーに分かりやすいエラーページを返すことも検討
        # return templates.TemplateResponse("error_page.html", {"request": request, "error_message": "必要な情報が不足しています。"})
        raise HTTPException(status_code=400, detail="Required information (pending_id) is missing from the URL. Please try again from the link in LINE.")

    return templates.TemplateResponse("liff_shift_confirm.html", {
        "request": request,
        "pending_id": pending_id
    })

# ==============================================================================
# APIエンドポイント群
# ==============================================================================

@router.post(
    "/api/v1/workplaces",
    response_model=WorkplaceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Workplaces API"]
)
async def create_new_workplace_shared_info(
    payload: WorkplaceCreatePayload,
    db_service: FirestoreService = Depends(get_db_service) # ★ 依存性注入を使用
):
    try:
        created_workplace = await db_service.create_shared_workplace_info(payload)
        return created_workplace
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create workplace information.")

@router.get(
    "/api/v1/workplaces",
    response_model=List[WorkplaceResponse],
    tags=["Workplaces API"]
)
async def list_all_workplaces(
    db_service: FirestoreService = Depends(get_db_service) # ★ 依存性注入を使用
):
    """登録されているすべての共有勤務場所情報をリストで取得します。"""
    try:
        workplaces = await db_service.get_all_shared_workplaces()
        return workplaces
    except Exception as e:
        print(f"ERROR: Error listing all workplaces: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list workplaces.")
        
@router.put(
    "/api/v1/users/{line_user_id}/my-workplace-settings/{workplace_id}",
    response_model=MyWorkplaceSettingResponse,
    tags=["User Settings API"]
)
async def set_or_update_my_workplace_setting(
    payload: MyWorkplaceSettingCreatePayload,
    line_user_id: str = FastApiPath(..., description="設定対象のユーザーのLINE ID"),
    workplace_id: str = FastApiPath(..., description="対象となるバイト先のID"),
    db_service: FirestoreService = Depends(get_db_service)
):
    # TODO: 認証処理
    try:
        my_setting = await db_service.set_user_target_name_for_workplace(
            line_user_id=line_user_id,
            workplace_id=workplace_id,
            payload=payload
        )
        return my_setting
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to set your workplace setting.")

@router.get("/api/v1/users/{line_user_id}/my-workplace-settings/{workplace_id}", response_model=Optional[MyWorkplaceSettingResponse], tags=["User Settings API"])
async def get_my_workplace_setting(
    line_user_id: str = FastApiPath(...),
    workplace_id: str = FastApiPath(...),
    db_service: FirestoreService = Depends(get_db_service)
):
    # TODO: 認証処理
    try:
        my_setting = await db_service.get_user_target_name_for_workplace(
            line_user_id=line_user_id,
            workplace_id=workplace_id
        )
        return my_setting
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get your workplace setting.")

# (他の担当者が実装しているエンドポイントは変更なし)
@router.get("/api/v1/users/{line_user_id}/shifts", tags=["Shift History API"])
async def get_user_shifts(
    line_user_id: str,
    db_service: FirestoreService = Depends(get_db_service)
):
    """指定されたユーザーのシフト履歴を取得します。"""
    # ... (db_service, workplace_id のチェックは同じ) ...
    try:
        workplace_id = await db_service.get_primary_workplace_id_for_user(line_user_id)
        if not workplace_id:
            return {"shifts": []}
        
        shift_history_list = await db_service.get_shift_history_for_user_in_workplace(
            workplace_id=workplace_id,
            line_user_id=line_user_id
        )
        if shift_history_list is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve shift history.")

        # ★★★ ここからが修正箇所 ★★★
        # Firestoreから返されたdatetimeオブジェクトを、フロントエンドで正しく解釈できる
        # タイムゾーン付きのISO 8601形式の文字列に変換する。
        
        processed_history = []
        for history_item in shift_history_list:
            if 'start_time' in history_item and isinstance(history_item['start_time'], datetime):
                # datetimeオブジェクトをISO形式文字列に変換 (例: "2025-07-25T08:30:00+00:00")
                history_item['start_time'] = history_item['start_time'].isoformat()
            
            if 'end_time' in history_item and isinstance(history_item['end_time'], datetime):
                history_item['end_time'] = history_item['end_time'].isoformat()
            
            processed_history.append(history_item)


        return {"shifts": processed_history} # ★ 変換後のリストを返す
        shift_history = await db_service.get_shift_history_for_user_in_workplace(
            workplace_id=workplace_id,
            line_user_id=line_user_id
        )
        return {"shifts": shift_history}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An unexpected error occurred while fetching shifts.")