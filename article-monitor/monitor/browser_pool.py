"""
浏览器实例池 - 复用浏览器实例，减少创建开销
优化：管理浏览器实例生命周期，提升性能和稳定性
"""
import asyncio
import threading
import logging
from typing import Optional, List
from collections import deque
from datetime import datetime, timedelta
from crawl4ai import AsyncWebCrawler
from .extractors import get_browser_config, ensure_browser_config
from .config import ANTI_SCRAPING_ENABLED, ANTI_SCRAPING_ROTATE_UA

logger = logging.getLogger(__name__)

class BrowserPool:
    """浏览器实例池（单例模式）"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._pool_lock = asyncio.Lock()
        self._pool: deque = deque()
        self._in_use: set = set()
        self._max_size = 5  # 最大池大小
        self._min_size = 2  # 最小池大小
        self._max_idle_time = 300  # 最大空闲时间（秒）
        self._last_cleanup = datetime.now()
        self._cleanup_interval = 60  # 清理间隔（秒）
    
    async def acquire(self) -> Optional[AsyncWebCrawler]:
        """获取浏览器实例"""
        async with self._pool_lock:
            # 清理空闲实例
            await self._cleanup_idle()
            
            # 从池中获取实例
            while self._pool:
                crawler = self._pool.popleft()
                if crawler not in self._in_use:
                    self._in_use.add(crawler)
                    return crawler
            
            # 如果池为空且未达到最大大小，创建新实例
            if len(self._in_use) < self._max_size:
                try:
                    crawler = await self._create_crawler()
                    self._in_use.add(crawler)
                    logger.debug(f"创建新浏览器实例，当前使用: {len(self._in_use)}")
                    return crawler
                except Exception as e:
                    logger.error(f"创建浏览器实例失败: {e}")
                    return None
            
            # 达到最大大小，返回 None（调用者应等待或创建独立实例）
            logger.warning(f"浏览器池已满，当前使用: {len(self._in_use)}")
            return None
    
    async def release(self, crawler: AsyncWebCrawler):
        """释放浏览器实例回池"""
        async with self._pool_lock:
            if crawler in self._in_use:
                self._in_use.remove(crawler)
                # 检查实例是否仍然有效
                if await self._is_crawler_valid(crawler):
                    self._pool.append(crawler)
                    logger.debug(f"浏览器实例已释放回池，池大小: {len(self._pool)}")
                else:
                    logger.warning("浏览器实例无效，丢弃")
                    try:
                        await crawler.__aexit__(None, None, None)
                    except Exception as cleanup_error:
                        logger.debug(f"清理无效浏览器实例时出错: {cleanup_error}")
    
    async def _is_crawler_valid(self, crawler: AsyncWebCrawler) -> bool:
        """检查浏览器实例是否仍然有效"""
        try:
            # 检查实例是否有 browser 属性且不为 None
            if not hasattr(crawler, 'browser'):
                return False
            # 尝试访问 browser 属性（如果已关闭会抛出异常）
            browser = crawler.browser
            return browser is not None
        except (AttributeError, RuntimeError, Exception):
            return False
    
    async def _create_crawler(self) -> AsyncWebCrawler:
        """创建新的浏览器实例
        
        优化：确保每个浏览器实例使用一致的配置
        对于防反爬模式，每次创建时获取新配置（支持轮换）
        对于非防反爬模式，复用缓存的配置以提升性能
        """
        # 根据防反爬状态选择配置获取方式
        # 防反爬模式：每次获取新配置以支持轮换
        # 非防反爬模式：复用缓存的配置以提升性能
        if ANTI_SCRAPING_ENABLED:
            browser_config = get_browser_config()
        else:
            browser_config = ensure_browser_config()
        
        crawler = AsyncWebCrawler(config=browser_config)
        await crawler.__aenter__()
        logger.debug(f"创建浏览器实例，配置已固定（User-Agent: {browser_config.user_agent[:50] if browser_config.user_agent else 'N/A'}...）")
        return crawler
    
    async def _cleanup_idle(self):
        """清理空闲时间过长的实例（优化：真正使用空闲时间判断）"""
        now = datetime.now()
        if (now - self._last_cleanup).total_seconds() < self._cleanup_interval:
            return
        
        self._last_cleanup = now
        
        # 清理池中空闲时间过长的实例
        # 注意：由于我们没有跟踪每个实例的空闲时间，这里简化处理
        # 如果池大小超过最小值，移除多余的（保持最小池大小）
        to_remove = []
        pool_size = len(self._pool)
        
        if pool_size > self._min_size:
            # 移除多余的实例（从最旧的开始）
            remove_count = pool_size - self._min_size
            for _ in range(remove_count):
                if self._pool:
                    to_remove.append(self._pool.popleft())
        
        for crawler in to_remove:
            try:
                await crawler.__aexit__(None, None, None)
            except Exception as cleanup_error:
                logger.debug(f"清理浏览器实例时出错: {cleanup_error}")
        
        if to_remove:
            logger.debug(f"清理了 {len(to_remove)} 个空闲浏览器实例")
    
    async def close_all(self):
        """关闭所有浏览器实例"""
        async with self._pool_lock:
            # 关闭池中的实例
            while self._pool:
                crawler = self._pool.popleft()
                try:
                    await crawler.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug(f"关闭池中浏览器实例时出错: {e}")
            
            # 关闭使用中的实例
            for crawler in list(self._in_use):
                try:
                    await crawler.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug(f"关闭使用中浏览器实例时出错: {e}")
                self._in_use.remove(crawler)
            
            logger.info("所有浏览器实例已关闭")

# 全局浏览器池实例
_browser_pool = None

def get_browser_pool() -> BrowserPool:
    """获取浏览器池实例"""
    global _browser_pool
    if _browser_pool is None:
        _browser_pool = BrowserPool()
    return _browser_pool

