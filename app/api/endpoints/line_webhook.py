# app/api/endpoints/line_webhook.py

from fastapi import APIRouter, Request, HTTPException, status
from linebot.v3.webhook import WebhookHandler # WebhookHandlerをインポート
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

from app.core.config import settings # 設定ファイルをインポート

router = APIRouter()

# WebhookHandlerのインスタンスを作成し、'handler'という変数に代入
handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Messaging API のクライアントを設定
configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))

# ... (POSTとGETの /callback エンドポイント定義はここにあるはず) ...
# POSTリクエストを処理するエンドポイント
@router.post("/callback", status_code=status.HTTP_200_OK)
async def callback_post(request: Request):
    """
    LINEプラットフォームからのWebhookイベント（メッセージ送信など）を受信処理します。
    """
    print("--- POST /callback START ---") # デバッグログ

    # X-Line-Signatureヘッダーを取得 (署名検証用)
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        print("!!! X-Line-Signature header not found in POST request !!!") # デバッグログ
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Line-Signature header not found"
        )
    print(f"POST Signature: {signature}") # デバッグログ

    # リクエストボディを取得
    body_bytes = await request.body()
    body = body_bytes.decode('utf-8')
    print(f"POST Request Body: {body}") # デバッグログ

    try:
        # 署名を検証し、イベントを各ハンドラにディスパッチ
        print("Attempting to call handler.handle(body, signature)...") # デバッグログ
        handler.handle(body, signature)
        print("handler.handle(body, signature) called successfully.") # デバッグログ
    except InvalidSignatureError:
        print("!!! Invalid signature. Please check your channel secret. !!!") # デバッグログ
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature. Please check your channel secret and incoming signature."
        )
    except Exception as e:
        error_message = f"Error processing webhook event: {str(e)}"
        print(f"!!! {error_message} !!!") # デバッグログ
        import traceback
        traceback.print_exc() # 詳細なトレースバックを出力
        # LINEプラットフォームにはエラー詳細を返さない方が良い場合もある
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while processing webhook."
        )

    print("--- POST /callback END (Successfully processed) ---") # デバッグログ
    return "OK" # LINEプラットフォームには常に200 OKを返す


# --- Webhook URLの検証用 (GETリクエスト) ---
@router.get("/callback", status_code=status.HTTP_200_OK)
async def callback_get():
    """
    LINE DevelopersコンソールのWebhook URL「検証」ボタンからのリクエストを処理します。
    通常、このエンドポイントは200 OKを返すだけで十分です。
    """
    print("--- GET /callback START (LINE Verification) ---") # デバッグログ
    # ここでは特に何も処理せず、200 OKを返す
    print("--- GET /callback END (Verified) ---") # デバッグログ
    return "OK (Webhook URL verified by GET)"

# MessageEvent (テキストメッセージ) を処理するハンドラ
# このデコレータがエラーの原因
@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message(event: MessageEvent):
    print("--- handle_text_message START ---") # 追加
    print(f"Event object: {event}") # 追加
    user_id = event.source.user_id
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "Unknown text message format"

    try:
        print("Trying to send reply...") 
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"受け取ったメッセージ: {received_text}")]
            )
        )
        print("Reply sent successfully.")
        print(f"Replied to {user_id} with: {received_text}")
    except Exception as e:
        print(f"!!! ERROR sending reply: {e} !!!")
        import traceback
        traceback.print_exc()
    print("--- handle_text_message END ---")

# 画像メッセージを受け取る場合のハンドラ
@handler.add(MessageEvent, message=WebhookImageMessageContent)
def handle_image_message(event: MessageEvent):
    print(f"Received image message event: {event}")
    user_id = event.source.user_id
    reply_token = event.reply_token
    message_id = event.message.id

    print(f"Image Message ID: {message_id}")

    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"画像を受け取りました！メッセージID: {message_id}")]
            )
        )
        print(f"Replied to {user_id} about received image (ID: {message_id}).")
    except Exception as e:
        print(f"Error sending reply for image: {e}")