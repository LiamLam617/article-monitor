"""
定时任务调度器 - 简单到不能再简单
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from .crawler import crawl_all_sync
from .config import CRAWL_INTERVAL_HOURS
from .database import get_setting

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def get_interval_hours():
    """获取爬取间隔（小时），优先从数据库读取"""
    value = get_setting('crawl_interval_hours', str(CRAWL_INTERVAL_HOURS))
    try:
        return int(value)
    except (ValueError, TypeError):
        return CRAWL_INTERVAL_HOURS

def start_scheduler():
    """启动定时任务"""
    interval_hours = get_interval_hours()
    
    # 添加定时任务
    scheduler.add_job(
        func=crawl_all_sync,
        trigger=IntervalTrigger(hours=interval_hours),
        id='crawl_job',
        name='定时爬取阅读数',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info(f"定时任务已启动，每 {interval_hours} 小时执行一次")
    
    # 立即执行一次
    logger.info("立即执行首次爬取...")
    crawl_all_sync()

def update_schedule():
    """更新定时任务间隔"""
    interval_hours = get_interval_hours()
    scheduler.reschedule_job(
        'crawl_job',
        trigger=IntervalTrigger(hours=interval_hours)
    )
    logger.info(f"定时任务已更新，每 {interval_hours} 小时执行一次")

def stop_scheduler():
    """停止定时任务"""
    scheduler.shutdown()
    logger.info("定时任务已停止")

