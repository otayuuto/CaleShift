from fastapi import Request
from typing import Optional
from app.services.firestore_service import FirestoreService

def get_db_service(request: Request) -> Optional[FirestoreService]:
    if hasattr(request.app.state, 'db_service'):
        return request.app.state.db_service
    return None