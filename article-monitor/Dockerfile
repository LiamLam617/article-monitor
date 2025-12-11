FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    FLASK_PORT=5001

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

RUN playwright install-deps chromium \
    && playwright install chromium

RUN groupadd -r monitor && useradd -r -g monitor -d /app -s /sbin/nologin monitor

COPY . .

RUN mkdir -p /app/data /app/logs \
    && chown -R monitor:monitor /app

USER monitor

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

CMD ["python", "run_monitor.py"]
