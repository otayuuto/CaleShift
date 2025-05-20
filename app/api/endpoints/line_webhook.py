# app/api/endpoints/line_webhook.py

import logging
import traceback # エラー時の詳細表示用
from fastapi import APIRouter, Request, HTTPException, status
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage as MessagingTextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent as WebhookTextMessageContent,
    ImageMessageContent as WebhookImageMessageContent,
)

from app.core.config import settings
from app.services import vision_service  # Vision APIサービスをインポート
from app.services import firestore_service # Firestoreサービスをインポート
from app.utils import image_parser       # テキスト解析ユーティリティをインポート

# ロガーの設定
# この設定はアプリケーションの起動時に一度だけ行われるのが理想的です。
# main.pyなどで一元管理するか、以下のようにフラグで重複実行を防ぎます。
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


router = APIRouter()

# WebhookHandlerのインスタンスを作成
handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Messaging API のクライアントを設定
# line_bot_api の初期化は try-except で囲み、失敗した場合の処理を考慮
try:
    configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
    line_bot_api_client = ApiClient(configuration) # 変数名をApiClientのインスタンスと明確に
    line_bot_api = MessagingApi(api_client=line_bot_api_client) # MessagingApiインスタンスを作成
    logger.info("LINE Messaging API client initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize LINE Messaging API client: {e}")
    logger.error(traceback.format_exc())
    # line_bot_api が初期化できなかった場合、None を設定して後でチェック
    line_bot_api = None


@router.post("/callback", status_code=status.HTTP_200_OK)
async def callback_post(request: Request):
    """
    LINEプラットフォームからのWebhookイベント（メッセージ送信など）を受信処理します。
    """
    logger.info("--- POST /callback Received ---")
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        logger.error("X-Line-Signature header not found in POST request.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Line-Signature header not found"
        )

    body_bytes = await request.body()
    body = body_bytes.decode('utf-8')
    # logger.debug(f"POST Request Body: {body}") # 必要に応じてデバッグ時に有効化

    if line_bot_api is None:
        logger.error("LINE Messaging API client is not initialized. Cannot handle webhook.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Bot internal error.")

    try:
        logger.info("Attempting to call handler.handle(body, signature)...")
        handler.handle(body, signature)
        logger.info("handler.handle(body, signature) called successfully.")
    except InvalidSignatureError:
        logger.warning("Invalid signature. Please check your channel secret.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature. Please check your channel secret and incoming signature."
        )
    except Exception as e:
        logger.error(f"Error processing webhook event: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while processing webhook."
        )

    logger.info("--- POST /callback Processed Successfully ---")
    return "OK"


@router.get("/callback", status_code=status.HTTP_200_OK)
async def callback_get():
    """
    LINE DevelopersコンソールのWebhook URL「検証」ボタンからのリクエストを処理します。
    """
    logger.info("--- GET /callback Received (LINE Verification) ---")
    return "OK (Webhook URL verified by GET)"


@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message(event: MessageEvent):
    user_id = event.source.user_id if event.source else "UnknownUser"
    logger.info(f"--- Handling Text Message from User: {user_id} ---")
    reply_token = event.reply_token
    received_text = "N/A"
    if isinstance(event.message, WebhookTextMessageContent):
        received_text = event.message.text
    logger.info(f"Received text: \"{received_text}\"")

    if line_bot_api is None:
        logger.error("LINE Messaging API client not initialized. Cannot send reply for text message.")
        return # 応答できないので処理を終了

    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"テキスト「{received_text}」を確認しました。シフト画像の送信をお待ちしています。")]
            )
        )
        logger.info(f"Replied to text message from {user_id}.")
    except Exception as e:
        logger.error(f"Error sending reply in handle_text_message: {str(e)}")
        logger.error(traceback.format_exc())
    logger.info(f"--- Finished Handling Text Message from User: {user_id} ---")


