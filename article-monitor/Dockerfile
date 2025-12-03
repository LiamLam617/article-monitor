# ==========================================
# Stage 1: Builder / Environment Setup
# ==========================================
FROM python:3.11-slim as builder

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # 设置时区为上海
    TZ=Asia/Shanghai \
    # 设置 Playwright 浏览器安装路径为系统全局路径
    PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright

# 1. 设置国内源 (加快构建速度)
# 替换 debian 源 (可选，如果构建慢可以取消注释)
# RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 2. 安装基础系统工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    tzdata \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 3. 复制依赖文件
COPY requirements.txt .

# 4. 安装 Python 依赖 (使用清华源)
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 安装 Playwright 依赖和浏览器
# 关键修复：以 root 身份安装浏览器到系统路径，确保所有用户都能访问
RUN playwright install-deps chromium \
    && PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright playwright install chromium

# ==========================================
# Stage 2: Final Runtime Image
# ==========================================
# 为了保持简单和环境一致性，我们在单阶段构建中完成，
# 或者可以直接复用上面的环境。对于 Playwright，多阶段构建比较复杂(因为需要复制大量系统库)，
# 所以这里我们保持单阶段，但在上面做好了清理。

# 创建非 root 用户 (安全性最佳实践)
RUN groupadd -r monitor && useradd -r -g monitor -d /app -s /sbin/nologin monitor

# 复制应用代码
COPY . .

# 创建必要的目录并设置权限
RUN mkdir -p /app/data /app/logs \
    && chown -R monitor:monitor /app

# 切换到非 root 用户
USER monitor

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# 启动命令
CMD ["python", "run_monitor.py"]
