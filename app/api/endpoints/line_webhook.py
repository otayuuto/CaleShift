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
from app.utils import image_parser # image_parser をインポート
import traceback

router = APIRouter()

handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))
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
        # ログにリクエストボディと署名を出力 (デバッグ用、個人情報が含まれる可能性があるので本番では注意)
        # print(f"DEBUG: Received body: {body}")
        # print(f"DEBUG: Received signature: {signature}")
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("ERROR: Invalid signature. Please check your channel secret.")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print(f"ERROR: Error handling webhook: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

    return "OK"


@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message(event: MessageEvent):
    user_id = event.source.user_id # ユーザーIDを取得
    print(f"INFO: Received text message from LINE User ID: [{user_id}], Text: \"{event.message.text}\"") # ユーザーIDをログに追加
    
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "Unknown text message format"

    try:
        # ... (既存のテキストメッセージ処理) ...
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"テキストメッセージを受け取りました: {received_text}")]
            )
        )
        print(f"INFO: Replied to text message for LINE User ID: [{user_id}]")
    except Exception as e:
        print(f"ERROR: Error sending text reply for LINE User ID: [{user_id}]: {e}")
        traceback.print_exc()


@handler.add(MessageEvent, message=WebhookImageMessageContent)
def handle_image_message(event: MessageEvent):
    user_id = event.source.user_id # ユーザーIDを取得
    message_id = event.message.id
    # ↓↓↓ ユーザーIDを強調してログに出力 ↓↓↓
    print(f"INFO: ***** Image message received from LINE User ID: [{user_id}], Message ID: [{message_id}] *****")

    reply_token = event.reply_token

    try:
        print(f"INFO: [{user_id}] Attempting to retrieve image content from LINE...")
        message_content_response = line_bot_blob_api.get_message_content(message_id=message_id)

        image_bytes = b''
        if hasattr(message_content_response, 'iter_content'):
            for chunk in message_content_response.iter_content():
                image_bytes += chunk
        else:
            image_bytes = message_content_response
        
        if not image_bytes:
            print(f"ERROR: [{user_id}] Failed to retrieve image content from LINE.")
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=[MessagingTextMessage(text="画像の取得に失敗しました。")])
            )
            return

        print(f"INFO: [{user_id}] Successfully retrieved {len(image_bytes)} bytes of image data from LINE.")
        print(f"INFO: [{user_id}] Sending image to Vision API for text detection...")
        detected_text = vision_service.detect_text_from_image_bytes(image_bytes)

        if detected_text:
            print(f"INFO: [{user_id}] Vision API detected text (length: {len(detected_text)}). Parsing text...")
            # print(f"DEBUG: [{user_id}] Detected text content:\n{detected_text[:500]}...") # 必要ならテキスト内容もログに

            parsed_shift_data_list = image_parser.parse_shift_text_to_structured_data(detected_text)

            if parsed_shift_data_list:
                reply_parts = ["シフト情報を解析しました:"]
                for shift_info in parsed_shift_data_list:
                    # (返信メッセージの整形は変更なし)
                    date_str = shift_info.date.strftime("%m/%d")
                    if shift_info.is_holiday:
                        reply_parts.append(f"- {date_str}: {shift_info.name or ''} 休み".strip())
                    else:
                        start_str = shift_info.start_time.strftime("%H:%M") if shift_info.start_time else "未定"
                        end_str = shift_info.end_time.strftime("%H:%M") if shift_info.end_time else "未定"
                        name_str = f"{shift_info.name} " if shift_info.name else ""
                        role_str = f"({shift_info.role})" if shift_info.role else ""
                        memo_str = f" [{shift_info.memo}]" if shift_info.memo else ""
                        reply_parts.append(f"- {date_str}: {name_str}{start_str}～{end_str} {role_str}{memo_str}".strip())
                
                reply_text = "\n".join(reply_parts)
                if len(reply_text) > 4800:
                    reply_text = reply_text[:4800] + "\n...(長すぎるため省略)"
                print(f"INFO: [{user_id}] Parsed shift data. Reply text generated.")
            else:
                print(f"WARNING: [{user_id}] No shift data could be parsed from the detected text.")
                reply_text = "テキストは抽出できましたが、シフト情報として解析できませんでした。画像のフォーマットを確認してください。"
        else:
            print(f"WARNING: [{user_id}] No text detected by Vision API or an error occurred.")
            reply_text = "画像からテキストを抽出できませんでした。文字が鮮明な画像をお試しください。"

        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[MessagingTextMessage(text=reply_text)])
        )
        print(f"INFO: [{user_id}] Replied to user with parsed result or error message.")

    except Exception as e:
        # ↓↓↓ エラーログにもユーザーIDを含める ↓↓↓
        print(f"ERROR: [{user_id}] Error processing image or replying: {e}")
        traceback.print_exc()
        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[MessagingTextMessage(text="画像の処理中に予期せぬエラーが発生しました。")]
                )
            )
        except Exception as e2:
            print(f"ERROR: [{user_id}] Error sending error reply: {e2}")
            traceback.print_exc()