# app/services/firestore_service.py
from google.cloud import firestore
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import traceback
import json
from fastapi.concurrency import run_in_threadpool # ★ run_in_threadpool をインポート

async def save_google_credentials_for_user(
    db_client: firestore.Client,
    line_user_id: str,
    credentials_json: str,
    scopes: List[str]
) -> bool:
    if not db_client:
        print("ERROR_FIRESTORE_SERVICE: Firestore client (db_client) is not provided.")
        return False
    
    try:
        user_doc_ref = db_client.collection('users').document(line_user_id)
        
        # user_doc_ref.get() は同期的メソッドなので、run_in_threadpool で実行
        user_doc = await run_in_threadpool(user_doc_ref.get) # ★ 変更点

        if not user_doc.exists:
            print(f"ERROR_FIRESTORE_SERVICE: User document for LINE user ID '{line_user_id}' not found.")
            return False

        auth_info_data = {
            'credentials_json': credentials_json,
            'scopes': scopes,
            'last_authenticated_at': datetime.now(timezone.utc)
        }
        update_data = {
            'google_auth_info': auth_info_data,
            'calendar_connected': True,
            'updated_at': datetime.now(timezone.utc)
        }
        
        # user_doc_ref.update() も同期的メソッドなので、run_in_threadpool で実行
        await run_in_threadpool(user_doc_ref.update, update_data) # ★ 変更点
        print(f"INFO_FIRESTORE_SERVICE: Successfully updated Google credentials for LINE user: {line_user_id}")
        return True
        
    except Exception as e:
        print(f"ERROR_FIRESTORE_SERVICE: Failed to save Google credentials for LINE user {line_user_id}: {e}")
        traceback.print_exc()
        return False

async def get_google_credentials_for_user(
    db_client: firestore.Client,
    line_user_id: str
) -> Optional[Dict[str, Any]]:
    if not db_client:
        print("ERROR_FIRESTORE_SERVICE: Firestore client (db_client) is not provided.")
        return None
    try:
        user_doc_ref = db_client.collection('users').document(line_user_id)
        
        user_doc = await run_in_threadpool(user_doc_ref.get) # ★ 変更点

        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data:
                auth_info = user_data.get('google_auth_info')
                if auth_info:
                    return auth_info
                else:
                    print(f"WARNING_FIRESTORE_SERVICE: 'google_auth_info' not found for {line_user_id}")
                    return None
            else:
                print(f"WARNING_FIRESTORE_SERVICE: User document data is None for {line_user_id}")
                return None
        else:
            print(f"WARNING_FIRESTORE_SERVICE: No user document found for {line_user_id}")
            return None
    except Exception as e:
        print(f"ERROR_FIRESTORE_SERVICE: Failed to get Google credentials for {line_user_id}: {e}")
        traceback.print_exc()
        return None

async def create_initial_user_document_on_follow(
    db_client: firestore.Client,
    line_user_id: str,
    display_name: Optional[str] = None
) -> bool:
    if not db_client:
        print("ERROR_FIRESTORE_SERVICE: Firestore client (db_client) is not provided.")
        return False
    try:
        user_doc_ref = db_client.collection('users').document(line_user_id)
        
        user_doc = await run_in_threadpool(user_doc_ref.get) # ★ 変更点

        if user_doc.exists:
            print(f"INFO_FIRESTORE_SERVICE: User document for {line_user_id} already exists.")
            # 必要なら updated_at を更新
            # await run_in_threadpool(user_doc_ref.update, {'updated_at': datetime.now(timezone.utc)})
            return True

        initial_user_data = {
            'user_id': line_user_id,
            'name': display_name or f"User-{line_user_id[:8]}",
            'email': "",
            'calendar_connected': False,
            'google_auth_info': None,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        await run_in_threadpool(user_doc_ref.set, initial_user_data) # ★ 変更点
        print(f"INFO_FIRESTORE_SERVICE: Successfully created initial user document for {line_user_id}")
        return True
    except Exception as e:
        print(f"ERROR_FIRESTORE_SERVICE: Failed to create initial user document for {line_user_id}: {e}")
        traceback.print_exc()
        return False