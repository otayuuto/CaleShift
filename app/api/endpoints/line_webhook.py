# app/api/endpoints/line_webhook.py (統合・修正後)
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, MessagingApiBlob, ReplyMessageRequest, PushMessageRequest, TextMessage as MessagingTextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent as WebhookTextMessageContent, ImageMessageContent as WebhookImageMessageContent, FollowEvent
from typing import Optional, List
import traceback
from datetime import date

from app.core.config import settings
from app.services import calendar_service, openai_service
from app.utils.image_parser import ShiftInfo
from app.api.dependencies import get_db_service
from app.services.firestore_service import FirestoreService

router = APIRouter()

line_webhook_handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))
line_bot_blob_api = MessagingApiBlob(api_client=ApiClient(configuration))

# --- バックグラウンドタスク (画像解析 -> 一時保存 -> 確認URL送信) ---
async def process_image_and_send_confirm_url(db_service: FirestoreService, user_id: str, message_id: str):
    try:
        image_bytes = b''
        message_content_response = line_bot_blob_api.get_message_content(message_id=message_id)
        if hasattr(message_content_response, 'iter_content'):
            for chunk in message_content_response.iter_content(): image_bytes += chunk
        else: image_bytes = message_content_response
        if not image_bytes: raise Exception("LINEからの画像の取得に失敗しました。")

        workplace_id = await db_service.get_primary_workplace_id_for_user(user_id)
        if not workplace_id: raise Exception("シフトを登録する勤務場所が設定されていません。LIFFアプリから設定してください。")

        user_shift_rules = await db_service.get_workplace_shift_rules(workplace_id)
        target_name_to_extract = await db_service.get_target_name_for_shift_extraction(user_id, workplace_id)
        
        openai_response_dict = await openai_service.analyze_shift_image_with_rules(
            image_bytes=image_bytes, specific_rules_text=user_shift_rules or "",
            current_date_for_context=date.today(), target_name=target_name_to_extract
        )
        if not openai_response_dict or not openai_response_dict.get("shifts"):
            raise Exception("AIが画像からシフト情報を解析できませんでした。")

        parsed_shift_data_list = []
        for raw_shift in openai_response_dict["shifts"]:
            try:
                parsed_shift_data_list.append(ShiftInfo(**raw_shift))
            except Exception as e: print(f"WARNING: Skipping a shift entry due to pydantic validation error: {e}")
        if not parsed_shift_data_list:
            raise Exception(f"AIが画像から「{target_name_to_extract or 'あなた'}」のシフト情報を見つけられませんでした。")

        shifts_to_save = [shift.model_dump(mode='json') for shift in parsed_shift_data_list]
        pending_id = await db_service.save_pending_shifts(user_id, workplace_id, shifts_to_save)
        if not pending_id: raise Exception("解析結果の一時保存に失敗しました。")

        confirm_url = f"{settings.SERVICE_URL}/liff/shifts/confirm?pending_id={pending_id}"
        final_reply_text = (
            f"AIが {len(parsed_shift_data_list)} 件のシフト情報を読み取りました。\n\n"
            "カレンダーに登録する前に、内容が正しいか以下のURLから確認・編集してください。\n"
            f"{confirm_url}"
        )
        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
    except Exception as e:
        traceback.print_exc()
        try:
            error_message = f"画像の処理中にエラーが発生しました。\n理由: {str(e)[:100]}"
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=error_message)]))
        except Exception as e2: print(f"Failed to send final error push message: {e2}")

# --- Webhookエンドポイント ---
@router.post("/callback", summary="LINE Bot Webhook callback")
async def line_webhook_callback(request: Request, background_tasks: BackgroundTasks, db_service: FirestoreService = Depends(get_db_service)):
    try:
        events = line_webhook_handler.parser.parse((await request.body()).decode('utf-8'), request.headers.get("X-Line-Signature"))
    except InvalidSignatureError: raise HTTPException(status_code=400, detail="Invalid signature")
    
    for event in events:
        user_id = event.source.user_id if event.source else "unknown_user"
        if isinstance(event, MessageEvent) and isinstance(event.message, WebhookImageMessageContent):
            try:
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[MessagingTextMessage(text="画像を受け付けました。AIがシフト情報を解析します。完了したら通知しますね！")]
                ))
            except Exception as e: print(f"Failed to send ACK for image message to {user_id}: {e}")
            background_tasks.add_task(process_image_and_send_confirm_url, db_service, user_id, event.message.id)
        elif isinstance(event, FollowEvent):
            await handle_follow_event(db_service, event)
        elif isinstance(event, MessageEvent) and isinstance(event.message, WebhookTextMessageContent):
            handle_text_message_sync(event)
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
        if settings.SERVICE_URL:
            # LIFFのGoogleカレンダー連携設定ページへのURLを案内する
            liff_auth_url = f"{settings.SERVICE_URL}/liff/google-calendar-auth" # liff_settings.pyで定義したパス
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