"""
配置文件 - 简单直接，不要过度设计
支持环境变量配置
"""
import os

# 数据库文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, '..', 'data', 'monitor.db')

# 可選調試日誌路徑（主要供開發除錯使用）
DEBUG_LOG_PATH = os.getenv('ARTICLE_MONITOR_DEBUG_LOG') or None

# ==================== 資源配置（2C2G 低資源模式） ====================
# RESOURCE_PROFILE=low 或 LOW_MEMORY=1 時啟用 2 核 2GB 友善預設（並發、池大小、SQLite、線程數等）
_RESOURCE_PROFILE = (os.getenv('RESOURCE_PROFILE', '').strip().lower() == 'low' or
                    os.getenv('LOW_MEMORY', '').strip() in ('1', 'true', 'yes'))

# 爬取配置（支持环境变量）
CRAWL_INTERVAL_HOURS = int(os.getenv('CRAWL_INTERVAL_HOURS', '6'))  # 每6小时爬取一次
CRAWL_TIMEOUT = int(os.getenv('CRAWL_TIMEOUT', '60'))  # 60秒超时

# 爬取并发数（同时爬取的文章数量，建议3-10之间）
# 低資源時預設 2，否則 5；不超過 10
_CRAWL_CONCURRENCY_DEFAULT = '2' if _RESOURCE_PROFILE else '5'
CRAWL_CONCURRENCY = min(int(os.getenv('CRAWL_CONCURRENCY', _CRAWL_CONCURRENCY_DEFAULT)), 10)

# 爬取延迟（秒，每个请求之间的延迟，0表示无延迟，建议0.5-1秒）
CRAWL_DELAY = float(os.getenv('CRAWL_DELAY', '1'))

# 每域名并发数（同一站点同时最多 N 个请求；0 表示不限制，沿用全局并发）
# 降低可提高同一站点大量文章时的成功率，避免触发反爬
CRAWL_CONCURRENCY_PER_DOMAIN = max(0, int(os.getenv('CRAWL_CONCURRENCY_PER_DOMAIN', '1')))

# 是否按站点交错调度（round-robin 按 site 打散顺序，使并发更均匀分布在多站点）
CRAWL_INTERLEAVE_BY_SITE = os.getenv('CRAWL_INTERLEAVE_BY_SITE', 'True').lower() in ('true', '1', 'yes')

# 同一域名两次请求之间的最小间隔（秒；0 表示不限制）
CRAWL_MIN_DELAY_PER_DOMAIN = max(0.0, float(os.getenv('CRAWL_MIN_DELAY_PER_DOMAIN', '0')))

# 重试配置
CRAWL_MAX_RETRIES = int(os.getenv('CRAWL_MAX_RETRIES', '10'))  # 最大重试次数（网络错误）
CRAWL_RETRY_DELAY = float(os.getenv('CRAWL_RETRY_DELAY', '2'))  # 重试延迟（秒）
CRAWL_RETRY_BACKOFF = float(os.getenv('CRAWL_RETRY_BACKOFF', '1.5'))  # 重试退避倍数
CRAWL_RETRY_MAX_DELAY = float(os.getenv('CRAWL_RETRY_MAX_DELAY', '30'))  # 最大重试延迟（秒）
CRAWL_RETRY_JITTER = os.getenv('CRAWL_RETRY_JITTER', 'True').lower() in ('true', '1', 'yes')  # 是否启用抖动

# 不同错误类型的重试配置
CRAWL_RETRY_NETWORK_MAX = int(os.getenv('CRAWL_RETRY_NETWORK_MAX', '10'))  # 网络错误最大重试次数
CRAWL_RETRY_PARSE_MAX = int(os.getenv('CRAWL_RETRY_PARSE_MAX', '3'))  # 解析错误最大重试次数
CRAWL_RETRY_SSL_MAX = int(os.getenv('CRAWL_RETRY_SSL_MAX', '5'))  # SSL错误最大重试次数
CRAWL_RETRY_SSL_DELAY = float(os.getenv('CRAWL_RETRY_SSL_DELAY', '5'))  # SSL错误固定延迟（秒）

