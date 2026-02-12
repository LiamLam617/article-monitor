# 文章閱讀數監測 - 支援 2 核 2GB 低資源部署（運行時設 RESOURCE_PROFILE=low 或 LOW_MEMORY=1）
# 構建: docker build -t article-monitor .
# 運行: 建議使用 docker-compose up -d（已配置 shm、資源限制與健康檢查）
FROM python:3.11-slim-bookworm

LABEL maintainer="article-monitor" \
      description="Article read count monitor with Playwright/Crawl4AI"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    FLASK_DEBUG=false \
    PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright

# 安裝系統依賴（curl 用於健康檢查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    wget \
    gnupg \
    ca-certificates \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依賴先行，利用分層緩存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Playwright + Chromium（爬蟲必需）；全局路徑供所有用戶使用
RUN playwright install-deps chromium \
    && PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright playwright install chromium \
    && chmod -R 755 /usr/local/share/playwright

# 非 root 運行（安全）
RUN groupadd -r monitor && useradd -r -g monitor -d /app -s /sbin/nologin monitor

COPY . .

# 數據與日誌目錄（卷掛載時可覆蓋）
RUN mkdir -p /app/data /app/logs \
    && chown -R monitor:monitor /app \
    && chown -R monitor:monitor /usr/local/share/playwright

USER monitor

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# 2C2G：compose 預設 RESOURCE_PROFILE=low、memory 2g；主機 ≥3GB 時可在 compose 中提高 memory 並取消 RESOURCE_PROFILE=low
CMD ["python", "run_monitor.py"]
