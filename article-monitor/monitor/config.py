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
CRAWL_CONCURRENCY = int(os.getenv('CRAWL_CONCURRENCY', '5'))

# 爬取延迟（秒，每个请求之间的延迟，0表示无延迟，建议0.5-1秒）
CRAWL_DELAY = float(os.getenv('CRAWL_DELAY', '1'))

# 重试配置
CRAWL_MAX_RETRIES = int(os.getenv('CRAWL_MAX_RETRIES', '10'))  # 最大重试次数
CRAWL_RETRY_DELAY = float(os.getenv('CRAWL_RETRY_DELAY', '2'))  # 重试延迟（秒）
CRAWL_RETRY_BACKOFF = float(os.getenv('CRAWL_RETRY_BACKOFF', '1.5'))  # 重试退避倍数

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
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() in ('true', '1', 'yes')

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
    'freebuf.com': 'freebuf',
    'sohu.com': 'sohu'
}

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
    'freebuf': {
        # FreeBuf 有滑块验证码反爬机制，可能导致提取失败
        # 尝试等待文章内容加载，而不是直接等待 .review 元素
        'wait_for': 'css:article, .article-content, .post-content',  # 等待文章内容加载
        'timeout': 30000,  # 30秒超时（减少无效等待）
        'delay_before_return': 2000,  # 等待2秒让JS渲染
        'js_extract': True,  # 使用 JavaScript 提取
        'patterns': [
            r'READ_COUNT:([\d,]+)',  # 从 JS 注入的标记提取
            r'</i>\s*([\d,]+)\s+</span>',  # 匹配 </i> 和 </span> 之间的数字
            r'</i>\s*([\d,]+)\s*</span>',
            r'<span[^>]*class="review"[^>]*>.*?</i>\s*([\d,]+)\s+</span>',
            r'class="review"[^>]*>.*?<i[^>]*>.*?</i>\s*([\d,]+)\s+</span>',
            r'class="review"[^>]*>.*?([\d,]+)\s+</span>',
            r'fire[^>]*>.*?([\d,]+)'  # 备选：火焰图标后的数字
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
