# app/services/firestore_service.py
from google.cloud.firestore_v1 import AsyncClient as FirestoreAsyncClient, Query
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime, timezone, timedelta
import traceback
from typing import List, Optional, Dict, Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.models.setting import (
    WorkplaceCreatePayload, WorkplaceResponse,
    MyWorkplaceSettingCreatePayload, MyWorkplaceSettingResponse,
    WorkplaceSharedSettings
)
# from app.utils.image_parser import ShiftInfo # このパスが正しいか確認

# --- ShiftInfoのダミークラス (image_parser.py が未実装の場合のエラー回避用) ---
try:
    from app.utils.image_parser import ShiftInfo
except ImportError:
    print("WARNING: Could not import ShiftInfo from app.utils.image_parser. Using dummy class.")
    class ShiftInfo:
        def __init__(self, date, start_time, end_time, name=None, role=None, memo=None):
            self.date = date
            self.start_time = start_time
            self.end_time = end_time
            self.name = name
            self.role = role
            self.memo = memo
# --- ダミークラスここまで ---

class FirestoreService:
    """
    Firestoreデータベースとのやり取りをカプセル化するサービスクラス。
    非同期クライアント (AsyncClient) を使用します。
    """
    def __init__(self):
        if not settings.GCP_PROJECT_ID:
            raise ValueError("GCP_PROJECT_ID environment variable is not set. Firestore client cannot be initialized.")
        
        try:
            self.db_async = FirestoreAsyncClient(project=settings.GCP_PROJECT_ID, database="caleshiftdb")
            print(f"INFO: Firestore AsyncClient initialized for project '{settings.GCP_PROJECT_ID}', database 'caleshiftdb'.")
        except Exception as e:
            print(f"CRITICAL: Failed to initialize Firestore AsyncClient.")
            traceback.print_exc()
            raise e
    
    async def close_client(self):
        if self.db_async:
            await self.db_async.close()

    # --- ユーザー関連 ---
    async def create_initial_user_document_on_follow(self, line_user_id: str, display_name: Optional[str] = None) -> bool:
        if not self.db_async: return False
        try:
            user_doc_ref = self.db_async.collection('users').document(line_user_id)
            doc_snapshot = await user_doc_ref.get()
            if doc_snapshot.exists: return True
            initial_user_data = {
                'user_id': line_user_id, 'name': display_name or f"User-{line_user_id[:8]}",
                'email': "", 'calendar_connected': False, 'google_auth_info': None,
                'created_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc)
            }
            await user_doc_ref.set(initial_user_data)
            return True
        except Exception:
            traceback.print_exc()
            return False

    async def save_google_credentials_for_user(self, line_user_id: str, credentials_json: str, scopes: List[str]) -> bool:
        if not self.db_async: return False
        try:
            user_doc_ref = self.db_async.collection('users').document(line_user_id)
            auth_info_data = {'credentials_json': credentials_json, 'scopes': scopes, 'last_authenticated_at': datetime.now(timezone.utc)}
            update_data = {'google_auth_info': auth_info_data, 'calendar_connected': True, 'updated_at': datetime.now(timezone.utc)}
            await user_doc_ref.set(update_data, merge=True)
            return True
        except Exception:
            traceback.print_exc()
            return False

    async def get_google_credentials_for_user(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        if not self.db_async: return None
        try:
            user_doc_ref = self.db_async.collection('users').document(line_user_id)
            doc_snapshot = await user_doc_ref.get()
            if doc_snapshot.exists:
                user_data = doc_snapshot.to_dict()
                return user_data.get('google_auth_info') if user_data else None
            return None
        except Exception:
            traceback.print_exc()
            return None

    # --- バイト先設定関連 ---
    async def create_shared_workplace_info(self, payload: WorkplaceCreatePayload) -> WorkplaceResponse:
        """新しい共有の勤務場所情報を作成します（重複チェック付き）。"""
        if not self.db_async: raise ConnectionError("Firestore client is not available.")
        
        workplaces_collection_ref = self.db_async.collection("workplaces")
        query = workplaces_collection_ref.where(filter=FieldFilter("workplace_name", "==", payload.workplace_name))
        existing_docs_stream = query.stream()
        existing_docs = [doc async for doc in existing_docs_stream] 
        
        if existing_docs:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"バイト先「{payload.workplace_name}」はすでに登録されています。")

        now = datetime.now(timezone.utc)
        new_workplace_doc_ref = workplaces_collection_ref.document()
        workplace_id = new_workplace_doc_ref.id
        data_to_save = {
            "workplace_id": workplace_id, "workplace_name": payload.workplace_name,
            "settings": payload.settings.dict(exclude_none=True),
            "created_by_user_id": payload.current_line_user_id,
            "created_at": now, "updated_at": now,
        }
        await new_workplace_doc_ref.set(data_to_save)
        return WorkplaceResponse(**data_to_save)

    async def get_all_shared_workplaces(self) -> List[WorkplaceResponse]:
        """登録されている全ての共有勤務場所情報をリストで取得します。不正なデータはスキップします。"""
        if not self.db_async: return []
        
        workplaces_collection_ref = self.db_async.collection("workplaces")
        workplaces_list: List[WorkplaceResponse] = []
        
        try:
            async for doc_snapshot in workplaces_collection_ref.stream():
                if doc_snapshot.exists:
                    data = doc_snapshot.to_dict()
                    try:
                        if data and "settings" in data and isinstance(data.get("settings"), dict):
                            workplaces_list.append(WorkplaceResponse(**data))
                    except Exception as p_error:
                        print(f"SKIPPING document (Pydantic validation error): {doc_snapshot.id}. Error: {p_error}")
            return workplaces_list
        except Exception as e:
            print("--- CRITICAL ERROR in get_all_shared_workplaces ---")
            traceback.print_exc()
            raise

    async def set_user_target_name_for_workplace(self, line_user_id: str, workplace_id: str, payload: MyWorkplaceSettingCreatePayload) -> MyWorkplaceSettingResponse:
        """ユーザー個人の勤務場所設定（シフト表での名前など）を作成または更新します。"""
        if not self.db_async: raise ConnectionError("Firestore client is not available.")
        now = datetime.now(timezone.utc)
        setting_doc_ref = self.db_async.collection("users").document(line_user_id).collection("my_workplace_settings").document(workplace_id)
        data_to_save = {
            "workplace_id": workplace_id, "line_user_id": line_user_id,
            "target_name_in_shift": payload.target_name_in_shift, "updated_at": now,
        }
        doc_snapshot = await setting_doc_ref.get()
        if not doc_snapshot.exists:
            data_to_save["linked_at"] = now
        else:
            existing_data = doc_snapshot.to_dict()
            data_to_save["linked_at"] = existing_data.get("linked_at", now) if existing_data else now
        await setting_doc_ref.set(data_to_save, merge=True)
        return MyWorkplaceSettingResponse(**data_to_save)

    async def get_user_target_name_for_workplace(self, line_user_id: str, workplace_id: str) -> Optional[MyWorkplaceSettingResponse]:
        if not self.db_async: return None
        setting_doc_ref = self.db_async.collection("users").document(line_user_id).collection("my_workplace_settings").document(workplace_id)
        doc_snapshot = await setting_doc_ref.get()
        if doc_snapshot.exists:
            return MyWorkplaceSettingResponse(**doc_snapshot.to_dict())
        return None

    # --- シフト解析・履歴関連 ---
    async def get_primary_workplace_id_for_user(self, line_user_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            settings_collection_ref = self.db_async.collection('users').document(line_user_id).collection('my_workplace_settings')
            docs_query = settings_collection_ref.limit(1)
            async for doc in docs_query.stream():
                return doc.id
            return None
        except Exception:
            traceback.print_exc()
            return None

    async def get_workplace_shift_rules(self, workplace_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id)
            doc_snapshot = await doc_ref.get()
            if doc_snapshot.exists:
                data = doc_snapshot.to_dict()
                settings_data = data.get('settings', {})
                date_rules = settings_data.get('date_rules', {})
                time_rules = settings_data.get('time_rules', {})
                date_desc = date_rules.get('custom_description', "")
                time_desc = time_rules.get('custom_description', "")
                parts = [f"日付に関するルール: {date_desc}" if date_desc else "", f"時刻に関するルール: {time_desc}" if time_desc else ""]
                final_rules = "\n".join(filter(None, parts))
                return final_rules if final_rules else "一般的なシフト表の形式で、日付、氏名、開始時間、終了時間を抽出してください。"
            return "一般的なシフト表の形式で、日付、氏名、開始時間、終了時間を抽出してください。"
        except Exception:
            traceback.print_exc()
            return None

    async def log_shift_history(self, workplace_id: str, line_user_id: str, shift_info: ShiftInfo, calendar_event_id: str, status: str = "created") -> bool:
        if not self.db_async or not workplace_id: return False
        try:
            history_collection_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history')
            history_doc_ref = history_collection_ref.document()
            start_dt = datetime.combine(shift_info.date, shift_info.start_time).replace(tzinfo=timezone.utc)
            end_dt = datetime.combine(shift_info.date, shift_info.end_time).replace(tzinfo=timezone.utc)
            if end_dt <= start_dt: end_dt += timedelta(days=1)
            history_data = {
                'user_id': line_user_id, 'date': shift_info.date.strftime("%Y-%m-%d"),
                'start_time': start_dt, 'end_time': end_dt, 'calendar_event_id': calendar_event_id,
                'status': status, 'created_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc),
                'name_in_shift': shift_info.name, 'role': shift_info.role, 'memo': shift_info.memo,
            }
            history_data = {k: v for k, v in history_data.items() if v is not None}
            await history_doc_ref.set(history_data)
            return True
        except Exception:
            traceback.print_exc()
            return False

    async def get_shift_history_for_user_in_workplace(self, workplace_id: str, line_user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.db_async: return []
        try:
            history_collection_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history')
            query = history_collection_ref.where(filter=FieldFilter('user_id', '==', line_user_id)).order_by('start_time', direction=Query.DESCENDING).limit(limit)
            history_list = []
            async for doc in query.stream():
                history_data = doc.to_dict()
                if history_data:
                    history_data['history_id'] = doc.id
                    history_list.append(history_data)
            return history_list
        except Exception:
            traceback.print_exc()
            return []