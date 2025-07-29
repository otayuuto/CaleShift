# app/services/firestore_service.py (統合・修正後)

from google.cloud.firestore_v1 import AsyncClient as FirestoreAsyncClient, Query
from google.cloud.firestore_v1.base_query import FieldFilter # 新しいクエリ構文
from google.oauth2 import service_account
from datetime import datetime, timezone, timedelta
import traceback
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, status
import json
import os

from app.core.config import settings
from app.models.setting import (
    WorkplaceCreatePayload, WorkplaceResponse,
    MyWorkplaceSettingCreatePayload, MyWorkplaceSettingResponse,
    # WorkplaceSharedSettings # get_all_shared_workplaces の中で直接パースするので不要な場合も
)
# --- ShiftInfoのインポート (存在しない場合のエラー回避策) ---
try:
    from app.utils.image_parser import ShiftInfo
except ImportError:
    print("WARNING_FS_SERVICE: Could not import ShiftInfo from app.utils.image_parser. Using a dummy class.")
    class ShiftInfo:
        def __init__(self, date, start_time, end_time, name=None, role=None, memo=None, is_holiday=False):
            self.date = date
            self.start_time = start_time
            self.end_time = end_time
            self.name = name
            self.role = role
            self.memo = memo
            self.is_holiday = is_holiday