@handler.add(MessageEvent, message=WebhookImageMessageContent)
def handle_image_message(event: MessageEvent):
    user_id = event.source.user_id if event.source else "UnknownUser"
    logger.info(f"--- Handling Image Message from User: {user_id} ---")
    reply_token = event.reply_token
    message_id = event.message.id
    logger.info(f"Image Message ID: {message_id}")

    if line_bot_api is None:
        logger.error("LINE Messaging API client not initialized. Cannot process image or send reply.")
        # ユーザーに応答できないため、ここで処理を終了するか、限定的な応答を試みる
        # ここでは何もしないで終了する (応答は返せない)
        return

    detected_text_response = "画像の処理を開始します..."
    parsed_shift_data_list = [] # 変数名を修正 (listであることを示す)

    try:
        logger.info(f"Attempting to get image content for message_id: {message_id}...")
        message_content_bytes = line_bot_api.get_message_content(message_id=message_id)

        if message_content_bytes:
            logger.info(f"Image content retrieved. Size: {len(message_content_bytes)} bytes.")

            logger.info("Sending image to Vision API...")
            text_from_vision = vision_service.detect_text_from_image_content(message_content_bytes)

            if text_from_vision:
                logger.info(f"Vision API detected text (length: {len(text_from_vision)}).")
                # logger.debug(f"Full detected text from Vision: {text_from_vision}") # デバッグ時

                logger.info("Parsing detected text for shift information...")
                parsed_shift_data_list = image_parser.parse_shift_text(text_from_vision) # 変数名を修正
                logger.info(f"Parsed shift data count: {len(parsed_shift_data_list)}")
                # logger.debug(f"Parsed shift data details: {parsed_shift_data_list}") # デバッグ時

                if parsed_shift_data_list:
                    summary = f"認識されたシフトは {len(parsed_shift_data_list)} 件です。\n"
                    for i, shift_item in enumerate(parsed_shift_data_list[:3]): # 変数名を修正
                        # shift_item が辞書であることを想定
                        date_val = shift_item.get('date', '日付不明')
                        start_time_val = shift_item.get('start_time', '開始不明')
                        end_time_val = shift_item.get('end_time', '終了不明')
                        summary += f"- {date_val} {start_time_val}-{end_time_val}\n"
                    if len(parsed_shift_data_list) > 3:
                        summary += "など。"
                    detected_text_response = summary

                    logger.info(f"Attempting to save {len(parsed_shift_data_list)} shifts to Firestore for user {user_id}...")
                    save_success = firestore_service.save_parsed_shifts(user_id, parsed_shift_data_list)
                    if save_success:
                        logger.info("Shift data saved to Firestore successfully.")
                        detected_text_response += "\nシフト情報をデータベースに保存しました。"
                    else:
                        logger.warning(f"Failed to save shifts to Firestore for user {user_id}.")
                        detected_text_response += "\nデータベースへの保存に失敗しました。"
                else:
                    detected_text_response = "画像からテキストは認識できましたが、有効なシフト情報を見つけられませんでした。"
                    logger.info("No valid shift data parsed from Vision API text.")
            else:
                detected_text_response = "画像からテキストを検出できませんでした。"
                logger.info("No text detected by Vision API.")
        else:
            detected_text_response = "画像の取得に失敗しました。再度お試しください。"
            logger.warning(f"Failed to retrieve image content for message_id: {message_id}")

    except Exception as e:
        detected_text_response = "画像の処理中に予期せぬエラーが発生しました。"
        logger.error(f"Unhandled error during image processing for message_id {message_id}: {str(e)}")
        logger.error(traceback.format_exc())

    # ユーザーへの返信
    try:
        logger.info(f"Attempting to reply to user {user_id} with result.")
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=detected_text_response)]
            )
        )
        logger.info(f"Successfully replied to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending final reply in handle_image_message: {str(e)}")
        logger.error(traceback.format_exc())
    logger.info(f"--- Finished Handling Image Message from User: {user_id} ---")