# app/services/firestore_service.py
from google.cloud import firestore
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import traceback
import json # 主に google_auth_service の refresh_access_token で使用
from fastapi.concurrency import run_in_threadpool
from app.utils.image_parser import ShiftInfo

# save_google_credentials_for_user, get_google_credentials_for_user, create_initial_user_document_on_follow
# は前回の修正で run_in_threadpool を使用しており、基本的なロジックは問題なさそうです。
# 以下、新しい関数を実装・調整します。

async def get_workplace_shift_rules(db_client: firestore.Client, workplace_id: str) -> Optional[str]:
    """
    指定された勤務場所IDのシフト記述ルールをFirestoreから取得します。
    /workplaces/{workplace_id} の settings.date_rules.custom_description と 
    settings.time_rules.custom_description を結合して返します。
    """
    if not db_client:
        print("ERROR_FS_SERVICE: Firestore client not provided for get_workplace_shift_rules.")
        return None
    try:
        doc_ref = db_client.collection('workplaces').document(workplace_id)
        doc_snapshot = await run_in_threadpool(doc_ref.get)

        if doc_snapshot.exists:
            data = doc_snapshot.to_dict()
            # Firestoreの画像に基づくと、settings -> date_rules/time_rules -> custom_description
            settings_data = data.get('settings') if data else None
            if settings_data and isinstance(settings_data, dict):
                date_rules_data = settings_data.get('date_rules')
                time_rules_data = settings_data.get('time_rules')

                date_desc = ""
                if date_rules_data and isinstance(date_rules_data, dict) and \
                   isinstance(date_rules_data.get('custom_description'), str):
                    date_desc = date_rules_data['custom_description']

                time_desc = ""
                if time_rules_data and isinstance(time_rules_data, dict) and \
                   isinstance(time_rules_data.get('custom_description'), str):
                    time_desc = time_rules_data['custom_description']
                
                full_rules_parts = []
                if date_desc:
                    full_rules_parts.append(f"日付に関するルール: {date_desc}")
                if time_desc:
                    full_rules_parts.append(f"時刻に関するルール: {time_desc}")
                
                if not full_rules_parts:
                    print(f"WARNING_FS_SERVICE: No custom descriptions found for workplace {workplace_id}.")
                    # フォールバックルール
                    return (
                        "日付は表の上部に記載され、曜日の下に対応する日付があります。"
                        "時刻は各氏名の行に記載されます。"
                        "一般的なシフト表の形式で、日付、氏名、開始時間、終了時間を抽出してください。"
                    )
                
                final_rules = "\n".join(full_rules_parts)
                print(f"INFO_FS_SERVICE: Retrieved shift rules for workplace {workplace_id}: '{final_rules[:150]}...'")
                return final_rules
            else:
                print(f"WARNING_FS_SERVICE: 'settings' field not found or not a map in workplace {workplace_id}.")
        else:
            print(f"WARNING_FS_SERVICE: Workplace document not found for ID: {workplace_id}")
        # ルールが見つからない場合、呼び出し側で汎用ルールを使うか、ここで汎用ルールを返す
        return (
            "日付は表の上部に記載され、曜日の下に対応する日付があります。"
            "時刻は各氏名の行に記載されます。"
            "一般的なシフト表の形式で、日付、氏名、開始時間、終了時間を抽出してください。"
        )
    except Exception as e:
        print(f"ERROR_FS_SERVICE: Failed to get shift rules for workplace {workplace_id}: {e}")
        traceback.print_exc()
        return None # エラー時もNoneを返す
