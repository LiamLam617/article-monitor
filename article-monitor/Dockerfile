FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    FLASK_DEBUG=false \
    PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright

# 安装系统依赖
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

# 先复制依赖文件，利用 Docker 缓存层优化构建
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 Playwright 和 Chromium（浏览器爬虫必需）
# 使用全局路径安装，确保所有用户都能访问
RUN playwright install-deps chromium \
    && PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright playwright install chromium \
    && chmod -R 755 /usr/local/share/playwright

# 创建非 root 用户（安全最佳实践）
RUN groupadd -r monitor && useradd -r -g monitor -d /app -s /sbin/nologin monitor

# 复制应用代码
COPY . .

# 创建必要的目录并设置权限
RUN mkdir -p /app/data /app/logs \
    && chown -R monitor:monitor /app \
    && chown -R monitor:monitor /usr/local/share/playwright

USER monitor

EXPOSE 5000

# 健康检查（使用 Python 腳本，更可靠）
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python3 /app/healthcheck.py

CMD ["python", "run_monitor.py"]
