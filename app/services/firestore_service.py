# app/services/firestore_service.py
from google.cloud import firestore
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from app.core.config import settings
from app.models.user import GoogleAuthInfo # Pydanticモデルを型ヒントやデータ変換に利用
from fastapi.concurrency import run_in_threadpool # 非同期処理のため

try:
    db = firestore.Client(project=settings.GCP_PROJECT_ID)
    print("INFO: Firestore client initialized successfully.")
except Exception as e:
    print(f"ERROR: Failed to initialize Firestore client: {e}")
    # アプリケーション起動時にFirestoreに接続できない場合は致命的エラーとして扱うことも検討
    db = None # グローバル変数としての db が None の場合、各関数でチェックする

async def _get_user_document_ref_by_line_id(line_user_id: str) -> Optional[firestore.DocumentReference]:
    """
    (同期的なFirestore呼び出しをラップ)
    LINE User ID (user_idフィールド) をもとに users コレクションのドキュメント参照を取得します。
    見つからない場合は None を返します。
    """
    if not db: return None
    
    def db_operation():
        users_ref = db.collection('users')
        query = users_ref.where('user_id', '==', line_user_id).limit(1)
        docs = list(query.stream()) # 同期的な呼び出し
        if docs:
            return docs[0].reference
        return None
    
    return await run_in_threadpool(db_operation)


async def save_google_credentials_for_user(
    line_user_id: str, 
    credentials_json: str, 
    scopes: List[str]
) -> bool:
    """
    指定されたLINEユーザーIDのユーザーのGoogle認証情報をFirestoreに保存/更新します。
    user_idフィールドでユーザーを検索し、見つかったドキュメントを更新するか、
    見つからなければ新規作成します (ドキュメントIDはFirestoreが自動生成)。
    """
    if not db:
        print("ERROR: Firestore client not initialized. Cannot save credentials.")
        return False
    
    try:
        user_doc_ref = await _get_user_document_ref_by_line_id(line_user_id)
        
        google_auth_data = GoogleAuthInfo( # Pydanticモデルでデータを整形
            credentials_json=credentials_json,
            scopes=scopes,
            last_authenticated_at=datetime.now(timezone.utc)
        ).model_dump(mode='json') # Firestoreに保存する辞書形式に変換

        current_time = datetime.now(timezone.utc) # FirestoreのSERVER_TIMESTAMPも使用可

        def db_operation_update(doc_ref, data_to_update):
            doc_ref.update(data_to_update) # 同期的な呼び出し

        def db_operation_create(data_to_create):
            # 新しいドキュメント参照 (ID自動生成) を作成してセット
            new_doc_ref = db.collection('users').document() 
            new_doc_ref.set(data_to_create) # 同期的な呼び出し
            return new_doc_ref.id

        if user_doc_ref:
            # 既存ドキュメントを更新
            update_data = {
                'google_auth_info': google_auth_data,
                'calendar_connected': True,
                'updated_at': current_time # または firestore.SERVER_TIMESTAMP
            }
            await run_in_threadpool(db_operation_update, user_doc_ref, update_data)
            print(f"INFO: Successfully updated Google credentials for user with line_user_id: {line_user_id} (doc_id: {user_doc_ref.id})")
        else:
            # ユーザーが存在しない場合、新規作成
            print(f"WARNING: User document for LINE User ID {line_user_id} not found. Creating new one.")
            user_data_to_create = {
                'user_id': line_user_id, # LINE User IDをフィールドに保存
                'calendar_connected': True,
                'google_auth_info': google_auth_data,
                'created_at': current_time,
                'updated_at': current_time,
                'name': None, # 必要に応じてデフォルト値や取得した値を設定
                # Userモデルで定義した他のフィールドの初期値も設定
            }
            new_doc_id = await run_in_threadpool(db_operation_create, user_data_to_create)
            print(f"INFO: Successfully created new user and saved Google credentials for line_user_id: {line_user_id} (new doc_id: {new_doc_id})")
            
        return True
    except Exception as e:
        print(f"ERROR: Failed to save Google credentials for LINE user {line_user_id}: {e}")
        import traceback
        traceback.print_exc()
        return False

async def get_google_credentials_from_user_doc(line_user_id: str) -> Optional[GoogleAuthInfo]:
    """
    (同期的なFirestore呼び出しをラップ)
    指定されたLINEユーザーIDのユーザーのGoogleAuthInfoをFirestoreから取得します。
    """
    if not db: return None

    user_doc_ref = await _get_user_document_ref_by_line_id(line_user_id)

    def db_operation_get(doc_ref):
        if doc_ref:
            user_doc = doc_ref.get() # 同期的な呼び出し
            if user_doc.exists:
                user_data = user_doc.to_dict()
                if user_data and 'google_auth_info' in user_data:
                    try:
                        # Firestoreから取得したデータをPydanticモデルに変換
                        return GoogleAuthInfo(**user_data['google_auth_info'])
                    except Exception as e_parse:
                        print(f"ERROR: Failed to parse google_auth_info for {line_user_id}: {e_parse}")
                        return None
        return None

    if user_doc_ref:
        auth_info = await run_in_threadpool(db_operation_get, user_doc_ref)
        if auth_info:
            return auth_info
    
    print(f"WARNING: No user document or google_auth_info found for LINE user ID: {line_user_id}")
    return None