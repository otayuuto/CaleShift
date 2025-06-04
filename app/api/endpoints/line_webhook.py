# app/api/endpoints/line_webhook.py

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks # BackgroundTasks をインポート
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
)

from typing import Optional

from app.core.config import settings
from app.services import vision_service, calendar_service
from app.utils import image_parser
import traceback
# import asyncio # asyncio.run() は使わないので不要になる

router = APIRouter()

handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))
line_bot_blob_api = MessagingApiBlob(api_client=ApiClient(configuration))

print("INFO - app.api.endpoints.line_webhook - LINE Messaging API clients initialized successfully.")


# 非同期の画像処理とカレンダー登録を行う関数 (ハンドラの外に定義)
async def process_image_and_notify_user(user_id: str, reply_token_for_initial_ack: Optional[str], message_id: str):
    """
    画像の処理、カレンダー登録、結果のプッシュ通知を行う非同期関数。
    reply_token_for_initial_ack は、もし最初に「処理中です」と返すなら使う。今回は使わない。
    """
    final_reply_text = "画像の処理が完了しました。" # デフォルトメッセージ
    try:
        print(f"BACKGROUND_TASK: [{user_id}] Started image processing for message_id: {message_id}")
        message_content_response = line_bot_blob_api.get_message_content(message_id=message_id)
        image_bytes = b''
        if hasattr(message_content_response, 'iter_content'):
            for chunk in message_content_response.iter_content():
                image_bytes += chunk
        else:
            image_bytes = message_content_response
        
        if not image_bytes:
            print(f"BACKGROUND_TASK_ERROR: [{user_id}] Failed to retrieve image content from LINE.")
            final_reply_text = "画像の取得に失敗しました。"
            # プッシュメッセージでエラーを通知
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
            return

        print(f"BACKGROUND_TASK_INFO: [{user_id}] Successfully retrieved {len(image_bytes)} bytes of image data.")
        detected_text = vision_service.detect_text_from_image_bytes(image_bytes)

        if detected_text:
            print(f"BACKGROUND_TASK_INFO: [{user_id}] Vision API detected text. Parsing...")
            parsed_shift_data_list = image_parser.parse_shift_text_to_structured_data(detected_text)

            if parsed_shift_data_list:
                created_event_ids = []
                failed_to_create_count = 0
                processed_shifts_count = 0
                parse_results_for_reply = []

                for shift_info in parsed_shift_data_list:
                    date_str = shift_info.date.strftime("%m/%d")
                    name_str_reply = f"{shift_info.name} " if shift_info.name else ""
                    role_str_reply = f"({shift_info.role})" if shift_info.role else ""
                    
                    if shift_info.is_holiday:
                        parse_results_for_reply.append(f"- {date_str}: {name_str_reply}休み")
                        continue
                    if not shift_info.start_time or not shift_info.end_time:
                        start_s = shift_info.start_time.strftime("%H:%M") if shift_info.start_time else "未定"
                        end_s = shift_info.end_time.strftime("%H:%M") if shift_info.end_time else "未定"
                        parse_results_for_reply.append(f"- {date_str}: {name_str_reply}{start_s}～{end_s} {role_str_reply} (時刻不備)".strip())
                        continue
                    
                    processed_shifts_count +=1
                    start_s = shift_info.start_time.strftime("%H:%M")
                    end_s = shift_info.end_time.strftime("%H:%M")
                    memo_s = f" [{shift_info.memo}]" if shift_info.memo else ""
                    parse_results_for_reply.append(f"- {date_str}: {name_str_reply}{start_s}～{end_s} {role_str_reply}{memo_s}".strip())

                    event_id = await calendar_service.create_calendar_event(user_id, shift_info)
                    if event_id:
                        created_event_ids.append(event_id)
                    else:
                        failed_to_create_count += 1
                
                # 返信メッセージの組み立て (変更なし)
                if not parsed_shift_data_list:
                    final_reply_text = "画像からシフト情報を読み取れませんでした。"
                elif processed_shifts_count == 0 and not created_event_ids and not failed_to_create_count :
                    final_reply_text = "解析結果:\n" + "\n".join(parse_results_for_reply)
                    final_reply_text += "\n\nカレンダーに登録可能な有効なシフトが見つかりませんでした。"
                elif created_event_ids:
                    final_reply_text = f"{len(created_event_ids)}件のシフトをカレンダーに登録しました。"
                    if failed_to_create_count > 0:
                        final_reply_text += f"\n{failed_to_create_count}件の登録に失敗しました。"
                    if parse_results_for_reply: # 解析結果があれば表示
                         final_reply_text += "\n\n解析されたシフト:\n" + "\n".join(parse_results_for_reply)
                elif failed_to_create_count > 0 :
                    final_reply_text = f"{failed_to_create_count}件全てのシフトのカレンダー登録に失敗しました。"
                    if parse_results_for_reply:
                         final_reply_text += "\n\n解析されたシフト:\n" + "\n".join(parse_results_for_reply)
                else:
                    final_reply_text = "カレンダーに登録するシフト情報が見つかりませんでした。"

            else:
                print(f"BACKGROUND_TASK_WARNING: [{user_id}] No shift data could be parsed.")
                final_reply_text = "テキストは抽出できましたが、シフト情報として解析できませんでした。"
        else:
            print(f"BACKGROUND_TASK_WARNING: [{user_id}] No text detected by Vision API.")
            final_reply_text = "画像からテキストを抽出できませんでした。"

        if len(final_reply_text) > 4800:
             final_reply_text = final_reply_text[:4800] + "\n...(長すぎるため省略)"
        
        # 結果をPush Messageでユーザーに通知
        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Pushed final result to user.")

    except Exception as e:
        print(f"BACKGROUND_TASK_ERROR: [{user_id}] Error in async process_image_and_notify_user: {e}")
        traceback.print_exc()
        try:
            line_bot_api.push_message(
                PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text="画像の処理中に予期せぬエラーが発生しました。")])
            )
        except Exception as e2:
            print(f"BACKGROUND_TASK_ERROR: [{user_id}] Error sending final error push message: {e2}")