class FirestoreService:
    """
    Firestoreデータベースとのやり取りをカプセル化するサービスクラス。
    非同期クライアント (AsyncClient) を使用します。
    """
    def __init__(self):
        if not settings.GCP_PROJECT_ID:
            print("CRITICAL_FS_SERVICE: GCP_PROJECT_ID is not set.")
            self.db_async: Optional[FirestoreAsyncClient] = None
            return

        database_id_to_use = settings.DATABASE_ID or "(default)"
        credentials = None
        creds_env_var = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        
        try:
            if creds_env_var:
                if os.path.exists(creds_env_var):
                    credentials = service_account.Credentials.from_service_account_file(creds_env_var)
                else:
                    creds_info = json.loads(creds_env_var)
                    credentials = service_account.Credentials.from_service_account_info(creds_info)
            self.db_async = FirestoreAsyncClient(
                project=settings.GCP_PROJECT_ID, database=database_id_to_use, credentials=credentials
            )
            print(f"INFO_FS_SERVICE: AsyncClient initialized for project '{settings.GCP_PROJECT_ID}', database '{database_id_to_use}'.")
        except Exception as e:
            print(f"CRITICAL_FS_SERVICE: Failed to initialize Firestore AsyncClient: {e}")
            traceback.print_exc()
            self.db_async = None
    
    async def close_client(self):
        if self.db_async:
            await self.db_async.close()

    # --- ユーザー関連 ---
    async def create_initial_user_document_on_follow(self, line_user_id: str, display_name: Optional[str] = None) -> bool:
        if not self.db_async: return False
        try:
            user_doc_ref = self.db_async.collection('users').document(line_user_id)
            doc_snapshot = await user_doc_ref.get()
            if doc_snapshot.exists:
                print(f"INFO_FS_SERVICE: User doc for {line_user_id} already exists.")
                return True
            initial_user_data = {
                'user_id': line_user_id, 'name': display_name or f"User-{line_user_id[:8]}",
                'email': "", 'calendar_connected': False, 'google_auth_info': None,
                'created_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc)
            }
            await user_doc_ref.set(initial_user_data)
            print(f"INFO_FS_SERVICE: Created initial user doc for {line_user_id}.")
            return True
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to create initial user doc for {line_user_id}: {e}")
            traceback.print_exc()
            return False

    async def save_google_credentials_for_user(self, line_user_id: str, credentials_json: str, scopes: List[str]) -> bool:
        if not self.db_async: return False
        try:
            user_doc_ref = self.db_async.collection('users').document(line_user_id)
            auth_info = {'credentials_json': credentials_json, 'scopes': scopes, 'last_authenticated_at': datetime.now(timezone.utc)}
            update_data = {'google_auth_info': auth_info, 'calendar_connected': True, 'updated_at': datetime.now(timezone.utc)}
            await user_doc_ref.set(update_data, merge=True)
            print(f"INFO_FS_SERVICE: Updated Google credentials for {line_user_id}")
            return True
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to save Google credentials for {line_user_id}: {e}")
            traceback.print_exc()
            return False

    async def get_google_credentials_for_user(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('users').document(line_user_id)
            doc = await doc_ref.get()
            if doc.exists:
                user_data = doc.to_dict()
                return user_data.get('google_auth_info') if user_data else None
            return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get Google credentials for {line_user_id}: {e}")
            traceback.print_exc()
            return None

    # --- バイト先設定関連 ---
    async def create_shared_workplace_info(self, payload: WorkplaceCreatePayload) -> WorkplaceResponse:
        if not self.db_async: raise ConnectionError("Firestore client not available.")
        
        workplaces_ref = self.db_async.collection("workplaces")
        query = workplaces_ref.where(filter=FieldFilter("workplace_name", "==", payload.workplace_name))
        existing_docs = [doc async for doc in query.stream()]
        if existing_docs:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"バイト先「{payload.workplace_name}」はすでに登録されています。")

        now = datetime.now(timezone.utc)
        new_doc_ref = workplaces_ref.document()
        workplace_id = new_doc_ref.id
        data_to_save = {
            "workplace_id": workplace_id, "workplace_name": payload.workplace_name,
            "settings": payload.settings.dict(exclude_none=True),
            "created_by_user_id": payload.current_line_user_id,
            "created_at": now, "updated_at": now,
        }
        await new_doc_ref.set(data_to_save)
        return WorkplaceResponse(**data_to_save)
    
    async def get_all_shared_workplaces(self) -> List[WorkplaceResponse]:
        if not self.db_async: return []
        workplaces_ref = self.db_async.collection("workplaces")
        workplaces_list: List[WorkplaceResponse] = []
        async for doc in workplaces_ref.stream():
            if doc.exists:
                try:
                    workplaces_list.append(WorkplaceResponse(**doc.to_dict()))
                except Exception as e:
                    print(f"SKIPPING workplace doc {doc.id} due to validation error: {e}")
        return workplaces_list

    async def set_user_target_name_for_workplace(self, line_user_id: str, workplace_id: str, payload: MyWorkplaceSettingCreatePayload) -> MyWorkplaceSettingResponse:
        if not self.db_async: raise ConnectionError("Firestore client not available.")
        now = datetime.now(timezone.utc)
        doc_ref = self.db_async.collection("users").document(line_user_id).collection("my_workplace_settings").document(workplace_id)
        data_to_save = {
            "workplace_id": workplace_id, "line_user_id": line_user_id,
            "target_name_in_shift": payload.target_name_in_shift, "updated_at": now,
        }
        doc = await doc_ref.get()
        if not doc.exists:
            data_to_save["linked_at"] = now
        else:
            existing_data = doc.to_dict()
            data_to_save["linked_at"] = existing_data.get("linked_at", now) if existing_data else now
        await doc_ref.set(data_to_save, merge=True)
        return MyWorkplaceSettingResponse(**data_to_save)

    # --- シフト解析・履歴関連 ---
    async def get_primary_workplace_id_for_user(self, line_user_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            settings_ref = self.db_async.collection('users').document(line_user_id).collection('my_workplace_settings')
            query = settings_ref.limit(1)
            async for doc in query.stream():
                return doc.id
            return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get primary wp_id for {line_user_id}: {e}")
            traceback.print_exc()
            return None

    async def get_workplace_shift_rules(self, workplace_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id)
            doc = await doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                if data and (settings_data := data.get('settings', {})):
                    date_rules = settings_data.get('date_rules', {})
                    time_rules = settings_data.get('time_rules', {})
                    date_desc = date_rules.get('custom_description', "")
                    time_desc = time_rules.get('custom_description', "")
                    parts = [f"日付に関するルール: {date_desc}" if date_desc else "", f"時刻に関するルール: {time_desc}" if time_desc else ""]
                    final_rules = "\n".join(filter(None, parts))
                    return final_rules if final_rules else None
            return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get shift rules for wp {workplace_id}: {e}")
            traceback.print_exc()
            return None
            
    async def save_pending_shifts(self, line_user_id: str, workplace_id: str, parsed_shifts: List[Dict[str, Any]]) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('pending_shifts').document()
            pending_data = {
                "line_user_id": line_user_id, "workplace_id": workplace_id, "parsed_shifts": parsed_shifts,
                "status": "pending", "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=24)
            }
            await doc_ref.set(pending_data)
            return doc_ref.id
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to save pending shifts for {line_user_id}: {e}")
            traceback.print_exc()
            return None

    async def get_pending_shifts(self, pending_id: str) -> Optional[Dict[str, Any]]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('pending_shifts').document(pending_id)
            doc = await doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get pending shifts for ID {pending_id}: {e}")
            traceback.print_exc()
            return None
        
    async def log_shift_history(self, workplace_id: str, line_user_id: str, shift_info: ShiftInfo, calendar_event_id: str, status: str = "created") -> bool:
        # このメソッドはHEADブランチからそのまま移行
        if not self.db_async: return False
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
            await history_doc_ref.set({k: v for k, v in history_data.items() if v is not None})
            return True
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to log shift history for {line_user_id}, wp {workplace_id}: {e}")
            traceback.print_exc()
            return False
    
    async def get_shift_history_for_user_in_workplace(self, workplace_id: str, line_user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        # このメソッドもHEADブランチからそのまま移行
        if not self.db_async: return []
        try:
            history_collection_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history')
            query = history_collection_ref.where(filter=FieldFilter('user_id', '==', line_user_id)).order_by('start_time', direction=Query.DESCENDING).limit(limit)
            history_list = []
            async for doc in query.stream():
                history_data = doc.to_dict()
                if history_data:
                    history_data['history_id'] = doc.id
                    history_data['workplace_id'] = workplace_id
                    history_list.append(history_data)
            return history_list
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get shift history for {line_user_id}, wp {workplace_id}: {e}")
            traceback.print_exc()
            return []

    async def get_shift_history_item(self, workplace_id: str, history_id: str) -> Optional[Dict[str, Any]]:
        """
        指定されたIDの単一のシフト履歴ドキュメントを取得します。
        """
        if not self.db_async:
            print("ERROR_FS_SERVICE: Firestore client not available.")
            return None
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history').document(history_id)
            doc = await doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            else:
                print(f"WARNING_FS_SERVICE: Shift history document not found: {workplace_id}/{history_id}")
                return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get shift history item {workplace_id}/{history_id}: {e}")
            traceback.print_exc()
            return None

    # (update_shift_history, delete_shift_history メソッドも同様に追加・修正)
    async def update_shift_history(self, workplace_id: str, history_id: str, update_data: Dict[str, Any]) -> bool:
        if not self.db_async: return False
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history').document(history_id)
            update_data_with_timestamp = update_data.copy()
            update_data_with_timestamp['updated_at'] = datetime.now(timezone.utc)
            await doc_ref.update(update_data_with_timestamp)
            print(f"INFO_FS_SERVICE: Updated shift history doc: {workplace_id}/{history_id}")
            return True
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to update shift history doc {workplace_id}/{history_id}: {e}")
            traceback.print_exc()
            return False

    async def delete_shift_history(self, workplace_id: str, history_id: str) -> bool:
        if not self.db_async: return False
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history').document(history_id)
            await doc_ref.delete()
            print(f"INFO_FS_SERVICE: Deleted shift history doc: {workplace_id}/{history_id}")
            return True
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to delete shift history doc {workplace_id}/{history_id}: {e}")
            traceback.print_exc()
            return False

    async def get_workplace_shift_rules(self, workplace_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc = await self.db_async.collection('workplaces').document(workplace_id).get()
            if doc.exists and doc.to_dict():
                settings_data = doc.to_dict().get('settings', {})
                date_desc = settings_data.get('date_rules', {}).get('custom_description', "")
                time_desc = settings_data.get('time_rules', {}).get('custom_description', "")
                parts = [f"日付に関するルール: {date_desc}" if date_desc else "", f"時刻に関するルール: {time_desc}" if time_desc else ""]
                final_rules = "\n".join(filter(None, parts))
                return final_rules or "一般的なシフト表の形式で、日付、氏名、開始時間、終了時間を抽出してください。"
            return "一般的なシフト表の形式で、日付、氏名、開始時間、終了時間を抽出してください。"
        except Exception: traceback.print_exc(); return None

    async def get_target_name_for_shift_extraction(self, line_user_id: str, workplace_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc = await self.db_async.collection("users").document(line_user_id).collection("my_workplace_settings").document(workplace_id).get()
            if doc.exists and doc.to_dict():
                return doc.to_dict().get('target_name_in_shift')
            return None
        except Exception: traceback.print_exc(); return None

    async def save_pending_shifts(self, line_user_id: str, workplace_id: str, parsed_shifts: List[Dict[str, Any]]) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('pending_shifts').document()
            pending_data = {
                "line_user_id": line_user_id, "workplace_id": workplace_id, "parsed_shifts": parsed_shifts,
                "status": "pending", "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=24)
            }
            await doc_ref.set(pending_data)
            return doc_ref.id
        except Exception: traceback.print_exc(); return None

    async def get_pending_shifts(self, pending_id: str) -> Optional[Dict[str, Any]]:
        if not self.db_async: return None
        try:
            doc = await self.db_async.collection('pending_shifts').document(pending_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception: traceback.print_exc(); return None
        
    async def log_shift_history(self, workplace_id: str, line_user_id: str, shift_info: ShiftInfo, calendar_event_id: str, status: str = "created") -> bool:
        if not self.db_async: return False
        try:
            history_collection_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history')
            start_dt = datetime.combine(shift_info.date, shift_info.start_time).replace(tzinfo=timezone.utc)
            end_dt = datetime.combine(shift_info.date, shift_info.end_time).replace(tzinfo=timezone.utc)
            if end_dt <= start_dt: end_dt += timedelta(days=1)
            history_data = {
                'user_id': line_user_id, 'date': shift_info.date.strftime("%Y-%m-%d"),
                'start_time': start_dt, 'end_time': end_dt, 'calendar_event_id': calendar_event_id,
                'status': status, 'created_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc),
                'name_in_shift': shift_info.name, 'role': shift_info.role, 'memo': shift_info.memo,
            }
            await history_collection_ref.document().set({k: v for k, v in history_data.items() if v is not None})
            return True
        except Exception: traceback.print_exc(); return False

    async def get_shift_history_for_user_in_workplace(self, workplace_id: str, line_user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.db_async: return []
        try:
            query = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history') \
                .where(filter=FieldFilter('user_id', '==', line_user_id)) \
                .order_by('start_time', direction=Query.DESCENDING).limit(limit)
            history_list = []
            async for doc in query.stream():
                data = doc.to_dict()
                if data:
                    data['history_id'] = doc.id
                    data['workplace_id'] = workplace_id
                    history_list.append(data)
            return history_list
        except Exception: traceback.print_exc(); return []

    async def check_duplicate_in_shift_history(self, workplace_id: str, line_user_id: str, shift_info: ShiftInfo) -> bool:
        if not self.db_async or not all([shift_info.date, shift_info.start_time, shift_info.end_time]): return False
        try:
            start_dt = datetime.combine(shift_info.date, shift_info.start_time, tzinfo=timezone.utc)
            end_dt = datetime.combine(shift_info.date, shift_info.end_time, tzinfo=timezone.utc)
            if end_dt <= start_dt: end_dt += timedelta(days=1)
            
            query = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history') \
                .where(filter=FieldFilter("user_id", "==", line_user_id)) \
                .where(filter=FieldFilter("start_time", "==", start_dt)) \
                .where(filter=FieldFilter("end_time", "==", end_dt)) \
                .limit(1)
            
            docs = [doc async for doc in query.stream()]
            return len(docs) > 0
        except Exception: traceback.print_exc(); return False
