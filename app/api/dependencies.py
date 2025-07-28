# app/api/dependencies.py
from fastapi import Request, HTTPException, status
from typing import Optional
from app.services.firestore_service import FirestoreService

def get_db_service(request: Request) -> FirestoreService:
    # main.py の startup イベントで格納されたインスタンスを返す
    if hasattr(request.app.state, 'db_service') and request.app.state.db_service:
        return request.app.state.db_service
    # 起動時にDB初期化に失敗した場合、ここでエラーを発生させる
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database service is not available."
    )