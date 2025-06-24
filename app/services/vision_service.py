# app/services/vision_service.py
from google.cloud import vision
import io

def detect_text_from_image_bytes(image_bytes: bytes) -> str | None: # Python 3.10+
# def detect_text_from_image_bytes(image_bytes: bytes) -> Optional[str]: # Python 3.9以前 + from typing import Optional
    """
    画像バイトデータからテキストを検出します。
    :param image_bytes: 画像のバイトデータ
    :return: 検出されたテキスト文字列、またはエラーの場合はNone
    """
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)
        response = client.text_detection(image=image) # または document_text_detection
        
        if response.error.message:
            raise Exception(
                f"{response.error.message}\nFor more info on error messages, "
                f"check: https://cloud.google.com/apis/design/errors"
            )

        if response.text_annotations:
            detected_text = response.text_annotations[0].description
            print(f"INFO - vision_service - Detected text (length: {len(detected_text)}). Preview: {detected_text[:100]}...")
            return detected_text
        else:
            print("INFO - vision_service - No text detected in the image.")
            return None

    except Exception as e:
        print(f"ERROR - vision_service - Error in Vision API call: {e}")
        import traceback
        traceback.print_exc()
        return None

# (オプション) ファイルパスから読み込む関数 (テスト用など)
# def detect_text_from_image_file(image_path: str) -> Optional[str]:
#     try:
#         with io