async def get_target_name_for_shift_extraction(
    db_client: firestore.Client,
    line_user_id: str,
    workplace_id: str
) -> Optional[str]:
    """
    指定されたユーザーと勤務場所の組み合わせで、シフト抽出対象の氏名をFirestoreから取得します。
    パス: /users/{line_user_id}/my_workplace_settings/{workplace_id}
    フィールド: target_name_in_shift
    """
    if not db_client:
        print("ERROR_FS_SERVICE: Firestore client (db_client) is not provided for get_target_name_for_shift_extraction.")
        return None
    try:
        doc_ref = db_client.collection('users').document(line_user_id) \
                        .collection('my_workplace_settings').document(workplace_id)
        doc_snapshot = await run_in_threadpool(doc_ref.get)

        if doc_snapshot.exists:
            data = doc_snapshot.to_dict()
            # 画像によると target_name_in_shift はトップレベルにある
            if data and 'target_name_in_shift' in data:
                target_name = data['target_name_in_shift']
                if isinstance(target_name, str) and target_name.strip():
                    print(f"INFO_FS_SERVICE: Retrieved target_name '{target_name}' for user {line_user_id}, workplace {workplace_id}")
                    return target_name
                else:
                    print(f"WARNING_FS_SERVICE: 'target_name_in_shift' is empty or not a string for user {line_user_id}, workplace {workplace_id}")
            else:
                print(f"WARNING_FS_SERVICE: 'target_name_in_shift' not found for user {line_user_id}, workplace {workplace_id}")
        else:
            print(f"WARNING_FS_SERVICE: my_workplace_settings document not found for user {line_user_id}, workplace {workplace_id}")
        return None # 対象名が見つからない場合はNone
    except Exception as e:
        print(f"ERROR_FS_SERVICE: Failed to get target name for user {line_user_id}, wp {workplace_id}: {e}")
        traceback.print_exc()
        return None

async def get_primary_workplace_id_for_user(db_client: firestore.Client, line_user_id: str) -> Optional[str]:
    """
    ユーザーの my_workplace_settings サブコレクションから最初のドキュメントID (workplace_id) を取得します。
    注意: Firestoreのコレクションの順序は保証されないため、「最初の」という概念は不安定です。
          ユーザーが複数の勤務場所を持つ場合、明確に「主要な」勤務場所を選択させる仕組みが必要です。
    """
    if not db_client:
        print("ERROR_FS_SERVICE: Firestore client (db_client) is not provided for get_primary_workplace_id_for_user.")
        return None
    try:
        settings_collection_ref = db_client.collection('users').document(line_user_id).collection('my_workplace_settings')
        
        # limit(1) で最初の1件を取得
        docs_query = settings_collection_ref.limit(1)
        docs_stream = await run_in_threadpool(docs_query.stream) # stream() も run_in_threadpool を使う
        
        doc_list = list(docs_stream) # イテレータをリストに変換

        if doc_list:
            # ドキュメントIDが workplace_id となっているという前提
            primary_wp_id = doc_list[0].id 
            print(f"INFO_FS_SERVICE: Found primary workplace_id '{primary_wp_id}' for user {line_user_id}")
            return primary_wp_id
        else:
            print(f"WARNING_FS_SERVICE: No workplace_settings found for user {line_user_id}. Cannot determine primary workplace_id.")
            return None
    except Exception as e:
        print(f"ERROR_FS_SERVICE: Failed to get primary workplace_id for user {line_user_id}: {e}")
        traceback.print_exc()
        return None

# --- 既存の関数 (save_google_credentials_for_user, get_google_credentials_for_user, create_initial_user_document_on_follow) ---
# これらは前回の修正で run_in_threadpool を使用しており、基本的なロジックは問題なさそうなので、そのまま残します。
# (以下、既存の関数のコード)
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
        user_doc = await run_in_threadpool(user_doc_ref.get)
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
        await run_in_threadpool(user_doc_ref.update, update_data)
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
        user_doc = await run_in_threadpool(user_doc_ref.get)
        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data:
                auth_info = user_data.get('google_auth_info')
                if auth_info: return auth_info
                else: print(f"WARNING_FIRESTORE_SERVICE: 'google_auth_info' not found for {line_user_id}")
            else: print(f"WARNING_FIRESTORE_SERVICE: User document data is None for {line_user_id}")
        else: print(f"WARNING_FIRESTORE_SERVICE: No user document found for {line_user_id}")
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
        user_doc = await run_in_threadpool(user_doc_ref.get)
        if user_doc.exists:
            print(f"INFO_FIRESTORE_SERVICE: User document for {line_user_id} already exists.")
            return True
        initial_user_data = {
            'user_id': line_user_id,
            'name': display_name or f"User-{line_user_id[:8]}",
            'email': "", 'calendar_connected': False, 'google_auth_info': None,
            'created_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc)
        }
        await run_in_threadpool(user_doc_ref.set, initial_user_data)
        print(f"INFO_FIRESTORE_SERVICE: Successfully created initial user document for {line_user_id}")
        return True
    except Exception as e:
        print(f"ERROR_FIRESTORE_SERVICE: Failed to create initial user document for {line_user_id}: {e}")
        traceback.print_exc()
        return False
