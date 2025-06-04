# app/services/firestore_service.py
from google.cloud import firestore
from typing import Optional, Dict, Any, List # List を追加
from datetime import datetime, timezone
# from app.models.user import User, GoogleAuthInfo
from app.core.config import settings
import traceback # traceback をインポート
import json # json をインポート (refresh_access_token で使用)

# Firestoreクライアントの初期化
try:
    # ↓↓↓ ここで database="caleshiftdb" を指定します ↓↓↓
    db = firestore.Client(project=settings.GCP_PROJECT_ID, database="caleshiftdb")
    print(f"INFO: Firestore client initialized successfully for database 'caleshiftdb' in project '{settings.GCP_PROJECT_ID}'.")
except Exception as e:
    print(f"ERROR: Failed to initialize Firestore client: {e}")
    traceback.print_exc()
    db = None

# (get_user_document_id_by_line_id 関数は、もしusersコレクションのドキュメントIDが
#  LINE User ID でない場合に user_id フィールドで検索するために使うなら残しておきます。
#  今回の save_google_credentials_for_user の実装では、ドキュメントID = LINE User ID を想定しています。)

async def save_google_credentials_for_user(line_user_id: str, credentials_json: str, scopes: List[str]):
    """
    指定されたLINEユーザーIDのユーザーのGoogle認証情報をFirestoreに保存/更新します。
    usersコレクションのドキュメントIDがLINE User IDそのものであることを想定。
    """
    if not db:
        print("ERROR: Firestore client not initialized. Cannot save credentials.")
        return False
    
    try:
        user_doc_ref = db.collection('users').document(line_user_id)
        user_doc = user_doc_ref.get() # 同期的にgetを実行

        auth_info_data = {
            'credentials_json': credentials_json,
            'scopes': scopes,
            'last_authenticated_at': datetime.now(timezone.utc)
        }

        if user_doc.exists:
            user_doc_ref.update({
                'google_auth_info': auth_info_data,
                'calendar_connected': True,
                'updated_at': datetime.now(timezone.utc)
            }) # 同期的にupdateを実行
            print(f"INFO: Successfully updated Google credentials for LINE user: {line_user_id}")
        else:
            print(f"WARNING: User document for LINE user ID {line_user_id} not found. Creating new one.")
            user_data_to_create = {
                # 'user_id': line_user_id, # ドキュメントIDがLINE User IDなので、このフィールドは必須ではない
                'name': 'New User', # 仮のデフォルト名
                'email': None,      # 仮
                'calendar_connected': True,
                'google_auth_info': auth_info_data,
                'created_at': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc)
            }
            user_doc_ref.set(user_data_to_create) # 同期的にsetを実行
            print(f"INFO: Successfully created user and saved Google credentials for LINE user: {line_user_id}")
            
        return True
    except Exception as e:
        print(f"ERROR: Failed to save Google credentials for LINE user {line_user_id}: {e}")
        traceback.print_exc()
        return False

async def get_google_credentials_for_user(line_user_id: str) -> Optional[Dict[str, Any]]:
    """
    指定されたLINEユーザーIDのユーザーのGoogle認証情報 (google_auth_infoマップ) をFirestoreから取得します。
    """
    if not db: return None
    try:
        user_doc_ref = db.collection('users').document(line_user_id)
        user_doc = user_doc_ref.get() # 同期的にgetを実行
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return user_data.get('google_auth_info')
        else:
            print(f"WARNING: No user document found for LINE user ID: {line_user_id}")
            return None
    except Exception as e:
        print(f"ERROR: Failed to get Google credentials for LINE user {line_user_id}: {e}")
        traceback.print_exc()
        return None

# (refresh_access_token 関数も同様に db を使うので、dbの初期化が成功していることが前提)
async def refresh_google_access_token_for_user(line_user_id: str) -> bool:
    """
    ユーザーのアクセストークンをリフレッシュし、更新された認証情報をFirestoreに保存します。
    :return: 成功した場合はTrue、失敗した場合はFalse
    """
    if not db: return False
    
    google_auth_info = await get_google_credentials_for_user(line_user_id)
    if not google_auth_info or not google_auth_info.get('credentials_json'):
        print(f"ERROR: No Google credentials found for user {line_user_id} to refresh.")
        return False

    credentials_json_str = google_auth_info['credentials_json']
    
    try:
        credentials = Credentials.from_authorized_user_info(json.loads(credentials_json_str), scopes=settings.GOOGLE_CALENDAR_SCOPES.split())
        if credentials and credentials.expired and credentials.refresh_token:
            print(f"INFO: Access token for {line_user_id} expired, attempting to refresh.")
            credentials.refresh(Request()) # google.auth.transport.requests.Request
            
            updated_credentials_json = credentials.to_json()
            updated_scopes = credentials.scopes if credentials.scopes else []
            
            # Firestoreに更新された認証情報を保存
            await save_google_credentials_for_user(line_user_id, updated_credentials_json, updated_scopes)
            print(f"INFO: Access token for {line_user_id} refreshed and saved successfully.")
            return True
        elif credentials and not credentials.expired:
            print(f"INFO: Access token for {line_user_id} is still valid.")
            return True # 更新不要だが成功とみなす
        else:
            print(f"WARNING: Could not refresh token for {line_user_id}. No refresh token or other issue.")
            return False
    except Exception as e:
        print(f"ERROR: Failed to refresh access token for user {line_user_id}: {e}")
        traceback.print_exc()
        return False