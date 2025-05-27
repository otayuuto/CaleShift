# app/utils/image_parser.py
import re
from datetime import datetime, time, date
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, field_validator

# ShiftInfoモデルとバリデータは変更なしでOK

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

    @field_validator('date', mode='before')
    @classmethod
    def parse_date_str(cls, value):
        if isinstance(value, str):
            current_year = datetime.now().year
            match_m_d_jp = re.fullmatch(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", value.strip())
            if match_m_d_jp:
                month, day_val = int(match_m_d_jp.group(1)), int(match_m_d_jp.group(2))
                try:
                    return date(current_year, month, day_val)
                except ValueError:
                    raise ValueError(f"Invalid date: {value}")
            raise ValueError(f"Unsupported date format: {value}")
        elif isinstance(value, datetime):
            return value.date()
        elif isinstance(value, date):
            return value
        return value

    @field_validator('start_time', 'end_time', mode='before')
    @classmethod
    def parse_time_str(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() == "休み":
                return None
            
            match_hm = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
            if match_hm:
                hour, minute = int(match_hm.group(1)), int(match_hm.group(2))
                try:
                    if hour == 24 and minute == 0:
                        hour = 0
                    return time(hour, minute)
                except ValueError:
                    raise ValueError(f"Invalid time: {value}")
            raise ValueError(f"Unsupported time format: {value}")
        elif isinstance(value, time):
            return value
        return value

def is_likely_name(text: str) -> bool:
    """氏名らしき文字列かどうかを判定する（簡易版）"""
    # 2文字以上で、数字や時刻パターンを含まない、など
    if len(text) >= 2 and not re.search(r"\d", text) and ":" not in text and "月" not in text and "日" not in text:
        # さらに漢字・ひらがな・カタカナのみ、などのチェックも有効
        if re.fullmatch(r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\uFF00-\uFFEF\u4E00-\u9FAF]+", text): # 全角文字のみ
             return True
    return False

def is_role(text: str) -> bool:
    """担当らしき文字列かどうか"""
    return any(kw in text for kw in ["ホール", "フロント"])

def is_time_str(text: str) -> bool:
    """HH:MM 形式の時刻文字列かどうか"""
    return bool(re.fullmatch(r"\d{1,2}\s*:\s*\d{2}", text.strip()))

def parse_shift_text_to_structured_data(text: str) -> List[ShiftInfo]:
    parsed_shifts: List[ShiftInfo] = []
    lines = [line.strip() for line in text.split('\n') if line.strip()] # 空行を除去

    table_date: Optional[date] = None
    current_year = datetime.now().year

    # 1. 全体の日付を抽出
    temp_lines_for_date_extraction = lines[:] # 元のlinesを変更しないようにコピー
    for i, line_content in enumerate(temp_lines_for_date_extraction):
        date_header_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", line_content)
        if date_header_match:
            month = int(date_header_match.group(1))
            day_val = int(date_header_match.group(2))
            try:
                table_date = date(current_year, month, day_val)
                print(f"INFO: Table date found: {table_date}")
                # 日付が見つかった行より後を処理対象とする (元のlinesから日付行を除く)
                # ただし、この日付情報自体が他の情報と混ざっている可能性もある
                # ここでは、日付が見つかったらそれを使用し、lines全体をスキャンする方針は維持
                break 
            except ValueError:
                print(f"WARNING: Found date-like pattern but invalid: {line_content}")
                pass
    
    if not table_date:
        print("WARNING: Could not determine the date for the shift table. Shifts won't be parsed without a date.")
        return [] # 日付が不明な場合は処理しない

    # 2. シフト情報のレコードを再構築しながらパース
    #    「氏名」->「担当」->「開始時間」->「終了時間」の順で出現すると仮定
    
    current_record: Dict[str, Any] = {}
    # 期待する次の要素のタイプ: 'name', 'role', 'start_time', 'end_time'
    expecting_next = 'name' 

    for line_idx, line_content in enumerate(lines):
        print(f"DEBUG: Processing line {line_idx}: \"{line_content}\" (Expecting: {expecting_next})")

        # "シフト表" や ヘッダーキーワードを含む行は情報抽出の対象外とする
        if "シフト表" in line_content or any(kw in line_content for kw in ["区別", "氏名", "担当", "開始", "終了"]):
            if current_record and 'start_time' in current_record: # 途中のレコードがあれば確定させる
                try:
                    shift = ShiftInfo(date=table_date, **current_record)
                    parsed_shifts.append(shift)
                    print(f"INFO: Parsed shift record (before header/title): {shift}")
                except ValueError as e:
                    print(f"ERROR: Could not create ShiftInfo from partial record {current_record}: {e}")
                current_record = {}
                expecting_next = 'name'
            print(f"DEBUG: Skipping header-like/title line: \"{line_content}\"")
            continue
        
        # 行番号らしきもの ("3", "4" など) もスキップ
        if re.fullmatch(r"\d{1,2}", line_content):
            print(f"DEBUG: Skipping line number-like: \"{line_content}\"")
            continue

        is_line_holiday = "休み" in line_content or "休業" in line_content

        if expecting_next == 'name':
            if is_likely_name(line_content):
                current_record['name'] = line_content
                expecting_next = 'role'
                if is_line_holiday: # 名前の行に「休み」があれば、そのレコードは休みとしてほぼ確定
                    current_record['is_holiday'] = True
                    # 休みの場合、次の担当や時間は必須ではない
            elif is_role(line_content): # 名前より先に担当が見つかる場合もあるかも
                current_record['role'] = line_content
                expecting_next = 'start_time' # 名前は不明のまま
            elif is_time_str(line_content): # 名前も担当もなくいきなり時間
                current_record['start_time'] = line_content.replace(" ", "")
                expecting_next = 'end_time'
            else:
                print(f"DEBUG: Expecting name, but got: \"{line_content}\". Resetting current record if any.")
                if current_record and 'start_time' in current_record : #不完全なレコードは保存しないか検討
                    pass # ここでは一旦保持
                # current_record = {} # リセットする方が安全かも
                # expecting_next = 'name'

        elif expecting_next == 'role':
            if is_role(line_content):
                current_record['role'] = line_content
                expecting_next = 'start_time'
            elif is_time_str(line_content): # 担当なしで時間
                current_record['start_time'] = line_content.replace(" ", "")
                expecting_next = 'end_time'
            elif is_likely_name(line_content): # 次の人の名前が来た場合、前のレコードを確定
                if current_record and 'name' in current_record: # 前のレコードに名前がある
                    # 前のレコードには開始時間がないかもしれない (例: Aさん(名前) -> Bさん(名前) -> Bさんの担当...)
                    # ここでは、start_timeがないレコードはまだ不完全として、新しい名前で上書きする
                    print(f"DEBUG: New name \"{line_content}\" found while expecting role for \"{current_record.get('name')}\". Resetting for new person.")
                    # 以前の不完全なレコードをどう扱うか？ここでは破棄して新しい名前で開始
                    current_record = {'name': line_content}
                    expecting_next = 'role' # 新しい人の担当を期待
                else: # 前のレコードに名前がない場合、これが名前かもしれない
                     current_record['name'] = line_content
                     expecting_next = 'role' # 担当を期待
            else: # 期待外のものが来た場合
                print(f"DEBUG: Expecting role, but got: \"{line_content}\".")
                # ここでレコードを確定させるか、継続するかはポリシーによる
                # ひとまず、次の要素を期待せずに進めてみる（次の行で時間が見つかることを期待）
                expecting_next = 'start_time'


        elif expecting_next == 'start_time':
            if is_time_str(line_content):
                current_record['start_time'] = line_content.replace(" ", "")
                expecting_next = 'end_time'
            elif is_likely_name(line_content): # 次の人の名前が来た場合、前のレコードを確定
                if current_record.get('name') and current_record.get('start_time') is None and not current_record.get('is_holiday'):
                    print(f"WARNING: Name \"{current_record.get('name')}\" had no start time, assuming it might be a day off or error. Processing next name.")
                elif current_record and ('start_time' in current_record or current_record.get('is_holiday')):
                    try:
                        shift = ShiftInfo(date=table_date, **current_record)
                        parsed_shifts.append(shift)
                        print(f"INFO: Parsed shift record (new name found): {shift}")
                    except ValueError as e:
                        print(f"ERROR: Could not create ShiftInfo from record {current_record}: {e}")
                current_record = {'name': line_content} # 新しいレコード開始
                expecting_next = 'role'
            else: # 期待外
                print(f"DEBUG: Expecting start_time, but got: \"{line_content}\".")
                # レコードをリセットするか、次のend_timeを期待するか。
                # ここでは、もし名前があれば、休みとみなせるか検討。なければリセット。
                if current_record.get('name') and not current_record.get('start_time'): # 開始時間がないまま別の情報
                    # is_holiday が既に設定されていなければ、この行の内容で判断
                    if is_line_holiday and not current_record.get('is_holiday'):
                        current_record['is_holiday'] = True
                        # 休みならここでレコード確定
                        try:
                            shift = ShiftInfo(date=table_date, **current_record)
                            parsed_shifts.append(shift)
                            print(f"INFO: Parsed holiday record (expecting start_time): {shift}")
                        except ValueError as e:
                            print(f"ERROR: Could not create ShiftInfo from record {current_record}: {e}")
                        current_record = {}
                        expecting_next = 'name'
                    # else: # 休みでもないし、時間でもない。前のレコードをどうするか。
                        # print(f"DEBUG: Incomplete record for {current_record.get('name')}, no start time or holiday. Resetting.")
                        # current_record = {}
                        # expecting_next = 'name'

        elif expecting_next == 'end_time':
            if is_time_str(line_content):
                current_record['end_time'] = line_content.replace(" ", "")
                # レコードが完成したのでShiftInfoを作成してリストに追加
                try:
                    shift = ShiftInfo(date=table_date, **current_record)
                    parsed_shifts.append(shift)
                    print(f"INFO: Parsed shift record (end_time found): {shift}")
                except ValueError as e:
                    print(f"ERROR: Could not create ShiftInfo from record {current_record}: {e}")
                current_record = {} # レコードをリセット
                expecting_next = 'name' # 次の人の名前を期待
            elif is_likely_name(line_content) or is_role(line_content) or is_time_str(line_content): # 終了時間ではなく次のレコードの情報が来た
                # 開始時間はあったが終了時間がないレコードを確定
                if current_record and 'start_time' in current_record:
                    print(f"WARNING: End time not found for record {current_record}, but new data \"{line_content}\" started. Saving with no end time.")
                    try:
                        shift = ShiftInfo(date=table_date, **current_record)
                        parsed_shifts.append(shift)
                        print(f"INFO: Parsed shift record (no end_time, new data found): {shift}")
                    except ValueError as e:
                        print(f"ERROR: Could not create ShiftInfo from record {current_record}: {e}")
                
                # 新しい情報の処理を開始
                current_record = {}
                expecting_next = 'name'
                # この行自体を再処理するために、ループのインデックスを戻すか、
                # またはこの行の情報をここで処理する。
                # 今回は、この行の情報を次のループで処理させるために、
                # current_record をリセットし、expecting_next を 'name' にして、
                # 次のループでこの行が 'name' として評価されるようにする。
                # より正確には、この行を再度処理するメカニズムが必要だが、ここでは単純化。
                # 簡易的には、この行の情報を再度評価させる
                if is_likely_name(line_content):
                    current_record['name'] = line_content
                    expecting_next = 'role'
                elif is_role(line_content):
                    current_record['role'] = line_content
                    expecting_next = 'start_time'
                elif is_time_str(line_content):
                    current_record['start_time'] = line_content.replace(" ", "")
                    expecting_next = 'end_time'

            else: # 期待外
                print(f"DEBUG: Expecting end_time, but got: \"{line_content}\". Finalizing record if possible.")
                if current_record and 'start_time' in current_record:
                    try:
                        shift = ShiftInfo(date=table_date, **current_record) # 終了時間なしで保存
                        parsed_shifts.append(shift)
                        print(f"INFO: Parsed shift record (no end_time, unexpected data): {shift}")
                    except ValueError as e:
                        print(f"ERROR: Could not create ShiftInfo from record {current_record}: {e}")
                current_record = {}
                expecting_next = 'name'
        
        # 休みフラグが立っていて、まだレコードが確定していなければ確定させる
        if current_record.get('is_holiday') and current_record.get('name') and \
           (expecting_next != 'name' or not parsed_shifts or parsed_shifts[-1].name != current_record.get('name')): # まだこの人の休みが保存されてない
            try:
                shift = ShiftInfo(date=table_date, **current_record)
                parsed_shifts.append(shift)
                print(f"INFO: Parsed holiday record (end of line processing): {shift}")
            except ValueError as e:
                print(f"ERROR: Could not create ShiftInfo from holiday record {current_record}: {e}")
            current_record = {}
            expecting_next = 'name'


    # ループ終了後、最後の不完全なレコードがあれば処理
    if current_record and ('start_time' in current_record or current_record.get('is_holiday')) and table_date:
        print(f"DEBUG: Processing leftover record: {current_record}")
        try:
            shift = ShiftInfo(date=table_date, **current_record)
            # 最後のレコードが有効かどうかのチェック
            if shift.start_time or shift.is_holiday:
                 parsed_shifts.append(shift)
                 print(f"INFO: Parsed leftover shift record: {shift}")
            else:
                print(f"DEBUG: Discarding leftover record as it's not a valid shift/holiday: {shift}")
        except ValueError as e:
            print(f"ERROR: Could not create ShiftInfo from leftover record {current_record}: {e}")


    if not parsed_shifts and lines:
        print("WARNING: No shifts were parsed using the new logic.")

    return parsed_shifts


if __name__ == '__main__':
    # ログの例から再構築したテキスト (実際のOCR結果はこれより揺れる)
    ocr_output_from_log = """
シフト表
5月 27日
区別
氏名
担当
開始時間終了時間
3
渡邊遼
ホール
10:00
16:00
4
渡邊荅士
フロント
10:00
16:00
5
6
金田翔
フロント
16:00
0:00
7
太田悠登
ホール
16:00
0:00
8
6
10
11
12
13
14
E
15
>>
Sheet1
準備完了
アクセシビリティ: 問題ありません ページ: 1/2
検索
SC
F1
3
    """
    print("--- Sample from OCR Log ---")
    shifts_from_ocr = parse_shift_text_to_structured_data(ocr_output_from_log)
    for shift in shifts_from_ocr:
        print(shift.model_dump_json(indent=2))

    print("\n--- Original Image Example ---")
    sample_text_vision_api_like = """
シフト表 5月 27日
区別 氏名 担当 開始時間 終了時間
渡邉遥 ホール 10:00 16:00
渡邉杏士 フロント 10:00 16:00
金田翔 フロント 16:00 0:00
太田悠登 ホール 16:00 0:00
    """
    shifts_from_image_orig = parse_shift_text_to_structured_data(sample_text_vision_api_like)
    for shift in shifts_from_image_orig:
        print(shift.model_dump_json(indent=2))