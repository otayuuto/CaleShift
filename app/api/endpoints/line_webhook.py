# app/api/endpoints/line_webhook.py

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage as MessagingTextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent as WebhookTextMessageContent,
    ImageMessageContent as WebhookImageMessageContent,
    FollowEvent, # FollowEvent もインポート
)
from google.cloud.firestore import Client as FirestoreClient # 型ヒント用

from typing import Optional, List # List をインポート

from app.core.config import settings
from app.services import vision_service, calendar_service, firestore_service # firestore_service もインポート
from app.utils.image_parser import ShiftInfo, parse_shift_text_to_structured_data # ShiftInfoとパーサーもインポート
import traceback

router = APIRouter()

# WebhookHandler はイベントのパースにのみ使用する（今回は）
handler_parser = WebhookHandler(settings.LINE_CHANNEL_SECRET).parser # パーサーのみ取得

# LINE SDKクライアントの初期化
configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(api_client=ApiClient(configuration))
line_bot_blob_api = MessagingApiBlob(api_client=ApiClient(configuration))

print("INFO - app.api.endpoints.line_webhook - LINE Messaging API clients initialized successfully.")


# 非同期の画像処理とカレンダー登録、結果通知を行う関数
async def process_image_and_calendar_registration(
    db_client: Optional[FirestoreClient], # Firestoreクライアントを引数で受け取る
    user_id: str,
    message_id: str
):
    """
    画像の処理、カレンダー登録、結果のプッシュ通知を行う非同期関数。
    """
    final_reply_text = "画像の処理が完了しました。" # デフォルト
    processed_shifts_count = 0
    created_event_ids: List[str] = []
    failed_to_create_count = 0
    parse_results_for_reply: List[str] = []

    try:
        if not db_client:
            print(f"BACKGROUND_TASK_ERROR: [{user_id}] Firestore client not available for message_id: {message_id}")
            final_reply_text = "データベース接続エラーが発生しました。"
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
            return

        print(f"BACKGROUND_TASK: [{user_id}] Started image processing for message_id: {message_id}")
        message_content_response = line_bot_blob_api.get_message_content(message_id=message_id)
        image_bytes = b''
        # iter_content() が存在するか確認してバイトデータを取得
        if hasattr(message_content_response, 'iter_content'):
            for chunk in message_content_response.iter_content():
                image_bytes += chunk
        else: # 直接バイト列が返ってくる場合など
            image_bytes = message_content_response

        if not image_bytes:
            print(f"BACKGROUND_TASK_ERROR: [{user_id}] Failed to retrieve image content from LINE.")
            final_reply_text = "画像の取得に失敗しました。"
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
            return

        print(f"BACKGROUND_TASK_INFO: [{user_id}] Retrieved {len(image_bytes)} bytes of image data.")
        detected_text = vision_service.detect_text_from_image_bytes(image_bytes)

        if detected_text:
            print(f"BACKGROUND_TASK_INFO: [{user_id}] Vision API detected text. Parsing...")
            # image_parser.py の関数名を合わせる (parse_shift_text_to_structured_data を使う)
            parsed_shift_data_list: List[ShiftInfo] = parse_shift_text_to_structured_data(detected_text)

            if parsed_shift_data_list:
                for shift_info in parsed_shift_data_list:
                    date_str = shift_info.date.strftime("%m/%d")
                    name_s = f"{shift_info.name} " if shift_info.name else ""
                    role_s = f"({shift_info.role})" if shift_info.role else ""
                    
                    if shift_info.is_holiday:
                        parse_results_for_reply.append(f"- {date_str}: {name_s}休み")
                        continue
                    if not shift_info.start_time or not shift_info.end_time:
                        start_t = shift_info.start_time.strftime("%H:%M") if shift_info.start_time else "未定"
                        end_t = shift_info.end_time.strftime("%H:%M") if shift_info.end_time else "未定"
                        parse_results_for_reply.append(f"- {date_str}: {name_s}{start_t}～{end_t} {role_s} (時刻不備)".strip())
                        continue
                    
                    processed_shifts_count += 1
                    start_t = shift_info.start_time.strftime("%H:%M")
                    end_t = shift_info.end_time.strftime("%H:%M")
                    memo_s = f" [{shift_info.memo}]" if shift_info.memo else ""
                    
                    # calendar_service.create_calendar_event に db_client を渡す
                    event_id = await calendar_service.create_calendar_event(db_client, user_id, shift_info)
                    if event_id:
                        created_event_ids.append(event_id)
                        parse_results_for_reply.append(f"- {date_str}: {name_s}{start_t}～{end_t} {role_s}{memo_s} -> 登録成功".strip())
                    else:
                        failed_to_create_count += 1
                        parse_results_for_reply.append(f"- {date_str}: {name_s}{start_t}～{end_t} {role_s}{memo_s} -> 登録失敗".strip())
                
                # --- 返信メッセージの組み立て ---
                if not parsed_shift_data_list : # パース結果が空のリストだった場合 (ありえないはずだが念のため)
                    final_reply_text = "画像からシフト情報を読み取れませんでした。"
                elif processed_shifts_count == 0: # 有効なシフトがなかった (休みや時刻不備のみ)
                    final_reply_text = "解析されたシフト:\n" + "\n".join(parse_results_for_reply)
                    final_reply_text += "\n\nカレンダーに登録可能な有効なシフトが見つかりませんでした。"
                elif created_event_ids: # 1件でも成功
                    final_reply_text = f"{len(created_event_ids)}件のシフトをカレンダーに登録しました。"
                    if failed_to_create_count > 0:
                        final_reply_text += f"\n{failed_to_create_count}件の登録に失敗しました。"
                    final_reply_text += "\n\n処理結果:\n" + "\n".join(parse_results_for_reply)
                elif failed_to_create_count > 0: # 全て失敗
                    final_reply_text = f"{failed_to_create_count}件全てのシフトのカレンダー登録に失敗しました。"
                    final_reply_text += "\n\n処理結果:\n" + "\n".join(parse_results_for_reply)
                else: # 通常ここには来ないはず
                    final_reply_text = "シフト情報を処理しましたが、結果が不明です。"

            else: # テキストは抽出できたが、シフト情報としてパースできなかった
                final_reply_text = "テキストは抽出できましたが、シフト情報として解析できませんでした。"
        else: # 画像からテキストを抽出できなかった
            final_reply_text = "画像からテキストを抽出できませんでした。"

        if len(final_reply_text) > 4800: # LINEのメッセージ長制限
             final_reply_text = final_reply_text[:4800] + "\n...(長すぎるため省略)"
        
        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=final_reply_text)]))
        print(f"BACKGROUND_TASK_INFO: [{user_id}] Pushed final result to user.")

    except Exception as e:
        print(f"BACKGROUND_TASK_ERROR: [{user_id}] Unhandled error in process_image_and_calendar_registration: {e}")
        traceback.print_exc()
        try:
            error_message_to_user = "画像の処理中に予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。"
            line_bot_api.push_message(
                PushMessageRequest(to=user_id, messages=[MessagingTextMessage(text=error_message_to_user)])
            )
        except Exception as e2:
            print(f"BACKGROUND_TASK_ERROR: [{user_id}] Failed to send final error push message: {e2}")


