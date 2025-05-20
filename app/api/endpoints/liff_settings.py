from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse # HTMLResponse は TemplateResponse の基底クラスの一つ
# from fastapi.templating import Jinja2Templates # ★不要になる

from app.models.setting import WorkplaceCreate, WorkplaceResponse, WorkplaceSettingsPayload # WorkplaceSettingsPayloadもインポート (将来のPUT用)
from app.services.firestore_service import FirestoreService
# from pathlib import Path # ★不要になる

# BASE_DIR = Path(__file__).resolve().parent.parent.parent # ★不要になる
# templates = Jinja2Templates(directory=BASE_DIR / "templates") # ★不要になる

router = APIRouter()

# FirestoreServiceのインスタンスを依存性注入で取得する
# (このシンプルなDIは、リクエストごとに新しいインスタンスを生成します)
def get_firestore_service():
    return FirestoreService()


@router.get("/liff/settings", response_class=HTMLResponse, tags=["LIFF"])
async def get_liff_settings_page(request: Request): # requestオブジェクトを受け取る
    """LIFF設定画面 (settings.html) を表示する"""
    templates = request.app.state.templates # ★main.pyのapp.stateからtemplatesを取得
    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not configured.")
    return templates.TemplateResponse("settings.html", {"request": request})


@router.post(
    "/api/v1/users/{line_user_id}/workplaces",
    response_model=WorkplaceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Workplace Settings API"] # タグ名を少し変更 (APIであることを明示)
)
async def create_new_workplace(
    line_user_id: str,
    workplace_data: WorkplaceCreate,
    db_service: FirestoreService = Depends(get_firestore_service)
):
    """
    新しいバイト先の設定をLIFFから受け取り、Firestoreに保存する
    """
    try:
        # FirestoreServiceのcreate_workplaceメソッドが非同期ならawaitする
        created_workplace = await db_service.create_workplace(
            line_user_id=line_user_id,
            workplace_data=workplace_data
        )
        # 同期メソッドの場合は await は不要 (FirestoreServiceの実装による)
        # created_workplace = db_service.create_workplace(
        #     line_user_id=line_user_id,
        #     workplace_data=workplace_data
        # )
        return created_workplace
    except Exception as e: # ここはより具体的な例外をキャッチするのが望ましい
        # 例: from google.cloud.exceptions import GoogleCloudError
        # except GoogleCloudError as e:
        #     raise HTTPException(status_code=503, detail=f"Firestore error: {str(e)}")
        print(f"Error creating workplace: {e}") # ログ出力
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while saving the settings. Please try again later."
        )

# (将来的に必要になるかもしれないエンドポイントのコメントアウトはそのまま)
# @router.get("/api/v1/users/{line_user_id}/workplaces", ...)
# ...