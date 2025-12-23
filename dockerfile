FROM python:3.11-slim

WORKDIR /app

# 先安裝依賴（利於快取）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案
COPY . .

# Cloud Run 會提供 PORT，預設 8080
ENV PORT=8080

# SQLite demo：單 worker，避免併發鎖死
CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT} jimmyworksheet:server"]
