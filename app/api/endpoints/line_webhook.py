# app/api/endpoints/line_webhook.py
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from linebot.v3.webhook import WebhookHandler # WebhookHandler を直接使う
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi, MessagingApiBlob,
    ReplyMessageRequest, PushMessageRequest, TextMessage as MessagingTextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent as WebhookTextMessageContent,
    ImageMessageContent as WebhookImageMessageContent, FollowEvent,
)
from google.cloud.firestore import Client as FirestoreClient
from typing import Optional, List, Dict, Any # Dict, Any を追加
import traceback
import json # OpenAIのレスポンスを扱うため

from app.core.config import settings
from app.services import vision_service, calendar_service, firestore_service, openai_service
from app.utils.image_parser import ShiftInfo # Pydanticモデルとして使用
from fastapi.concurrency import run_in_threadpool # Firestore呼び出し用
from datetime import date

from app.api.dependencies import get_db_service
from app.services.firestore_service import FirestoreService


router = APIRouter()

# WebhookHandlerのインスタンスを作成 (署名検証とイベントパースに使用)
line_webhook_handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# LINE SDKクライアントの初期化
configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))
line_bot_blob_api = MessagingApiBlob(api_client=ApiClient(configuration))

print("INFO_LINE_WEBHOOK: LINE Messaging API clients initialized successfully.")

async def process_image_and_calendar_registration(
    db_service: FirestoreService,
    user_id: str,
    message_id: str
):
    final_reply_text = "画像の解析とカレンダー登録処理が完了しました。"
    created_event_ids: List[str] = []
    failed_to_create_count = 0
    parse_results_for_reply: List[str] = []
    parsed_shift_data_list: List[ShiftInfo] = []

    try:

        print(f"BACKGROUND_TASK_INFO: [{user_id}] Started image processing for message_id: {message_id}")
        message_content_response = line_bot_blob_api.get_message_content(message_id=message_id)
        image_bytes = b''
        if hasattr(message_content_response, 'iter_content'):
            for chunk in message_content_response.iter_content(): image_bytes += chunk
        else: image_bytes = message_content_response

        if not image_bytes:
            final_reply_text = "LINEからの画像の取得に失敗しました。"
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
            return
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Retrieved {len(image_bytes)} bytes of image data. OCR in progress...")

