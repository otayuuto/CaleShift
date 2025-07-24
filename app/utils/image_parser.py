# app/utils/image_parser.py
import re
from datetime import datetime, time, date
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, field_validator, ValidationError # Pydantic関連のインポートはそのまま

# ★★★ OpenAIサービスをインポート ★★★
from app.services import openai_service 
# ★★★ Firestoreクライアントの型ヒントと、ルール取得関数を使うならそれも ★★★
# from google.cloud.firestore import Client as FirestoreClient 
# from app.services.openai_service import get_shift_rules_for_user # ルール取得関数

# ShiftInfoモデルの定義は変更なし (OpenAIの出力JSONをこのモデルにマッピングするため)
class ShiftInfo(BaseModel):
    date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    name: Optional[str] = None
    role: Optional[str] = None
    memo: Optional[str] = None
    is_holiday: bool = False

    model_config = {
        "arbitrary_types_allowed": True
    }

    # バリデータも基本的には変更なし (OpenAIからの出力が期待通りなら不要になることも)
    @field_validator('date', mode='before')
    @classmethod
    def parse_date_str(cls, value):
        print(f"DEBUG_VALIDATOR (date): Received value: '{value}' (type: {type(value)})")
        if isinstance(value, str):
            # 形式1: YYYY-MM-DD
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                # 形式2: ISO 8601形式のdatetime文字列 (例: '2025-06-20T17:00:00.000Z')
                try:
                    # fromisoformatはタイムゾーンも扱う
                    return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
                except ValueError:
                    raise ValueError(f"Invalid date format: {value}")
        elif isinstance(value, datetime):
            return value.date()
        elif isinstance(value, date):
            return value
        raise TypeError(f"Unsupported type for date: {type(value)}")

    @field_validator('start_time', 'end_time', mode='before')
    @classmethod
    def parse_time_str(cls, value, info: any = None):
        field_name = info.field_name if info else "unknown_field"
        print(f"DEBUG_VALIDATOR ({field_name}): Received value: '{value}' (type: {type(value)})")
        if value is None or isinstance(value, time):
            return value
        if isinstance(value, str):
            value_stripped = value.strip()
            if not value_stripped: return None
            
            # 試行するフォーマットのリスト
            time_formats = [
                "%H:%M:%S",  # "22:00:00" 形式
                "%H:%M",      # "22:00" 形式
            ]
            
            for fmt in time_formats:
                try:
                    parsed_time = datetime.strptime(value_stripped, fmt).time()
                    print(f"DEBUG_VALIDATOR ({field_name}): Parsed '{value_stripped}' with format '{fmt}' to {parsed_time}")
                    return parsed_time
                except ValueError:
                    continue # 次のフォーマットを試す
            
            # どのフォーマットにも一致しなかった場合
            print(f"ERROR_VALIDATOR ({field_name}): Failed to parse time string '{value_stripped}' with any known format.")
            raise ValueError(f"Invalid time format: {value_stripped}")
        
        elif isinstance(value, datetime): # ★ datetimeオブジェクトが直接渡された場合
             return value.time()

        raise TypeError(f"Unsupported type for time: {type(value)}")

