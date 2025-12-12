"""
Flask应用 - 简单的RESTful API和前端
"""
from flask import Flask, render_template, request, jsonify, Response, send_file
from flask_cors import CORS
import asyncio
import csv
import io
from datetime import datetime
from typing import List
from .database import (
    init_db, add_article, get_all_articles, get_all_articles_with_latest_count,
    get_read_counts, delete_article, get_latest_read_count, get_setting, set_setting,
    add_read_count, get_platform_health, get_platform_failures, get_all_failures,
    get_failure_stats, add_articles_batch, add_read_counts_batch
)
import logging

logger = logging.getLogger(__name__)
from .scheduler import start_scheduler
from urllib.parse import urlparse
from .config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG, SUPPORTED_SITES, CRAWL_INTERVAL_HOURS, is_platform_allowed


def normalize_url(url: str) -> str:
    """規範化 URL，修正已知平台的非標準格式"""
    # 掘金: spost -> post
    if 'juejin.cn' in url:
        url = url.replace('/spost/', '/post/')
    return url

app = Flask(__name__)
CORS(app)

# 初始化数据库
init_db()

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    """处理 favicon 请求，避免 404 错误"""
    return Response(status=204)  # 204 No Content

@app.route('/api/articles', methods=['GET'])
def get_articles():
    """获取所有文章（优化：使用批量查询避免N+1问题）"""
    articles = get_all_articles_with_latest_count()
    return jsonify({'success': True, 'data': articles})

@app.route('/api/articles/batch', methods=['POST'])
def create_articles_batch():
    """批量添加文章（优化：使用异步任务队列，立即返回任务ID）"""
    data = request.json
    urls = data.get('urls', [])
    
    if not urls:
        return jsonify({'success': False, 'error': 'URL列表不能为空'}), 400
    
    # 去重、過濾空值、規範化 URL
    urls = list(set([normalize_url(u.strip()) for u in urls if u.strip()]))
    
    if not urls:
        return jsonify({'success': False, 'error': '有效URL不能为空'}), 400
        
    # 如果URL数量较少（<=5），直接处理；否则使用异步任务
    if len(urls) <= 5:
        # 小批量：直接处理
        try:
            results = asyncio.run(_process_urls_sync(urls))
            return jsonify({'success': True, 'results': results})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    else:
        # 大批量：使用异步任务队列
        from .task_manager import get_task_manager
        task_manager = get_task_manager()
        task_id = task_manager.submit_task(_process_urls_async, urls)
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': f'已提交 {len(urls)} 个URL，正在后台处理',
            'status_url': f'/api/tasks/{task_id}'
        })

async def _process_urls_async(task_id: str, urls: List[str]):
    """异步处理URL列表（用于任务队列）"""
    from .task_manager import get_task_manager
    task_manager = get_task_manager()
    
    results = []
    total = len(urls)
    
    # 使用浏览器池
    from .browser_pool import get_browser_pool
    browser_pool = get_browser_pool()
    
    # 批量处理（每批10个）
    batch_size = 10
    for i in range(0, total, batch_size):
        batch_urls = urls[i:i+batch_size]
        batch_results = await _process_batch(batch_urls, browser_pool)
        results.extend(batch_results)
        
        # 更新进度
        task_manager.update_task_progress(task_id, {
            'processed': len(results),
            'total': total,
            'success': sum(1 for r in results if r.get('success')),
            'failed': sum(1 for r in results if not r.get('success'))
        })
    
    # 保存最终结果到任务
    task = task_manager.get_task(task_id)
    if task:
        task['results'] = results

async def _process_urls_sync(urls: List[str]):
    """同步处理URL列表（用于小批量）"""
    from .browser_pool import get_browser_pool
    browser_pool = get_browser_pool()
    return await _process_batch(urls, browser_pool)