# --- 2. ユーザーの勤務場所ID、ルール、対象氏名を取得 (ロジックをここに統合) ---
        workplace_id = await db_service.get_primary_workplace_id_for_user(user_id)
        if not workplace_id:
            print(f"BACKGROUND_TASK_ERROR: [{user_id}] No primary workplace found. Cannot proceed.")
            final_reply_text = "シフトを登録する勤務場所が設定されていません。LIFFアプリから設定してください。"
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
            return

        print(f"INFO_WEBHOOK: [{user_id}] Using workplace_id '{workplace_id}' for rules, target name, and history.")
        user_shift_rules = await db_service.get_workplace_shift_rules(workplace_id)
        target_name_to_extract = await db_service.get_target_name_for_shift_extraction(user_id, workplace_id)

        if not user_shift_rules: # ルールが取得できなかった場合のフォールバック
            print(f"WARNING_WEBHOOK: [{user_id}] No specific shift rules found. Using generic prompt.")
            user_shift_rules = "提供された画像から、日付、氏名、開始時間、終了時間を抽出し、JSON形式で返してください。"

        # --- 3. OpenAI APIを呼び出してシフト情報を解析 (画像入力バージョン) ---
        today_date = date.today()
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Requesting OpenAI with image. Target: '{target_name_to_extract or 'All'}'.")
        openai_response_dict = await openai_service.analyze_shift_image_with_rules(
            image_bytes=image_bytes,
            specific_rules_text=user_shift_rules,
            current_date_for_context=today_date,
            target_name=target_name_to_extract,
            image_description="これは従業員の週間または月間勤務シフト表の画像です。表形式になっている可能性が高いです。"
        )

        # --- 4. レスポンスの解析、カレンダー登録、履歴保存 (変更なし) ---
        if openai_response_dict and openai_response_dict.get("shifts") is not None and isinstance(openai_response_dict.get("shifts"), list):
            raw_shifts_from_openai = openai_response_dict["shifts"]
            if not raw_shifts_from_openai:
                final_reply_text = f"AIが画像から「{target_name_to_extract or 'あなた'}」のシフト情報を見つけられませんでした。"
            else:
                for raw_shift in raw_shifts_from_openai:
                    try:
                        shift_obj = ShiftInfo(**raw_shift)
                        # target_nameのフィルタリング
                        if target_name_to_extract and shift_obj.name and target_name_to_extract.lower() not in shift_obj.name.lower():
                            continue
                        parsed_shift_data_list.append(shift_obj)
                    except Exception as e_pydantic:
                        print(f"CRITICAL_WEBHOOK_ERROR: [{user_id}] Failed to convert OpenAI entry to ShiftInfo: {raw_shift}. Error: {e_pydantic}")
                        traceback.print_exc()
                        parse_results_for_reply.append(f"- 解析エラー: {str(raw_shift)[:50]}...")
        else:
            final_reply_text = "AIによるシフト情報の解析に失敗しました (OpenAIからの応答が不正または期待する形式ではありません)。"
            print(f"ERROR_WEBHOOK: [{user_id}] OpenAI response was None or not in expected format. Response: {openai_response_dict}")

        print(f"DEBUG_WEBHOOK: [{user_id}] Final parsed_shift_data_list: {parsed_shift_data_list}")

        if parsed_shift_data_list:
            print(f"DEBUG_WEBHOOK: [{user_id}] parsed_shift_data_list is NOT empty. Proceeding to calendar registration.")
            processed_shifts_count = 0
            for shift_info in parsed_shift_data_list:
                date_str = shift_info.date.strftime("%m/%d") if shift_info.date else "日付不明"
                name_s = f"{shift_info.name} " if shift_info.name else ""
                role_s = f"({shift_info.role})" if shift_info.role else ""
                
                if shift_info.is_holiday:
                    parse_results_for_reply.append(f"- {date_str}: {name_s}休み")
                    continue
                if not shift_info.start_time or not shift_info.end_time or not shift_info.date:
                    start_t = shift_info.start_time.strftime("%H:%M") if shift_info.start_time else "未定"
                    end_t = shift_info.end_time.strftime("%H:%M") if shift_info.end_time else "未定"
                    parse_results_for_reply.append(f"- {date_str}: {name_s}{start_t}～{end_t} {role_s} (情報不備)".strip())
                    failed_to_create_count += 1
                    continue
                
                processed_shifts_count += 1
                start_t = shift_info.start_time.strftime("%H:%M")
                end_t = shift_info.end_time.strftime("%H:%M")
                memo_s = f" [{shift_info.memo}]" if shift_info.memo else ""
                
                event_id = await calendar_service.create_calendar_event(db_service, user_id, shift_info)
                if event_id:
                    created_event_ids.append(event_id)
                    parse_results_for_reply.append(f"- {date_str}: {name_s}{start_t}～{end_t} {role_s}{memo_s} -> 登録成功".strip())

                    print(f"BACKGROUND_TASK_INFO: [{user_id}] Logging successful shift to history for workplace {workplace_id}. Event ID: {event_id}")
                    await db_service.log_shift_history( # db_service経由で呼び出す
                        workplace_id=workplace_id,
                        line_user_id=user_id,
                        shift_info=shift_info,
                        calendar_event_id=event_id, # ★★★ ここで定義済みの event_id を渡す ★★★
                        status="created"
                    )

                else:
                    failed_to_create_count += 1
                    parse_results_for_reply.append(f"- {date_str}: {name_s}{start_t}～{end_t} {role_s}{memo_s} -> 登録失敗".strip())
            
            if not parsed_shift_data_list: # ShiftInfoに変換できるものがなかった場合
                if not final_reply_text or final_reply_text == "画像の解析とカレンダー登録処理が完了しました。":
                    final_reply_text = "AIがシフト情報を解析しましたが、カレンダーに登録できる形式ではありませんでした。"
            elif processed_shifts_count == 0 : # 有効なシフトがなかった
                final_reply_text = "解析された情報:\n" + "\n".join(parse_results_for_reply)
                final_reply_text += "\n\nカレンダーに登録可能な有効なシフトが見つかりませんでした。"
            elif created_event_ids:
                final_reply_text = f"{len(created_event_ids)}件のシフトをカレンダーに登録しました。"
                if failed_to_create_count > 0:
                    final_reply_text += f"\n{failed_to_create_count}件は登録/処理できませんでした。"
                final_reply_text += "\n\n処理結果:\n" + "\n".join(parse_results_for_reply)
            elif failed_to_create_count > 0: # 全て失敗
                final_reply_text = f"{failed_to_create_count}件全てのシフトの登録/処理に失敗しました。"
                final_reply_text += "\n\n処理結果:\n" + "\n".join(parse_results_for_reply)
            # (elseブロックは不要)
        elif not final_reply_text or final_reply_text == "画像の解析とカレンダー登録処理が完了しました。":
            print(f"DEBUG_WEBHOOK: [{user_id}] parsed_shift_data_list IS empty AND final_reply_text is not set to a specific error. Setting generic parse error.")
            final_reply_text = "AIが画像からシフト情報を解析できませんでした。" # または類似のメッセージ
        else:
            print(f"DEBUG_WEBHOOK: [{user_id}] parsed_shift_data_list IS empty BUT final_reply_text was already set to: {final_reply_text}")

        if len(final_reply_text) > 4800:
            final_reply_text = final_reply_text[:4800] + "\n...(長すぎるため省略)"
        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Pushed final result to user.")

    except Exception as e:
        print(f"BACKGROUND_TASK_ERROR: [{user_id}] Unhandled error in process_image_and_calendar_registration: {e}")
        traceback.print_exc()
        try:
            error_message_to_user = "画像の処理中に予期せぬエラーが発生しました。運営にご連絡ください。"
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=error_message_to_user)]))
        except Exception as e2:
            print(f"BACKGROUND_TASK_ERROR: [{user_id}] Failed to send final error push message: {e2}")