# ==================== 防反爬配置 ====================
# 是否启用防反爬功能
ANTI_SCRAPING_ENABLED = os.getenv('ANTI_SCRAPING_ENABLED', 'True').lower() in ('true', '1', 'yes')

# 是否轮换 User-Agent
ANTI_SCRAPING_ROTATE_UA = os.getenv('ANTI_SCRAPING_ROTATE_UA', 'True').lower() in ('true', '1', 'yes')

# 是否使用随机延迟
ANTI_SCRAPING_RANDOM_DELAY = os.getenv('ANTI_SCRAPING_RANDOM_DELAY', 'True').lower() in ('true', '1', 'yes')

# 是否启用隐身模式（隐藏自动化特征）
ANTI_SCRAPING_STEALTH_MODE = os.getenv('ANTI_SCRAPING_STEALTH_MODE', 'True').lower() in ('true', '1', 'yes')

# 随机延迟范围（秒）
ANTI_SCRAPING_MIN_DELAY = float(os.getenv('ANTI_SCRAPING_MIN_DELAY', '1.0'))
ANTI_SCRAPING_MAX_DELAY = float(os.getenv('ANTI_SCRAPING_MAX_DELAY', '5.0'))

# User-Agent 轮换间隔（每隔多少个请求更换）
ANTI_SCRAPING_UA_ROTATION_MIN = int(os.getenv('ANTI_SCRAPING_UA_ROTATION_MIN', '10'))
ANTI_SCRAPING_UA_ROTATION_MAX = int(os.getenv('ANTI_SCRAPING_UA_ROTATION_MAX', '30'))

# Flask配置（支持环境变量）
FLASK_HOST = os.getenv('FLASK_HOST', '127.0.0.1')
FLASK_PORT = int(os.getenv('FLASK_PORT', '5001'))
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')

# 支持的网站
SUPPORTED_SITES = {
    'juejin.cn': 'juejin',
    'csdn.net': 'csdn',
    'cnblogs.com': 'cnblog',
    '51cto.com': '51cto',
    'china.com': 'MBB',
    'elecfans.com': 'elecfans',
    'segmentfault.com': 'segmentfault',
    'jianshu.com': 'jinshu',  # 修改为 jinshu 以匹配数据库
    'eefocus.com': 'eefocus',
    'sohu.com': 'sohu'
}

# 允许爬取的平台（白名单，支持环境变量，用逗号分隔）
# 如果为空列表，则允许所有平台
# 例如：ALLOWED_PLATFORMS=juejin,csdn,cnblog
ALLOWED_PLATFORMS_ENV = os.getenv('ALLOWED_PLATFORMS', '').strip()
if ALLOWED_PLATFORMS_ENV:
    ALLOWED_PLATFORMS = [p.strip() for p in ALLOWED_PLATFORMS_ENV.split(',') if p.strip()]
else:
    # 默认白名单：只允许常用平台
    ALLOWED_PLATFORMS = ['juejin', 'csdn', 'cnblog', '51cto', 'segmentfault', 'jinshu', 'MBB', 'elecfans', 'sohu', 'eefocus']

def is_platform_allowed(site: str) -> bool:
    """检查平台是否在白名单中
    
    Args:
        site: 平台名称（如 'juejin', 'csdn'）
        
    Returns:
        如果白名单为空或平台在白名单中，返回 True；否则返回 False
    """
    if not ALLOWED_PLATFORMS:  # 空列表表示允许所有平台
        return True
    return site in ALLOWED_PLATFORMS if site else False

from .platform_rules import PLATFORM_EXTRACTORS

# ==================== 應用常量 ====================
# CSV 導出相關
CSV_EXPORT_BATCH_SIZE = 100  # CSV 導出批次大小

