# app/api/endpoints/line_webhook.py

import logging
import traceback
from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks # BackgroundTasks をインポート
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    PushMessageRequest, # PushMessageのために追加
    TextMessage as MessagingTextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent as WebhookTextMessageContent,
    ImageMessageContent as WebhookImageMessageContent,
    # FollowEventなども必要ならインポート
)
from typing import Optional, List # Optional, List をインポート

from app.core.config import settings
from app.services import vision_service, calendar_service # calendar_service もインポート
from app.utils import image_parser
# from app.services import firestore_service # firestore_service も後で使うなら

# ロガーの設定 (main.pyなどで一元的に行うのが理想)
logger = logging.getLogger(__name__)
if not logger.hasHandlers(): # 基本的なフォールバック設定
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

router = APIRouter()

handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Messaging API クライアントの初期化 (1回にまとめる)
configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))
line_bot_blob_api = MessagingApiBlob(api_client=ApiClient(configuration))

logger.info("--- LINE Messaging API clients (MessagingApi & MessagingApiBlob) initialized (line_webhook.py) ---")


# バックグラウンドで画像処理とカレンダー登録、結果通知を行う非同期関数
async def process_image_and_calendar_task(
    user_id: str,
    message_id: str,
    # db_client: firestore.Client # Firestoreを使う場合はDIまたはapp.stateから取得
):
    logger.info(f"BACKGROUND_TASK: Started for user [{user_id}], message_id [{message_id}]")
    final_push_message_text = "画像の処理中にエラーが発生しました。" # デフォルトのエラーメッセージ

    try:
        # 1. 画像コンテンツの取得
        logger.info(f"BACKGROUND_TASK: [{user_id}] Getting image content for message_id [{message_id}]...")
        message_content_stream = line_bot_blob_api.get_message_content(message_id=message_id)
        image_bytes = b''
        for chunk in message_content_stream:
            if isinstance(chunk, int): image_bytes += bytes([chunk])
            elif isinstance(chunk, bytes): image_bytes += chunk
            else: logger.warning(f"BACKGROUND_TASK: [{user_id}] Unexpected chunk type: {type(chunk)}")
        
        if not image_bytes:
            logger.warning(f"BACKGROUND_TASK: [{user_id}] Failed to retrieve image content from LINE.")
            final_push_message_text = "画像の取得に失敗しました。"
        else:
            logger.info(f"BACKGROUND_TASK: [{user_id}] Image retrieved ({len(image_bytes)} bytes). Calling Vision API...")
            # 2. Vision API でテキスト抽出
            text_from_vision = vision_service.detect_text_from_image_bytes(image_bytes)

            if text_from_vision:
                logger.info(f"BACKGROUND_TASK: [{user_id}] Vision API detected text. Parsing shifts...")
                # 3. テキスト解析
                parsed_shifts_list = image_parser.parse_shift_text_to_structured_data(text_from_vision)
                logger.info(f"BACKGROUND_TASK: [{user_id}] Parsed {len(parsed_shifts_list)} shifts.")

                if parsed_shifts_list:
                    results_summary_parts = [f"画像から{len(parsed_shifts_list)}件のシフト情報を認識しました。"]
                    created_count = 0
                    failed_count = 0

                    for shift_info in parsed_shifts_list:
                        date_str = shift_info.date.strftime("%m/%d") if shift_info.date else "日付不明"
                        name_str = f"{shift_info.name} " if shift_info.name else ""
                        role_str = f"({shift_info.role}) " if shift_info.role else ""
                        start_str = shift_info.start_time.strftime("%H:%M") if shift_info.start_time else "開始不明"
                        end_str = shift_info.end_time.strftime("%H:%M") if shift_info.end_time else "終了不明"
                        
                        if shift_info.is_holiday:
                            results_summary_parts.append(f"- {date_str}: {name_str}休み")
                            continue
                        if not shift_info.start_time or not shift_info.end_time:
                            results_summary_parts.append(f"- {date_str}: {name_str}{role_str}{start_str}～{end_str} (時刻不備)")
                            continue
                        
                        # 4. カレンダー登録
                        logger.info(f"BACKGROUND_TASK: [{user_id}] Attempting to create calendar event for shift: {shift_info.date} {start_str}-{end_str}")
                        event_id = await calendar_service.create_calendar_event(user_id, shift_info)
                        if event_id:
                            created_count += 1
                            results_summary_parts.append(f"- {date_str}: {name_str}{role_str}{start_str}～{end_str} [登録済]")
                            logger.info(f"BACKGROUND_TASK: [{user_id}] Calendar event created: {event_id}")
                        else:
                            failed_count += 1
                            results_summary_parts.append(f"- {date_str}: {name_str}{role_str}{start_str}～{end_str} [登録失敗]")
                            logger.warning(f"BACKGROUND_TASK: [{user_id}] Failed to create calendar event for shift: {shift_info.date}")
                    
                    if created_count > 0:
                        final_push_message_text = f"{created_count}件のシフトをカレンダーに登録しました。"
                        if failed_count > 0:
                            final_push_message_text += f"\n{failed_count}件の登録に失敗しました。"
                    elif failed_count > 0:
                        final_push_message_text = "シフトのカレンダー登録に全て失敗しました。"
                    else: # 有効なシフトがなかった場合 (例: 休みのみ、時刻不備のみ)
                        final_push_message_text = "カレンダーに登録可能な有効なシフトが見つかりませんでした。"
                    
                    final_push_message_text += "\n\n認識結果:\n" + "\n".join(results_summary_parts[1:]) # 最初の汎用メッセージを除外

                else: # パース結果が空の場合
                    final_push_message_text = "画像からテキストは認識できましたが、有効なシフト情報を見つけられませんでした。"
            else: # Vision APIがテキストを検出しなかった場合
                final_push_message_text = "画像からテキストを検出できませんでした。"
    except Exception as e:
        logger.error(f"BACKGROUND_TASK: [{user_id}] Error in process_image_and_calendar_task: {str(e)}", exc_info=True)
        final_push_message_text = "画像の処理中に予期せぬエラーが発生しました。システム管理者にご連絡ください。"

    # 最終結果をPush Messageでユーザーに通知
    try:
        if len(final_push_message_text) > 5000: # LINEのPush Messageの文字数制限
            final_push_message_text = final_push_message_text[:4990] + "\n...(長すぎるため省略)"
        
        logger.info(f"BACKGROUND_TASK: [{user_id}] Sending push message with result: \"{final_push_message_text[:100]}...\"")
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[MessagingTextMessage(text=final_push_message_text)]
            )
        )
        logger.info(f"BACKGROUND_TASK: [{user_id}] Successfully pushed result to user.")
    except Exception as e_push:
        logger.error(f"BACKGROUND_TASK: [{user_id}] Failed to send push message: {str(e_push)}", exc_info=True)