@router.post("/callback", summary="LINE Bot Webhook callback")
async def line_webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db_service: FirestoreService = Depends(get_db_service)
):
    signature = request.headers.get("X-Line-Signature")
    if not signature: raise HTTPException(status_code=400, detail="X-Line-Signature header not found")
    body_bytes = await request.body()
    body = body_bytes.decode('utf-8')
    print(f"INFO_WEBHOOK: Received webhook body (first 500 chars): {body[:500]}...")
    # db_service = request.app.state.db
    try:
        events = line_webhook_handler.parser.parse(body, signature) # parserだけ使う
    except InvalidSignatureError: # ... (エラー処理)
        print("ERROR_WEBHOOK: Invalid signature.")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e: # ... (エラー処理)
        print(f"ERROR_WEBHOOK: Error parsing webhook body: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error parsing webhook body")

    for event in events:
        user_id = event.source.user_id if event.source else "unknown_user"
        print(f"INFO_WEBHOOK: Processing event for user_id: {user_id}, event_type: {event.type}")
        if isinstance(event, MessageEvent):
            if isinstance(event.message, WebhookImageMessageContent):
                print(f"INFO_WEBHOOK: Image event from {user_id}. Msg ID: {event.message.id}. Adding to background.")
                try:
                    line_bot_api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[MessagingTextMessage(text="画像を受け付けました。AIがシフト情報を解析しカレンダーに登録します。少々お待ちください…")]
                    ))
                    print(f"INFO_WEBHOOK: Sent ACK to {user_id} for image message.")
                except Exception as e_ack:
                    print(f"ERROR_WEBHOOK: Failed to send ACK for image message to {user_id}: {e_ack}")
                background_tasks.add_task(
                    process_image_and_calendar_registration,
                    db_service,
                    user_id,
                    event.message.id
                )
            elif isinstance(event.message, WebhookTextMessageContent):
                handle_text_message_sync(event)
            else:
                print(f"INFO_WEBHOOK: Received other message type from {user_id}: {event.message.type}")
        elif isinstance(event, FollowEvent):
            await handle_follow_event(db_service, event)
        else:
            print(f"INFO_WEBHOOK: Received other event type: {event.type}")
    return "OK"


def handle_text_message_sync(event: MessageEvent): # 同期関数のまま
    user_id = event.source.user_id if event.source else "unknown_user"
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "Unknown"
    print(f"INFO_WEBHOOK: Text message from {user_id}: \"{received_text}\"")
    try:
        reply_msg = f"テキスト「{received_text}」を認識しました。"
        if received_text.lower() == "連携状況": reply_msg = "Googleカレンダー連携はLIFFアプリから確認・設定できます。"
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[MessagingTextMessage(text=reply_msg)]))
        print(f"INFO_WEBHOOK: Replied to text message for {user_id}")
    except Exception as e:
        print(f"ERROR_WEBHOOK: Error sending text reply for {user_id}: {e}")
        traceback.print_exc()

async def handle_follow_event(db_service: FirestoreService, event: FollowEvent):
    line_user_id = event.source.user_id
    reply_token = event.reply_token
    print(f"INFO_WEBHOOK: User {line_user_id} followed the bot.")
    if not db_service:
        print(f"ERROR_WEBHOOK: FirestoreService not available in handle_follow_event for {line_user_id}")
        return
    display_name = None # Profile API呼び出しは省略
    print(f"INFO_WEBHOOK: [FollowEvent] Display name acquisition skipped for simplicity for {line_user_id}.")
    success = await db_service.create_initial_user_document_on_follow(line_user_id, display_name)
    if success:
        message_text = "友だち追加ありがとうございます！シフト管理ボットです。"
        if settings.NGROK_URL:
            # LIFFのGoogleカレンダー連携設定ページへのURLを案内する
            liff_auth_url = f"{settings.NGROK_URL}/liff/google-calendar-auth" # liff_settings.pyで定義したパス
            # LIFF URLにline_idを含める必要はない (LIFF SDKが取得するため)
            message_text += (
                "\n\nシフトをカレンダーに自動登録するには、Googleアカウントとの連携が必要です。"
                f"\n以下のURLから連携設定ページを開いてください。\n{liff_auth_url}"
            )
        else:
            message_text += "\n\nGoogle連携機能は現在準備中です。"
        try:
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[MessagingTextMessage(text=message_text)]))
            print(f"INFO_WEBHOOK: Sent follow-up message to {line_user_id}")
        except Exception as e_reply:
            print(f"ERROR_WEBHOOK: Failed to send follow-up message to {line_user_id}: {e_reply}")
    else:
        print(f"ERROR_WEBHOOK: Failed to create initial user document for {line_user_id} on follow.")