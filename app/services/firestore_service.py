
from google.cloud import firestore_v1 as firestore # firestore_v1.Client と firestore_v1.AsyncClient を使用
from datetime import datetime, timezone

from app.core.config import settings # GCP_PROJECT_ID を使う場合
from app.models.setting import WorkplaceCreate, WorkplaceResponse # LIFF設定保存用のPydanticモデル

# --- 既存の同期処理 (save_parsed_shifts) のためのFirestoreクライアント ---
# この部分は変更しません
db_sync = firestore.Client(project=settings.GCP_PROJECT_ID if settings.GCP_PROJECT_ID else None)

def save_parsed_shifts(user_id: str, shifts: list[dict]):
    """
    解析されたシフト情報をユーザーごとにFirestoreに保存する。(同期処理)
    Args:
        user_id: LINEユーザーID
        shifts: 解析されたシフト情報のリスト (各要素は辞書)
    """
    if not shifts:
        print(f"No shifts to save for user {user_id}.")
        return False

    try:
        batch = db_sync.batch() # 既存の同期クライアント db_sync を使用
        user_shifts_collection = db_sync.collection('users').document(user_id).collection('shifts')

        for shift_data in shifts:
            doc_ref = user_shifts_collection.document()
            data_to_save = shift_data.copy()
            data_to_save['line_user_id'] = user_id
            # 同期クライアントでは firestore.SERVER_TIMESTAMP を使用
            data_to_save['created_at'] = firestore. अभी # または firestore.SERVER_TIMESTAMP
            batch.set(doc_ref, data_to_save)
        batch.commit()
        print(f"Successfully saved {len(shifts)} shifts for user {user_id} to Firestore.")
        return True
    except Exception as e:
        print(f"Error saving shifts for user {user_id} to Firestore: {e}")
        return False

# --- ここから新しく追加する非同期処理 (LIFF設定保存) のための FirestoreService クラス ---
class FirestoreService:
    def __init__(self):
        if settings.GCP_PROJECT_ID:
            self.db_async = firestore.AsyncClient(project=settings.GCP_PROJECT_ID)
        else:
            print("Warning: GCP_PROJECT_ID is not set for AsyncClient. Firestore client will try to infer it.")
            self.db_async = firestore.AsyncClient()

    async def create_workplace(self, line_user_id: str, workplace_data: WorkplaceCreate) -> WorkplaceResponse:
        """
        新しいバイト先設定をFirestoreに作成する (非同期処理)
        """
        now = datetime.now(timezone.utc)

        user_doc_ref = self.db_async.collection("users").document(line_user_id)
        workplaces_collection_ref = user_doc_ref.collection("workplaces")
        new_workplace_doc_ref = workplaces_collection_ref.document()
        workplace_id = new_workplace_doc_ref.id

        data_to_save = {
            "workplace_id": workplace_id,
            "workplace_name": workplace_data.workplace_name,
            "settings": workplace_data.settings.dict(exclude_none=True),
            "line_user_id": line_user_id,
            "created_at": now, # 非同期クライアントの場合、datetimeオブジェクトを直接渡すのが一般的
            "updated_at": now,
        }

        try:
            await new_workplace_doc_ref.set(data_to_save)
            print(f"Successfully created workplace '{workplace_id}' for user '{line_user_id}' (async)")
        except Exception as e:
            print(f"Error saving workplace to Firestore (async): {e}")
            raise

        response_data = WorkplaceResponse(
            workplace_id=workplace_id,
            workplace_name=workplace_data.workplace_name,
            settings=workplace_data.settings,
            line_user_id=line_user_id,
            created_at=now,
            updated_at=now,
        )
        return response_data

    # (オプション) 特定ユーザーのシフトを取得する関数などの例 (既存のものはコメントアウトのまま)
    # def get_user_shifts(user_id: str): # これは同期のまま
    #     shifts = []
    #     docs = db_sync.collection('users').document(user_id).collection('shifts').stream()
    #     for doc in docs:
    #         shifts.append(doc.to_dict())
    #     return shifts

    # --- 将来的にFirestoreServiceクラスに追加するかもしれない非同期メソッドのプレースホルダ ---
    # async def get_workplace_async(self, line_user_id: str, workplace_id: str) -> Optional[WorkplaceResponse]:
    #     # ... (非同期でバイト先設定を取得するロジック) ...
    #     pass