# Dockerfile (修正・最適化後)

# 1. ベースイメージの選択
# 安定しており、広く使われているバージョン（例: 3.11-slim）を使用します。
# あなたのローカル開発環境のPythonバージョンに合わせるのが理想的です。
FROM python:3.11-slim

# 環境変数を設定 (Pythonのバッファリングを無効にし、ログがすぐに出力されるようにする)
ENV PYTHONUNBUFFERED 1

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
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]