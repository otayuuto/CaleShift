# app/services/firestore_service.py
# (HEADブランチとorigin/aoshiブランチの機能を統合・再構築)

from google.cloud.firestore_v1 import AsyncClient as FirestoreAsyncClient, Query # AsyncClientとQueryをインポート
from datetime import datetime, timezone, timedelta
import traceback
from typing import List, Optional, Dict, Any

from app.core.config import settings
# アプリケーションのデータ構造を定義したPydanticモデルをインポート
from app.models.setting import (
    WorkplaceCreatePayload, WorkplaceResponse,
    MyWorkplaceSettingCreatePayload, MyWorkplaceSettingResponse,
    WorkplaceSharedSettings
)
from app.utils.image_parser import ShiftInfo

class FirestoreService:
    """
    Firestoreデータベースとのやり取りをカプセル化するサービスクラス。
    非同期クライアント (AsyncClient) を使用します。
    """
    def __init__(self):
        # アプリケーション起動時に一度だけクライアントを初期化する
        if settings.GCP_PROJECT_ID:
            # ★ データベースID 'caleshiftdb' を明示的に指定
            self.db_async = FirestoreAsyncClient(project=settings.GCP_PROJECT_ID, database="caleshiftdb")
            print(f"INFO_FS_SERVICE: AsyncClient initialized for project '{settings.GCP_PROJECT_ID}', database 'caleshiftdb'.")
        else:
            # GCP_PROJECT_IDがない場合は、アプリケーションが正しく動作しない可能性が高い
            print("CRITICAL_FS_SERVICE: GCP_PROJECT_ID is not set. Firestore client could not be initialized properly.")
            self.db_async = None
    
    async def close_client(self):
        """アプリケーション終了時に非同期クライアントを閉じる"""
        if self.db_async:
            await self.db_async.close()
            print("INFO_FS_SERVICE: AsyncClient closed.")

    # --- ユーザー関連のメソッド (HEADブランチの機能を移行) ---

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
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to create initial user doc for {line_user_id}: {e}")
            traceback.print_exc()
            return False

    async def save_google_credentials_for_user(self, line_user_id: str, credentials_json: str, scopes: List[str]) -> bool:
        if not self.db_async: return False
        try:
            user_doc_ref = self.db_async.collection('users').document(line_user_id)
            doc_snapshot = await user_doc_ref.get()
            if not doc_snapshot.exists:
                print(f"ERROR_FS_SERVICE: User doc for {line_user_id} not found to save credentials.")
                return False
            auth_info_data = {
                'credentials_json': credentials_json, 'scopes': scopes,
                'last_authenticated_at': datetime.now(timezone.utc)
            }
            update_data = {
                'google_auth_info': auth_info_data, 'calendar_connected': True,
                'updated_at': datetime.now(timezone.utc)
            }
            await user_doc_ref.update(update_data)
            print(f"INFO_FS_SERVICE: Updated Google credentials for {line_user_id}")
            return True
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to save Google credentials for {line_user_id}: {e}")
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
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get Google credentials for {line_user_id}: {e}")
            traceback.print_exc()
            return None
            
    # --- 勤務場所(Workplace)とシフト履歴(Shift History)関連のメソッド ---

    async def log_shift_history(self, workplace_id: str, line_user_id: str, shift_info: ShiftInfo, calendar_event_id: str, status: str = "created") -> bool:
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
            # Noneのフィールドは保存しないようにする
            history_data = {k: v for k, v in history_data.items() if v is not None}
            await history_doc_ref.set(history_data)
            print(f"INFO_FS_SERVICE: Logged shift to history for user {line_user_id} in wp {workplace_id}.")
            return True
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to log shift history for {line_user_id}, wp {workplace_id}: {e}")
            traceback.print_exc()
            return False

    async def get_shift_history_for_user_in_workplace(self, workplace_id: str, line_user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.db_async: return []
        try:
            history_collection_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history')
            query = history_collection_ref.where('user_id', '==', line_user_id).order_by('start_time', direction=Query.DESCENDING).limit(limit)
            history_list = []
            async for doc in query.stream():
                history_data = doc.to_dict()
                if history_data:
                    history_data['history_id'] = doc.id
                    history_data['workplace_id'] = workplace_id
                    history_list.append(history_data)
            print(f"INFO_FS_SERVICE: Retrieved {len(history_list)} history entries for {line_user_id} from wp {workplace_id}")
            return history_list
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get shift history for {line_user_id}, wp {workplace_id}: {e}")
            traceback.print_exc()
            return [] # エラー時は空リストを返す

    # --- origin/aoshi ブランチから移行したバイト先設定関連メソッド ---
    # get_primary_workplace_id_for_user, get_workplace_shift_rules などもここに含める

    async def get_primary_workplace_id_for_user(self, line_user_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            settings_collection_ref = self.db_async.collection('users').document(line_user_id).collection('my_workplace_settings')
            docs_query = settings_collection_ref.limit(1)
            async for doc in docs_query.stream():
                print(f"INFO_FS_SERVICE: Found primary wp_id '{doc.id}' for user {line_user_id}")
                return doc.id # 最初のドキュメントのIDを返す
            print(f"WARNING_FS_SERVICE: No workplace_settings found for user {line_user_id}.")
            return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get primary wp_id for {line_user_id}: {e}")
            traceback.print_exc()
            return None

    async def get_workplace_shift_rules(self, workplace_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id)
            doc_snapshot = await doc_ref.get()
            if doc_snapshot.exists:
                data = doc_snapshot.to_dict()
                settings_data = data.get('settings') if data else None
                if settings_data and isinstance(settings_data, dict):
                    date_rules = settings_data.get('date_rules', {})
                    time_rules = settings_data.get('time_rules', {})
                    date_desc = date_rules.get('custom_description', "") if isinstance(date_rules, dict) else ""
                    time_desc = time_rules.get('custom_description', "") if isinstance(time_rules, dict) else ""
                    parts = [f"日付に関するルール: {date_desc}" if date_desc else "", f"時刻に関するルール: {time_desc}" if time_desc else ""]
                    final_rules = "\n".join(filter(None, parts))
                    return final_rules if final_rules else None
            return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get shift rules for wp {workplace_id}: {e}")
            traceback.print_exc()
            return None

    async def get_target_name_for_shift_extraction(self, line_user_id: str, workplace_id: str) -> Optional[str]:
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection("users").document(line_user_id).collection("my_workplace_settings").document(workplace_id)
            doc_snapshot = await doc_ref.get()
            if doc_snapshot.exists:
                data = doc_snapshot.to_dict()
                return data.get('target_name_in_shift') if data else None
            return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get target name for user {line_user_id}, wp {workplace_id}: {e}")
            traceback.print_exc()
            return None
            
    async def create_shared_workplace_info(self, payload: WorkplaceCreatePayload) -> WorkplaceResponse:
        # origin/aoshi のコードをそのままメソッド化
        if not self.db_async: raise ConnectionError("Firestore client is not available.")
        now = datetime.now(timezone.utc)
        workplaces_collection_ref = self.db_async.collection("workplaces")
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

    async def get_shift_history_item(self, workplace_id: str, history_id: str) -> Optional[Dict[str, Any]]:
        """単一のシフト履歴ドキュメントを取得します。"""
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history').document(history_id)
            doc = await doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e: # ...
            return None

    async def update_shift_history(self, workplace_id: str, history_id: str, update_data: Dict[str, Any]) -> bool:
        """シフト履歴ドキュメントを更新します。"""
        if not self.db_async: return False
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history').document(history_id)
            update_data['updated_at'] = datetime.now(timezone.utc)
            await doc_ref.update(update_data)
            print(f"INFO_FS_SERVICE: Updated shift history doc: {workplace_id}/{history_id}")
            return True
        except Exception as e: # ...
            return False

    async def delete_shift_history(self, workplace_id: str, history_id: str) -> bool:
        """シフト履歴ドキュメントを削除します。"""
        if not self.db_async: return False
        try:
            doc_ref = self.db_async.collection('workplaces').document(workplace_id).collection('shift_history').document(history_id)
            await doc_ref.delete()
            print(f"INFO_FS_SERVICE: Deleted shift history doc: {workplace_id}/{history_id}")
            return True
        except Exception as e: # ...
            return False
    async def save_pending_shifts(
        self,
        line_user_id: str,
        workplace_id: str,
        parsed_shifts: List[Dict[str, Any]] # Pydanticオブジェクトを辞書に変換して渡す
    ) -> Optional[str]:
        """
        解析されたシフト情報を一時的なコレクションに保存し、ドキュメントIDを返す。
        """
        if not self.db_async: return None
        try:
            # pending_shifts コレクションに新しいドキュメントを作成 (IDは自動生成)
            pending_doc_ref = self.db_async.collection('pending_shifts').document()
            
            pending_data = {
                "line_user_id": line_user_id,
                "workplace_id": workplace_id,
                "parsed_shifts": parsed_shifts, # 辞書のリスト
                "status": "pending",
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=24) # 例: 24時間の有効期限
            }

            await pending_doc_ref.set(pending_data)
            pending_id = pending_doc_ref.id
            print(f"INFO_FS_SERVICE: Saved pending shifts for user {line_user_id}. Pending ID: {pending_id}")
            return pending_id
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to save pending shifts for user {line_user_id}: {e}")
            traceback.print_exc()
            return None

    async def get_pending_shifts(self, pending_id: str) -> Optional[Dict[str, Any]]:
        """
        指定されたIDの保留中シフト情報を取得します。
        """
        if not self.db_async: return None
        try:
            doc_ref = self.db_async.collection('pending_shifts').document(pending_id)
            doc = await doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            else:
                print(f"WARNING_FS_SERVICE: Pending shifts document not found for ID: {pending_id}")
                return None
        except Exception as e:
            print(f"ERROR_FS_SERVICE: Failed to get pending shifts for ID {pending_id}: {e}")
            traceback.print_exc()
            return None

    # (参考) 古い保留データを削除する関数 (Cloud Functionsなどで定期実行すると良い)
    # async def delete_expired_pending_shifts(self):
    #     if not self.db_async: return
    #     now = datetime.now(timezone.utc)
    #     query = self.db_async.collection('pending_shifts').where('expires_at', '<', now)
    #     async for doc in query.stream():
    #         await doc.reference.delete()
    #         print(f"Deleted expired pending shift: {doc.id}")