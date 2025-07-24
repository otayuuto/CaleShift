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