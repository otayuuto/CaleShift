# app/services/vision_service.py
from google.cloud import vision
import io

def detect_text_from_image_bytes(image_bytes: bytes) -> str | None:
    """
    画像バイトデータからテキストを検出します。
    :param image_bytes: 画像のバイトデータ
    :return: 検出されたテキスト文字列、またはエラーの場合はNone
    """
    try:
        client = vision.ImageAnnotatorClient() # クライアントはリクエストごとに作成しても良いし、
                                            # アプリケーション起動時に一度だけ作成して保持しても良い

        image = vision.Image(content=image_bytes)

        # TEXT_DETECTION を使用 (OCR)
        response = client.text_detection(image=image)
        texts = response.text_annotations

        if response.error.message:
            raise Exception(
                f"{response.error.message}\nFor more info on error messages, "
                f"check: https://cloud.google.com/apis/design/errors"
            )

        if texts:
            # 最初の要素 (index 0) は画像全体から検出されたテキストブロック全体を含むことが多い
            # 他の要素は個々の単語や行
            detected_text = texts[0].description
            print(f"Detected text from image:\n{detected_text[:500]}...") # 長いので一部表示
            return detected_text
        else:
            print("No text detected in the image.")
            return None

    except Exception as e:
        print(f"Error in Vision API call: {e}")
        return None

def detect_text_from_image_file(image_path: str) -> str | None:
    """
    画像ファイルパスからテキストを検出します。(テスト用などに)
    :param image_path: 画像ファイルのパス
    :return: 検出されたテキスト文字列、またはエラーの場合はNone
    """
    try:
        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()
        return detect_text_from_image_bytes(content)
    except Exception as e:
        print(f"Error reading image file {image_path}: {e}")
        return None

# (オプション) 他の検出機能（手書き文字検出 DOCUMENT_TEXT_DETECTION など）も必要に応じて追加