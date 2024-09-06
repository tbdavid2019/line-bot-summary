# 使用官方的 Python 3.11 slim 作為基礎映像
FROM python:3.11-slim

# 設置工作目錄
WORKDIR /app

# 複製當前目錄內容到容器的 /app 目錄下
COPY . /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    curl \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libxdamage1 \
    libgtk-3-0 \
    libwayland-client0 \
    libwayland-egl1 \
    libwayland-server0 \
    libx11-xcb1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install playwright

# 安裝 playwright 的瀏覽器依賴
RUN playwright install --with-deps

# 開放5000埠，讓外部可以連接
EXPOSE 5000

# 使用 gunicorn 啟動應用
CMD ["gunicorn", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]