# FastAPIのコールバックエンドポイント (変更箇所)
@router.post("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks): # BackgroundTasks をDI
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="X-Line-Signature header not found")

    body_bytes = await request.body()
    body = body_bytes.decode('utf-8')

    try:
        # WebhookHandlerに渡す前に、background_tasks をグローバルか何かにセットするか、
        # あるいは、handleメソッドを呼び出すのではなく、イベントをパースして、
        # 各イベントタイプに応じた処理（バックグラウンドタスクの登録など）をここで行う。
        #
        # 今回は、WebhookHandlerの仕組みを維持しつつ、
        # handle_image_message が呼び出された際に background_tasks を使えるようにする。
        # これは少しトリッキーなので、よりシンプルなのはイベントをここでパースする方法。
        #
        # 簡単な回避策として、リクエストスコープで background_tasks を保持する (DIは関数ごと)
        # または、handler.handle の代わりにイベントを直接処理する。

        # --- WebhookHandlerを使わずにイベントを直接処理するアプローチ ---
        events = handler.parser.parse(body, signature) # WebhookHandlerのパーサーだけ利用
        for event in events:
            if isinstance(event, MessageEvent):
                user_id = event.source.user_id if event.source else "unknown_user"
                if isinstance(event.message, WebhookImageMessageContent):
                    print(f"INFO: Image event received for user {user_id}. Adding to background tasks.")
                    # reply_token はここでは使わず、処理結果はPush Messageで送る
                    background_tasks.add_task(process_image_and_notify_user, user_id, None, event.message.id)
                elif isinstance(event.message, WebhookTextMessageContent):
                    # テキストメッセージは従来通り同期的に処理（またはこれも非同期にするか）
                    # ここでは handle_text_message を直接呼び出す (background_tasks は渡せない)
                    # もしテキストメッセージも非同期処理が必要なら同様のパターンで。
                    handle_text_message_sync_wrapper(event) # 同期ラッパー経由
                # 他のメッセージタイプもここに追加可能
            # 他のイベントタイプ (FollowEventなど) も処理可能
        
        # --- WebhookHandlerをそのまま使う場合 (background_tasksを渡すのが難しい) ---
        # この場合、handle_image_message内で background_tasks を直接使えないので、
        # 別の方法で非同期タスクを起動する必要がある (例: FastAPIのグローバルな executor を使うなど)
        # もしくは、FastAPIのレスポンスを返す前に同期的に reply する形に戻す。
        # handler.handle(body, signature) # この呼び出し方だと background_tasks を渡せない

    except InvalidSignatureError:
        # (変更なし)
        print("ERROR: Invalid signature. Please check your channel secret.")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        # (変更なし)
        print(f"ERROR: Error handling webhook: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

    # LINEプラットフォームにはすぐに200 OKを返す
    return "OK"


# handle_text_message は同期的なので、直接呼び出すためのラッパー (もし必要なら)
def handle_text_message_sync_wrapper(event: MessageEvent):
    # この関数は実際には @handler.add で登録されたものが直接呼ばれるので、
    # callback内でイベントタイプを判別して、同期処理を呼び出す場合、
    # handler.handle を使わずに、このようにする。
    # ただし、@handler.add を使うなら、このラッパーは不要。
    try:
        user_id = event.source.user_id if event.source else "unknown_user"
        print(f"INFO: Received text message from LINE User ID: [{user_id}], Text: \"{event.message.text}\"")
        reply_token = event.reply_token
        received_text = event.message.text

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


# WebhookHandler に登録する同期関数 (ここからバックグラウンドタスクを起動)
@handler.add(MessageEvent, message=WebhookImageMessageContent)
def handle_image_message_trigger(event: MessageEvent):
    user_id = event.source.user_id if event.source else "unknown_user"
    message_id = event.message.id
    reply_token = event.reply_token # reply_tokenは最初のACKに使うか、Push Messageなら不要

    print(f"INFO: ***** Image message trigger from LINE User ID: [{user_id}], Message ID: [{message_id}] *****")

    # ここで BackgroundTasks を直接使えないので、工夫が必要。
    # 1. FastAPIの Request オブジェクトから BackgroundTasks を取得する (通常はエンドポイントの引数でDI)
    # 2. または、メインの /callback エンドポイントでイベントをパースし、そこからタスクを起動する (上記で試した方法)

    # --- 案2: /callback でパースし、このハンドラは使わない ---
    # この @handler.add はコメントアウトし、/callback 内で MessageEvent と WebhookImageMessageContent を判定して
    # background_tasks.add_task(process_image_and_notify_user, ...) を呼び出すのが最もクリーン。

    # --- もしこのハンドラを維持したい場合の一時的な対応 (非推奨) ---
    # 即時応答として「処理を開始しました」と返し、実際の処理は非同期で行うことを示唆する。
    # ただし、バックグラウンドタスクの起動はこの関数スコープから直接は難しい。
    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[MessagingTextMessage(text="画像を受け付けました。処理結果は後ほど通知します。")]
            )
        )
        print(f"INFO: [{user_id}] Sent initial ACK for image message.")
        # 実際の非同期処理の起動は別途検討が必要（例: メッセージキューイングなど）
        # ここでは、FastAPIのコールバックエンドポイントが BackgroundTasks を使えるように修正するのが本筋。
    except Exception as e:
        print(f"ERROR: [{user_id}] Failed to send initial ACK: {e}")


# テキストメッセージハンドラは従来通り
@handler.add(MessageEvent, message=WebhookTextMessageContent)
def handle_text_message(event: MessageEvent):
    # (変更なし)
    user_id = event.source.user_id
    print(f"INFO: Received text message from LINE User ID: [{user_id}], Text: \"{event.message.text}\"")
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "Unknown text message format"
    try:
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