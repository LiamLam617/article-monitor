"""
防反爬模块 - Anti-Anti-Scraping System

核心策略：
1. 擬人化 (Humanization) - 模拟真实用户行为
2. 去特徵化 (De-fingerprinting) - 隐藏自动化痕迹

功能层次：
- 网络层：User-Agent 池、请求头伪装
- 协议层：HTTP Headers 偽装、Referer 策略
- 应用层：浏览器指纹隐藏、视口随机化
- 行为层：随机延迟、鼠标移动模拟
"""
import random
import time
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


# ==================== User-Agent 池 ====================
# 真实的浏览器 User-Agent，定期更新
USER_AGENTS = {
    'chrome_windows': [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ],
    'chrome_mac': [
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ],
    'firefox_windows': [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0',
    ],
    'firefox_mac': [
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',
    ],
    'edge_windows': [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
    ],
    'safari_mac': [
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    ]
}

# 所有 UA 扁平化列表（用于随机选择）
ALL_USER_AGENTS = [ua for uas in USER_AGENTS.values() for ua in uas]


# ==================== 语言和地区配置 ====================
ACCEPT_LANGUAGES = [
    'zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7',
    'zh-TW,zh;q=0.9,en;q=0.8',
    'zh-CN,zh;q=0.9',
    'en-US,en;q=0.9,zh-CN;q=0.8',
    'ja-JP,ja;q=0.9,en;q=0.8',
]

# 时区偏移（分钟）
TIMEZONES = [
    480,   # UTC+8 (中国)
    540,   # UTC+9 (日本)
    -480,  # UTC-8 (太平洋)
    0,     # UTC (格林威治)
]


# ==================== 视口尺寸 ====================
# 常见的屏幕分辨率
VIEWPORT_SIZES = [
    (1920, 1080),  # Full HD
    (1366, 768),   # 常见笔记本
    (1536, 864),   # 常见笔记本
    (1440, 900),   # MacBook
    (1280, 720),   # HD
    (1600, 900),   # 常见
    (2560, 1440),  # 2K
    (1280, 800),   # MacBook Air
]


# ==================== Referer 策略 ====================
REFERER_STRATEGIES = {
    'search_engine': [
        'https://www.google.com/',
        'https://www.google.com/search?q=tech+article',
        'https://www.bing.com/',
        'https://www.bing.com/search?q=programming',
        'https://www.baidu.com/',
        'https://www.baidu.com/s?wd=技术文章',
    ],
    'social_media': [
        'https://twitter.com/',
        'https://www.facebook.com/',
        'https://www.linkedin.com/',
        'https://weibo.com/',
    ],
    'direct': [None],  # 直接访问，不带 Referer
}


@dataclass
class BrowserProfile:
    """浏览器配置文件 - 保持指纹一致性"""
    user_agent: str
    accept_language: str
    timezone_offset: int
    viewport_width: int
    viewport_height: int
    platform: str
    vendor: str
    referer: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'user_agent': self.user_agent,
            'accept_language': self.accept_language,
            'timezone_offset': self.timezone_offset,
            'viewport_width': self.viewport_width,
            'viewport_height': self.viewport_height,
            'platform': self.platform,
            'vendor': self.vendor,
            'referer': self.referer,
        }


