# 1. ベースイメージの選択
FROM python:3.12-slim

# 2. 作業ディレクトリの設定
WORKDIR /app

# ★★★ 3. ビルドに必要なツールをインストール ★★★
# RUN コマンドを分割し、このステップを追加します。
# これにより、C++コンパイラ (g++) などがインストールされます。
RUN apt-get update && apt-get install -y --no-install-recommends build-essential python3-dev

# 4. 依存関係ファイルのコピー
COPY ./requirements.txt /app/requirements.txt

# 5. 依存関係をインストール
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 6. アプリケーションコードのコピー
COPY ./app /app/app
COPY ./main.py /app/main.py
COPY ./templates /app/templates
# もし static ディレクトリも使用している場合は追加
# COPY ./static /app/static

# 7. アプリケーションの起動コマンド
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]