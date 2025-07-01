# app/services/firestore_service.py

from google.cloud import firestore_v1 as firestore
from datetime import datetime, timezone
import traceback
from typing import List, Optional

from app.core.config import settings
from app.models.setting import (
    WorkplaceCreatePayload, WorkplaceResponse,
    MyWorkplaceSettingCreatePayload, MyWorkplaceSettingResponse,
    WorkplaceSharedSettings # get_all_shared_workplaces で使う可能性
)

# --- 既存の同期処理 (save_parsed_shifts) はそのまま ---
if settings.GCP_PROJECT_ID:
    db_sync = firestore.Client(project=settings.GCP_PROJECT_ID, database="caleshiftdb")
else:
    print("Warning: GCP_PROJECT_ID is not set for sync client.")
    db_sync = firestore.Client(database="caleshiftdb")

def save_parsed_shifts(user_id: str, shifts: list[dict]):
    if not shifts:
        print(f"No shifts to save for user {user_id}.")
        return False
    try:
        batch = db_sync.batch()
        user_shifts_collection = db_sync.collection('users').document(user_id).collection('shifts')
        for shift_data in shifts:
            doc_ref = user_shifts_collection.document()
            data_to_save = shift_data.copy()
            data_to_save['line_user_id'] = user_id
            data_to_save['created_at'] = firestore.SERVER_TIMESTAMP
            batch.set(doc_ref, data_to_save)
        batch.commit()
        print(f"Successfully saved {len(shifts)} shifts for user {user_id} to Firestore.")
        return True
    except Exception as e:
        print(f"Error saving shifts for user {user_id} to Firestore: {e}")
        traceback.print_exc()
        return False

# --- FirestoreService クラスのメソッド追加・変更 ---
class FirestoreService:
    def __init__(self):
        if settings.GCP_PROJECT_ID:
            self.db_async = firestore.AsyncClient(project=settings.GCP_PROJECT_ID, database="caleshiftdb")
        else:
            print("Warning: GCP_PROJECT_ID is not set for AsyncClient.")
            self.db_async = firestore.AsyncClient(database="caleshiftdb")

    async def create_shared_workplace_info(self, payload: WorkplaceCreatePayload) -> WorkplaceResponse:
        now = datetime.now(timezone.utc)
        workplaces_collection_ref = self.db_async.collection("workplaces")
        new_workplace_doc_ref = workplaces_collection_ref.document()
        workplace_id = new_workplace_doc_ref.id

        data_to_save = {
            "workplace_id": workplace_id,
            "workplace_name": payload.workplace_name,
            "settings": payload.settings.dict(exclude_none=True),
            "created_by_user_id": payload.current_line_user_id,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await new_workplace_doc_ref.set(data_to_save)
            print(f"Successfully created shared workplace '{workplace_id}' by user '{payload.current_line_user_id}'")
        except Exception as e:
            print("--- Error in create_shared_workplace_info ---")
            traceback.print_exc()
            raise
        return WorkplaceResponse(**data_to_save)

    async def get_all_shared_workplaces(self) -> List[WorkplaceResponse]:
        workplaces_collection_ref = self.db_async.collection("workplaces")
        workplaces_list: List[WorkplaceResponse] = []
        print("Attempting to retrieve all shared workplaces...")
        try:
            async for doc_snapshot in workplaces_collection_ref.stream():
                # ↓ tryブロック内のインデントも揃える (例: さらにスペース4つ)
                if doc_snapshot.exists:
                    data = doc_snapshot.to_dict()
                    print(f"Processing document ID: {doc_snapshot.id}, Data: {data}")
                    try:
                        if data and "settings" in data and isinstance(data["settings"], dict):
                           data["settings"] = WorkplaceSharedSettings(**data["settings"])
                        workplaces_list.append(WorkplaceResponse(**data))
                    except Exception as pydantic_error:
                        print(f"--- Pydantic Validation Error for Document ID: {doc_snapshot.id} ---")
                        print(f"Raw Data: {data}")
                        print(f"Pydantic Error: {pydantic_error}")
                        traceback.print_exc()
                        print("--------------------------------------------------------------------")
            print(f"Successfully processed. Number of valid workplaces retrieved: {len(workplaces_list)}")
        except Exception as e:
            print("--------------------------------------------------")
            print(f"Error retrieving all shared workplaces from Firestore:")
            print(f"Error type: {type(e)}")
            print(f"Error message: {str(e)}")
            print("Traceback:")
            traceback.print_exc()
            print("--------------------------------------------------")
            raise
        return workplaces_list 

    async def set_user_target_name_for_workplace(
        self, line_user_id: str, workplace_id: str, payload: MyWorkplaceSettingCreatePayload
    ) -> MyWorkplaceSettingResponse:
        now = datetime.now(timezone.utc)
        setting_doc_ref = self.db_async.collection("users").document(line_user_id)\
                                     .collection("my_workplace_settings").document(workplace_id)
        data_to_save = {
            "workplace_id": workplace_id,
            "line_user_id": line_user_id,
            "target_name_in_shift": payload.target_name_in_shift,
            "updated_at": now,
        }
        try:
            doc_snapshot = await setting_doc_ref.get()
            if not doc_snapshot.exists:
                data_to_save["linked_at"] = now
            else:
                existing_data = doc_snapshot.to_dict()
                data_to_save["linked_at"] = existing_data.get("linked_at", now) # 既存がなければ今

            await setting_doc_ref.set(data_to_save, merge=True)
            print(f"Successfully set/updated target_name for user '{line_user_id}', workplace '{workplace_id}'")
        except Exception as e:
            print("--- Error in set_user_target_name_for_workplace ---")
            traceback.print_exc()
            raise
        return MyWorkplaceSettingResponse(**data_to_save)

    async def get_user_target_name_for_workplace(
        self, line_user_id: str, workplace_id: str
    ) -> Optional[MyWorkplaceSettingResponse]:
        setting_doc_ref = self.db_async.collection("users").document(line_user_id)\
                                     .collection("my_workplace_settings").document(workplace_id)
        try:
            doc_snapshot = await setting_doc_ref.get()
            if doc_snapshot.exists:
                data = doc_snapshot.to_dict()
                return MyWorkplaceSettingResponse(**data)
            return None
        except Exception as e:
            print("--- Error in get_user_target_name_for_workplace ---")
            traceback.print_exc()
            raise