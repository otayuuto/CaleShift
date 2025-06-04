# app/api/endpoints/liff_settings.py
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from typing import List # List をインポート (将来的に使う可能性のため)

from app.models.setting import WorkplaceCreate, WorkplaceResponse # WorkplaceSettingsPayload はまだ使わない
# ↓↓↓ FirestoreService クラスではなく、必要な関数をインポートするように変更 ↓↓↓
#from app.services.firestore_service import (
    #create_workplace_for_user, # ← この名前の関数を firestore_service.py に作成する必要がある
    #get_workplaces_for_user,   # ← 同上 (GETリクエスト用)
    #update_workplace_for_user, # ← 同上 (PUTリクエスト用)
    #delete_workplace_for_user  # ← 同上 (DELETEリクエスト用)
    # 現状、google認証関連の関数しかないので、バイト先作成用の関数を firestore_service.py に追加する必要がある
    # 例として、バイト先作成用の関数名を仮に create_workplace_setting とします。
    # この関数は firestore_service.py に async def create_workplace_setting(...) として実装されている必要があります。
#)
# Firestoreにバイト先情報を保存する新しい関数を定義する必要があるため、一旦コメントアウト
# from app.services.firestore_service import create_workplace_setting (仮の関数名)

router = APIRouter()

# FirestoreServiceのインスタンスを依存性注入で取得する代わりに、
# エンドポイント内で直接 firestore_service.py の関数を呼び出す。
# def get_firestore_service(): # ← この関数は不要になる
#     return FirestoreService()


@router.get("/liff/settings", response_class=HTMLResponse, tags=["LIFF Settings"]) # タグ名を変更
async def get_liff_settings_page(request: Request):
    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not configured.")
    # settings.html に渡すコンテキスト (例: 既存のバイト先情報など) があればここで取得・設定
    # context = {"request": request, "existing_workplaces": await get_workplaces_for_user(line_user_id)}
    # line_user_id をどう取得するかが課題 (LIFFのIDトークンからなど)
    return templates.TemplateResponse("settings.html", {"request": request})


@router.post(
    "/api/v1/users/{line_user_id}/workplaces", # パスは既存のまま
    response_model=WorkplaceResponse, # レスポンスモデルも既存のまま
    status_code=status.HTTP_201_CREATED,
    tags=["Workplace Settings API"]
)
async def create_new_workplace(
    line_user_id: str, # URLパスからLINE User IDを取得
    workplace_data: WorkplaceCreate, # リクエストボディからバイト先データ
    # db_service: FirestoreService = Depends(get_firestore_service) # ← 依存性注入は使わない
):
    """
    新しいバイト先の設定をLIFFから受け取り、Firestoreに保存する
    """
    try:
        # FirestoreServiceのメソッド呼び出しではなく、直接インポートした関数を呼び出す
        # (この create_workplace_setting 関数は firestore_service.py に新しく実装する必要がある)
        #
        # created_workplace_dict = await create_workplace_setting(
        #     line_user_id=line_user_id,
        #     workplace_name=workplace_data.name,
        #     # workplace_data に含まれる他の情報 (shift_rulesなど) も渡す
        #     shift_rules=workplace_data.shift_rules.model_dump() if workplace_data.shift_rules else None
        # )
        #
        # if not created_workplace_dict:
        #     raise HTTPException(status_code=500, detail="Failed to create workplace in Firestore.")
        #
        # # WorkplaceResponse モデルに変換して返す
        # return WorkplaceResponse(**created_workplace_dict)

        # 現状 create_workplace_setting が未実装なので、ダミーレスポンスを返すか、
        # または、このエンドポイントを一旦コメントアウトする
        print(f"INFO: Received request to create workplace for {line_user_id} with data: {workplace_data.model_dump()}")
        # ダミーのレスポンス (実際にはFirestoreに保存してその結果を返す)
        dummy_response_data = {
            "workplace_id": "dummy_wp_id_" + workplace_data.name.replace(" ", "_").lower(),
            "user_id": line_user_id,
            "name": workplace_data.name,
            "shift_rules": workplace_data.shift_rules.model_dump() if workplace_data.shift_rules else {},
            "created_at": datetime.now(), # モックデータなので注意
            "updated_at": datetime.now()
        }
        return WorkplaceResponse(**dummy_response_data)

    except HTTPException as http_exc: # FastAPIのHTTPExceptionはそのまま再送出
        raise http_exc
    except Exception as e:
        print(f"ERROR: Error creating workplace for {line_user_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while saving the workplace settings."
        )

# (将来のGET, PUT, DELETEエンドポイントも同様に、
#  firestore_service.py に対応する関数を作成し、それを直接呼び出す形になる)