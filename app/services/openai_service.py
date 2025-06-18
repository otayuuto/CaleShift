# app/services/openai_service.py
import openai # type: ignore
from typing import Optional, Dict, Any
import json
import traceback
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings

# OpenAI APIキーの確認 (モジュールロード時)
OPENAI_API_KEY_CONFIGURED = False
if settings.OPENAI_API_KEY:
    OPENAI_API_KEY_CONFIGURED = True
    print("INFO_OPENAI_SERVICE: OpenAI API key found in settings.")
else:
    print("CRITICAL_OPENAI_SERVICE: OPENAI_API_KEY not found in settings. OpenAI API will not work.")

async def analyze_shift_text_with_rules(
    ocr_text: str,
    shift_rules: str,
    target_name: Optional[str] = None,
    image_description: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    OCRテキストとシフト記述ルール、抽出対象氏名を元に、OpenAI APIを使ってシフト情報を解析します。
    """
    if not OPENAI_API_KEY_CONFIGURED:
        print("ERROR_OPENAI_SERVICE: OpenAI API key not configured. Cannot analyze text.")
        return None # または {"shifts": []} を返して呼び出し側でハンドリング
    if not ocr_text:
        print("WARNING_OPENAI_SERVICE: OCR text is empty. Cannot analyze.")
        return {"shifts": []}
    if not shift_rules:
        print("WARNING_OPENAI_SERVICE: Shift rules are empty. Analysis might be less accurate.")
        # ルールがない場合は、汎用的な指示にする
        shift_rules = "一般的なシフト表の形式に従い、日付、氏名、開始時間、終了時間を抽出してください。"

    system_prompt_content = (
        "あなたはシフト表解析の専門家です。提供されたOCRテキストを、与えられたシフト記述ルールおよび抽出対象の氏名（もしあれば）に基づいて正確に解析し、"
        "シフト情報をJSON形式で出力してください。\n"
        "各シフトエントリには、date (YYYY-MM-DD形式)、start_time (HH:MM形式、24時間表記)、end_time (HH:MM形式、24時間表記)、"
        "name (文字列、無ければnull)、role (文字列、無ければnull)、memo (文字列、無ければnull)、is_holiday (boolean) を含めてください。\n"
        "日付の年は、特に指定がなければ現在の年と仮定し、月と日から完全な日付を生成してください。\n"
        "時刻が「休み」や「0:00-0:00」のように実質的な休みを示す場合は、is_holidayをtrueにしてください。それ以外はis_holiday: falseです。\n"
        "出力は必ず指定のJSONフォーマットに従い、余計な説明や前置きは不要です。"
    )
    if target_name:
        system_prompt_content += f"\n特に「{target_name}」という氏名の人物のシフト情報のみを抽出対象とします。他の人物の情報は結果に含めないでください。"
    else:
        system_prompt_content += "\n画像に含まれる全ての人物のシフト情報を抽出してください。"

    user_prompt_content = (
        f"以下のOCRテキストを、下記のシフト記述ルールに従って解析してください。\n\n"
        f"--- シフト記述ルール ---\n{shift_rules}\n\n"
    )
    if target_name:
        user_prompt_content += f"--- 抽出対象の氏名 ---\n{target_name}\n\n"
    if image_description:
        user_prompt_content += f"--- 画像に関する補足情報 ---\n{image_description}\n\n"

    user_prompt_content += (
        "OCRテキスト:\n"
        f"{ocr_text}\n\n"
        "解析結果を以下のJSON形式で返してください:\n"
        "{\n"
        "  \"shifts\": [\n"
        "    {\n"
        "      \"date\": \"YYYY-MM-DD\",\n"
        "      \"start_time\": \"HH:MM\",\n"
        "      \"end_time\": \"HH:MM\",\n"
        "      \"name\": \"氏名\",\n"
        "      \"role\": \"担当\",\n"
        "      \"memo\": \"メモ\",\n"
        "      \"is_holiday\": false\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "対象のシフト情報が全く見つからない場合は、`{\"shifts\": []}` を返してください。"
    )

    prompt_messages = [
        {"role": "system", "content": system_prompt_content},
        {"role": "user", "content": user_prompt_content}
    ]

    response_content_str = None # エラー時のログ出力用
    try:
        print(f"DEBUG_OPENAI_SERVICE: Sending request to OpenAI. Prompt user text length: {len(user_prompt_content)}")
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY) # APIキーを使ってクライアントを初期化

        completion = await run_in_threadpool(
            client.chat.completions.create,
            model="gpt-4.1-nano-2025-04-14", # JSONモードをサポートするモデル
            response_format={"type": "json_object"}, # JSONモードを有効化
            messages=prompt_messages,
            temperature=0.1,
            max_tokens=2048 # 必要に応じて調整
        )
        response_content_str = completion.choices[0].message.content
        print(f"DEBUG_OPENAI_SERVICE: Received response from OpenAI API (first 500 chars): {response_content_str[:500] if response_content_str else 'None'}")

        if not response_content_str:
            print("ERROR_OPENAI_SERVICE: OpenAI API returned empty content.")
            return {"shifts": []}

        parsed_json = json.loads(response_content_str)
        if "shifts" not in parsed_json or not isinstance(parsed_json["shifts"], list):
            print(f"ERROR_OPENAI_SERVICE: OpenAI API response is not in the expected JSON format. Missing 'shifts' list. Response: {parsed_json}")
            return {"shifts": []}
        return parsed_json
    except json.JSONDecodeError as e:
        print(f"ERROR_OPENAI_SERVICE: Failed to decode JSON response from OpenAI: {e}. Response was: {response_content_str}")
        return {"shifts": []}
    except openai.APIError as e: # openaiライブラリのAPIエラー
        print(f"ERROR_OPENAI_SERVICE: OpenAI API returned an API Error: {e.status_code} - {e.message}")
        return None # APIエラーの場合はNoneを返して呼び出し元で区別できるようにする
    except Exception as e:
        print(f"ERROR_OPENAI_SERVICE: An unexpected error occurred while calling OpenAI API: {e}")
        traceback.print_exc()
        return None # その他の予期せぬエラーもNoneを返す