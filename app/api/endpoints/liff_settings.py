# app/api/endpoints/liff_settings.py
from fastapi import APIRouter, Request, Depends, HTTPException, status # Depends は現状使っていない
from fastapi.responses import HTMLResponse
from typing import List, Optional # Optional を追加 (将来的に使う可能性のため)
from datetime import datetime # ダミーレスポンス用に datetime をインポート

from app.models.setting import WorkplaceCreate, WorkplaceResponse
# Firestore関連の関数は、必要に応じて firestore_service.py からインポートする
# from app.services.firestore_service import (
#     create_workplace_setting, # 仮の関数名
#     get_workplaces_for_user,
#     # ... 他のバイト先設定関連の関数
# )

router = APIRouter()

# 既存のバイト先設定LIFFページ用エンドポイント
@router.get("/liff/settings", response_class=HTMLResponse, tags=["LIFF Pages"]) # タグ名を統一
async def get_liff_workplace_settings_page(request: Request): # 関数名をより具体的に変更
    """バイト先設定用LIFFページ (settings.html) を表示します。"""
    templates = request.app.state.templates
    if templates is None:
        print("ERROR: Template engine not configured in main.py for /liff/settings")
        raise HTTPException(status_code=500, detail="Server configuration error: Template engine not found.")
    try:
        # settings.html に渡すコンテキスト (例: 既存のバイト先情報など)
        # line_user_id = request.session.get('current_line_user_id') # セッションからLINE User IDを取得する例
        # existing_workplaces = []
        # if line_user_id:
        #     existing_workplaces = await get_workplaces_for_user(request.app.state.db, line_user_id)
        
        return templates.TemplateResponse("settings.html", {
            "request": request,
            # "existing_workplaces": existing_workplaces # 取得したバイト先情報を渡す
        })
    except Exception as e:
        print(f"ERROR: Failed to render LIFF template 'settings.html': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="LIFF page 'settings.html' could not be loaded.")


# ★★★ Googleカレンダー連携用LIFFアプリの新しいエンドポイント ★★★
@router.get("/liff/google-calendar-auth", response_class=HTMLResponse, tags=["LIFF Pages"]) # タグ名を統一
async def liff_google_calendar_auth_page(request: Request):
    """Googleカレンダー連携用LIFFアプリのページ (liff_google_calendar_auth.html) を表示します。"""
    templates = request.app.state.templates
    if templates is None:
        print("ERROR: Template engine not configured in main.py for /liff/google-calendar-auth")
        raise HTTPException(status_code=500, detail="Server configuration error: Template engine not found.")
    try:
        # liff_google_calendar_auth.html に渡すコンテキストがあればここで設定
        # 例: 既に連携済みかどうかの情報など
        # line_user_id = request.session.get('current_line_user_id')
        # calendar_status = await get_calendar_connection_status(request.app.state.db, line_user_id)
        return templates.TemplateResponse("liff_google_calendar_auth.html", {
            "request": request,
            # "calendar_connected": calendar_status # 連携状態を渡す
        })
    except Exception as e:
        print(f"ERROR: Failed to render LIFF template 'liff_google_calendar_auth.html': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="LIFF page 'liff_google_calendar_auth.html' could not be loaded.")


# 既存のバイト先作成APIエンドポイント
@router.post(
    "/api/v1/users/{line_user_id}/workplaces",
    response_model=WorkplaceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Workplace Settings API"]
)
async def create_new_workplace(
    request: Request, # ★ request を追加して app.state.db を使えるようにする
    line_user_id: str,
    workplace_data: WorkplaceCreate,
):
    """
    新しいバイト先の設定をLIFFから受け取り、Firestoreに保存する (現在ダミー処理)
    """
    # db_client = request.app.state.db # ★ Firestoreクライアントを取得
    # if not db_client:
    #     raise HTTPException(status_code=500, detail="Database connection not available.")

    try:
        # created_workplace_dict = await create_workplace_setting( # firestore_service の関数
        #     db_client=db_client,
        #     line_user_id=line_user_id,
        #     workplace_name=workplace_data.name,
        #     shift_rules=workplace_data.shift_rules.model_dump() if workplace_data.shift_rules else None
        # )
        # if not created_workplace_dict:
        #     raise HTTPException(status_code=500, detail="Failed to create workplace in Firestore.")
        # return WorkplaceResponse(**created_workplace_dict)

        print(f"INFO: Received request to create workplace for {line_user_id} with data: {workplace_data.model_dump_json()}")
        dummy_response_data = {
            "workplace_id": "dummy_wp_id_" + workplace_data.name.replace(" ", "_").lower(),
            "user_id": line_user_id,
            "name": workplace_data.name,
            "shift_rules": workplace_data.shift_rules.model_dump() if workplace_data.shift_rules else {},
            "created_at": datetime.now(timezone.utc), # UTCタイムゾーン情報を付加
            "updated_at": datetime.now(timezone.utc)  # UTCタイムゾーン情報を付加
        }
        return WorkplaceResponse(**dummy_response_data)

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"ERROR: Error creating workplace for {line_user_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while saving the workplace settings."
        )

# (将来のGET, PUT, DELETEエンドポイントも同様)