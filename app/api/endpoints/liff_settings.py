# app/api/endpoints/liff_settings.py (統合・修正後)
from fastapi import APIRouter, Request, Depends, HTTPException, status, Body, Path as FastApiPath
from fastapi.responses import HTMLResponse
import traceback
from typing import List, Optional

# --- Pydanticモデルをインポート ---
# origin/aoshiブランチのモデルをベースにする
from app.models.setting import (
    WorkplaceCreatePayload, WorkplaceResponse,
    MyWorkplaceSettingCreatePayload, MyWorkplaceSettingResponse
)

# --- サービスと依存性注入をインポート ---
from app.services.firestore_service import FirestoreService
from app.api.dependencies import get_db_service # main.pyのapp.stateからサービスを取得する関数

router = APIRouter()

# ==============================================================================
# LIFFページを返すエンドポイント群
# ==============================================================================

@router.get("/liff/settings", response_class=HTMLResponse, tags=["LIFF Pages"])
async def get_liff_workplace_settings_page(request: Request):
    """(バイト先設定用) LIFFページ (settings.html) を表示します。"""
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Server configuration error: Template engine not found.")
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

# ==============================================================================
# APIエンドポイント群
# ==============================================================================

# --- バイト先 (Workplace) の共有情報に関するAPI ---

@router.post(
    "/api/v1/workplaces",
    response_model=WorkplaceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Workplaces API (Shared)"]
)
async def create_new_workplace_shared_info(
    payload: WorkplaceCreatePayload,
    db_service: FirestoreService = Depends(get_db_service)
):
    """新しい共有の勤務場所情報を作成します。"""
    try:
        created_workplace = await db_service.create_shared_workplace_info(payload)
        return created_workplace
    except Exception as e:
        print(f"ERROR: Error creating shared workplace info: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create workplace information.")

@router.get(
    "/api/v1/workplaces",
    response_model=List[WorkplaceResponse],
    tags=["Workplaces API (Shared)"]
)
async def list_all_workplaces(db_service: FirestoreService = Depends(get_db_service)):
    """登録されているすべての共有勤務場所情報をリストで取得します。"""
    try:
        workplaces = await db_service.get_all_shared_workplaces() # このメソッドをfirestore_service.pyに実装する必要あり
        return workplaces
    except Exception as e:
        print(f"ERROR: Error listing all workplaces: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list workplaces.")

# --- ユーザー個別の勤務場所設定に関するAPI ---

@router.put(
    "/api/v1/users/{line_user_id}/my-workplace-settings/{workplace_id}",
    response_model=MyWorkplaceSettingResponse,
    tags=["User's Workplace Settings API"]
)
async def set_or_update_my_workplace_setting(
    payload: MyWorkplaceSettingCreatePayload,
    line_user_id: str = FastApiPath(..., description="設定対象のユーザーのLINE ID"),
    workplace_id: str = FastApiPath(..., description="対象となるバイト先のID"),
    db_service: FirestoreService = Depends(get_db_service)
):
    """ユーザー個人の勤務場所設定（シフト表での名前など）を作成または更新します。"""
    # TODO: 認証: リクエスト元のユーザーが line_user_id と一致するか検証するロジックが必要
    try:
        my_setting = await db_service.set_user_target_name_for_workplace( # このメソッドをfirestore_service.pyに実装する必要あり
            line_user_id=line_user_id,
            workplace_id=workplace_id,
            payload=payload
        )
        return my_setting
    except Exception as e:
        print(f"ERROR: Error setting user's workplace setting for user {line_user_id}, wp {workplace_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to set your workplace setting.")

@router.get(
    "/api/v1/users/{line_user_id}/my-workplace-settings/{workplace_id}",
    response_model=Optional[MyWorkplaceSettingResponse],
    tags=["User's Workplace Settings API"]
)
async def get_my_workplace_setting(
    line_user_id: str = FastApiPath(..., description="設定対象のユーザーのLINE ID"),
    workplace_id: str = FastApiPath(..., description="対象となるバイト先のID"),
    db_service: FirestoreService = Depends(get_db_service)
):
    """ユーザー個人の勤務場所設定を取得します。"""
    # TODO: 認証: リクエスト元のユーザーが line_user_id と一致するか検証するロジックが必要
    try:
        my_setting = await db_service.get_user_target_name_for_workplace( # get_target_name_for_shift_extractionを改名・拡張
            line_user_id=line_user_id,
            workplace_id=workplace_id
        )
        if my_setting is None:
            return None # 200 OK と空のボディを返す
        return my_setting
    except Exception as e:
        print(f"ERROR: Error getting user's workplace setting for user {line_user_id}, wp {workplace_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get your workplace setting.")

# --- シフト履歴に関するAPI ---

@router.get("/api/v1/users/{line_user_id}/shifts", tags=["Shift History API"])
async def get_user_shifts(
    line_user_id: str,
    db_service: FirestoreService = Depends(get_db_service)
):
    """指定されたユーザーのシフト履歴を取得します。"""
    # TODO: 認証: リクエスト元のユーザーが line_user_id と一致するか検証するロジックが必要
    try:
        # どの勤務場所の履歴を取得するか？ -> まずは主要な勤務場所とする
        workplace_id = await db_service.get_primary_workplace_id_for_user(line_user_id)
        if not workplace_id:
            return {"shifts": []}
        
        shift_history = await db_service.get_shift_history_for_user_in_workplace(
            workplace_id=workplace_id,
            line_user_id=line_user_id
        )
        if shift_history is None: # サービス関数でエラーが発生した場合
            raise HTTPException(status_code=500, detail="Failed to retrieve shift history.")
        
        return {"shifts": shift_history}
    except Exception as e:
        print(f"ERROR: Error in get_user_shifts endpoint for {line_user_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An unexpected error occurred while fetching shifts.")