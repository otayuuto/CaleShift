# app/utils/image_parser.py (新規作成 - 例)
import re
from datetime import datetime

def parse_shift_text(raw_text: str) -> list[dict]:
    """
    Vision APIから抽出されたRAWテキストを解析し、シフト情報のリストを返す。
    各シフト情報は辞書形式で、日付、開始時刻、終了時刻などを含む。
    この関数は非常に単純な例であり、実際のシフト表の形式に合わせて
    高度な解析ロジック（正規表現、キーワード抽出など）が必要。
    """
    parsed_shifts = []
    # 例: "2024/07/20 10:00-18:00 アルバイト" のような行を探す
    # この正規表現は非常に単純なので、実際のデータに合わせて要調整
    pattern = re.compile(r"(\d{4}/\d{1,2}/\d{1,2})\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*(.*)")

    for line in raw_text.splitlines():
        match = pattern.search(line)
        if match:
            date_str, start_time_str, end_time_str, description = match.groups()
            try:
                # 簡単なバリデーションと型変換 (より堅牢なエラー処理が必要)
                shift_date = datetime.strptime(date_str, "%Y/%m/%d").date()
                # 時刻もdatetimeオブジェクトとして扱うと後で便利
                # start_datetime = datetime.strptime(f"{date_str} {start_time_str}", "%Y/%m/%d %H:%M")
                # end_datetime = datetime.strptime(f"{date_str} {end_time_str}", "%Y/%m/%d %H:%M")

                parsed_shifts.append({
                    "date": str(shift_date), # Firestoreには文字列で保存するのが無難な場合も
                    "start_time": start_time_str,
                    "end_time": end_time_str,
                    "description": description.strip() if description else "シフト",
                    "raw_line": line # 元の行も保存しておくとデバッグに便利
                })
            except ValueError as e:
                print(f"Skipping line due to parsing error: {line} - {e}")
                # logger.warning(f"Skipping line due to parsing error: {line} - {e}") # logging使う場合

    return parsed_shifts

# テスト用の簡単な例
if __name__ == '__main__':
    sample_text = """
    シフト表
    2024/07/20 10:00-18:00 アルバイトA
    2024/07/21 13:00 - 17:00 アルバイトB
    休み
    2024/07/22 09:00-15:30
    無効な行
    """
    shifts = parse_shift_text(sample_text)
    for shift in shifts:
        print(shift)