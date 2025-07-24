# app/api/endpoints/liff_settings.py
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
async def liff_shift_confirm_page(
    request: Request,
    pending_id: Optional[str] = None, # ★ pending_id をオプショナルにする
    liff_state: Optional[str] = None # ★ liff.state を受け取る (クエリパラメータ名は 'liff.state' ではなく 'liff_state')
                                    # FastAPIはドットを含むクエリパラメータ名を扱いにくい場合があるため、
                                    # request.query_params を直接見る方が確実
):
    """シフト登録確認・編集用LIFFページ (liff_shift_confirm.html) を表示します。"""
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Server configuration error: Template engine not found.")

    final_pending_id = pending_id # まずは直接の pending_id を試す

    # もし pending_id が直接取得できなければ、liff.state をパースしてみる
    if not final_pending_id:
        # FastAPIではクエリパラメータのドットがアンダースコアに変換されることがあるが、
        # request.query_params を直接見るのが最も確実
        liff_state_from_query = request.query_params.get("liff.state")
        if liff_state_from_query:
            print(f"DEBUG: Found liff.state: {liff_state_from_query}")
            # liff.state の値はURLエンコードされている (例: %3Fpending_id%3Dxxxx)
            # さらに、その中身もクエリ文字列になっている (例: ?pending_id=xxxx)
            # URLデコードはFastAPIが自動で行うので、中身のクエリをパースする
            
            # liff.state の先頭が '?' で始まっている場合がある
            query_in_liff_state = liff_state_from_query
            if query_in_liff_state.startswith("?"):
                query_in_liff_state = query_in_liff_state[1:]
                
            parsed_params = parse_qs(query_in_liff_state)
            if 'pending_id' in parsed_params:
                final_pending_id = parsed_params['pending_id'][0] # parse_qs は値のリストを返す
                print(f"DEBUG: Extracted pending_id from liff.state: {final_pending_id}")

    if not final_pending_id:
        # それでも見つからない場合はエラー
        print("ERROR: Could not find 'pending_id' directly or within 'liff.state'.")
        raise HTTPException(status_code=400, detail="Required parameter 'pending_id' is missing.")

    return templates.TemplateResponse("liff_shift_confirm.html", {
        "request": request,
        "pending_id": final_pending_id # 抽出したIDをテンプレートに渡す
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
    try:
        workplace_id = await db_service.get_primary_workplace_id_for_user(line_user_id)
        if not workplace_id:
            return {"shifts": []}
        shift_history = await db_service.get_shift_history_for_user_in_workplace(
            workplace_id=workplace_id,
            line_user_id=line_user_id
        )
        return {"shifts": shift_history}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An unexpected error occurred while fetching shifts.")