# FastAPIのコールバックエンドポイント
@router.post("/callback", summary="LINE Bot Webhook callback")
async def line_webhook_callback(request: Request, background_tasks: BackgroundTasks):
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="X-Line-Signature header not found")

    body_bytes = await request.body()
    body = body_bytes.decode('utf-8')
    print(f"INFO: Received webhook body: {body[:500]}...") # 長すぎる場合は一部表示

    db_client = request.app.state.db # main.py の startup で初期化されたDBクライアント

    try:
        events = handler_parser.parse(body, signature) # WebhookHandlerのパーサーだけ利用
    except InvalidSignatureError:
        print("ERROR: Invalid signature. Please check your channel secret.")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print(f"ERROR: Error parsing webhook body: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error parsing webhook body")

    for event in events:
        user_id = event.source.user_id if event.source else "unknown_user"
        print(f"INFO: Processing event for user_id: {user_id}, event_type: {event.type}")

        if isinstance(event, MessageEvent):
            if isinstance(event.message, WebhookImageMessageContent):
                print(f"INFO: Image event received from {user_id}. Adding to background tasks. Message ID: {event.message.id}")
                # ユーザーには即時応答 (ACK) を返す
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[MessagingTextMessage(text="画像を受け付けました。シフト情報を解析し、カレンダーに登録します。完了したら通知しますね！")]
                        )
                    )
                    print(f"INFO: Sent ACK to {user_id} for image message.")
                except Exception as e_ack:
                    print(f"ERROR: Failed to send ACK for image message to {user_id}: {e_ack}")
                
                # バックグラウンドで重い処理を実行
                background_tasks.add_task(
                    process_image_and_calendar_registration,
                    db_client, # Firestoreクライアントを渡す
                    user_id,
                    event.message.id
                )
            elif isinstance(event.message, WebhookTextMessageContent):
                # テキストメッセージは従来通り同期的に処理
                handle_text_message_sync(event) # 同期関数を呼び出し
            # 他のメッセージタイプ (スタンプなど) の処理もここに追加可能
            else:
                print(f"INFO: Received other message type from {user_id}: {event.message.type}")
                # 必要なら応答
                # line_bot_api.reply_message(
                #     ReplyMessageRequest(reply_token=event.reply_token, messages=[MessagingTextMessage(text="このメッセージタイプはまだ処理できません。")]))

        elif isinstance(event, FollowEvent):
            # フォローイベントの処理
            await handle_follow_event(db_client, event) # db_client を渡す

        # 他のイベントタイプ (UnfollowEvent, PostbackEventなど) の処理もここに追加可能
        else:
            print(f"INFO: Received other event type: {event.type}")

    return "OK" # LINEプラットフォームには常に200 OKを返す


