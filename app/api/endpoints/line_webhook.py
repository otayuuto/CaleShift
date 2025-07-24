# app/api/endpoints/line_webhook.py
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi, MessagingApiBlob,
    ReplyMessageRequest, PushMessageRequest, TextMessage as MessagingTextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent as WebhookTextMessageContent,
    ImageMessageContent as WebhookImageMessageContent, FollowEvent,
)
from typing import Optional, List
import traceback
from datetime import date

from app.core.config import settings
# calendar_service と vision_service はこのファイルでは直接不要になる
from app.services import calendar_service, firestore_service, openai_service
from app.utils.image_parser import ShiftInfo
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
    try:
        # --- 1. 画像取得 ---
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Started image processing for message_id: {message_id}")
        message_content_response = line_bot_blob_api.get_message_content(message_id=message_id)
        image_bytes = b''
        if hasattr(message_content_response, 'iter_content'):
            for chunk in message_content_response.iter_content(): image_bytes += chunk
        else: image_bytes = message_content_response

        if not image_bytes:
            raise Exception("LINEからの画像の取得に失敗しました。")
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Retrieved {len(image_bytes)} bytes of image data.")

        # --- 2. ユーザーの勤務場所ID、ルール、対象氏名を取得 ---
        workplace_id = await db_service.get_primary_workplace_id_for_user(user_id)
        if not workplace_id:
            raise Exception("シフトを登録する勤務場所が設定されていません。LIFFアプリから設定してください。")

        print(f"INFO_WEBHOOK: [{user_id}] Using workplace_id '{workplace_id}' for rules and target name.")
        user_shift_rules = await db_service.get_workplace_shift_rules(workplace_id)
        target_name_to_extract = await db_service.get_target_name_for_shift_extraction(user_id, workplace_id)
        
        if not user_shift_rules:
            user_shift_rules = "提供された画像から、日付、氏名、開始時間、終了時間を抽出し、JSON形式で返してください。"
        
        # --- 3. OpenAI APIでシフト情報を解析 ---
        today_date = date.today()
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Requesting OpenAI with image. Target: '{target_name_to_extract or 'All'}'.")
        openai_response_dict = await openai_service.analyze_shift_image_with_rules(
            image_bytes=image_bytes,
            specific_rules_text=user_shift_rules,
            current_date_for_context=today_date,
            target_name=target_name_to_extract,
            image_description="これは従業員の週間または月間勤務シフト表の画像です。"
        )

        if not openai_response_dict or not openai_response_dict.get("shifts"):
            raise Exception("AIが画像からシフト情報を解析できませんでした。")

        # --- 4. 解析結果をPydanticモデルに変換 (検証目的) ---
        parsed_shift_data_list: List[ShiftInfo] = []
        for raw_shift in openai_response_dict["shifts"]:
            try:
                # ターゲット名でのフィルタリング
                if target_name_to_extract and raw_shift.get("name") and target_name_to_extract.lower() not in raw_shift.get("name").lower():
                    continue
                parsed_shift_data_list.append(ShiftInfo(**raw_shift))
            except Exception as e:
                print(f"WARNING: Skipping a shift entry due to pydantic validation error: {e}")
        
        if not parsed_shift_data_list:
            raise Exception(f"AIが画像から「{target_name_to_extract or 'あなた'}」のシフト情報を見つけられませんでした。")

        # --- 5. 解析結果を一時保存し、確認用LIFF URLを送信 ---
        # PydanticオブジェクトをJSONシリアライズ可能な辞書のリストに変換して保存
        shifts_to_save = [shift.model_dump(mode='json') for shift in parsed_shift_data_list]

        pending_id = await db_service.save_pending_shifts(user_id, workplace_id, shifts_to_save)
        if not pending_id:
            raise Exception("解析結果の一時保存に失敗しました。")

        # 確認用LIFF URLを組み立てる (LIFFのエンドポイントURLは .env で管理するのが望ましい)
        confirm_liff_endpoint = "/liff/shifts/confirm" # フェーズ2で作成するLIFFページのパス
        confirm_url = f"{settings.NGROK_URL}{confirm_liff_endpoint}?pending_id={pending_id}"
        
        final_reply_text = (
            f"AIが {len(parsed_shift_data_list)} 件のシフト情報を読み取りました。\n\n"
            "カレンダーに登録する前に、内容が正しいか以下のURLから確認・編集してください。\n"
            f"{confirm_url}"
        )

        # ユーザーにPush Messageで通知
        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Sent confirmation URL to user.")

    except Exception as e:
        # --- 6. エラーハンドリング ---
        print(f"BACKGROUND_TASK_ERROR: [{user_id}] Error in process_image_and_calendar_registration: {e}")
        traceback.print_exc()
        try:
            error_message_to_user = f"画像の処理中にエラーが発生しました。\n理由: {str(e)[:100]}"
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