# 任務管理器相關
TASK_QUEUE_TIMEOUT = 5.0  # 任務隊列超時時間（秒）
_MAX_CONCURRENT_TASKS_DEFAULT = 2 if _RESOURCE_PROFILE else 3
MAX_CONCURRENT_TASKS = int(os.getenv('MAX_CONCURRENT_TASKS', str(_MAX_CONCURRENT_TASKS_DEFAULT)))

# 批量處理相關
BATCH_PROCESS_SIZE = 10  # 批量處理 URL 的批次大小
BATCH_PROCESS_CONCURRENCY = 5  # 批量處理的並發數

# 健康檢查相關
HEALTH_CHECK_TIMEOUT = 3  # 健康檢查超時時間（秒）
_MAX_HEALTH_CHECK_WORKERS_DEFAULT = 4 if _RESOURCE_PROFILE else 20
MAX_HEALTH_CHECK_WORKERS = int(os.getenv('MAX_HEALTH_CHECK_WORKERS', str(_MAX_HEALTH_CHECK_WORKERS_DEFAULT)))

# 瀏覽器池（低資源時 max=2, min=1，與 CRAWL_CONCURRENCY=2 搭配）
_BROWSER_POOL_MAX_DEFAULT = 2 if _RESOURCE_PROFILE else 5
_BROWSER_POOL_MIN_DEFAULT = 1 if _RESOURCE_PROFILE else 2
BROWSER_POOL_MAX_SIZE = int(os.getenv('BROWSER_POOL_MAX_SIZE', str(_BROWSER_POOL_MAX_DEFAULT)))
BROWSER_POOL_MIN_SIZE = int(os.getenv('BROWSER_POOL_MIN_SIZE', str(_BROWSER_POOL_MIN_DEFAULT)))

# SQLite 每連接 cache 大小（KB）。低資源時 2MB，否則 64MB。PRAGMA cache_size 使用負值表示頁數（約 1 頁=1KB）
_SQLITE_CACHE_KB_DEFAULT = 2048 if _RESOURCE_PROFILE else 65536
SQLITE_CACHE_SIZE_KB = int(os.getenv('SQLITE_CACHE_SIZE_KB', str(_SQLITE_CACHE_KB_DEFAULT)))

# ==================== 飞书 Bitable 配置 ====================
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '').strip()
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '').strip()
FEISHU_BITABLE_APP_TOKEN = os.getenv('FEISHU_BITABLE_APP_TOKEN', '').strip()
FEISHU_BITABLE_TABLE_ID = os.getenv('FEISHU_BITABLE_TABLE_ID', '').strip()

# Bitable 列名映射（与多维表格中的字段名一致，可被请求体覆盖）
FEISHU_BITABLE_FIELD_URL = os.getenv('FEISHU_BITABLE_FIELD_URL', '发布链接')
FEISHU_BITABLE_FIELD_TOTAL_READ = os.getenv('FEISHU_BITABLE_FIELD_TOTAL_READ', '总阅读量')
FEISHU_BITABLE_FIELD_READ_24H = os.getenv('FEISHU_BITABLE_FIELD_READ_24H', '24小时阅读量')
FEISHU_BITABLE_FIELD_READ_72H = os.getenv('FEISHU_BITABLE_FIELD_READ_72H', '72小时阅读量')
FEISHU_BITABLE_FIELD_ERROR = os.getenv('FEISHU_BITABLE_FIELD_ERROR', '失败原因')

# 写回 Bitable 时错误信息最大长度（字符）
def _parse_error_message_max_len() -> int:
    raw = os.getenv('FEISHU_BITABLE_ERROR_MESSAGE_MAX_LEN', '200').strip()
    try:
        n = int(raw)
    except ValueError:
        n = 200
    return min(500, max(100, n))


FEISHU_BITABLE_ERROR_MESSAGE_MAX_LEN = _parse_error_message_max_len()
