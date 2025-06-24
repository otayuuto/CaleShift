# app/services/openai_service.py
import openai
from typing import List, Optional, Dict, Any
import json
import traceback
from fastapi.concurrency import run_in_threadpool
from datetime import date, timedelta # timedelta をインポート
import base64

from app.core.config import settings

OPENAI_API_KEY_CONFIGURED = bool(settings.OPENAI_API_KEY)
if OPENAI_API_KEY_CONFIGURED:
    print("INFO_OPENAI_SERVICE: OpenAI API key found in settings.")
else:
    print("CRITICAL_OPENAI_SERVICE: OPENAI_API_KEY not found. OpenAI API will not work.")


async def analyze_shift_image_with_rules(
    image_bytes: bytes,
    specific_rules_text: str,
    current_date_for_context: date,
    target_name: Optional[str] = None,
    image_description: Optional[str] = "..."
) -> Optional[Dict[str, Any]]:
    if not OPENAI_API_KEY_CONFIGURED:
        print("CRITICAL_OPENAI_SERVICE: API key not configured. Returning None.")
        return None
    if not image_bytes:
        print("WARNING_OPENAI_SERVICE: Image bytes are empty. Returning {'shifts': []}.")
        return {"shifts": []}
    if not specific_rules_text:
        print("WARNING_OPENAI_SERVICE: Specific rules text is empty. Using generic. Returning {'shifts': []} for safety.")
        # または、ここでNoneを返すか、汎用ルールで試行するか
        # return {"shifts": []} 
        specific_rules_text = "画像からシフト情報を抽出してください。"

    current_date_str = current_date_for_context.strftime('%Y年%m月%d日')
    current_year = current_date_for_context.year

    # ★★★ プロンプトに現在の日付情報を組み込む ★★★
    system_prompt_content = (
        f"あなたは超高精度なシフト表解析AIです。本日は {current_date_str} です。\n"
        "提供される画像は、従業員の1日分の勤務シフトが記載された表です。\n"
        "**最重要タスク: 画像を上から下へ1行ずつ処理し、各行が誰のどのようなシフト情報を示しているかを特定し、JSON形式で出力すること。**\n\n"
        "解析ステップ:\n"
        "1. **日付の特定:** ユーザー提供の『勤務場所固有のシフト表ルール』の「日付に関するルール」と画像全体から、このシフト表が示す単一の日付 (YYYY-MM-DD形式) を決定してください。この日付は抽出される全てのシフトエントリに適用されます。\n"
        f"   (年が不明な場合は {current_year}年 としてください。月またぎルールも考慮してください。)\n\n"
        "2. **各行の情報のパース:** 画像の表部分を1行ずつ見てください。\n"
        "   各行には通常、「氏名」「担当」「開始時間」「終了時間」の情報が含まれていると期待されます。これらの情報を正確に抜き出してください。\n"
        "   - **氏名 (name):** その行の人物の名前を抽出します。\n"
        "   - **担当 (role):** もしあれば、その人物の担当や役割を抽出します。なければnull。\n"
        "   - **開始時間 (start_time) と 終了時間 (end_time):** ユーザー提供の『勤務場所固有のシフト表ルール』の「時刻に関するルール」に従い、HH:MM形式で抽出します。勤務がない場合やルールで休みと判断される場合はnullにしてください。\n"
        "   - **休み (is_holiday):** 開始時間と終了時間が両方nullの場合、またはルールで休みと明示されている場合はtrue、それ以外はfalseとします。\n"
        "ステップ4: JSON形式での出力\n"
        "  - 上記ステップで得られた情報を元に、各シフトエントリをJSONオブジェクトとしてください。\n"
        "  - 各エントリには、date (YYYY-MM-DD)、start_time (HH:MM)、end_time (HH:MM)、name、role、memo (もしあればnull)、is_holiday (boolean) を含めてください。\n"
        "  - 氏名が特定できないシフトはnameをnullにしてください。roleやmemoも同様です。\n"
        "出力は必ず指定のJSONフォーマットに従い、余計な説明や前置きは一切不要です。\n"
        "シフト情報が全く見つからない場合は、`{\"shifts\": []}` という空のリストを含むJSONを返してください。"
    )

    if target_name:
        system_prompt_content += (
            f"\n--- ★★★最重要抽出対象★★★ ---\n"
            f"このシフト表から、**氏名が「{target_name}」と完全に一致する人物のシフト情報のみを抽出してください。** " # 「完全に一致する」を追加
            f"他の全ての人物の情報は無視し、結果のJSONには「{target_name}」さんのシフトのみを含めてください。"
            f"もし「{target_name}」という名前の人物が見つからない、またはその人物のシフト情報が一切ない場合は、必ず `{{\"shifts\": []}}` という空のJSONを返してください。"
        )
    else:
        system_prompt_content += "\n--- 抽出対象の氏名 ---\n画像に含まれる全ての人物のシフト情報を抽出してください。"

    base64_image = base64.b64encode(image_bytes).decode('utf-8')


    user_message_content_list: List[Dict[str, Any]] = [ # 変数名を変更して型ヒントを明確に
        {"type": "text", "text": f"本日は {current_date_str} です...\n--- 勤務場所固有のシフト表ルール ---\n{specific_rules_text}\n\n"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "auto"}}
    ]
    
    if image_description: user_message_content_list[0]["text"] += f"\n--- 画像に関する補足情報 ---\n{image_description}\n\n"
    user_message_content_list[0]["text"] += "\n--- 解析結果の出力 (JSON形式) ---\n..."
    
    prompt_messages = [
        {"role": "system", "content": system_prompt_content},
        {"role": "user", "content": user_message_content_list} # ★ user_message_content_list を使用
    ]

    response_content_str = None
    try:
        print(f"DEBUG_OPENAI_SERVICE: Attempting OpenAI API call with model: {settings.OPENAI_MODEL_NAME or 'gpt-4o-mini'}.")
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        
        # ★★★ API呼び出しの直前にもう一度ログ ★★★
        print(f"DEBUG_OPENAI_SERVICE: Messages being sent to OpenAI (type: {type(prompt_messages)}):")
        # messagesの内容が非常に長くなる可能性があるので、主要な部分だけ表示するか、長さを表示
        print(f"DEBUG_OPENAI_SERVICE: System prompt length: {len(prompt_messages[0]['content'])}")
        if isinstance(prompt_messages[1]['content'], list):
            print(f"DEBUG_OPENAI_SERVICE: User message parts: {len(prompt_messages[1]['content'])}")
            for i, part in enumerate(prompt_messages[1]['content']):
                if part['type'] == 'text':
                    print(f"DEBUG_OPENAI_SERVICE: User message text part {i} (first 100 chars): {part['text'][:100]}")
                elif part['type'] == 'image_url':
                    print(f"DEBUG_OPENAI_SERVICE: User message image part {i} (URL starts with): {part['image_url']['url'][:100]}")
        else: # 古いテキストのみのプロンプトの場合 (念のため)
            print(f"DEBUG_OPENAI_SERVICE: User prompt (text only, first 100 chars): {prompt_messages[1]['content'][:100]}")


        completion = await run_in_threadpool(
            client.chat.completions.create,
            model=settings.OPENAI_MODEL_NAME or "gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=prompt_messages,
            temperature=0.1,
            max_tokens=3000
        )
        print("DEBUG_OPENAI_SERVICE: OpenAI API call nominally successful (status-wise).")

        if completion.choices and completion.choices[0].message:
            response_content_str = completion.choices[0].message.content
            print(f"DEBUG_OPENAI_SERVICE: Received raw response content (first 500): {response_content_str[:500] if response_content_str else 'None'}")
        else:
            print("ERROR_OPENAI_SERVICE: OpenAI API response structure unexpected. No choices or message found.")
            print(f"DEBUG_OPENAI_SERVICE: Full completion object: {completion.model_dump_json(indent=2) if completion else 'None'}")
            return None # 予期せぬレスポンス構造

        if not response_content_str:
            print("ERROR_OPENAI_SERVICE: OpenAI API returned empty content string in message.")
            return {"shifts": []}

        parsed_json = json.loads(response_content_str)
        print(f"DEBUG_OPENAI_SERVICE: Successfully parsed JSON response: {str(parsed_json)[:500]}")

        if "shifts" not in parsed_json or not isinstance(parsed_json["shifts"], list):
            print(f"ERROR_OPENAI_SERVICE: Parsed JSON not in expected format. Response: {parsed_json}")
            return {"shifts": []}
        
        print(f"DEBUG_OPENAI_SERVICE: Returning successfully from analyze_shift_image_with_rules with {len(parsed_json['shifts'])} shifts.")
        return parsed_json
    
    except json.JSONDecodeError as e:
        print(f"CRITICAL_OPENAI_ERROR: Failed to decode JSON response. Returning {{'shifts': []}}.")
        return {"shifts": []}
    except openai.APIError as e:
        print(f"ERROR_OPENAI_SERVICE: OpenAI API returned an API Error: {e.status_code} - {str(e)}")
        return None
    except Exception as e:
        print(f"ERROR_OPENAI_SERVICE: An unexpected error occurred while calling OpenAI API: {e}")
        traceback.print_exc()
        return None

    except openai.APIStatusError as e: # より具体的なAPIエラーの型
        print(f"CRITICAL_OPENAI_ERROR: API Status Error. Returning None.")
        traceback.print_exc()
        return None # APIエラーの場合はNone

    except openai.APIConnectionError as e:
        print(f"CRITICAL_OPENAI_ERROR: Failed to connect to OpenAI API: {e}")
        traceback.print_exc()
        return None # 接続エラー

    except openai.RateLimitError as e:
        print(f"CRITICAL_OPENAI_ERROR: OpenAI API request exceeded rate limit: {e}")
        traceback.print_exc()
        return None # レートリミットエラー

    except openai.APIError as e: # その他のOpenAIライブラリのAPIエラー
        print(f"CRITICAL_OPENAI_ERROR: OpenAI API returned a generic API Error: {str(e)}")
        traceback.print_exc()
        return None

    except Exception as e: # 予期せぬその他のエラー
        print(f"CRITICAL_OPENAI_ERROR: An unexpected error occurred in analyze_shift_text_with_rules: {e}")
        print(f"CRITICAL_OPENAI_ERROR: An unexpected error occurred. Returning None.")
        traceback.print_exc()
        return None