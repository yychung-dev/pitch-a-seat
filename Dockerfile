# 使用 amd64 架構的 python 3.11 映像
FROM python:3.11-slim

# 安裝必要系統套件
RUN apt-get update && apt-get install -y gcc libjpeg-dev zlib1g-dev && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製依賴與安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製所有程式碼與 static 檔案
COPY . .

# 對外expose container port 8000
EXPOSE 8000

# 執行 FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

