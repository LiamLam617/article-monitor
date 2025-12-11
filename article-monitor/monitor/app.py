"""
Flask应用 - 简单的RESTful API和前端
"""
from flask import Flask, render_template, request, jsonify, Response, send_file
from flask_cors import CORS
import asyncio
import csv
import io
from datetime import datetime
from .database import (
    init_db, add_article, get_all_articles, get_read_counts,
    delete_article, get_latest_read_count, get_setting, set_setting,
    add_read_count, get_platform_health, get_platform_failures
)
from .extractors import extract_read_count
from .scheduler import start_scheduler
from urllib.parse import urlparse
from .config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG, SUPPORTED_SITES, CRAWL_INTERVAL_HOURS


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
    """获取所有文章"""
    articles = get_all_articles()
    
    # 添加最新阅读数
    for article in articles:
        latest = get_latest_read_count(article['id'])
        article['latest_count'] = latest['count'] if latest else 0
        article['latest_timestamp'] = latest['timestamp'] if latest else None
    
    return jsonify({'success': True, 'data': articles})

@app.route('/api/articles/batch', methods=['POST'])
def create_articles_batch():
    """批量添加文章"""
    data = request.json
    urls = data.get('urls', [])
    
    if not urls:
        return jsonify({'success': False, 'error': 'URL列表不能为空'}), 400
    
    # 去重、過濾空值、規範化 URL
    urls = list(set([normalize_url(u.strip()) for u in urls if u.strip()]))
    
    if not urls:
        return jsonify({'success': False, 'error': '有效URL不能为空'}), 400
        
    results = []
    
    # 导入必要的模块（在函数外部，确保所有内部函数都能访问）
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from .extractors import create_shared_crawler
    
    # 异步处理函数
    async def process_urls():
        # 使用共享浏览器实例
        try:
            crawler = await create_shared_crawler()
        except Exception as e:
            # 降级：如果无法创建共享实例，results中记录错误
            return [{'url': u, 'success': False, 'error': f'无法启动爬虫: {str(e)}'} for u in urls]

        try:
            tasks = []
            for url in urls:
                tasks.append(process_single_url(url, crawler))
            
            return await asyncio.gather(*tasks)
        finally:
            await crawler.__aexit__(None, None, None)

    async def process_single_url(url, crawler):
        try:
            # 验证URL
            try:
                parsed = urlparse(url)
                if not parsed.scheme or not parsed.netloc:
                    return {'url': url, 'success': False, 'error': '无效的URL格式'}
            except:
                return {'url': url, 'success': False, 'error': 'URL解析失败'}
            
            # 检测网站类型
            domain = parsed.netloc.lower()
            site = None
            for site_domain, site_name in SUPPORTED_SITES.items():
                if site_domain in domain:
                    site = site_name
                    break
            
            # 爬取标题和阅读数
            title = None
            count = None
            
            # 根据网站类型设置超时时间（FreeBuf 需要更长时间）
            timeout = 30000  # 默认30秒
            if site == 'freebuf':
                timeout = 60000  # FreeBuf 使用60秒
            
            crawler_config = CrawlerRunConfig(
                page_timeout=timeout,
                remove_overlay_elements=True
            )
            
            try:
                result = await crawler.arun(url, config=crawler_config)
                if result.success:
                    title = result.metadata.get('title', '')
                    if not title:
                        # 尝试从HTML提取
                        import re
                        match = re.search(r'<title[^>]*>([^<]+)</title>', result.html, re.IGNORECASE)
                        if match:
                            title = match.group(1).strip()
                    
                    # 清理标题
                    if title:
                        suffixes = [' - 掘金', ' - 稀土掘金', ' - CSDN', ' - 博客园', 
                                   ' - 面包板', ' - SegmentFault', ' - 简书', ' - 与非网']
                        for suffix in suffixes:
                            if title.endswith(suffix):
                                title = title[:-len(suffix)].strip()
                                break
                                
                    # 尝试提取阅读数
                    count = await extract_read_count(url, crawler)
            except Exception as e:
                # 爬取失败不影响添加，只是没有初始数据
                pass
                
            # 添加到数据库
            try:
                article_id = add_article(url, title=title, site=site)
                
                # 保存初始阅读数
                initial_count = count if count is not None else 0
                add_read_count(article_id, initial_count)
                
                return {
                    'url': url,
                    'success': True,
                    'data': {
                        'id': article_id,
                        'title': title,
                        'site': site,
                        'initial_count': initial_count
                    }
                }
            except Exception as e:
                if 'UNIQUE constraint failed' in str(e):
                    return {'url': url, 'success': False, 'error': '文章已存在'}
                return {'url': url, 'success': False, 'error': str(e)}
                
        except Exception as e:
            return {'url': url, 'success': False, 'error': str(e)}

    # 运行异步任务
    try:
        results = asyncio.run(process_urls())
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
    except:
        return jsonify({'success': False, 'error': '无效的URL'}), 400
    
    # 检测网站类型
    domain = parsed.netloc.lower()
    site = None
    for site_domain, site_name in SUPPORTED_SITES.items():
        if site_domain in domain:
            site = site_name
            break
    
    # 立即爬取一次获取标题和阅读数
    title = None
    count = None
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        browser_config = BrowserConfig(headless=True)
        crawler_config = CrawlerRunConfig(
            page_timeout=30000,
            remove_overlay_elements=True
        )
        
        async def fetch_title_and_count():
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url, config=crawler_config)
                if result.success:
                    # 获取标题
                    title_text = result.metadata.get('title', '')
                    if not title_text:
                        # 尝试从HTML提取
                        import re
                        match = re.search(r'<title[^>]*>([^<]+)</title>', result.html, re.IGNORECASE)
                        if match:
                            title_text = match.group(1).strip()
                    
                    # 清理标题：去除常见后缀
                    if title_text:
                        suffixes = [' - 掘金', ' - 稀土掘金', ' - CSDN', ' - 博客园', 
                                   ' - 面包板', ' - SegmentFault', ' - 简书']
                        for suffix in suffixes:
                            if title_text.endswith(suffix):
                                title_text = title_text[:-len(suffix)].strip()
                                break
                    
                    # 获取阅读数
                    read_count = await extract_read_count(url)
                    return title_text or None, read_count
                return None, None
        
        title, count = asyncio.run(fetch_title_and_count())
    except Exception as e:
        print(f"初次爬取失败: {e}")
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
        
        # 获取文章信息
        articles = get_all_articles()
        article = next((a for a in articles if a['id'] == article_id), None)
        
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
            except:
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