async def _process_batch(urls: List[str], browser_pool) -> List[dict]:
    """处理一批URL"""
    from .extractors import extract_article_info
    from .database import add_articles_batch, add_read_counts_batch
    
    results = []
    articles_to_add = []
    read_counts_to_add = []
    
    # 并发处理URL
    async def process_single_url(url: str):
        try:
            # 验证URL
            try:
                parsed = urlparse(url)
                if not parsed.scheme or not parsed.netloc:
                    return {'url': url, 'success': False, 'error': '无效的URL格式'}
            except (ValueError, AttributeError) as e:
                logger.debug(f"URL解析失败 {url}: {e}")
                return {'url': url, 'success': False, 'error': 'URL解析失败'}
            
            # 检测网站类型
            domain = parsed.netloc.lower()
            site = None
            for site_domain, site_name in SUPPORTED_SITES.items():
                if site_domain in domain:
                    site = site_name
                    break
            
            # 检查平台是否在白名单中
            if not is_platform_allowed(site):
                return {
                    'url': url,
                    'success': False,
                    'error': f'平台 "{site or "未知"}" 不在允许列表中，已跳过'
                }
            
            # 从浏览器池获取实例
            crawler = await browser_pool.acquire()
            if not crawler:
                # 如果池已满，创建独立实例
                from .extractors import create_shared_crawler
                crawler = await create_shared_crawler()
                use_pool = False
            else:
                use_pool = True
            
            try:
                # 爬取标题和阅读数
                info = await extract_article_info(url, crawler)
                title = info.get('title')
                count = info.get('read_count')
            except Exception as e:
                logger.debug(f"爬取失败 {url}: {e}")
                title = None
                count = None
            finally:
                if use_pool:
                    await browser_pool.release(crawler)
                else:
                    await crawler.__aexit__(None, None, None)
            
            # 准备批量插入数据
            articles_to_add.append((url, title, site))
            read_counts_to_add.append((count if count is not None else 0,))
            
            return {
                'url': url,
                'success': True,
                'data': {
                    'title': title,
                    'site': site,
                    'initial_count': count if count is not None else 0
                }
            }
        except Exception as e:
            return {'url': url, 'success': False, 'error': str(e)}
                
    # 并发处理（限制并发数）
    semaphore = asyncio.Semaphore(5)  # 每批最多5个并发
    
    async def process_with_semaphore(url):
        async with semaphore:
            return await process_single_url(url)
    
    tasks = [process_with_semaphore(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理异常结果
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed_results.append({'url': urls[i], 'success': False, 'error': str(result)})
        else:
            processed_results.append(result)
    
    # 批量插入数据库
    try:
        article_ids = add_articles_batch(articles_to_add)
        
        # 准备阅读数记录（需要article_id）
        read_count_records = []
        for i, (article_id, count_data) in enumerate(zip(article_ids, read_counts_to_add)):
            if article_id:
                read_count_records.append((article_id, count_data[0]))
        
        if read_count_records:
            add_read_counts_batch(read_count_records)
        
        # 更新结果中的article_id
        article_idx = 0
        for result in processed_results:
            if result.get('success') and article_idx < len(article_ids):
                result['data']['id'] = article_ids[article_idx]
                article_idx += 1
    except Exception as e:
        logger.error(f"批量插入数据库失败: {e}")
        # 回退到逐个插入
        for result in processed_results:
            if result.get('success'):
                try:
                    article_id = add_article(
                        result['data'].get('url'),
                        result['data'].get('title'),
                        result['data'].get('site')
                    )
                    add_read_count(article_id, result['data'].get('initial_count', 0))
                    result['data']['id'] = article_id
                except Exception as e2:
                    result['success'] = False
                    result['error'] = str(e2)
    
    return processed_results

@app.route('/api/articles', methods=['POST'])
def create_article():
    """添加文章"""
    data = request.json
    url = normalize_url(data.get('url', '').strip())
    
    if not url:
        return jsonify({'success': False, 'error': 'URL不能为空'}), 400
    
    # 验证URL
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return jsonify({'success': False, 'error': '无效的URL'}), 400
    except (ValueError, AttributeError) as e:
        logger.debug(f"URL解析失败 {url}: {e}")
        return jsonify({'success': False, 'error': '无效的URL'}), 400
    
    # 检测网站类型
    domain = parsed.netloc.lower()
    site = None
    for site_domain, site_name in SUPPORTED_SITES.items():
        if site_domain in domain:
            site = site_name
            break
    
    # 检查平台是否在白名单中
    if not is_platform_allowed(site):
        return jsonify({
            'success': False,
            'error': f'平台 "{site or "未知"}" 不在允许列表中，已跳过'
        }), 400
    
    # 立即爬取一次获取标题和阅读数（使用统一的提取函数）
    title = None
    count = None
    try:
        from .extractors import extract_article_info, create_shared_crawler
        
        async def fetch_title_and_count():
            crawler = await create_shared_crawler()
            try:
                info = await extract_article_info(url, crawler)
                return info.get('title'), info.get('read_count')
            finally:
                await crawler.__aexit__(None, None, None)
        
        title, count = asyncio.run(fetch_title_and_count())
    except Exception as e:
        logger.debug(f"初次爬取失败 {url}: {e}")
        count = None
        title = None
    
    try:
        article_id = add_article(url, title=title, site=site)
        
        # 立即保存初始阅读数（如果爬取失败则为0）
        initial_count = count if count is not None else 0
        add_read_count(article_id, initial_count)
        
        return jsonify({
            'success': True,
            'data': {'id': article_id, 'url': url, 'title': title, 'site': site, 'initial_count': initial_count}
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/articles/<int:article_id>', methods=['DELETE'])
def remove_article(article_id):
    """删除文章"""
    try:
        delete_article(article_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/articles/<int:article_id>/history', methods=['GET'])
def get_history(article_id):
    """获取阅读数历史"""
    try:
        limit = request.args.get('limit', 100, type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        group_by_hour = request.args.get('group_by_hour', 'false').lower() == 'true'
        
        history = get_read_counts(article_id, limit=limit, start_date=start_date, end_date=end_date, group_by_hour=group_by_hour)
        
        # 获取文章信息（优化：直接查询单篇文章，避免获取所有文章）
        from .database import get_article_by_id
        article = get_article_by_id(article_id)
        
        if not article:
            return jsonify({'success': False, 'error': '文章不存在'}), 404
        
        # 如果指定了日期范围但数据为空，检查是否有任何历史数据
        # 如果没有指定日期范围，或者有数据，直接返回
        # 如果指定了日期范围但数据为空，也返回空数组（前端会处理）
        
        return jsonify({
            'success': True,
            'data': history,  # 可能为空数组，前端会处理
            'title': article.get('title', ''),
            'url': article.get('url', ''),
            'site': article.get('site', '')
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawl', methods=['POST'])
def manual_crawl():
    """手动触发爬取"""
    try:
        from .crawler import crawl_all_sync
        # 在后台执行
        import threading
        thread = threading.Thread(target=crawl_all_sync)
        thread.start()
        return jsonify({'success': True, 'message': '爬取任务已启动'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawl/stop', methods=['POST'])
def stop_crawl():
    """停止爬取"""
    try:
        from .crawler import stop_crawling
        stop_crawling()
        return jsonify({'success': True, 'message': '正在停止爬取...'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """获取设置"""
    try:
        interval_hours = get_setting('crawl_interval_hours', str(CRAWL_INTERVAL_HOURS))
        # 确保返回整数
        try:
            interval_hours = int(interval_hours)
        except (ValueError, TypeError):
            interval_hours = CRAWL_INTERVAL_HOURS
        
        return jsonify({
            'success': True,
            'data': {
                'crawl_interval_hours': interval_hours
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """更新设置"""
    try:
        data = request.json
        interval_hours = data.get('crawl_interval_hours')
        
        if interval_hours is None:
            return jsonify({'success': False, 'error': '缺少 crawl_interval_hours 参数'}), 400
        
        try:
            interval_hours = int(interval_hours)
            if interval_hours < 1:
                return jsonify({'success': False, 'error': '爬取间隔必须大于0'}), 400
        except ValueError:
            return jsonify({'success': False, 'error': '爬取间隔必须是数字'}), 400
        
        set_setting('crawl_interval_hours', interval_hours)
        
        # 更新定时任务
        from .scheduler import update_schedule
        update_schedule()
        
        return jsonify({
            'success': True,
            'message': '设置已更新'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/statistics', methods=['GET'])
def get_statistics():
    """获取统计数据 - 返回日期或小时范围"""
    try:
        from datetime import datetime, timedelta

        # 支持 days 参数（兼容旧版本）或 start_date/end_date
        days = request.args.get('days', type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        group_by_hour = request.args.get('group_by_hour', 'false').lower() == 'true'

        # 如果没有指定日期范围，默认7天
        if not days and not (start_date and end_date):
            days = 7

        # 生成时间序列
        date_list = []
        
        # 如果是按小时分组（今天视图）
        if group_by_hour and start_date and start_date == end_date:
            # 生成今天的24小时时间点
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            for hour in range(24):
                time_point = start_dt + timedelta(hours=hour)
                date_list.append(time_point.strftime('%Y-%m-%d %H:00:00'))
        elif start_date and end_date:
            # 使用自定义日期范围
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            current = start_dt
            while current <= end_dt:
                date_list.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)
            days = len(date_list)
        else:
            # 使用days参数
            for i in range(days):
                date = (datetime.now() - timedelta(days=days-1-i)).strftime('%Y-%m-%d')
                date_list.append(date)

        return jsonify({
            'success': True,
            'data': {
                'dates': date_list,
                'date_range': {
                    'start': date_list[0] if date_list else '',
                    'end': date_list[-1] if date_list else ''
                },
                'group_by_hour': group_by_hour
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawl/progress', methods=['GET'])
def get_crawl_progress():
    """获取爬取进度"""
    try:
        from .crawler import get_crawl_progress
        progress = get_crawl_progress()
        return jsonify({'success': True, 'data': progress})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        from .task_manager import get_task_manager
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)
        if task:
            return jsonify({'success': True, 'data': task})
        else:
            return jsonify({'success': False, 'error': '任务不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def cancel_task(task_id):
    """取消任务"""
    try:
        from .task_manager import get_task_manager
        task_manager = get_task_manager()
        if task_manager.cancel_task(task_id):
            return jsonify({'success': True, 'message': '任务已取消'})
        else:
            return jsonify({'success': False, 'error': '无法取消任务'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/failures', methods=['GET'])
def get_failures():
    """获取失败列表"""
    try:
        limit = request.args.get('limit', 100, type=int)
        site = request.args.get('site', None)
        
        failures = get_all_failures(limit=limit, site=site)
        stats = get_failure_stats()
        
        return jsonify({
            'success': True,
            'data': {
                'failures': failures,
                'stats': stats
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/failures/retry/<int:article_id>', methods=['POST'])
def retry_failure(article_id):
    """重试失败的文章"""
    try:
        from .crawler import crawl_all_sync
        from .database import get_article_by_id
        
        # 检查文章是否存在
        article = get_article_by_id(article_id)
        if not article:
            return jsonify({'success': False, 'error': '文章不存在'}), 404
        
        # 在后台执行爬取
        import threading
        thread = threading.Thread(target=lambda: crawl_all_sync())
        thread.start()
        
        return jsonify({
            'success': True,
            'message': '已加入爬取队列，请稍后查看结果'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/export/csv', methods=['POST'])
def export_csv():
    """导出数据为CSV格式"""
    try:
        data = request.json
        article_ids = data.get('article_ids', [])
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not article_ids:
            return jsonify({'success': False, 'error': '请选择要导出的文章'}), 400
        
        # 创建CSV文件在内存中
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 写入BOM以支持Excel正确显示中文
        output.write('\ufeff')
        
        # 写入表头
        writer.writerow(['文章标题', '网站', 'URL', '阅读数', '记录时间'])
        
        # 获取每篇文章的数据
        for article_id in article_ids:
            articles = get_all_articles()
            article = next((a for a in articles if a['id'] == article_id), None)
            
            if not article:
                continue
            
            # 获取该文章的阅读数历史
            history = get_read_counts(article_id, start_date=start_date, end_date=end_date)
            
            for record in history:
                writer.writerow([
                    article.get('title', 'N/A'),
                    article.get('site', 'N/A'),
                    article.get('url', 'N/A'),
                    record['count'],
                    record['timestamp']
                ])
        
        # 准备下载
        output.seek(0)
        filename = f"article_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return Response(
            output.getvalue().encode('utf-8-sig'),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'text/csv; charset=utf-8-sig'
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/export/all-csv', methods=['GET'])
def export_all_csv():
    """导出所有文章数据为CSV"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # 创建CSV文件在内存中
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 写入BOM以支持Excel正确显示中文
        output.write('\ufeff')
        
        # 写入表头
        writer.writerow(['文章标题', '网站', 'URL', '阅读数', '记录时间'])
        
        # 获取所有文章
        articles = get_all_articles()
        
        for article in articles:
            # 获取该文章的阅读数历史
            history = get_read_counts(article['id'], start_date=start_date, end_date=end_date)
            
            for record in history:
                writer.writerow([
                    article.get('title', 'N/A'),
                    article.get('site', 'N/A'),
                    article.get('url', 'N/A'),
                    record['count'],
                    record['timestamp']
                ])
        
        # 准备下载
        output.seek(0)
        filename = f"all_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return Response(
            output.getvalue().encode('utf-8-sig'),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'text/csv; charset=utf-8-sig'
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/monitor/health', methods=['GET'])
def get_system_health():
    """获取系统健康状态"""
    try:
        import psutil
        import socket
        import time
        from datetime import datetime, timedelta
        
        # 1. 系统资源
        # 首次调用 cpu_percent 会返回 0，所以这里只是获取当前瞬时状态
        cpu_percent = psutil.cpu_percent(interval=None) 
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('.')
        
        system_status = {
            'cpu': {
                'percent': cpu_percent,
                'count': psutil.cpu_count()
            },
            'memory': {
                'total': memory.total,
                'available': memory.available,
                'percent': memory.percent
            },
            'disk': {
                'total': disk.total,
                'free': disk.free,
                'percent': disk.percent
            }
        }
        
        # 2. 平台健康度
        platforms = get_platform_health()
        failures = get_platform_failures()
        
        # 按平台分组失败记录
        failures_by_site = {}
        for f in failures:
            site = f['site'] or '其他'
            if site not in failures_by_site:
                failures_by_site[site] = []
            # 只保留最近5条
            if len(failures_by_site[site]) < 5:
                failures_by_site[site].append({
                    'id': f['id'],
                    'title': f['title'] or f['url'],
                    'url': f['url'],
                    'error': f['last_error'],
                    'time': f['last_crawl_time']
                })

        crawl_interval = int(get_setting('crawl_interval_hours', str(CRAWL_INTERVAL_HOURS)))
        
        platform_status = []
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
                # 如果没有文章，也算是正常
                if article_count == 0:
                    status = 'ok'
                    msg = '无文章'
            else:
                try:
                    last_dt = datetime.strptime(last_update, '%Y-%m-%d %H:%M:%S')
                    diff_hours = (now - last_dt).total_seconds() / 3600
                    
                    # 判断逻辑：
                    # 警告：超过爬取间隔的 2 倍
                    # 错误：超过爬取间隔的 4 倍
                    if diff_hours > crawl_interval * 4:
                        status = 'error'
                        msg = f'严重延迟 ({int(diff_hours)}小时)'
                    elif diff_hours > crawl_interval * 2:
                        status = 'warning'
                        msg = f'延迟 ({int(diff_hours)}小时)'
                except:
                    status = 'unknown'
                    msg = '时间格式错误'
            
            # 如果有失败记录，且状态目前是ok，则升级为warning
            if site_failures and status == 'ok':
                status = 'warning'
                msg = f'有 {len(site_failures)} 篇失败'
            elif site_failures:
                 msg += f', {len(site_failures)} 篇失败'

            platform_status.append({
                'site': site,
                'status': status,
                'message': msg,
                'last_update': last_update,
                'article_count': article_count,
                'failures': site_failures
            })
            
        # 3. 网络连通性 (并发检查)
        import concurrent.futures
        
        def check_conn(host, port=443):
            try:
                start = time.time()
                socket.create_connection((host, port), timeout=3)
                return {'ok': True, 'latency': int((time.time() - start) * 1000)}
            except (socket.error, OSError, TimeoutError) as e:
                logger.debug(f"网络连接检查失败 {host}:{port}: {e}")
                return {'ok': False, 'latency': 0}
        
        # 准备检查列表
        targets = [('互联网连通性', 'www.baidu.com')]
        for domain, name in SUPPORTED_SITES.items():
            targets.append((name, domain))
            
        network_results = {}
        
        # 使用线程池并发检查，避免阻塞
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            future_to_target = {
                executor.submit(check_conn, domain, 443): (name, domain) 
                for name, domain in targets
            }
            
            for future in concurrent.futures.as_completed(future_to_target):
                name, domain = future_to_target[future]
                try:
                    result = future.result()
                    network_results[domain] = {
                        'name': name,
                        'host': domain,
                        'status': result
                    }
                except Exception:
                    network_results[domain] = {
                        'name': name,
                        'host': domain,
                        'status': {'ok': False, 'latency': 0}
                    }
        
        # 排序：互联网连通性第一，其他按字母
        sorted_network = []
        if 'www.baidu.com' in network_results:
             sorted_network.append(network_results.pop('www.baidu.com'))
             
        for domain in sorted(network_results.keys()):
            sorted_network.append(network_results[domain])
                
        return jsonify({
            'success': True,
            'data': {
                'system': system_status,
                'platforms': platform_status,
                'network': sorted_network,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # 启动定时任务
    start_scheduler()
    
    # 启动Flask
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

