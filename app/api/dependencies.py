from fastapi import Request, HTTPException, status
from app.services.firestore_service import FirestoreService
def get_db_service() -> FirestoreService:
    return FirestoreService()
    
    if not hasattr(request.app.state, 'db_service') or not request.app.state.db_service:
        # main.pyのstartupでエラーが発生した場合、この依存関係は解決できない
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not available. Check application startup logs."
        )
    return request.app.state.db_service