class AntiScrapingManager:
    """防反爬管理器 - 核心类"""
    
    def __init__(self, 
                 rotate_user_agent: bool = True,
                 random_delay: bool = True,
                 stealth_mode: bool = True,
                 min_delay: float = 1.0,
                 max_delay: float = 5.0):
        """
        初始化防反爬管理器
        
        Args:
            rotate_user_agent: 是否轮换 User-Agent
            random_delay: 是否使用随机延迟
            stealth_mode: 是否启用隐身模式
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
        """
        self.rotate_user_agent = rotate_user_agent
        self.random_delay = random_delay
        self.stealth_mode = stealth_mode
        self.min_delay = min_delay
        self.max_delay = max_delay
        
        # 当前会话的浏览器配置（保持一致性）
        self._current_profile: Optional[BrowserProfile] = None
        self._request_count = 0
        self._profile_rotation_interval = random.randint(10, 30)  # 每 10-30 个请求换一次配置
        
    def get_browser_profile(self, force_new: bool = False) -> BrowserProfile:
        """获取浏览器配置文件
        
        Args:
            force_new: 是否强制生成新的配置
            
        Returns:
            BrowserProfile: 浏览器配置
        """
        self._request_count += 1
        
        # 是否需要轮换配置
        should_rotate = (
            force_new or 
            self._current_profile is None or 
            (self.rotate_user_agent and 
             self._request_count >= self._profile_rotation_interval)
        )
        
        if should_rotate:
            self._current_profile = self._generate_profile()
            self._request_count = 0
            self._profile_rotation_interval = random.randint(10, 30)
            logger.debug(f"🔄 生成新的浏览器配置: {self._current_profile.user_agent[:50]}...")
            
        return self._current_profile
    
    def _generate_profile(self) -> BrowserProfile:
        """生成随机的浏览器配置文件"""
        # 随机选择浏览器类型
        browser_type = random.choice(list(USER_AGENTS.keys()))
        user_agent = random.choice(USER_AGENTS[browser_type])
        
        # 根据 UA 确定平台
        if 'Windows' in user_agent:
            platform = 'Win32'
        elif 'Macintosh' in user_agent or 'Mac OS' in user_agent:
            platform = 'MacIntel'
        else:
            platform = 'Linux x86_64'
        
        # 确定浏览器厂商
        if 'Chrome' in user_agent or 'Edg' in user_agent:
            vendor = 'Google Inc.'
        elif 'Firefox' in user_agent:
            vendor = ''
        elif 'Safari' in user_agent:
            vendor = 'Apple Computer, Inc.'
        else:
            vendor = ''
        
        # 随机视口大小
        viewport = random.choice(VIEWPORT_SIZES)
        
        # 随机语言和时区
        accept_language = random.choice(ACCEPT_LANGUAGES)
        timezone_offset = random.choice(TIMEZONES)
        
        # 随机 Referer 策略
        strategy = random.choice(['search_engine', 'direct', 'direct'])  # 直接访问概率更高
        referer = random.choice(REFERER_STRATEGIES[strategy])
        
        return BrowserProfile(
            user_agent=user_agent,
            accept_language=accept_language,
            timezone_offset=timezone_offset,
            viewport_width=viewport[0],
            viewport_height=viewport[1],
            platform=platform,
            vendor=vendor,
            referer=referer
        )
    
    def get_random_delay(self) -> float:
        """获取符合正态分布的随机延迟时间
        
        使用正态分布模拟人类行为，大部分延迟集中在中间值
        
        Returns:
            float: 延迟时间（秒）
        """
        if not self.random_delay:
            return self.min_delay
        
        # 使用正态分布
        mean = (self.min_delay + self.max_delay) / 2
        std_dev = (self.max_delay - self.min_delay) / 4
        
        delay = random.gauss(mean, std_dev)
        # 限制在合理范围内
        delay = max(self.min_delay, min(self.max_delay, delay))
        
        return delay
    
    async def human_delay(self):
        """执行人类化延迟"""
        import asyncio
        delay = self.get_random_delay()
        logger.debug(f"⏳ 人类化延迟: {delay:.2f}秒")
        await asyncio.sleep(delay)
    
    def get_stealth_js(self) -> str:
        """获取隐身模式 JavaScript 代码
        
        用于注入到页面中，隐藏自动化特征
        """
        profile = self.get_browser_profile()
        
        return f"""
        // 隐藏 webdriver 属性
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined
        }});
        
        // 修改 navigator 属性
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{profile.platform}'
        }});
        
        Object.defineProperty(navigator, 'vendor', {{
            get: () => '{profile.vendor}'
        }});
        
        Object.defineProperty(navigator, 'languages', {{
            get: () => ['{profile.accept_language.split(",")[0]}', 'en']
        }});
        
        // 隐藏自动化相关属性
        Object.defineProperty(navigator, 'plugins', {{
            get: () => [
                {{name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'}},
                {{name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'}},
                {{name: 'Native Client', filename: 'internal-nacl-plugin'}}
            ]
        }});
        
        // 修改 Chrome 特有属性
        window.chrome = {{
            runtime: {{}},
            loadTimes: function() {{}},
            csi: function() {{}},
            app: {{}}
        }};
        
        // 隐藏 Playwright/Puppeteer 特征
        delete window.__playwright;
        delete window.__puppeteer;
        delete window.__selenium_evaluate;
        delete window.__selenium_unwrapped;
        delete window.__webdriver_evaluate;
        delete window.__driver_evaluate;
        delete window.__webdriver_unwrapped;
        delete window.__driver_unwrapped;
        delete window.__lastWatirAlert;
        delete window.__lastWatirConfirm;
        delete window.__lastWatirPrompt;
        delete document.__webdriver_evaluate;
        delete document.__selenium_evaluate;
        delete document.__webdriver_script_function;
        delete document.__webdriver_script_func;
        delete document.__webdriver_script_fn;
        delete document.$chrome_asyncScriptInfo;
        delete document.$cdc_asdjflasutopfhvcZLmcfl_;
        
        // 修改 permissions 查询
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({{ state: Notification.permission }}) :
            originalQuery(parameters)
        );
        
        // Canvas 指纹随机化（添加微小噪声）
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            if (type === 'image/png' && this.width > 16 && this.height > 16) {{
                const ctx = this.getContext('2d');
                if (ctx) {{
                    const imageData = ctx.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {{
                        // 添加微小噪声（不影响视觉效果）
                        imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + (Math.random() - 0.5) * 2));
                    }}
                    ctx.putImageData(imageData, 0, 0);
                }}
            }}
            return originalToDataURL.apply(this, arguments);
        }};
        
        // WebGL 指纹随机化
        const getParameterProxyHandler = {{
            apply: function(target, thisArg, argumentsList) {{
                const param = argumentsList[0];
                const gl = thisArg;
                
                // 随机化一些不影响功能的参数
                if (param === 37445) {{ // UNMASKED_VENDOR_WEBGL
                    return 'Intel Inc.';
                }}
                if (param === 37446) {{ // UNMASKED_RENDERER_WEBGL
                    return 'Intel(R) Iris(TM) Graphics';
                }}
                
                return Reflect.apply(target, thisArg, argumentsList);
            }}
        }};
        
        try {{
            const canvas = document.createElement('canvas');
            const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
            if (gl) {{
                const originalGetParameter = gl.getParameter;
                gl.getParameter = new Proxy(originalGetParameter, getParameterProxyHandler);
            }}
        }} catch(e) {{}}
        
        console.log('🛡️ Anti-detection scripts loaded');
        """
    
    def get_http_headers(self, url: str = None) -> Dict[str, str]:
        """获取伪装的 HTTP 请求头
        
        Args:
            url: 目标 URL（用于生成合适的 Referer）
            
        Returns:
            Dict: HTTP 请求头字典
        """
        profile = self.get_browser_profile()
        
        headers = {
            'User-Agent': profile.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': profile.accept_language,
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        
        # 添加 Chrome 特有的 Sec-Ch-Ua 头
        if 'Chrome' in profile.user_agent:
            chrome_version = '120'
            # 从 UA 中提取版本号
            import re
            match = re.search(r'Chrome/(\d+)', profile.user_agent)
            if match:
                chrome_version = match.group(1)
            
            headers.update({
                'Sec-Ch-Ua': f'"Not_A Brand";v="8", "Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': f'"{profile.platform.replace("32", "").replace("Intel", "").strip()}"',
            })
        
        # 添加 Referer（如果有）
        if profile.referer:
            headers['Referer'] = profile.referer
        
        return headers
    
    def get_browser_config(self) -> Dict:
        """获取 Playwright/Crawl4AI 浏览器配置
        
        Returns:
            Dict: 浏览器配置字典
        """
        profile = self.get_browser_profile()
        
        return {
            'headless': True,
            'viewport_width': profile.viewport_width,
            'viewport_height': profile.viewport_height,
            'user_agent': profile.user_agent,
            'verbose': False,
            # 额外的浏览器参数
            'extra_args': [
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                f'--window-size={profile.viewport_width},{profile.viewport_height}',
            ]
        }
    
    def get_crawler_config(self, timeout: int = 30000, wait_for: str = None) -> Dict:
        """获取 Crawl4AI 爬取配置
        
        Args:
            timeout: 页面超时时间（毫秒）
            wait_for: 等待元素选择器
            
        Returns:
            Dict: 爬取配置字典
        """
        config = {
            'page_timeout': timeout,
            'remove_overlay_elements': True,
            'screenshot': False,
        }
        
        if wait_for:
            config['wait_for'] = wait_for
        
        # 如果启用隐身模式，注入 JavaScript
        if self.stealth_mode:
            config['js_code'] = self.get_stealth_js()
        
        return config


class MouseSimulator:
    """鼠标移动模拟器 - 使用贝塞尔曲线"""
    
    @staticmethod
    def bezier_curve(t: float, p0: Tuple[float, float], p1: Tuple[float, float], 
                     p2: Tuple[float, float], p3: Tuple[float, float]) -> Tuple[float, float]:
        """三次贝塞尔曲线计算
        
        Args:
            t: 参数 [0, 1]
            p0, p1, p2, p3: 控制点
            
        Returns:
            Tuple: (x, y) 坐标
        """
        x = (1-t)**3 * p0[0] + 3*(1-t)**2*t * p1[0] + 3*(1-t)*t**2 * p2[0] + t**3 * p3[0]
        y = (1-t)**3 * p0[1] + 3*(1-t)**2*t * p1[1] + 3*(1-t)*t**2 * p2[1] + t**3 * p3[1]
        return (x, y)
    
    @staticmethod
    def generate_human_path(start: Tuple[int, int], end: Tuple[int, int], 
                           steps: int = 50) -> List[Tuple[int, int]]:
        """生成模拟人类的鼠标移动路径
        
        Args:
            start: 起始点 (x, y)
            end: 终点 (x, y)
            steps: 路径点数量
            
        Returns:
            List: 路径点列表
        """
        # 生成随机控制点（模拟人类不精确的移动）
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        
        # 控制点偏移（添加曲线感）
        offset_x = random.uniform(-abs(dx) * 0.3, abs(dx) * 0.3)
        offset_y = random.uniform(-abs(dy) * 0.3, abs(dy) * 0.3)
        
        p0 = (float(start[0]), float(start[1]))
        p1 = (start[0] + dx * 0.3 + offset_x, start[1] + dy * 0.3 + offset_y)
        p2 = (start[0] + dx * 0.7 + offset_x * 0.5, start[1] + dy * 0.7 + offset_y * 0.5)
        p3 = (float(end[0]), float(end[1]))
        
        path = []
        for i in range(steps):
            t = i / (steps - 1)
            # 添加微小抖动
            x, y = MouseSimulator.bezier_curve(t, p0, p1, p2, p3)
            x += random.uniform(-2, 2)
            y += random.uniform(-2, 2)
            path.append((int(x), int(y)))
        
        return path
    
    @staticmethod
    def generate_scroll_pattern(total_distance: int, step_count: int = 5) -> List[int]:
        """生成人类化的滚动模式
        
        Args:
            total_distance: 总滚动距离
            step_count: 滚动步数
            
        Returns:
            List: 每步滚动距离列表
        """
        if step_count <= 0:
            return [total_distance]
        
        # 使用正态分布生成滚动距离
        distances = []
        remaining = total_distance
        
        for i in range(step_count - 1):
            # 随机分配剩余距离
            portion = random.gauss(remaining / (step_count - i), remaining * 0.1)
            portion = max(50, min(portion, remaining - 50 * (step_count - i - 1)))
            distances.append(int(portion))
            remaining -= int(portion)
        
        distances.append(remaining)
        return distances


# 全局实例
_anti_scraping_manager: Optional[AntiScrapingManager] = None


def get_anti_scraping_manager(
    rotate_user_agent: bool = True,
    random_delay: bool = True,
    stealth_mode: bool = True,
    min_delay: float = 1.0,
    max_delay: float = 5.0
) -> AntiScrapingManager:
    """获取防反爬管理器单例
    
    Args:
        rotate_user_agent: 是否轮换 User-Agent
        random_delay: 是否使用随机延迟
        stealth_mode: 是否启用隐身模式
        min_delay: 最小延迟（秒）
        max_delay: 最大延迟（秒）
        
    Returns:
        AntiScrapingManager: 防反爬管理器实例
    """
    global _anti_scraping_manager
    
    if _anti_scraping_manager is None:
        _anti_scraping_manager = AntiScrapingManager(
            rotate_user_agent=rotate_user_agent,
            random_delay=random_delay,
            stealth_mode=stealth_mode,
            min_delay=min_delay,
            max_delay=max_delay
        )
    
    return _anti_scraping_manager


def reset_anti_scraping_manager():
    """重置防反爬管理器"""
    global _anti_scraping_manager
    _anti_scraping_manager = None


# 便捷函数
def get_random_user_agent() -> str:
    """获取随机 User-Agent"""
    return random.choice(ALL_USER_AGENTS)


def get_random_viewport() -> Tuple[int, int]:
    """获取随机视口尺寸"""
    return random.choice(VIEWPORT_SIZES)


def get_human_delay(min_delay: float = 1.0, max_delay: float = 5.0) -> float:
    """获取人类化延迟（正态分布）"""
    mean = (min_delay + max_delay) / 2
    std_dev = (max_delay - min_delay) / 4
    delay = random.gauss(mean, std_dev)
    return max(min_delay, min(max_delay, delay))