@router.post("/callback", status_code=status.HTTP_200_OK)
async def callback_endpoint(request: Request, background_tasks: BackgroundTasks): # background_tasks をDI
    logger.info("--- POST /callback Received ---")
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        logger.error("X-Line-Signature header not found.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Line-Signature header missing")

    body = await request.body() # bodyをbytesで取得
    
    try:
        # WebhookHandlerのパーサーを使ってイベントをパース
        # handler.handle(body.decode('utf-8'), signature) を直接呼び出すと、
        # 同期的なハンドラ内で非同期タスクを起動するのが難しいため、イベントを個別に処理
        events = handler.parser.parse(body.decode('utf-8'), signature)
        logger.info(f"Parsed {len(events)} event(s) from webhook.")

        for event in events:
            if isinstance(event, MessageEvent):
                user_id = event.source.user_id if event.source else "unknown_user"
                
                if isinstance(event.message, WebhookImageMessageContent):
                    logger.info(f"Image message received from user [{user_id}]. Adding to background tasks.")
                    # 先にACK応答 (「処理を開始しました」)
                    try:
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[MessagingTextMessage(text="画像を受け付けました。シフト情報を解析し、カレンダーに登録します。少々お待ちください...")]
                            )
                        )
                        logger.info(f"Sent ACK reply to user [{user_id}] for image message.")
                    except Exception as e_ack:
                        logger.error(f"Failed to send ACK reply to user [{user_id}]: {e_ack}", exc_info=True)
                    
                    # 重い処理をバックグラウンドタスクとして登録
                    # Firestoreクライアントを渡す場合は、request.app.state.db を渡す
                    # db_client_from_state = request.app.state.db if hasattr(request.app, 'state') and hasattr(request.app.state, 'db') else None
                    background_tasks.add_task(
                        process_image_and_calendar_task,
                        user_id,
                        event.message.id,
                        # db_client_from_state # 必要なら渡す
                    )
                
                elif isinstance(event.message, WebhookTextMessageContent):
                    # テキストメッセージは従来通り同期的に処理
                    handle_text_message_sync(event) # 同期的なハンドラを呼び出す
            
            # elif isinstance(event, FollowEvent): # フォローイベントの処理
            #     handle_follow_event_sync(event) # 同期的なフォローイベントハンドラ

            else:
                logger.info(f"Received unhandled event type: {type(event)}")
        
    except InvalidSignatureError:
        logger.warning("Invalid signature. Check channel secret.", exc_info=True) # トレースバックも出す
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature.")
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error processing webhook.")

    logger.info("--- POST /callback Processed (events dispatched) ---")
    return "OK" # LINEプラットフォームにはすぐに200 OKを返す


