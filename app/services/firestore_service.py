# app/services/firestore_service.py (新規作成 - 例)
from google.cloud import firestore
from app.core.config import settings # GCP_PROJECT_ID を使う場合

# 環境変数 GOOGLE_APPLICATION_CREDENTIALS が設定されていれば、
# クライアントは自動で認証情報を見つけます。
# project_id は明示的に指定することも、クライアントが自動で見つけるのに任せることも可能
db = firestore.Client(project=settings.GCP_PROJECT_ID if settings.GCP_PROJECT_ID else None)

def save_parsed_shifts(user_id: str, shifts: list[dict]):
    """
    解析されたシフト情報をユーザーごとにFirestoreに保存する。
    Args:
        user_id: LINEユーザーID
        shifts: 解析されたシフト情報のリスト (各要素は辞書)
    """
    if not shifts:
        # logger.info(f"No shifts to save for user {user_id}.")
        print(f"No shifts to save for user {user_id}.")
        return False

    try:
        # バッチ書き込みを使用すると効率的
        batch = db.batch()
        user_shifts_collection = db.collection('users').document(user_id).collection('shifts')

        for shift_data in shifts:
            # ドキュメントIDは自動生成させるか、日付と開始時間などからユニークなIDを生成する
            # ここでは自動生成の例
            doc_ref = user_shifts_collection.document()
            # 保存するデータにユーザーIDや登録日時などを追加しても良い
            data_to_save = shift_data.copy() # 元のデータを変更しないようにコピー
            data_to_save['line_user_id'] = user_id
            data_to_save['created_at'] = firestore.SERVER_TIMESTAMP # 保存日時
            batch.set(doc_ref, data_to_save)
        batch.commit()
        # logger.info(f"Successfully saved {len(shifts)} shifts for user {user_id} to Firestore.")
        print(f"Successfully saved {len(shifts)} shifts for user {user_id} to Firestore.")
        return True
    except Exception as e:
        # logger.error(f"Error saving shifts for user {user_id} to Firestore: {e}")
        print(f"Error saving shifts for user {user_id} to Firestore: {e}")
        # import traceback
        # logger.error(traceback.format_exc())
        return False

# (オプション) 特定ユーザーのシフトを取得する関数などの例
# def get_user_shifts(user_id: str):
#     shifts = []
#     docs = db.collection('users').document(user_id).collection('shifts').stream()
#     for doc in docs:
#         shifts.append(doc.to_dict())
#     return shifts