# app/api/endpoints/line_webhook.py

from fastapi import APIRouter, Request, HTTPException
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, # ApiClientを直接使うのではなく、Configuration経由で
    Configuration, # Configuration をインポート
    MessagingApi,
    ReplyMessageRequest,
    TextMessage as MessagingTextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent as WebhookTextMessageContent,
)

from app.core.config import settings

router = APIRouter()

handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Messaging API のクライアントを設定 (修正箇所)
# 1. Configurationオブジェクトを作成
configuration = Configuration(
    access_token=settings.LINE_CHANNEL_ACCESS_TOKEN
)

# 2. Configurationオブジェクトを使ってApiClientを初期化し、それをMessagingApiに渡す
#    または、MessagingApiがConfigurationを直接受け取る場合もある
#    以下のいずれかのパターンを試す
# パターンA: MessagingApiがConfigurationオブジェクトを直接受け取る (推奨されることが多い)
line_bot_api = MessagingApi(api_client=ApiClient(configuration)) # より明示的
# または、よりシンプルにMessagingApiがConfigurationを直接受け取る場合:
# line_bot_api = MessagingApi(configuration) # こちらも試す価値あり

# (古いSDKや特定のバージョンでのApiClientの使い方だった場合、このブロックは不要)
# configuration = ApiClient(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN) # 元のコード
# line_bot_api = MessagingApi(configuration) # 元のコード


@router.post("/callback")
async def callback(request: Request):
    # ... (変更なし) ...
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
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

    return "OK"

@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message(event: MessageEvent):
    # ... (変更なし) ...
    print(f"Received text message event: {event}")
    user_id = event.source.user_id
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "Unknown text message format"

    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text=f"受け取ったメッセージ: {received_text}")]
            )
        )
        print(f"Replied to {user_id} with: {received_text}")
    except Exception as e:
        print(f"Error sending reply: {e}")