"""
配置文件 - 简单直接，不要过度设计
支持环境变量配置
"""
import os

# 数据库文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, '..', 'data', 'monitor.db')

# 爬取配置（支持环境变量）
CRAWL_INTERVAL_HOURS = int(os.getenv('CRAWL_INTERVAL_HOURS', '6'))  # 每6小时爬取一次
CRAWL_TIMEOUT = int(os.getenv('CRAWL_TIMEOUT', '60'))  # 60秒超时

# 爬取并发数（同时爬取的文章数量，建议3-10之间）
# 优化：根据平台数量动态调整，但不超过10
CRAWL_CONCURRENCY = min(int(os.getenv('CRAWL_CONCURRENCY', '5')), 10)

# 爬取延迟（秒，每个请求之间的延迟，0表示无延迟，建议0.5-1秒）
CRAWL_DELAY = float(os.getenv('CRAWL_DELAY', '1'))

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
FLASK_PORT = int(os.getenv('FLASK_PORT', '5000'))
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
    ALLOWED_PLATFORMS = ['juejin', 'csdn', 'cnblog', '51cto', 'segmentfault', 'jinshu', 'MBB', 'elecfans', 'sohu']

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

# 平台提取规则配置
# 每个平台可以定义多个提取模式，按优先级顺序尝试
# 支持的字段：
#   - patterns: 正则表达式列表，用于从HTML中提取阅读数
#   - wait_for: CSS选择器，等待该元素加载（可选）
#   - timeout: 页面超时时间（毫秒），默认20000
#   - parse_method: 解析方法，支持 'number'（默认）, 'number_with_suffix'（支持k/m/w后缀）
PLATFORM_EXTRACTORS = {
    'juejin': {
        'wait_for': 'css:.views-count',
        'patterns': [
            r'class="views-count"[^>]*>([^<]+)',
            r'([\d,]+[km]?)\s*阅读'
        ],
        'parse_method': 'number_with_suffix'
    },
    'csdn': {
        'wait_for': 'css:.read-count',
        'patterns': [
            r'class="read-count"[^>]*>([^<]+)',
            r'阅读[：:]\s*([\d,]+[kmwKMW]?)',
            r'([\d,]+[kmwKMW]?)\s*阅读'
        ],
        'parse_method': 'number_with_suffix'
    },
    'cnblog': {
        'wait_for': 'css:#post_view_count',
        'patterns': [
            r'id="post_view_count"[^>]*>([\d,]+)</span>',
            r'id="post_view_count"[^>]*>([\d,]+)',
            r'阅读[：:]\s*([\d,]+)',
            r'views[：:]\s*([\d,]+)'
        ],
        'parse_method': 'number'
    },
    '51cto': {
        'timeout': 30000,
        'patterns': [
            r'<em[^>]*>阅读数</em>\s*<b[^>]*>([\d,]+)</b>',
            r'阅读数</em>\s*<b[^>]*>([\d,]+)</b>',
            r'阅读数[：:]\s*([\d,]+)',
            r'<p[^>]*class="[^"]*mess-tag[^"]*"[^>]*>.*?<b[^>]*>([\d,]+)</b>'
        ],
        'parse_method': 'number'
    },
    'segmentfault': {
        'patterns': [
            r'<span[^>]*>阅读\s*<!--[^>]*-->\s*([\d,]+)</span>',
            r'阅读\s+([\d,]+)'
        ],
        'parse_method': 'number'
    },
    'jinshu': {
        'patterns': [
            r'<span[^>]*>阅读\s+([\d,]+)</span>',
            r'阅读\s*([\d,]+)'
        ],
        'parse_method': 'number'
    },
    'elecfans': {
        'patterns': [
            r'<span[^>]*class="art_click_count"[^>]*>([\d,]+)</span>',
            r'([\d,]+)\s*次阅读'
        ],
        'parse_method': 'number'
    },
    'MBB': {
        'timeout': 30000,
        'patterns': [
            r'<span[^>]*class="[^"]*view[^"]*"[^>]*>([\d,]+)</span>',
            r'阅读\s*([\d,]+)',
            r'浏览\s*([\d,]+)',
            r'([\d,]+)\s*阅读'
        ],
        'parse_method': 'number'
    },
    'eefocus': {
        'patterns': [
            r'<div[^>]*class="hot-num"[^>]*>.*?<img[^>]*>([\d,]+)</div>',
            r'class="hot-num"[^>]*>.*?([\d,]+)',
            r'([\d,]+)\s*次?阅读'
        ],
        'parse_method': 'number'
    },
    'sohu': {
        # 使用 JavaScript 条件等待：确保 em[data-role="pv"] 中有数字
        'wait_for': 'js:() => { const el = document.querySelector("em[data-role=\\"pv\\"]"); return el && /^\\d+$/.test(el.textContent.trim()); }',
        'timeout': 30000,
        'js_extract': True,  # 使用 JavaScript 提取
        'patterns': [
            r'SOHU_PV_COUNT:(\d+)',  # 从注入的标记提取
            r'阅读\s*\(\s*(\d+)\s*\)',  # 匹配 "阅读 (601)"
            r'>(\d+)</em>',  # 直接匹配 em 中的数字
        ],
        'parse_method': 'number'
    },
    # 通用提取器（作为后备方案）
    'generic': {
        'patterns': [
            r'阅读[：:]\s*([\d,]+[kmw]?)',
            r'views[：:]\s*([\d,]+[kmw]?)',
            r'阅读数[：:]\s*([\d,]+[kmw]?)',
            r'([\d,]+[kmw]?)\s*阅读',
            r'([\d,]+[kmw]?)\s*views'
        ],
        'parse_method': 'number_with_suffix'
    }
}

# ==================== 應用常量 ====================
# CSV 導出相關
CSV_EXPORT_BATCH_SIZE = 100  # CSV 導出批次大小

# 任務管理器相關
TASK_QUEUE_TIMEOUT = 5.0  # 任務隊列超時時間（秒）
MAX_CONCURRENT_TASKS = 3  # 最大並發任務數

# 批量處理相關
BATCH_PROCESS_SIZE = 10  # 批量處理 URL 的批次大小
BATCH_PROCESS_CONCURRENCY = 5  # 批量處理的並發數

# 健康檢查相關
HEALTH_CHECK_TIMEOUT = 3  # 健康檢查超時時間（秒）
MAX_HEALTH_CHECK_WORKERS = 20  # 健康檢查最大工作線程數
