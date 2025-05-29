# app/api/endpoints/line_webhook.py

from fastapi import APIRouter, Request, HTTPException
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
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
import traceback # スタックトレース表示用
from app.utils import image_parser

router = APIRouter()

handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Messaging API (テキストメッセージ送受信など) のクライアント
configuration = Configuration(
    access_token=settings.LINE_CHANNEL_ACCESS_TOKEN
)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))

# Messaging API Blob (画像などのコンテンツ取得用) のクライアント
line_bot_blob_api = MessagingApiBlob(api_client=ApiClient(configuration))

print("INFO - app.api.endpoints.line_webhook - LINE Messaging API clients initialized successfully.")


@router.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="X-Line-Signature header not found")

    body_bytes = await request.body()
    body = body_bytes.decode('utf-8')

    try:
        print(f"Received body: {body}")
        print(f"Received signature: {signature}")
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel secret.")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print(f"Error handling webhook: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

    return "OK"


@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message(event: MessageEvent):
    print(f"Received text message event from {event.source.user_id}: {event.message.text}")
    user_id = event.source.user_id
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "Unknown text message format"

    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"テキストメッセージを受け取りました: {received_text}")]
            )
        )
        print(f"Replied to {user_id} with text: {received_text}")
    except Exception as e:
        print(f"Error sending text reply: {e}")
        traceback.print_exc()


@handler.add(MessageEvent, message=WebhookImageMessageContent)
def handle_image_message(event: MessageEvent):
    print(f"Received image message event from {event.source.user_id}, message_id: {event.message.id}")
    user_id = event.source.user_id
    reply_token = event.reply_token
    message_id = event.message.id

    try:
        # 1. LINEサーバーから画像コンテンツを取得 (修正箇所)
        #    MessagingApiBlob のインスタンスを使用する
        message_content_response = line_bot_blob_api.get_message_content(message_id=message_id) # <<<--- line_bot_blob_api を使用

        image_bytes = b''
        # message_content_response は直接バイト列を返す場合と、ストリーミングオブジェクトを返す場合がある
        # SDKのバージョンや具体的な返り値の型によって以下のように処理を分けるのが確実
        if hasattr(message_content_response, 'iter_content'): # ストリーミングの場合
            for chunk in message_content_response.iter_content():
                image_bytes += chunk
        else: # 直接バイト列が返ってくる場合 (小さいファイルなど)
            image_bytes = message_content_response


        if not image_bytes:
            print("Failed to retrieve image content from LINE.")
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[MessagingTextMessage(text="画像の取得に失敗しました。")]
                )
            )
            return

        print(f"Successfully retrieved {len(image_bytes)} bytes of image data from LINE.")

        # 2. vision_service を使って画像をVision APIに送信
        detected_text = vision_service.detect_text_from_image_bytes(image_bytes)

        if detected_text:
            print(f"Vision API detected text (length: {len(detected_text)}). Parsing...")
            
            # テキストパーサーを呼び出す
            parsed_shift_data_list = image_parser.parse_shift_text_to_structured_data(detected_text)

            if parsed_shift_data_list:
                reply_parts = ["シフト情報を解析しました:"]
                for shift_info in parsed_shift_data_list:
                    date_str = shift_info.date.strftime("%m/%d")
                    if shift_info.is_holiday:
                        reply_parts.append(f"- {date_str}: 休み")
                    else:
                        start_str = shift_info.start_time.strftime("%H:%M") if shift_info.start_time else "未定"
                        end_str = shift_info.end_time.strftime("%H:%M") if shift_info.end_time else "未定"
                        memo_str = f" ({shift_info.memo})" if shift_info.memo else ""
                        reply_parts.append(f"- {date_str}: {start_str}～{end_str}{memo_str}")
                
                reply_text = "\n".join(reply_parts)
                if len(reply_text) > 4800: # LINEのメッセージ長制限考慮
                    reply_text = reply_text[:4800] + "\n...(長すぎるため省略)"
            else:
                print("No shift data could be parsed from the detected text.")
                reply_text = "テキストは抽出できましたが、シフト情報として解析できませんでした。画像のフォーマットを確認してください。"
        else:
            reply_text = f"画像から抽出したテキスト:\n{detected_text}"
            print("No text detected by Vision API or an error occurred.")
            reply_text = "画像からテキストを抽出できませんでした。文字が鮮明な画像をお試しください。"

        # 3. 解析結果をユーザーに返信
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=reply_text)]
            )
        )
        print(f"Replied to {user_id} with Vision API result.")

    except Exception as e:
        print(f"Error processing image or replying: {e}")
        traceback.print_exc()
        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[MessagingTextMessage(text="画像の処理中に予期せぬエラーが発生しました。")]
                )
            )
        except Exception as e2:
            print(f"Error sending error reply: {e2}")
            traceback.print_exc()