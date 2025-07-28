# app/services/firestore_service.py
# (HEADブランチとorigin/developerブランチの機能を統合・再構築した完全版)

from google.cloud.firestore_v1 import AsyncClient as FirestoreAsyncClient, Query, FieldFilter
from google.oauth2 import service_account
from datetime import datetime, timezone, timedelta
import traceback
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, status
import json
import os

from app.core.config import settings
# アプリケーションのデータ構造を定義したPydanticモデルをインポート
from app.models.setting import (
    WorkplaceCreatePayload, WorkplaceResponse,
    MyWorkplaceSettingCreatePayload, MyWorkplaceSettingResponse
)
from app.utils.image_parser import ShiftInfo

class FirestoreService:
    """
    Firestoreデータベースとのやり取りをカプセル化するサービスクラス。
    非同期クライアント (AsyncClient) を使用します。
    """
    def __init__(self):
        """
        FirestoreServiceのコンストラクタ。
        環境変数 GOOGLE_APPLICATION_CREDENTIALS の内容を自動で判定し、
        Firestoreの非同期クライアントを初期化します。
        """
        if not settings.GCP_PROJECT_ID:
            print("CRITICAL_FS_SERVICE: GCP_PROJECT_ID is not set. Firestore client cannot be initialized.")
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
                project=settings.GCP_PROJECT_ID,
                database=database_id_to_use,
                credentials=credentials
            )
            print(f"INFO_FS_SERVICE: AsyncClient initialized for project '{settings.GCP_PROJECT_ID}', database '{database_id_to_use}'.")
        except Exception as e:
            print(f"CRITICAL_FS_SERVICE: Failed to initialize Firestore AsyncClient: {e}")
            traceback.print_exc()
            self.db_async = None
    
    async def close_client(self):
        """アプリケーション終了時に非同期クライアントを閉じる"""
        if self.db_async:
            await self.db_async.close()
            print("INFO_FS_SERVICE: AsyncClient closed.")

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
            print(f"INFO_FS_SERVICE: Created initial user doc for {line_user_id}")
            return True
        except Exception: traceback.print_exc(); return False

    async def save_google_credentials_for_user(self, line_user_id: str, credentials_json: str, scopes: List[str]) -> bool:
        if not self.db_async: return False
        try:
            user_doc_ref = self.db_async.collection('users').document(line_user_id)
            auth_info = {'credentials_json': credentials_json, 'scopes': scopes, 'last_authenticated_at': datetime.now(timezone.utc)}
            update_data = {'google_auth_info': auth_info, 'calendar_connected': True, 'updated_at': datetime.now(timezone.utc)}
            await user_doc_ref.set(update_data, merge=True)
            print(f"INFO_FS_SERVICE: Updated Google credentials for {line_user_id}")
            return True
        except Exception: traceback.print_exc(); return False

    async def get_google_credentials_for_user(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        if not self.db_async: return None
        try:
            doc = await self.db_async.collection('users').document(line_user_id).get()
            if doc.exists:
                user_data = doc.to_dict()
                return user_data.get('google_auth_info') if user_data else None
            return None
        except Exception: traceback.print_exc(); return None

    # --- 勤務場所とユーザー設定関連 ---

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
    
    async def set_user_target_name_for_workplace(self, line_user_id: str, workplace_id: str, payload: MyWorkplaceSettingCreatePayload) -> MyWorkplaceSettingResponse:
        if not self.db_async: raise ConnectionError("Firestore client is not available.")
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
            query = self.db_async.collection('users').document(line_user_id).collection('my_workplace_settings').limit(1)
            async for doc in query.stream():
                return doc.id
            return None
        except Exception: traceback.print_exc(); return None

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