@router.get("/callback", status_code=status.HTTP_200_OK) # 検証用GETエンドポイント
async def callback_get_verification():
    logger.info("--- GET /callback Received (LINE Verification) ---")
    return "OK"


# WebhookHandlerに登録する同期的なテキストメッセージハンドラ
@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message_sync(event: MessageEvent):
    user_id = event.source.user_id if event.source else "UnknownUser"
    logger.info(f"--- SYNC: Handling Text Message from User: {user_id} ---")
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "N/A"
    logger.info(f"SYNC: Received text: \"{received_text}\" from {user_id}")

    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"テキスト「{received_text}」を確認しました。シフト画像の送信をお待ちしています。")]
            )
        )
        logger.info(f"SYNC: Replied to text message from {user_id}.")
    except Exception as e:
        logger.error(f"SYNC: Error sending reply in handle_text_message_sync: {str(e)}", exc_info=True)
    logger.info(f"--- SYNC: Finished Handling Text Message from User: {user_id} ---")


# WebhookHandlerに登録する同期的な画像メッセージハンドラ (ACK応答のみ)
# 実際の処理はバックグラウンドタスクで行うため、このハンドラは /callback エンドポイントから直接は呼ばれなくなる
# ただし、handler.parser.parse(body, signature) を使う場合は、
# このようなハンドラが登録されている必要があるかもしれない（SDKの内部実装による）
# もし不要ならコメントアウトまたは削除しても良い
@handler.add(MessageEvent, message=WebhookImageMessageContent)
def handle_image_message_placeholder(event: MessageEvent):
    user_id = event.source.user_id if event.source else "UnknownUser"
    logger.info(f"SYNC_PLACEHOLDER: Image message event triggered for user [{user_id}] "
                f"(actual processing in background task via /callback endpoint).")
    # ここでは何もしない。実際の処理は process_image_and_calendar_task で行われる。
    # /callback エンドポイントで直接イベントを処理するため、このハンドラは実質的に使われない。
    pass

# (もしあれば) フォローイベントハンドラ
# @handler.add(FollowEvent)
# def handle_follow_event_sync(event: FollowEvent):
#     user_id = event.source.user_id
#     logger.info(f"--- SYNC: User {user_id} followed the bot ---")
#     # firestore_service.create_initial_user_document_on_follow(...) などを呼び出す
#     # reply_token もあるので、挨拶メッセージなども送信可能