async def log_shift_history(
    db_client: firestore.Client,
    workplace_id: str,
    line_user_id: str,
    shift_info: ShiftInfo,
    calendar_event_id: str,
    status: str = "created"
) -> bool:
    """
    カレンダーに登録されたシフト情報を、指定された勤務場所のサブコレクションに保存します。
    パス: /workplaces/{workplace_id}/shift_history/{自動ID}
    """
    if not db_client:
        print("ERROR_FS_SERVICE: Firestore client not provided for log_shift_history.")
        return False
    if not workplace_id:
        print("ERROR_FS_SERVICE: workplace_id is required to log shift history.")
        return False
    
    try:
        # ★★★ 保存パスを /workplaces/{workplace_id}/shift_history に変更 ★★★
        history_collection_ref = db_client.collection('workplaces').document(workplace_id).collection('shift_history')
        history_doc_ref = history_collection_ref.document() # ドキュメントIDは自動生成

        history_data = {
            'user_id': line_user_id, # この履歴がどのユーザーのものかを示す
            # 'workplace_id' フィールドは不要 (親ドキュメントが示しているため)
            
            'date': shift_info.date.strftime("%Y-%m-%d"),
            # 日付をまたぐシフトの場合も考慮し、開始/終了日時の両方をタイムスタンプで持つ
            'start_time': datetime.combine(shift_info.date, shift_info.start_time).replace(tzinfo=timezone.utc),
            'end_time': datetime.combine(shift_info.date, shift_info.end_time).replace(tzinfo=timezone.utc),

            'calendar_event_id': calendar_event_id,
            'status': status,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        # 終了時刻が開始時刻より早い場合、日付を1日進める
        if history_data['end_time'] <= history_data['start_time']:
            history_data['end_time'] += timedelta(days=1)

        # ShiftInfoの他の情報も保存
        if shift_info.name: history_data['name_in_shift'] = shift_info.name # Firestoreのフィールド名に合わせる
        if shift_info.role: history_data['role'] = shift_info.role
        if shift_info.memo: history_data['memo'] = shift_info.memo

        await run_in_threadpool(history_doc_ref.set, history_data)
        
        print(f"INFO_FS_SERVICE: Successfully logged shift to history for user {line_user_id} in workplace {workplace_id}. History Doc ID: {history_doc_ref.id}")
        return True

    except Exception as e:
        print(f"ERROR_FS_SERVICE: Failed to log shift to history for user {line_user_id}, workplace {workplace_id}: {e}")
        traceback.print_exc()
        return False
async def get_shift_history_for_user_in_workplace(
    db_client: firestore.Client,
    workplace_id: str,
    line_user_id: str,
    limit: int = 50
) -> Optional[List[Dict[str, Any]]]:
    """
    指定された勤務場所の、指定されたユーザーのシフト履歴を取得します。
    """
    if not db_client: return None
    try:
        history_collection_ref = db_client.collection('workplaces').document(workplace_id).collection('shift_history')
        
        query = history_collection_ref.where('user_id', '==', line_user_id) \
                                    .order_by('start_time', direction=firestore.Query.DESCENDING) \
                                    .limit(limit)
        
        docs_stream = await run_in_threadpool(query.stream)
        history_list = []
        for doc in docs_stream:
            history_data = doc.to_dict()
            if history_data:
                history_data['history_id'] = doc.id # ドキュメントIDも追加
                history_list.append(history_data)
        
        print(f"INFO_FS_SERVICE: Retrieved {len(history_list)} history entries for user {line_user_id} from workplace {workplace_id}")
        return history_list
    except Exception as e:
        print(f"ERROR_FS_SERVICE: Failed to get shift history for user {line_user_id}, workplace {workplace_id}: {e}")
        traceback.print_exc()
        return None