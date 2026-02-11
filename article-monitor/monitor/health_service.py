import time
import socket
import concurrent.futures
from datetime import datetime, timedelta
from typing import Dict, Any, List

import psutil

from .config import HEALTH_CHECK_TIMEOUT, MAX_HEALTH_CHECK_WORKERS, CRAWL_INTERVAL_HOURS, SUPPORTED_SITES
from .database import get_platform_health, get_platform_failures, get_setting
import logging


logger = logging.getLogger(__name__)


def _build_system_status() -> Dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('.')

    return {
        'cpu': {
            'percent': cpu_percent,
            'count': psutil.cpu_count(),
        },
        'memory': {
            'total': memory.total,
            'available': memory.available,
            'percent': memory.percent,
        },
        'disk': {
            'total': disk.total,
            'free': disk.free,
            'percent': disk.percent,
        },
    }


def _build_platform_status() -> List[Dict[str, Any]]:
    platforms = get_platform_health()
    failures = get_platform_failures()

    failures_by_site: Dict[str, List[Dict[str, Any]]] = {}
    for f in failures:
        site = f['site'] or '其他'
        if site not in failures_by_site:
            failures_by_site[site] = []
        if len(failures_by_site[site]) < 5:
            failures_by_site[site].append(
                {
                    'id': f['id'],
                    'title': f['title'] or f['url'],
                    'url': f['url'],
                    'error': f['last_error'],
                    'time': f['last_crawl_time'],
                }
            )

    crawl_interval = int(get_setting('crawl_interval_hours', str(CRAWL_INTERVAL_HOURS)))
    platform_status: List[Dict[str, Any]] = []
    now = datetime.now()

    for p in platforms:
        site = p['site'] or '其他'
        last_update = p['last_update']
        article_count = p['article_count']

        status = 'ok'
        msg = '正常'
        site_failures = failures_by_site.get(site, [])

        if not last_update:
            status = 'unknown'
            msg = '无数据'
            if article_count == 0:
                status = 'ok'
                msg = '无文章'
        else:
            try:
                last_dt = datetime.strptime(last_update, '%Y-%m-%d %H:%M:%S')
                diff_hours = (now - last_dt).total_seconds() / 3600
                if diff_hours > crawl_interval * 4:
                    status = 'error'
                    msg = f'严重延迟 ({int(diff_hours)}小时)'
                elif diff_hours > crawl_interval * 2:
                    status = 'warning'
                    msg = f'延迟 ({int(diff_hours)}小时)'
            except (ValueError, TypeError) as e:
                logger.debug(f"解析時間格式失敗: {e}")
                status = 'unknown'
                msg = '时间格式错误'
            except Exception as e:
                logger.warning(f"處理平台狀態時發生未知錯誤: {e}")
                status = 'unknown'
                msg = '时间格式错误'

        if site_failures and status == 'ok':
            status = 'warning'
            msg = f'有 {len(site_failures)} 篇失败'
        elif site_failures:
            msg += f', {len(site_failures)} 篇失败'

        platform_status.append(
            {
                'site': site,
                'status': status,
                'message': msg,
                'last_update': last_update,
                'article_count': article_count,
                'failures': site_failures,
            }
        )

    return platform_status


def _check_conn(host: str, port: int = 443) -> Dict[str, Any]:
    try:
        start = time.time()
        socket.create_connection((host, port), timeout=HEALTH_CHECK_TIMEOUT)
        return {'ok': True, 'latency': int((time.time() - start) * 1000)}
    except (socket.error, OSError, TimeoutError) as e:
        logger.debug(f"网络连接检查失败 {host}:{port}: {e}")
        return {'ok': False, 'latency': 0}


def _build_network_status() -> List[Dict[str, Any]]:
    targets = [('互联网连通性', 'www.baidu.com')]
    for domain, name in SUPPORTED_SITES.items():
        targets.append((name, domain))

    network_results: Dict[str, Dict[str, Any]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_HEALTH_CHECK_WORKERS) as executor:
        future_to_target = {
            executor.submit(_check_conn, domain, 443): (name, domain) for name, domain in targets
        }

        for future in concurrent.futures.as_completed(future_to_target):
            name, domain = future_to_target[future]
            try:
                result = future.result()
                network_results[domain] = {'name': name, 'host': domain, 'status': result}
            except Exception as e:
                logger.debug(f"網絡檢查異常 {domain}: {e}")
                network_results[domain] = {
                    'name': name,
                    'host': domain,
                    'status': {'ok': False, 'latency': 0},
                }

    sorted_network: List[Dict[str, Any]] = []
    if 'www.baidu.com' in network_results:
        sorted_network.append(network_results.pop('www.baidu.com'))

    for domain in sorted(network_results.keys()):
        sorted_network.append(network_results[domain])

    return sorted_network


def get_system_health_payload() -> Dict[str, Any]:
    """組合系統健康狀態 payload，供 API 回傳使用。"""
    system_status = _build_system_status()
    platform_status = _build_platform_status()
    network_status = _build_network_status()

    return {
        'system': system_status,
        'platforms': platform_status,
        'network': network_status,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }

