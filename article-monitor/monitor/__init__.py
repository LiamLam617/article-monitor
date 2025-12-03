"""
Article Monitor - 文章阅读数监测系统

这个包提供了一个完整的文章阅读数监测解决方案，包括：
- 多平台文章爬取
- 数据存储和管理
- 定时任务调度
- Web界面展示
"""

__version__ = "1.0.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

from .app import app
from .config import (
    DATABASE_PATH,
    CRAWL_INTERVAL_HOURS,
    FLASK_HOST,
    FLASK_PORT,
    SUPPORTED_SITES,
)
from .database import init_db

__all__ = [
    "app",
    "init_db",
    "DATABASE_PATH",
    "CRAWL_INTERVAL_HOURS",
    "FLASK_HOST",
    "FLASK_PORT",
    "SUPPORTED_SITES",
    "__version__",
]