# テキストメッセージを処理する同期関数
def handle_text_message_sync(event: MessageEvent):
    user_id = event.source.user_id if event.source else "unknown_user"
    reply_token = event.reply_token
    received_text = event.message.text if isinstance(event.message, WebhookTextMessageContent) else "Unknown"
    
    print(f"INFO: Text message from {user_id}: \"{received_text}\"")
    try:
        # 簡単なオウム返しか、特定のコマンドに応じた処理
        if received_text.lower() == "連携状況":
            # (例) Firestoreから連携状況を取得して返す (非同期処理が必要になる)
            # この関数は同期なので、ここでは単純な返信に留めるか、
            # 非同期処理を呼び出すトリガーとする (結果はPush Message)
            # status_message = get_connection_status_sync(user_id) # 仮の同期関数
            reply_msg = "Googleカレンダー連携機能は開発中です。"
        else:
            reply_msg = f"テキストメッセージ「{received_text}」を受け取りました。"

        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[MessagingTextMessage(text=reply_msg)])
        )
        print(f"INFO: Replied to text message for {user_id}")
    except Exception as e:
        print(f"ERROR: Error sending text reply for {user_id}: {e}")
        traceback.print_exc()


# フォローイベントを処理する非同期関数
async def handle_follow_event(db_client: Optional[FirestoreClient], event: FollowEvent):
    line_user_id = event.source.user_id
    reply_token = event.reply_token
    print(f"INFO: User {line_user_id} followed the bot.")

    if not db_client:
        print(f"ERROR: Firestore client not available in handle_follow_event for {line_user_id}")
        # フォロー時のDBエラーはユーザーには通知しにくいが、ログには残す
        return

    display_name = None
    try:
        # ここでLINE Profile APIを呼び出す処理を入れる (line_bot_api を使う)
        # 例: profile = line_bot_api.get_profile(line_user_id)
        #     display_name = profile.display_name
        # ただし、MessagingApi には get_profile がないので、別のSDK (linebot v2など) や直接APIを叩く必要がある
        # 簡単のため、ここでは表示名なしで進める
        print(f"INFO: [FollowEvent] Display name acquisition skipped for simplicity for {line_user_id}.")
    except Exception as e_profile:
        print(f"WARNING: [FollowEvent] Failed to get user profile for {line_user_id}: {e_profile}")

    success = await firestore_service.create_initial_user_document_on_follow(db_client, line_user_id, display_name)

    if success:
        ngrok_base_url = settings.NGROK_URL
        login_url_path = f"{settings.API_V1_STR}/google/login"
        message_text = "友だち追加ありがとうございます！シフト管理ボットです。"
        if ngrok_base_url:
            oauth_start_url = f"{ngrok_base_url}{login_url_path}?line_id={line_user_id}"
            if display_name: oauth_start_url += f"&display_name={display_name}" # URLエンコード推奨
            
            message_text += (
                "\n\nシフトをカレンダーに自動登録するには、Googleアカウントとの連携が必要です。"
                f"\n以下のURLから連携を開始してくださいね！\n{oauth_start_url}"
            )
        else:
            message_text += "\n\n現在、システム設定の問題でGoogle連携URLをご案内できません。後ほどお試しください。"
        
        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=[MessagingTextMessage(text=message_text)])
            )
            print(f"INFO: Sent follow-up message to {line_user_id}")
        except Exception as e_reply:
            print(f"ERROR: Failed to send follow-up message to {line_user_id}: {e_reply}")
    else:
        print(f"ERROR: Failed to create initial user document for {line_user_id} on follow.")