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
    MessagingApiBlob, # ★★★ これを使います ★★★
    ReplyMessageRequest,
    TextMessage as MessagingTextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent as WebhookTextMessageContent,
    ImageMessageContent as WebhookImageMessageContent,
)

from app.core.config import settings
from app.services import vision_service
# from app.services import firestore_service # firestore_service.save_parsed_shifts を使うならインポート
from app.utils import image_parser
# import traceback # 重複しているので一つに
# import logging # 重複しているので一つに

# ロガーの設定
logger = logging.getLogger(__name__)
# ロガーの基本設定はmain.pyやアプリケーションの起動時に行うのが一般的
# ここでは、もし設定されていなければというフォールバック
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


router = APIRouter()

handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Messaging API (テキストメッセージ送受信など) のクライアント
configuration = Configuration(
    access_token=settings.LINE_CHANNEL_ACCESS_TOKEN
)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))

# ★★★ Messaging API Blob (画像などのコンテンツ取得用) のクライアント ★★★
line_bot_blob_api = MessagingApiBlob(api_client=ApiClient(configuration))

logger.info("--- LINE Messaging API clients (MessagingApi & MessagingApiBlob) initialized successfully (line_webhook.py) ---")

@router.post("/callback", status_code=status.HTTP_200_OK)
async def callback_post(request: Request):
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
    # logger.debug(f"POST Request Body: {body}")

    if line_bot_api is None or line_bot_blob_api is None: # blob_apiもチェック
        logger.error("LINE Messaging API client(s) not initialized. Cannot handle webhook.")
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
        logger.error(f"Error processing webhook event: {str(e)}", exc_info=True) # exc_info=Trueでトレースバックも
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while processing webhook."
        )

    logger.info("--- POST /callback Processed Successfully ---")
    return "OK"


@router.get("/callback", status_code=status.HTTP_200_OK)
async def callback_get():
    logger.info("--- GET /callback Received (LINE Verification) ---")
    return "OK (Webhook URL verified by GET)"


@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message(event: MessageEvent): # 同期関数のまま
    user_id = event.source.user_id if event.source else "UnknownUser"
    logger.info(f"--- Handling Text Message from User: {user_id} ---")
    reply_token = event.reply_token
    received_text = "N/A"
    if isinstance(event.message, WebhookTextMessageContent):
        received_text = event.message.text
    logger.info(f"Received text: \"{received_text}\"")

    if line_bot_api is None:
        logger.error("LINE Messaging API client not initialized. Cannot send reply for text message.")
        return

    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"テキスト「{received_text}」を確認しました。シフト画像の送信をお待ちしています。")]
            )
        )
        logger.info(f"Replied to text message from {user_id}.")
    except Exception as e:
        logger.error(f"Error sending reply in handle_text_message: {str(e)}", exc_info=True)
    logger.info(f"--- Finished Handling Text Message from User: {user_id} ---")


# app/api/endpoints/line_webhook.py
# ... (他の部分は変更なし) ...

@handler.add(MessageEvent, message=WebhookImageMessageContent)
def handle_image_message(event: MessageEvent): # 同期関数のまま
    user_id = event.source.user_id if event.source else "UnknownUser"
    logger.info(f"--- Handling Image Message from User: {user_id} ---")
    reply_token = event.reply_token
    message_id = event.message.id
    logger.info(f"Image Message ID: {message_id}")

    if line_bot_api is None or line_bot_blob_api is None:
        logger.error("LINE Messaging API client(s) not initialized. Cannot process image or send reply.")
        return

    final_reply_text = "画像の処理中に予期せぬエラーが発生しました。"

    try:
        logger.info(f"Attempting to get image content for message_id: {message_id}...")
        message_content_stream = line_bot_blob_api.get_message_content(message_id=message_id)
        
        image_bytes = b''
        # ストリームからバイトデータを読み込む
        for chunk in message_content_stream:
            if isinstance(chunk, int): # ★★★ もしchunkが整数ならバイトに変換 ★★★
                image_bytes += bytes([chunk])
            elif isinstance(chunk, bytes): # chunkがバイト列ならそのまま連結
                image_bytes += chunk
            else:
                # 予期しない型の場合の処理 (エラーログなど)
                logger.warning(f"Unexpected chunk type encountered: {type(chunk)}. Skipping this chunk.")
                continue 
        
        if not image_bytes:
            logger.warning(f"Failed to retrieve image content for message_id: {message_id}")
            final_reply_text = "画像の取得に失敗しました。再度お試しください。"
        else:
            logger.info(f"Image content retrieved. Size: {len(image_bytes)} bytes.")
            logger.info("Sending image to Vision API...")
            text_from_vision = vision_service.detect_text_from_image_bytes(image_bytes)

            if text_from_vision:
                logger.info(f"Vision API detected text (length: {len(text_from_vision)}).")
                logger.info("Parsing detected text for shift information...")
                parsed_shifts_list = image_parser.parse_shift_text_to_structured_data(text_from_vision)
                logger.info(f"Parsed shift data count: {len(parsed_shifts_list)}")

                if parsed_shifts_list:
                    summary = f"認識されたシフトは {len(parsed_shifts_list)} 件です。\n"
                    for i, shift_info in enumerate(parsed_shifts_list[:3]):
                        date_val = shift_info.date.strftime("%m/%d") if shift_info.date else '日付不明'
                        start_time_val = shift_info.start_time.strftime("%H:%M") if shift_info.start_time else '開始不明'
                        end_time_val = shift_info.end_time.strftime("%H:%M") if shift_info.end_time else '終了不明'
                        name_part = f"{shift_info.name} " if shift_info.name else ""
                        role_part = f"({shift_info.role}) " if shift_info.role else ""
                        summary += f"- {date_val}: {name_part}{role_part}{start_time_val}～{end_time_val}\n"
                    if len(parsed_shifts_list) > 3:
                        summary += "など。"
                    final_reply_text = summary
                else:
                    final_reply_text = "画像からテキストは認識できましたが、有効なシフト情報を見つけられませんでした。"
                    logger.info("No valid shift data parsed from Vision API text.")
            else:
                final_reply_text = "画像からテキストを検出できませんでした。"
                logger.info("No text detected by Vision API.")
    
    except AttributeError as ae:
        final_reply_text = "画像処理の内部エラーが発生しました (コード: ATTR_ERR)。"
        logger.error(f"AttributeError during image processing for message_id {message_id}: {str(ae)}", exc_info=True)
    except TypeError as te: # ★★★ 今回の TypeError をキャッチ ★★★
        final_reply_text = "画像データの処理中に型エラーが発生しました (コード: TYPE_ERR)。"
        logger.error(f"TypeError during image processing for message_id {message_id}: {str(te)}", exc_info=True)
    except Exception as e:
        final_reply_text = "画像の処理中に予期せぬエラーが発生しました (コード: GEN_ERR)。"
        logger.error(f"Unhandled error during image processing for message_id {message_id}: {str(e)}", exc_info=True)

    # ユーザーへの返信 (変更なし)
    try:
        logger.info(f"Attempting to reply to user {user_id} with: \"{final_reply_text[:100]}...\"")
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=final_reply_text)]
            )
        )
        logger.info(f"Successfully replied to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending final reply in handle_image_message: {str(e)}", exc_info=True)
    logger.info(f"--- Finished Handling Image Message from User: {user_id} ---")