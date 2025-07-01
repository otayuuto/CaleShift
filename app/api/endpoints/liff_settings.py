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

router = APIRouter()

def get_firestore_service():
    return FirestoreService()

# (get_current_line_user_id_from_liff 依存性注入関数は、実際の認証方法に合わせて実装が必要)
# async def get_current_line_user_id_from_liff(request: Request) -> str:
#     # ... (認証ロジック) ...
#     # return "verified_user_id"
#     pass


@router.get("/liff/settings", response_class=HTMLResponse, tags=["LIFF Display"])
async def get_liff_settings_page(request: Request):
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not configured.")
    return templates.TemplateResponse("settings.html", {"request": request})


@router.post(
    "/api/v1/workplaces",
    response_model=WorkplaceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Workplaces (Shared Info)"]
)
async def create_new_workplace_shared_info(
    payload_with_user_id: WorkplaceCreatePayload, # Pydanticモデルでリクエストボディ全体を受け取る
    db_service: FirestoreService = Depends(get_firestore_service)
):
    try:
        created_workplace = await db_service.create_shared_workplace_info(
            # created_by_user_id は payload_with_user_id から取得
            # payload も payload_with_user_id を渡す (サービス側で分解)
            payload=payload_with_user_id
        )
        return created_workplace
    except Exception as e:
        print(f"Error creating shared workplace info:")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create workplace information.")

@router.get(
    "/api/v1/workplaces",
    response_model=List[WorkplaceResponse],
    tags=["Workplaces (Shared Info)"]
)
async def list_all_workplaces(db_service: FirestoreService = Depends(get_firestore_service)):
    try:
        workplaces = await db_service.get_all_shared_workplaces()
        return workplaces
    except Exception as e:
        print(f"Error listing all workplaces:")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list workplaces.")


@router.put(
    "/api/v1/users/{line_user_id}/my-workplace-settings/{workplace_id}",
    response_model=MyWorkplaceSettingResponse,
    tags=["User's Workplace Settings"]
)
async def set_or_update_my_workplace_setting(
    line_user_id: str = FastApiPath(..., description="設定対象のユーザーのLINE ID"),
    workplace_id: str = FastApiPath(..., description="対象となるバイト先のID"),
    payload: MyWorkplaceSettingCreatePayload = Body(...),
    db_service: FirestoreService = Depends(get_firestore_service)
):
    # 認証: 操作者が対象のユーザー本人であるか確認するロジックが別途必要
    try:
        my_setting = await db_service.set_user_target_name_for_workplace(
            line_user_id=line_user_id,
            workplace_id=workplace_id,
            payload=payload
        )
        return my_setting
    except Exception as e:
        print(f"Error setting user's workplace setting for user {line_user_id}, workplace {workplace_id}:")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to set your workplace setting.")

@router.get(
    "/api/v1/users/{line_user_id}/my-workplace-settings/{workplace_id}",
    response_model=Optional[MyWorkplaceSettingResponse], # 設定がない場合もあるのでOptional
    tags=["User's Workplace Settings"]
)
async def get_my_workplace_setting(
    line_user_id: str = FastApiPath(..., description="設定対象のユーザーのLINE ID"),
    workplace_id: str = FastApiPath(..., description="対象となるバイト先のID"),
    db_service: FirestoreService = Depends(get_firestore_service)
):
    # 認証: 操作者が対象のユーザー本人であるか確認するロジックが別途必要
    try:
        my_setting = await db_service.get_user_target_name_for_workplace(
            line_user_id=line_user_id,
            workplace_id=workplace_id
        )
        if my_setting is None:
            # 404を返すか、空の成功レスポンスを返すかは設計による
            # raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
            return None # ここではNoneを返す（FastAPIが適切に処理）
        return my_setting
    except Exception as e:
        print(f"Error getting user's workplace setting for user {line_user_id}, workplace {workplace_id}:")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get your workplace setting.")