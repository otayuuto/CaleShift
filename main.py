# main.py (設定読み込み確認版)
from fastapi import FastAPI
# config.py から settings オブジェクトをインポート
from app.core.config import settings # app/core/config.py が存在する必要あり

app = FastAPI(title=settings.PROJECT_NAME) # タイトルを設定から取得

@app.get("/")
async def read_root():
    # .envから読み込んだ値（またはデフォルト値）が表示される
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}

@app.get("/config-check")
async def check_config():
    # .envから読み込んだシークレットなどを確認（本番では公開しないように注意）
    return {"line_secret_loaded": bool(settings.LINE_CHANNEL_SECRET != "dummy_secret")}

if __name__ == "__main__":
    import uvicorn
    # hostを環境変数から読み込む例 (より柔軟)
    # uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)