# ★★★ メインのパース関数をOpenAIを使うように変更 ★★★
async def parse_shift_text_to_structured_data(
    ocr_text: str,
    line_user_id: str, # ルール取得のためにユーザーIDが必要になる場合
    db_client: Optional[Any] = None, # Firestoreクライアント (ルール取得用) # Any は firestore.Client の方が良い
    image_description: Optional[str] = None # 画像に関する補足 (オプション)
) -> List[ShiftInfo]:
    """
    OCRテキストとユーザー固有のシフト記述ルールをOpenAI APIに送信し、
    解析されたシフト情報をShiftInfoオブジェクトのリストとして返します。
    """
    parsed_shifts_objects: List[ShiftInfo] = []

    # 1. ユーザー固有のシフト記述ルールを取得 (Firestoreなどから)
    #    ここでは、事前に取得済みのルールが shift_rules_text として渡されると仮定。
    #    もし、この関数内で取得するなら db_client と line_user_id が必要。
    # shift_rules_text = await openai_service.get_shift_rules_for_user(db_client, line_user_id)
    # 今回のフローでは、事前に登録されたルールを渡す想定なので、引数に追加する方が良いかもしれない。
    # ここでは、仮に固定のルールを使うか、引数で渡されることを期待する。
    # 実際のシフト記述ルールはフローのステップ3で登録され、
    # この関数が呼び出される際には既に取得できている前提とする。
    # そのため、この関数の引数に shift_rules_text: str を追加するのが良い。
    # ここでは、仮に固定のルールを設定（画像で提供された内容に基づく）
    # TODO: 実際には外部から取得したルールを使うようにする
    shift_rules_text = """
    - 日付は「X月 Y日」のようにヘッダーに記載されていることが多い。
    - 表形式で「区別」「氏名」「担当」「開始時間」「終了時間」の列がある。
    - 時刻は「HH:MM」形式で記載されている。
    - 「0:00」は午前0時（深夜）を示す。
    - 「休み」や「休」と記載されていればその日は休みとして扱う。
    - 氏名、担当、開始時間、終了時間が1行にまとまっている場合もあれば、OCRの結果、複数行に分割されている場合もある。
    - 1つの画像に複数人のシフトが含まれる場合、各人ごとにシフト情報を抽出する。
    """
    print(f"DEBUG_PARSER: Using shift rules for user {line_user_id}:\n{shift_rules_text[:200]}...")


    # 2. OpenAI APIを呼び出してテキストを解析
    #    openai_service.analyze_shift_text_with_rules は async def である必要がある
    analyzed_data_dict = await openai_service.analyze_shift_text_with_rules(
        ocr_text=ocr_text,
        shift_rules=shift_rules_text, # ここでユーザー固有のルールを渡す
        image_description=image_description
    )

    if not analyzed_data_dict or "shifts" not in analyzed_data_dict:
        print("ERROR_PARSER: Failed to get structured data from OpenAI service or response format is wrong.")
        return [] # 空のリストを返す

    # 3. 解析結果 (JSON) を ShiftInfo オブジェクトのリストに変換
    raw_shifts_list = analyzed_data_dict.get("shifts", [])
    for raw_shift_entry in raw_shifts_list:
        try:
            # name, role, memo が null の場合、PydanticモデルのOptionalで処理される
            # is_holiday がない場合はデフォルトの False になる
            shift_obj = ShiftInfo(
                date=raw_shift_entry.get("date"), # バリデータが文字列をdate型に変換
                start_time=raw_shift_entry.get("start_time"), # バリデータが文字列をtime型に変換
                end_time=raw_shift_entry.get("end_time"), # バリデータが文字列をtime型に変換
                name=raw_shift_entry.get("name"),
                role=raw_shift_entry.get("role"),
                memo=raw_shift_entry.get("memo"),
                is_holiday=raw_shift_entry.get("is_holiday", False) # デフォルトFalse
            )
            parsed_shifts_objects.append(shift_obj)
            print(f"DEBUG_PARSER: Successfully converted OpenAI output to ShiftInfo: {shift_obj.model_dump_json()}")
        except Exception as e: # Pydanticのバリデーションエラーなど
            print(f"ERROR_PARSER: Failed to convert raw shift entry to ShiftInfo object: {raw_shift_entry}. Error: {e}")
            # エラーがあったエントリはスキップするか、部分的にでも記録するか検討
            
    if not parsed_shifts_objects and raw_shifts_list:
        print("WARNING_PARSER: OpenAI returned shift entries, but none could be converted to ShiftInfo objects.")
    elif not parsed_shifts_objects:
        print("INFO_PARSER: No shift information was extracted or parsed.")
        
    return parsed_shifts_objects

# テスト用の簡単な実行 (変更なしでOK、ただし呼び出し方を調整する必要があるかも)
# if __name__ == '__main__':
#     # ... テストコード ...
#     # テスト時には、ocr_text, line_user_id, (db_client), shift_rules_text を用意する必要がある